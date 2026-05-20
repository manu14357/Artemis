# Models Directory

This directory holds trained model files. **No pre-trained models are shipped with ARTEMIS v2** — you must train your own or source them externally.

## Required Files

| File | Description | Training Script |
|------|-------------|----------------|
| `acoustic_drone_cnn.tflite` | MobileNetV2 acoustic classifier (ARM TFLite) | `scripts/train_acoustic_model.py` |
| `acoustic_drone_cnn.onnx` | Same model in ONNX format (for x86 dev machines) | `scripts/train_acoustic_model.py` |

## Training

See **Section 6** of `ARTEMIS_v2_Full_Documentation.docx` and [docs/NODE_SETUP.md](../docs/NODE_SETUP.md) for full training instructions.

Quick reference:

```bash
python scripts/train_acoustic_model.py \
    --drone-clips data/drone/ \
    --ambient-clips data/ambient/ \
    --epochs 50 \
    --output models/acoustic_drone_cnn.tflite
```

## Git LFS

Model files (`.tflite`, `.onnx`, `.pt`, `.h5`) are excluded from normal git tracking via `.gitignore`.  
If you want to version-control them, set up [Git LFS](https://git-lfs.com/) and track the extensions:

```bash
git lfs install
git lfs track "*.tflite" "*.onnx"
git add .gitattributes
```
