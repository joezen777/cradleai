#!/bin/bash
# CUDA-enabled OpenCV Setup Script for NVIDIA RTX 5070
# This script provides installation options for CUDA-compatible OpenCV

echo "=================================================="
echo "CUDA-Enabled OpenCV Setup for RTX 5070"
echo "=================================================="

# Check if running in WSL
if grep -q Microsoft /proc/version 2>/dev/null; then
    echo "✓ Detected WSL environment"
    WSL=true
else
    echo "✗ Native Linux environment"
    WSL=false
fi

# Step 1: Check CUDA installation
echo ""
echo "Step 1: Checking CUDA installation..."
if command -v nvcc &> /dev/null; then
    echo "✓ CUDA compiler found:"
    nvcc --version
else
    echo "✗ CUDA compiler (nvcc) not found"
    echo "  Please install CUDA Toolkit from: https://developer.nvidia.com/cuda-downloads"
fi

# Step 2: Check NVIDIA driver
echo ""
echo "Step 2: Checking NVIDIA driver..."
if command -v nvidia-smi &> /dev/null; then
    echo "✓ NVIDIA driver found:"
    nvidia-smi --query-gpu=name,driver_version,cuda_version --format=csv,noheader
else
    echo "✗ NVIDIA driver not found"
    echo "  Please install NVIDIA drivers"
fi

# Step 3: Installation options
echo ""
echo "=================================================="
echo "Installation Options for CUDA-Enabled OpenCV"
echo "=================================================="

echo ""
echo "OPTION 1: Build OpenCV with CUDA from Source (RECOMMENDED)"
echo "  - Full CUDA support for RTX 5070"
echo "  - Optimized performance"
echo "  - Takes 2-4 hours to build"
echo ""
echo "OPTION 2: Install standard OpenCV (CPU-only, QUICK)"
echo "  - No GPU acceleration"
echo "  - Fast installation (5 minutes)"
echo "  - Good for development/testing"
echo ""
echo "OPTION 3: Use conda-forge CUDA builds"
echo "  - Requires conda installation"
echo "  - Moderate installation time"
echo ""

read -p "Select option (1/2/3): " choice

case $choice in
    1)
        echo ""
        echo "Building OpenCV with CUDA support from source..."
        echo "This process will take 2-4 hours."
        echo ""
        
        # Install build dependencies
        echo "Installing build dependencies..."
        sudo apt update
        sudo apt install -y \
            build-essential \
            cmake \
            git \
            pkg-config \
            libgtk-3-dev \
            libavcodec-dev \
            libavformat-dev \
            libswscale-dev \
            libv4l-dev \
            libxvidcore-dev \
            libx264-dev \
            libjpeg-dev \
            libpng-dev \
            libtiff-dev \
            gfortran \
            openexr \
            libatlas-base-dev \
            python3-dev \
            python3-numpy \
            libtbb2 \
            libtbb-dev \
            libeigen3-dev \
            yasm \
            libfaac-dev \
            libmp3lame-dev \
            libopencore-amrnb-dev \
            libopencore-amrwb-dev \
            libtheora-dev \
            libvorbis-dev \
            libxvidcore-dev \
            x264 \
            v4l-utils
        
        # Clone OpenCV repositories
        echo "Cloning OpenCV repositories..."
        cd ~
        if [ ! -d "opencv" ]; then
            git clone https://github.com/opencv/opencv.git
            git clone https://github.com/opencv/opencv_contrib.git
        fi
        
        cd opencv
        git checkout 4.8.0
        cd ../opencv_contrib
        git checkout 4.8.0
        
        # Create build directory
        echo "Creating build directory..."
        cd ~/opencv
        mkdir -p build
        cd build
        
        # Configure CMake with CUDA support
        echo "Configuring CMake with CUDA support for RTX 5070..."
        cmake -D CMAKE_BUILD_TYPE=RELEASE \
              -D CMAKE_INSTALL_PREFIX=/usr/local \
              -D INSTALL_PYTHON_EXAMPLES=ON \
              -D INSTALL_C_EXAMPLES=OFF \
              -D OPENCV_EXTRA_MODULES_PATH=~/opencv_contrib/modules \
              -D PYTHON_EXECUTABLE=$(which python3) \
              -D BUILD_opencv_python2=OFF \
              -D BUILD_opencv_python3=ON \
              -D BUILD_EXAMPLES=ON \
              -D WITH_CUDA=ON \
              -D CUDA_ARCH_BIN="9.0" \
              -D CUDA_ARCH_PTX="" \
              -D WITH_CUDNN=ON \
              -D OPENCV_DNN_CUDA=ON \
              -D ENABLE_FAST_MATH=ON \
              -D CUDA_FAST_MATH=ON \
              -D WITH_CUBLAS=ON \
              -D WITH_V4L=ON \
              -D WITH_GSTREAMER=ON \
              -D WITH_OPENGL=ON \
              -D BUILD_opencv_cudaobjdetect=ON \
              -D BUILD_opencv_cudabgsegm=ON \
              -D BUILD_opencv_cudacodec=ON \
              -D BUILD_opencv_cudafeatures2d=ON \
              -D BUILD_opencv_cudafilters=ON \
              -D BUILD_opencv_cudaimgproc=ON \
              -D BUILD_opencv_cudalegacy=ON \
              -D BUILD_opencv_cudaobjdetect=ON \
              -D BUILD_opencv_cudaoptflow=ON \
              -D BUILD_opencv_cudastereo=ON \
              -D BUILD_opencv_cudawarping=ON \
              -D BUILD_opencv_cudacodec=ON \
              ..
        
        # Build
        echo "Building OpenCV (this will take several hours)..."
        make -j$(nproc)
        
        # Install
        echo "Installing OpenCV..."
        sudo make install
        sudo ldconfig
        
        echo "✓ OpenCV with CUDA support installed successfully!"
        ;;
        
    2)
        echo ""
        echo "Installing standard OpenCV (CPU-only)..."
        
        # Activate virtual environment if it exists
        if [ -f ".venv/bin/activate" ]; then
            source .venv/bin/activate
        fi
        
        pip install opencv-python numpy
        echo "✓ Standard OpenCV installed (CPU-only)"
        echo "  Note: For CUDA support, use option 1 or 3"
        ;;
        
    3)
        echo ""
        echo "Installing conda-forge CUDA build..."
        echo "Note: This requires conda to be installed"
        
        # Check if conda is available
        if command -v conda &> /dev/null; then
            conda install -c conda-forge opencv-cuda
            echo "✓ CUDA-enabled OpenCV installed via conda"
        else
            echo "✗ conda not found"
            echo "  Install conda from: https://docs.conda.io/en/latest/miniconda.html"
        fi
        ;;
        
    *)
        echo "Invalid option selected"
        exit 1
        ;;
esac

echo ""
echo "=================================================="
echo "Installation Complete!"
echo "=================================================="
echo ""
echo "To verify your installation, run:"
echo "  python check_cuda.py"
echo ""