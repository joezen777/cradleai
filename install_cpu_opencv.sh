#!/bin/bash
# Quick CPU-only OpenCV Installation
# Use this for immediate development/testing (no GPU acceleration)

echo "Installing CPU-only OpenCV (quick installation)..."
echo ""

# Navigate to project directory
cd "$(dirname "$0")"

# Activate virtual environment
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
    echo "✓ Virtual environment activated"
else
    echo "✗ Virtual environment not found"
    echo "  Creating virtual environment..."
    python3 -m venv .venv
    source .venv/bin/activate
fi

# Ensure pip is installed
echo "Ensuring pip is installed..."
python -m ensurepip --upgrade --quiet

# Install packages
echo "Installing OpenCV and NumPy..."
pip install --upgrade pip
pip install opencv-python numpy

echo ""
echo "✓ CPU-only OpenCV installed successfully!"
echo ""
echo "To verify installation:"
echo "  python check_cuda.py"
echo ""
echo "To run video analysis:"
echo "  python video_scene_analyzer.py"
echo ""
echo "Note: For GPU acceleration with your RTX 5070, run:"
echo "  bash setup_cuda_opencv.sh"
echo ""