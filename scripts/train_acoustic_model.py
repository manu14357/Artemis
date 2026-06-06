#!/usr/bin/env python3
"""
artemis/scripts/train_acoustic_model.py
Complete acoustic drone detection model training pipeline.

Trains a MobileNetV2 classifier on mel spectrograms from 4-channel audio.
Exports to TFLite for Raspberry Pi 5 inference.

Dataset Requirements:
- drone/: WAV files with drone audio (500ms clips, 16kHz, 4-channel or mono)
- ambient/: WAV files with background noise (same format)

Public datasets to bootstrap:
- DroneAudioDataset: https://github.com/gumberss/DroneAudioDataset
- ESC-50: https://github.com/karolpiczak/ESC-50
- DCASE 2023 Drone Detection Challenge

Usage:
    python scripts/train_acoustic_model.py \
        --drone-clips data/drone \
        --ambient-clips data/ambient \
        --epochs 50 \
        --output models/acoustic_drone_cnn.tflite
"""

from __future__ import annotations

import argparse
import os
import random
import sys
from pathlib import Path

import numpy as np
import tensorflow as tf
from tensorflow.keras import layers, models, optimizers, callbacks

# Set seeds for reproducibility
SEED = 42
random.seed(SEED)
np.random.seed(SEED)
tf.random.set_seed(SEED)


# ---------------------------------------------------------------------------
# Audio preprocessing (matches perception/acoustic/classifier.py)
# ---------------------------------------------------------------------------

SAMPLE_RATE = 16000
WINDOW_MS = 500
WINDOW_SAMPLES = int(SAMPLE_RATE * WINDOW_MS / 1000)  # 8000
N_MELS = 64
N_FFT = 512
HOP_LENGTH = 160
TARGET_TIME_FRAMES = 32  # 64x32 input for MobileNetV2


def _hz_to_mel(hz: float) -> float:
    return 2595.0 * np.log10(1.0 + hz / 700.0)


def _mel_to_hz(mel: float) -> float:
    return 700.0 * (10.0 ** (mel / 2595.0) - 1.0)


def _mel_filterbank(n_mels: int, n_fft: int, sr: int, fmin: float = 0.0, fmax: float = None) -> np.ndarray:
    if fmax is None:
        fmax = sr / 2.0
    mel_min = _hz_to_mel(fmin)
    mel_max = _hz_to_mel(fmax)
    mel_points = np.linspace(mel_min, mel_max, n_mels + 2)
    hz_points = _mel_to_hz(mel_points)
    bin_points = np.floor((n_fft + 1) * hz_points / sr).astype(int)

    n_freq = n_fft // 2 + 1
    fb = np.zeros((n_mels, n_freq))
    for m in range(1, n_mels + 1):
        start = min(int(bin_points[m - 1]), n_freq - 1)
        center = min(int(bin_points[m]), n_freq - 1)
        end = min(int(bin_points[m + 1]), n_freq - 1)
        for k in range(start, center):
            if center != start and k < n_freq:
                fb[m - 1, k] = (k - start) / (center - start)
        for k in range(center, end):
            if end != center and k < n_freq:
                fb[m - 1, k] = (end - k) / (end - center)
    return fb


_MEL_FB = _mel_filterbank(N_MELS, N_FFT, SAMPLE_RATE)


def compute_mel_spectrogram(audio: np.ndarray) -> np.ndarray:
    """
    Compute log-mel spectrogram from mono audio.
    Returns shape (n_mels, time_frames).
    """
    # Ensure correct length
    if len(audio) < WINDOW_SAMPLES:
        audio = np.pad(audio, (0, WINDOW_SAMPLES - len(audio)))
    elif len(audio) > WINDOW_SAMPLES:
        audio = audio[:WINDOW_SAMPLES]

    # STFT
    window = np.hanning(N_FFT)
    frames = []
    for start in range(0, len(audio) - N_FFT, HOP_LENGTH):
        frame = audio[start:start + N_FFT] * window
        spectrum = np.abs(np.fft.rfft(frame)) ** 2
        frames.append(spectrum)

    if not frames:
        return np.zeros((N_MELS, 1))

    power_spec = np.array(frames).T  # (n_freq, time)
    mel_spec = _MEL_FB @ power_spec
    log_mel = 10.0 * np.log10(np.maximum(mel_spec, 1e-10))
    return log_mel.astype(np.float32)


def resize_spectrogram(mel: np.ndarray, target_frames: int = TARGET_TIME_FRAMES) -> np.ndarray:
    """Resize time dimension to target_frames using linear interpolation."""
    from scipy.signal import resample
    if mel.shape[1] != target_frames:
        return resample(mel, target_frames, axis=1)
    return mel


def normalize_spectrogram(mel: np.ndarray) -> np.ndarray:
    """Min-max normalize to [0, 1]."""
    mel_min = mel.min()
    mel_max = mel.max()
    mel_range = mel_max - mel_min
    if mel_range > 1e-8:
        return (mel - mel_min) / mel_range
    return np.zeros_like(mel)


