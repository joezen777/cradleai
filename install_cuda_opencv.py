#!/usr/bin/env python3
"""
CUDA-compatible OpenCV installation script for NVIDIA RTX 5070
Detects CUDA version and installs appropriate OpenCV build with CUDA support.
"""

import subprocess
import sys
import platform
from pathlib import Path


def check_cuda_installation():
    """Check if CUDA is installed and get version."""
    try:
        result = subprocess.run(['nvcc', '--version'], capture_output=True, text=True)
        if result.returncode == 0:
            print("✓ CUDA detected:")
            print(result.stdout)
            
            # Extract CUDA version
            for line in result.stdout.split('\n'):
                if 'release' in line.lower():
                    version_start = line.find('release') + 8
                    version_end = line.find(',', version_start)
                    cuda_version = line[version_start:version_end].strip()
                    print(f"CUDA Version: {cuda_version}")
                    return cuda_version
        
        print("✗ CUDA compiler (nvcc) not found in PATH")
        return None
        
    except FileNotFoundError:
        print("✗ CUDA toolkit not found. Please install CUDA Toolkit.")
        return None


def check_gpu_info():
    """Get GPU information."""
    try:
        result = subprocess.run(['nvidia-smi'], capture_output=True, text=True)
        if result.returncode == 0:
            print("✓ NVIDIA GPU detected:")
            print(result.stdout)
            return result.stdout
        else:
            print("✗ nvidia-smi failed")
            return None
    except FileNotFoundError:
        print("✗ NVIDIA driver not found")
        return None


def get_cuda_arch_for_rtx_5070():
    """
    Get CUDA architecture for RTX 5070.
    RTX 50-series uses the Blackwell architecture (compute capability 9.0+)
    """
    # RTX 5070 likely has compute capability 9.0 or higher
    # This is based on Blackwell architecture
    return "9.0"  # Conservative estimate, may need adjustment


