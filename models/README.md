# ARTEMIS Pre-trained Models

This directory should contain pre-trained models for the ARTEMIS counter-drone system.

## Acoustic Model

**File**: `acoustic_drone_cnn.tflite`
**Architecture**: MobileNetV2 (α=0.35) on 64×32 log-mel spectrograms
**Input**: 500ms audio clips, 16kHz, mono (channel 0 of 4-ch ReSpeaker)
**Output**: Binary classification (drone vs background), sigmoid [0,1]
**Training Data**: DroneAudioDataset + ESC-50 + DCASE 2023
**Expected Accuracy**: 90-96% on held-out test set
**Inference Time**: ~180-280ms on RPi 5 CPU, ~20-40ms with Hailo-8L

### To Train Your Own:
```bash
# Collect/prepare data
mkdir -p data/drone data/ambient
# Put drone WAV files in data/drone/, ambient in data/ambient/

# Train
python scripts/train_acoustic_model.py \
    --drone-clips data/drone \
    --ambient-clips data/ambient \
    --epochs 50 \
    --output models/acoustic_drone_cnn.tflite
```

### Quick Test (synthetic data):
```bash
python scripts/train_acoustic_model.py \
    --drone-clips dummy \
    --ambient-clips dummy \
    --epochs 3 \
    --output models/acoustic_drone_cnn.tflite \
    --quick-test
```

## Optical Model (YOLOv8-nano)

**File**: `yolov8n_drone.pt` or `yolov8n_drone.onnx`
**Architecture**: YOLOv8-nano (3.2M params)
**Input**: 640×640 RGB
**Classes**: drone, bird, plane, helicopter
**Inference Time**: ~50ms on RPi 5 CPU (NCNN), ~15ms with Hailo-8L

### To Train:
```bash
# Prepare YOLO format dataset
# data/
#   train/images/
#   train/labels/
#   val/images/
#   val/labels/
# data.yaml

yolo detect train data=data.yaml model=yolov8n.pt epochs=100 imgsz=640
```

## Radar Model (Micro-Doppler Classifier)

**File**: `radar_microdoppler_cnn.tflite`
**Architecture**: 1D-CNN on Doppler-time spectrograms
**Input**: 256×64 (range-Doppler map)
**Classes**: DJI_Mavic, DJI_Mini, Autel_Evo, FPV_Generic, Bird, Clutter
**Status**: Not yet implemented

## Downloading Pre-trained Models

Pre-trained models will be released on GitHub Releases. For now, you must train your own using the scripts above.

### Public Datasets for Acoustic Training:
1. **DroneAudioDataset** (4 drone types + ambient) - https://github.com/gumberss/DroneAudioDataset
2. **ESC-50** (environmental sounds for ambient class) - https://github.com/karolpiczak/ESC-50
3. **DCASE 2023 Task 3** (drone detection challenge) - https://dcase.community/challenge2023/task-drone-detection

### Public Datasets for Optical Training:
1. **Drone vs Bird** - various Kaggle datasets
2. **UAV-Optical** - aerial drone detection
3. **VisDrone** - https://github.com/VisDrone/VisDrone-Dataset

## Model Format Notes

- **TFLite** (.tflite): Used for acoustic and radar models (TensorFlow Lite runtime)
- **ONNX** (.onnx): Alternative format, can be converted to TFLite or used with ONNX Runtime
- **PyTorch** (.pt): Used for YOLOv8, export to ONNX for deployment

## Raspberry Pi 5 Optimization

For best performance on RPi 5:
1. Use `tflite-runtime` (not full TensorFlow)
2. Enable XNNPACK delegate: `interpreter = tf.lite.Interpreter(model_path=..., experimental_delegates=[tf.lite.experimental.load_delegate('libxnnpack_delegate.so')])`
3. For YOLO: Use NCNN or ONNX Runtime with CPU optimization
4. Consider Hailo-8L AI accelerator ($70) for 10× speedup