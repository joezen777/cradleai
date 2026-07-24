# CUDA-Enabled OpenCV Setup for NVIDIA RTX 5070

This guide explains how to install CUDA-compatible OpenCV for your NVIDIA RTX 5070 GPU.

## Prerequisites

1. **NVIDIA Drivers** - Must be installed first
2. **CUDA Toolkit** - Required for GPU acceleration
3. **Build Tools** - For building OpenCV from source

## Quick Setup Options

### Option 1: Quick Start (CPU-only, 5 minutes)
**For immediate development/testing without GPU acceleration**

```bash
# Install CPU-only OpenCV
pip install opencv-python numpy

# Run video analysis
python video_scene_analyzer.py
```

### Option 2: Full CUDA Support (2-4 hours)
**For maximum performance with RTX 5070 GPU acceleration**

```bash
# Run the automated setup script
bash setup_cuda_opencv.sh

# Select option 1 to build OpenCV with CUDA support
```

### Option 3: Conda CUDA Build (30 minutes)
**If you have conda installed**

```bash
conda install -c conda-forge opencv-cuda
```

## Verification

Check your CUDA setup:
```bash
python check_cuda.py
```

Expected output for full CUDA support:
```
✓ NVIDIA driver detected:
✓ CUDA compiler (nvcc) found:
✓ OpenCV version: 4.8.0
✓ CUDA-enabled devices: 1
✓ OpenCV is compiled with CUDA support!
```

## CUDA Architecture for RTX 5070

The RTX 5070 uses the Blackwell architecture with compute capability 9.0+.
The build scripts are pre-configured for this architecture.

## Video Analysis with GPU

Once CUDA is enabled, your video analysis script can use GPU acceleration:

```python
import cv2

# Upload frame to GPU
gpu_frame = cv2.cuda_GpuMat()
gpu_frame.upload(frame)

# Process on GPU
gray_gpu = cv2.cuda.cvtColor(gpu_frame, cv2.COLOR_BGR2GRAY)
hist_gpu = cv2.cuda.calcHist(gray_gpu, [0], None, [256], [0, 256])

# Download result back to CPU
result = hist_gpu.download()
```

## Troubleshooting

### "nvcc not found"
- Install CUDA Toolkit: https://developer.nvidia.com/cuda-downloads
- Add CUDA to your PATH: `export PATH=/usr/local/cuda/bin:$PATH`

### "OpenCV compiled without CUDA support"
- Rebuild OpenCV with CUDA: `bash setup_cuda_opencv.sh` (option 1)
- Or install conda build: `conda install -c conda-forge opencv-cuda`

### "nvidia-smi failed"
- Install NVIDIA drivers for your system
- In WSL: Install WSL2 with NVIDIA GPU support

## Performance Comparison

| Setup | Installation Time | Scene Detection Speed | Notes |
|-------|-------------------|----------------------|-------|
| CPU-only | 5 min | 1x | Good for testing |
| CUDA (conda) | 30 min | 5-10x | Moderate performance |
| CUDA (source) | 2-4 hours | 10-20x | Best performance |

## Files in This Package

- `video_scene_analyzer.py` - Main video analysis script
- `setup_cuda_opencv.sh` - Automated CUDA OpenCV setup
- `check_cuda.py` - CUDA verification script
- `install_cuda_opencv.py` - Python setup helper
- `requirements.txt` - Python dependencies

## Running the Video Analysis

After setting up OpenCV:

```bash
python video_scene_analyzer.py
```

This will:
1. Extract audio from `CradleAnimatic.webm`
2. Detect scene changes using histogram analysis
3. Extract clips for each scene
4. Export first/last frames for each scene
5. Create metadata JSONL file with all clip information

Output structure:
```
output/
├── audio.wav              # Extracted audio
├── metadata.jsonl         # Scene metadata database
├── clips/                 # Extracted video clips
│   ├── scene_001.webm
│   ├── scene_002.webm
│   └── ...
└── frames/                # First/last frames
    ├── scene_001_first_frame.png
    ├── scene_001_last_frame.png
    └── ...
```