def install_cuda_opencv_from_source():
    """
    Instructions for building OpenCV with CUDA support from source.
    This is the most reliable method for CUDA support.
    """
    print("\n" + "="*60)
    print("Building OpenCV with CUDA Support from Source")
    print("="*60)
    
    cuda_version = check_cuda_installation()
    if not cuda_version:
        print("\n✗ CUDA not found. Please install CUDA Toolkit first.")
        print("  Download from: https://developer.nvidia.com/cuda-downloads")
        return False
    
    gpu_info = check_gpu_info()
    cuda_arch = get_cuda_arch_for_rtx_5070()
    
    print(f"\nTarget CUDA Architecture: {cuda_arch} (RTX 5070)")
    print(f"CUDA Version: {cuda_version}")
    
    print("\n" + "-"*60)
    print("To build OpenCV with CUDA support, follow these steps:")
    print("-"*60)
    
    install_script = f'''#!/bin/bash
# OpenCV with CUDA build script for RTX 5070

# Install build dependencies
sudo apt update
sudo apt install -y \\
    build-essential \\
    cmake \\
    git \\
    pkg-config \\
    libgtk-3-dev \\
    libavcodec-dev \\
    libavformat-dev \\
    libswscale-dev \\
    libv4l-dev \\
    libxvidcore-dev \\
    libx264-dev \\
    libjpeg-dev \\
    libpng-dev \\
    libtiff-dev \\
    gfortran \\
    openexr \\
    libatlas-base-dev \\
    python3-dev \\
    python3-numpy \\
    libtbb2 \\
    libtbb-dev \\
    libeigen3-dev \\
    yasm \\
    libfaac-dev \\
    libmp3lame-dev \\
    libopencore-amrnb-dev \\
    libopencore-amrwb-dev \\
    libtheora-dev \\
    libvorbis-dev \\
    libxvidcore-dev \\
    x264 \\
    v4l-utils

# Clone OpenCV repositories
cd ~
git clone https://github.com/opencv/opencv.git
git clone https://github.com/opencv/opencv_contrib.git

cd opencv
git checkout 4.8.0  # Stable version
cd ../opencv_contrib
git checkout 4.8.0

# Create build directory
cd ~/opencv
mkdir build
cd build

# Configure CMake with CUDA support for RTX 5070
cmake -D CMAKE_BUILD_TYPE=RELEASE \\
      -D CMAKE_INSTALL_PREFIX=/usr/local \\
      -D INSTALL_PYTHON_EXAMPLES=ON \\
      -D INSTALL_C_EXAMPLES=OFF \\
      -D OPENCV_EXTRA_MODULES_PATH=~/opencv_contrib/modules \\
      -D PYTHON_EXECUTABLE=$(which python3) \\
      -D BUILD_opencv_python2=OFF \\
      -D BUILD_opencv_python3=ON \\
      -D BUILD_EXAMPLES=ON \\
      -D WITH_CUDA=ON \\
      -D CUDA_ARCH_BIN="{cuda_arch}" \\
      -D CUDA_ARCH_PTX="" \\
      -D WITH_CUDNN=ON \\
      -D OPENCV_DNN_CUDA=ON \\
      -D ENABLE_FAST_MATH=ON \\
      -D CUDA_FAST_MATH=ON \\
      -D WITH_CUBLAS=ON \\
      -D WITH_V4L=ON \\
      -D WITH_GSTREAMER=ON \\
      -D WITH_OPENGL=ON \\
      -D BUILD_opencv_cudaobjdetect=ON \\
      -D BUILD_opencv_cudabgsegm=ON \\
      -D BUILD_opencv_cudacodec=ON \\
      -D BUILD_opencv_cudafeatures2d=ON \\
      -D BUILD_opencv_cudafilters=ON \\
      -D BUILD_opencv_cudaimgproc=ON \\
      -D BUILD_opencv_cudalegacy=ON \\
      -D BUILD_opencv_cudaobjdetect=ON \\
      -D BUILD_opencv_cudaoptflow=ON \\
      -D BUILD_opencv_cudastereo=ON \\
      -D BUILD_opencv_cudawarping=ON \\
      -D BUILD_opencv_cudacodec=ON \\
      ..

# Build (use all cores, this will take a while)
make -j$(nproc)

# Install
sudo make install
sudo ldconfig

# Create Python symlink
cd ~
git clone https://github.com/skvark/opencv-python
cd opencv-python
python3 -m pip install -r requirements.txt
python3 setup.py install --user
'''

    script_path = Path("build_cuda_opencv.sh")
    with open(script_path, 'w') as f:
        f.write(install_script)
    
    print(f"\n✓ Installation script created: {script_path}")
    print("\nTo build OpenCV with CUDA support:")
    print(f"  1. chmod +x {script_path}")
    print(f"  2. ./{script_path}")
    print("\nNote: This process will take several hours and requires ~10GB of disk space.")
    
    return True


def install_prebuilt_cuda_opencv():
    """
    Attempt to install pre-built CUDA-enabled OpenCV packages.
    """
    print("\n" + "="*60)
    print("Installing Pre-built CUDA-enabled OpenCV")
    print("="*60)
    
    print("\nSearching for CUDA-compatible OpenCV packages...")
    
    # Option 1: Try unofficial CUDA builds
    unofficial_packages = [
        "opencv-contrib-python-cuda",  # Some community builds
    ]
    
    print("\nNote: Official PyPI packages do not include CUDA support.")
    print("Options for CUDA-enabled OpenCV:")
    print("\n1. Build from source (recommended - see function above)")
    print("2. Use conda-forge CUDA builds:")
    print("   conda install -c conda-forge opencv-cuda")
    print("3. Use unofficial wheels (not recommended for production)")
    
    return False


