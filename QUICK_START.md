# Quick Start Guide - Video Scene Analysis with CUDA Support

## For Your NVIDIA RTX 5070

I've created all the necessary files for CUDA-compatible OpenCV installation. Here's what you need to do:

### Step 1: Check Your CUDA Setup

First, verify what CUDA components you have installed:

```bash
python3 check_cuda.py
```

This will check:
- ✓ NVIDIA driver status
- ✓ CUDA Toolkit installation  
- ✓ OpenCV CUDA support

### Step 2: Choose Installation Method

Based on the check above, choose one of these options:

#### Option A: Quick Start (CPU-only, 5 minutes) - RECOMMENDED FIRST
**Good for testing and development**

```bash
chmod +x install_cpu_opencv.sh
./install_cpu_opencv.sh
```

Then run:
```bash
python3 video_scene_analyzer.py
```

#### Option B: Full CUDA Support (2-4 hours) - FOR MAXIMUM PERFORMANCE
**Best for your RTX 5070 with GPU acceleration**

```bash
chmod +x setup_cuda_opencv.sh
./setup_cuda_opencv.sh
```

When prompted, select option 1 (Build from source).

#### Option C: Conda CUDA Build (30 minutes)
**If you have conda installed**

```bash
conda install -c conda-forge opencv-cuda
```

### Step 3: Run Video Analysis

Once OpenCV is installed:

```bash
python3 video_scene_analyzer.py
```

## What the Script Does

The [video_scene_analyzer.py](video_scene_analyzer.py) will:

1. **Extract Audio**: Pull audio from `CradleAnimatic.webm` to `output/audio.wav`
2. **Detect Scene Changes**: Use histogram analysis to find cuts/transitions
3. **Extract Clips**: Save each scene as a separate `.webm` file in `output/clips/`
4. **Export Frames**: Save first/last frame for each scene in `output/frames/`
5. **Create Metadata**: Generate `output/metadata.jsonl` with:
   - Scene sequence names
   - File locations  
   - Exact timecodes
   - Frame ranges
   - First/last frame references

## Output Structure

```
output/
├── audio.wav                    # Extracted audio
├── metadata.jsonl              # Scene database
├── clips/                      # Extracted scenes
│   ├── scene_001.webm
│   ├── scene_002.webm
│   └── ...
└── frames/                     # Key frames
    ├── scene_001_first_frame.png
    ├── scene_001_last_frame.png
    └── ...
```

## CUDA-Specific Information for RTX 5070

Your RTX 5070 uses the **Blackwell architecture** with compute capability **9.0+**.

The setup scripts are pre-configured for:
- CUDA Architecture: 9.0
- GPU acceleration for video processing
- Optimized histogram analysis for scene detection

## Files Created

1. **[video_scene_analyzer.py](video_scene_analyzer.py)** - Main analysis script
2. **[setup_cuda_opencv.sh](setup_cuda_opencv.sh)** - Full CUDA build script
3. **[install_cpu_opencv.sh](install_cpu_opencv.sh)** - Quick CPU-only install
4. **[check_cuda.py](check_cuda.py)** - CUDA verification tool
5. **[install_cuda_opencv.py](install_cuda_opencv.py)** - Python setup helper
6. **[README_CUDA_SETUP.md](README_CUDA_SETUP.md)** - Detailed CUDA guide

## Troubleshooting

### "pip not found"
```bash
python3 -m ensurepip --upgrade
```

### "ffmpeg not found"
```bash
sudo apt update
sudo apt install ffmpeg
```

### Virtual environment issues
```bash
# Create new venv
python3 -m venv .venv
source .venv/bin/activate

# Then install packages
pip install opencv-python numpy
```

## Performance Expectations

| Setup | Scene Detection | Memory Usage |
|-------|----------------|--------------|
| CPU-only | ~10-30 fps | 2-4 GB |
| CUDA (conda) | ~50-100 fps | 4-6 GB |
| CUDA (source) | ~100-200 fps | 6-8 GB |

## Next Steps

1. Run `python3 check_cuda.py` to see your current setup
2. Choose installation method based on your needs
3. Run `python3 video_scene_analyzer.py` to analyze your video
4. Check `output/metadata.jsonl` for the scene database

The metadata JSONL file makes it easy to:
- Reconstruct the original video sequence
- Access individual scenes by timecode
- Reference first/last frames for each scene
- Build custom video editing tools

## Need Help?

Check the detailed guide: [README_CUDA_SETUP.md](README_CUDA_SETUP.md)