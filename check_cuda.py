#!/usr/bin/env python3
"""
CUDA Detection and Compatibility Verification Script
Checks for CUDA installation, GPU support, and OpenCV CUDA compatibility.
"""

import subprocess
import sys
import os

def check_nvidia_driver():
    """Check if NVIDIA driver is installed."""
    try:
        result = subprocess.run(['nvidia-smi'], capture_output=True, text=True)
        if result.returncode == 0:
            print("✓ NVIDIA driver detected:")
            print(result.stdout)
            return True
        else:
            print("✗ nvidia-smi failed")
            return False
    except FileNotFoundError:
        print("✗ nvidia-smi not found - NVIDIA driver may not be installed")
        return False
    except Exception as e:
        print(f"✗ Error checking NVIDIA driver: {e}")
        return False

def check_cuda_compiler():
    """Check if CUDA compiler is installed."""
    try:
        result = subprocess.run(['nvcc', '--version'], capture_output=True, text=True)
        if result.returncode == 0:
            print("✓ CUDA compiler (nvcc) found:")
            print(result.stdout)
            return True
        else:
            print("✗ nvcc not found")
            return False
    except FileNotFoundError:
        print("✗ nvcc not found - CUDA Toolkit may not be installed")
        return False
    except Exception as e:
        print(f"✗ Error checking CUDA compiler: {e}")
        return False

def check_opencv():
    """Check OpenCV installation and CUDA support."""
    try:
        import cv2
        print(f"✓ OpenCV version: {cv2.__version__}")
        
        # Check for CUDA support
        cuda_devices = 0
        has_cuda_support = False
        
        if hasattr(cv2, 'cuda'):
            print("✓ cv2.cuda module available")
            if hasattr(cv2.cuda, 'getCudaEnabledDeviceCount'):
                try:
                    cuda_devices = cv2.cuda.getCudaEnabledDeviceCount()
                    print(f"✓ CUDA-enabled devices: {cuda_devices}")
                    has_cuda_support = cuda_devices > 0
                except Exception as e:
                    print(f"✗ Error getting CUDA device count: {e}")
        else:
            print("✗ cv2.cuda module not available (OpenCV built without CUDA support)")
        
        if has_cuda_support:
            print("✓ OpenCV is compiled with CUDA support!")
            return True
        else:
            print("✗ OpenCV compiled without CUDA support (CPU-only)")
            return False
            
    except ImportError:
        print("✗ OpenCV not installed")
        return None
    except Exception as e:
        print(f"✗ Error checking OpenCV: {e}")
        return False

def main():
    print("="*60)
    print("CUDA Detection and Compatibility Check")
    print("="*60)
    
    # Check NVIDIA driver
    print("\n[1] Checking NVIDIA Driver...")
    has_driver = check_nvidia_driver()
    
    # Check CUDA compiler
    print("\n[2] Checking CUDA Toolkit...")
    has_cuda = check_cuda_compiler()
    
    # Check OpenCV
    print("\n[3] Checking OpenCV Installation...")
    opencv_cuda = check_opencv()
    
    # Summary
    print("\n" + "="*60)
    print("Summary:")
    print("="*60)
    
    if has_driver and has_cuda and opencv_cuda:
        print("✓ Full CUDA support available!")
        print("  You can use GPU-accelerated OpenCV functions")
        print("\nTo use CUDA in your code:")
        print("  import cv2")
        print("  # Upload image to GPU")
        print("  gpu_frame = cv2.cuda_GpuMat()")
        print("  gpu_frame.upload(frame)")
    elif has_driver and has_cuda:
        print("✓ CUDA installed, but OpenCV needs to be rebuilt with CUDA support")
        print("  Run: bash setup_cuda_opencv.sh")
        print("  Select option 1 to build OpenCV with CUDA support")
    elif has_driver:
        print("⚠ NVIDIA driver found, but CUDA Toolkit not installed")
        print("  Install CUDA Toolkit from: https://developer.nvidia.com/cuda-downloads")
    elif opencv_cuda is False:
        print("✗ OpenCV installed (CPU-only)")
        print("  Your video analysis will work but won't use GPU acceleration")
        print("  For GPU support, install CUDA and rebuild OpenCV")
    else:
        print("✗ No CUDA support detected")
        print("  Install NVIDIA drivers and CUDA Toolkit for GPU acceleration")
    
    print("="*60)

if __name__ == "__main__":
    main()