def create_cuda_detection_script():
    """Create a script to verify CUDA installation and compatibility."""
    script = '''#!/usr/bin/env python3
"""
CUDA Detection and Compatibility Verification Script
"""

import subprocess
import sys
import pynvml

def check_cuda():
    print("="*60)
    print("CUDA Detection and Compatibility Check")
    print("="*60)
    
    # Check nvidia-smi
    try:
        result = subprocess.run(['nvidia-smi'], capture_output=True, text=True)
        if result.returncode == 0:
            print("\\n✓ nvidia-smi working:")
            print(result.stdout)
        else:
            print("✗ nvidia-smi failed")
            return False
    except FileNotFoundError:
        print("✗ nvidia-smi not found")
        return False
    
    # Check nvcc
    try:
        result = subprocess.run(['nvcc', '--version'], capture_output=True, text=True)
        if result.returncode == 0:
            print("\\n✓ nvcc (CUDA compiler) found:")
            print(result.stdout)
        else:
            print("✗ nvcc not found")
    except FileNotFoundError:
        print("✗ nvcc not found")
    
    # Check GPU details using pynvml
    try:
        pynvml.nvmlInit()
        device_count = pynvml.nvmlDeviceGetCount()
        print(f"\\n✓ Found {device_count} NVIDIA device(s):")
        
        for i in range(device_count):
            handle = pynvml.nvmlDeviceGetHandleByIndex(i)
            name = pynvml.nvmlDeviceGetName(handle)
            compute_capability = pynvml.nvmlDeviceGetCudaComputeCapability(handle)
            memory_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            
            print(f"\\n  Device {i}:")
            print(f"    Name: {name}")
            print(f"    Compute Capability: {compute_capability[0]}.{compute_capability[1]}")
            print(f"    Total Memory: {memory_info.total / 1024**3:.2f} GB")
            print(f"    Free Memory: {memory_info.free / 1024**3:.2f} GB")
        
        pynvml.nvmlShutdown()
        
    except Exception as e:
        print(f"\\n✗ Error getting GPU details: {e}")
    
    # Check OpenCV CUDA support
    try:
        import cv2
        print(f"\\n✓ OpenCV version: {cv2.__version__}")
        
        # Check for CUDA support
        if hasattr(cv2.cuda, 'getCudaEnabledDeviceCount'):
            cuda_devices = cv2.cuda.getCudaEnabledDeviceCount()
            if cuda_devices > 0:
                print(f"✓ OpenCV CUDA support: {cuda_devices} device(s)")
                print("✓ OpenCV is compiled with CUDA support!")
            else:
                print("✗ OpenCV compiled without CUDA support")
        else:
            print("✗ OpenCV compiled without CUDA support")
            
    except ImportError:
        print("\\n✗ OpenCV not installed")
    except Exception as e:
        print(f"\\n✗ Error checking OpenCV CUDA: {e}")
    
    print("\\n" + "="*60)

if __name__ == "__main__":
    check_cuda()
'''
    
    script_path = Path("check_cuda.py")
    with open(script_path, 'w') as f:
        f.write(script)
    
    print(f"✓ CUDA detection script created: {script_path}")
    return script_path


def main():
    print("="*60)
    print("CUDA-Enabled OpenCV Installation for RTX 5070")
    print("="*60)
    
    # Check current environment
    print("\nStep 1: Checking CUDA installation...")
    cuda_version = check_cuda_installation()
    
    print("\nStep 2: Checking GPU information...")
    gpu_info = check_gpu_info()
    
    print("\nStep 3: Creating CUDA detection script...")
    detection_script = create_cuda_detection_script()
    
    print("\nStep 4: Installation options...")
    print("\nFor CUDA-enabled OpenCV on RTX 5070, you have two main options:")
    
    print("\n" + "-"*60)
    print("OPTION 1: Build from Source (RECOMMENDED)")
    print("-"*60)
    print("  Pros: Full CUDA support, optimized for your GPU")
    print("  Cons: Takes several hours to build")
    success = install_cuda_opencv_from_source()
    
    print("\n" + "-"*60)
    print("OPTION 2: Use conda-forge CUDA builds")
    print("-"*60)
    print("  Command: conda install -c conda-forge opencv-cuda")
    print("  Pros: Faster installation")
    print("  Cons: May not have latest features")
    
    print("\n" + "-"*60)
    print("OPTION 3: Install CPU-only OpenCV (fallback)")
    print("-"*60)
    print("  Command: pip install opencv-python numpy")
    print("  Note: No GPU acceleration")
    
    print("\n" + "="*60)
    print("Next Steps:")
    print("="*60)
    print(f"1. Check your CUDA setup: python {detection_script}")
    print("2. Choose installation method above")
    print("3. Verify installation: python check_cuda.py")
    print("\nNote: Building from source will take 2-4 hours but provides")
    print("      the best performance and CUDA compatibility for RTX 5070.")
    print("="*60)


if __name__ == "__main__":
    main()