def preprocess_audio_file(filepath: str) -> np.ndarray:
    """
    Load audio file and preprocess to model input format.
    Returns (N_MELS, TARGET_TIME_FRAMES, 1) float32 array.
    """
    try:
        import soundfile as sf
        audio, sr = sf.read(filepath, dtype='float32')
        if sr != SAMPLE_RATE:
            # Resample if needed
            from scipy.signal import resample
            audio = resample(audio, int(len(audio) * SAMPLE_RATE / sr))
        # Use first channel if multi-channel
        if audio.ndim > 1:
            audio = audio[:, 0]
    except Exception as e:
        print(f"Warning: Could not load {filepath}: {e}")
        return np.zeros((N_MELS, TARGET_TIME_FRAMES, 1), dtype=np.float32)

    mel = compute_mel_spectrogram(audio)
    mel = resize_spectrogram(mel)
    mel = normalize_spectrogram(mel)
    return mel[..., np.newaxis]  # Add channel dimension


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_dataset(drone_dir: str, ambient_dir: str, val_split: float = 0.2):
    """Load and preprocess dataset from directories."""
    drone_files = list(Path(drone_dir).glob("*.wav")) + list(Path(drone_dir).glob("*.WAV"))
    ambient_files = list(Path(ambient_dir).glob("*.wav")) + list(Path(ambient_dir).glob("*.WAV"))

    if not drone_files:
        raise ValueError(f"No drone audio files found in {drone_dir}")
    if not ambient_files:
        raise ValueError(f"No ambient audio files found in {ambient_dir}")

    print(f"Found {len(drone_files)} drone clips, {len(ambient_files)} ambient clips")

    # Balance classes
    min_count = min(len(drone_files), len(ambient_files))
    drone_files = drone_files[:min_count]
    ambient_files = ambient_files[:min_count]

    # Shuffle
    random.shuffle(drone_files)
    random.shuffle(ambient_files)

    # Split
    split_idx = int(min_count * (1 - val_split))
    train_drone = drone_files[:split_idx]
    val_drone = drone_files[split_idx:]
    train_ambient = ambient_files[:split_idx]
    val_ambient = ambient_files[split_idx:]

    def process_files(file_list, label):
        X = []
        y = []
        for f in file_list:
            mel = preprocess_audio_file(str(f))
            X.append(mel)
            y.append(label)
        return np.array(X), np.array(y)

    X_train_d, y_train_d = process_files(train_drone, 1)
    X_train_a, y_train_a = process_files(train_ambient, 0)
    X_val_d, y_val_d = process_files(val_drone, 1)
    X_val_a, y_val_a = process_files(val_ambient, 0)

    X_train = np.concatenate([X_train_d, X_train_a])
    y_train = np.concatenate([y_train_d, y_train_a])
    X_val = np.concatenate([X_val_d, X_val_a])
    y_val = np.concatenate([y_val_d, y_val_a])

    # Shuffle training set
    idx = np.arange(len(X_train))
    np.random.shuffle(idx)
    X_train = X_train[idx]
    y_train = y_train[idx]

    print(f"Train: {len(X_train)} samples, Val: {len(X_val)} samples")
    return (X_train, y_train), (X_val, y_val)


# ---------------------------------------------------------------------------
# Model architecture
# ---------------------------------------------------------------------------

def build_model(input_shape=(N_MELS, TARGET_TIME_FRAMES, 1), dropout=0.3):
    """Build MobileNetV2-based classifier for drone detection."""
    base_model = tf.keras.applications.MobileNetV2(
        input_shape=input_shape,
        include_top=False,
        weights=None,  # Train from scratch
        alpha=0.35,    # Small width multiplier for edge deployment
    )

    # Freeze early layers (optional - we train all for small model)
    # for layer in base_model.layers[:20]:
    #     layer.trainable = False

    inputs = tf.keras.Input(shape=input_shape)
    x = base_model(inputs, training=False)
    x = layers.GlobalAveragePooling2D()(x)
    x = layers.Dropout(dropout)(x)
    x = layers.Dense(64, activation='relu')(x)
    x = layers.Dropout(dropout/2)(x)
    outputs = layers.Dense(1, activation='sigmoid')(x)

    model = tf.keras.Model(inputs, outputs)
    return model


# ---------------------------------------------------------------------------
# Training
# ---------------------------------------------------------------------------

def train_model(
    drone_dir: str,
    ambient_dir: str,
    epochs: int = 50,
    batch_size: int = 32,
    learning_rate: float = 1e-3,
    output_path: str = "models/acoustic_drone_cnn.tflite",
    val_split: float = 0.2,
):
    """Main training function."""

    # Load data
    (X_train, y_train), (X_val, y_val) = load_dataset(drone_dir, ambient_dir, val_split)

    # Build model
    model = build_model()
    model.summary()

    # Compile
    model.compile(
        optimizer=optimizers.Adam(learning_rate=learning_rate),
        loss='binary_crossentropy',
        metrics=['accuracy', tf.keras.metrics.AUC(name='auc')]
    )

    # Callbacks
    cb = [
        callbacks.EarlyStopping(monitor='val_auc', patience=10, mode='max', restore_best_weights=True),
        callbacks.ReduceLROnPlateau(monitor='val_auc', factor=0.5, patience=5, mode='max', min_lr=1e-6),
        callbacks.ModelCheckpoint('models/best_acoustic_model.keras', monitor='val_auc', mode='max', save_best_only=True),
    ]

    # Train
    history = model.fit(
        X_train, y_train,
        validation_data=(X_val, y_val),
        epochs=epochs,
        batch_size=batch_size,
        callbacks=cb,
        verbose=1,
    )

    # Evaluate
    val_loss, val_acc, val_auc = model.evaluate(X_val, y_val, verbose=0)
    print(f"\nValidation: loss={val_loss:.4f}, acc={val_acc:.4f}, AUC={val_auc:.4f}")

    # Convert to TFLite
    converter = tf.lite.TFLiteConverter.from_keras_model(model)
    converter.optimizations = [tf.lite.Optimize.DEFAULT]
    # For full integer quantization (faster on RPi), uncomment:
    # converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS_INT8]
    # converter.inference_input_type = tf.uint8
    # converter.inference_output_type = tf.uint8
    # converter.representative_dataset = representative_dataset_gen(X_train)

    tflite_model = converter.convert()

    # Save
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'wb') as f:
        f.write(tflite_model)

    print(f"\nTFLite model saved to {output_path} ({len(tflite_model) / 1024:.1f} KB)")

    # Test TFLite model
    test_tflite_model(output_path, X_val[:10], y_val[:10])

    return model, history


def test_tflite_model(tflite_path: str, X_test: np.ndarray, y_test: np.ndarray):
    """Verify TFLite model produces similar results."""
    interpreter = tf.lite.Interpreter(model_path=tflite_path)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    correct = 0
    for x, y in zip(X_test, y_test):
        interpreter.set_tensor(input_details[0]['index'], x[np.newaxis, ...])
        interpreter.invoke()
        pred = interpreter.get_tensor(output_details[0]['index'])[0][0]
        pred_label = 1 if pred > 0.5 else 0
        if pred_label == y:
            correct += 1

    print(f"TFLite accuracy on {len(X_test)} samples: {correct}/{len(X_test)} = {correct/len(X_test):.2%}")


def representative_dataset_gen(X_train):
    """Generator for post-training quantization calibration."""
    for i in range(min(100, len(X_train))):
        yield [X_train[i:i+1].astype(np.float32)]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Train ARTEMIS acoustic drone detection model")
    parser.add_argument("--drone-clips", required=True, help="Directory with drone WAV files")
    parser.add_argument("--ambient-clips", required=True, help="Directory with ambient WAV files")
    parser.add_argument("--epochs", type=int, default=50, help="Training epochs")
    parser.add_argument("--batch-size", type=int, default=32, help="Batch size")
    parser.add_argument("--lr", type=float, default=1e-3, help="Learning rate")
    parser.add_argument("--output", required=True, help="Output TFLite model path")
    parser.add_argument("--val-split", type=float, default=0.2, help="Validation split fraction")
    parser.add_argument("--quick-test", action="store_true", help="Run quick test with synthetic data")

    args = parser.parse_args()

    if args.quick_test:
        print("Running quick test with synthetic data...")
        # Generate synthetic data for testing
        import tempfile
        import soundfile as sf
        with tempfile.TemporaryDirectory() as tmpdir:
            drone_dir = Path(tmpdir) / "drone"
            ambient_dir = Path(tmpdir) / "ambient"
            drone_dir.mkdir()
            ambient_dir.mkdir()
            # Generate synthetic drone-like and ambient-like audio
            for i in range(20):
                # Drone: tonal components
                t = np.arange(WINDOW_SAMPLES) / SAMPLE_RATE
                drone_audio = 0.5 * np.sin(2*np.pi*200*t) + 0.3*np.sin(2*np.pi*400*t) + 0.1*np.random.randn(WINDOW_SAMPLES)
                sf.write(drone_dir / f"drone_{i}.wav", drone_audio.astype(np.float32), SAMPLE_RATE)
                # Ambient: colored noise
                ambient_audio = 0.1 * np.random.randn(WINDOW_SAMPLES)
                sf.write(ambient_dir / f"ambient_{i}.wav", ambient_audio.astype(np.float32), SAMPLE_RATE)
            train_model(str(drone_dir), str(ambient_dir), epochs=3, output=args.output)
        return 0

    # Verify directories exist
    if not Path(args.drone_clips).exists():
        print(f"Error: Drone clips directory not found: {args.drone_clips}")
        return 1
    if not Path(args.ambient_clips).exists():
        print(f"Error: Ambient clips directory not found: {args.ambient_clips}")
        return 1

    train_model(
        drone_dir=args.drone_clips,
        ambient_dir=args.ambient_clips,
        epochs=args.epochs,
        batch_size=args.batch_size,
        learning_rate=args.lr,
        output_path=args.output,
        val_split=args.val_split,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())