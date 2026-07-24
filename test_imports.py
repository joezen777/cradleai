#!/usr/bin/env python3
"""
Simple test for GCP Vision API connection
"""

import sys
import os

# Try to import key modules
try:
    import google.generativeai as genai
    print("✓ google.generativeai imported successfully")
except ImportError as e:
    print(f"✗ Failed to import google.generativeai: {e}")
    sys.exit(1)

try:
    from PIL import Image
    print("✓ PIL imported successfully")
except ImportError as e:
    print(f"✗ Failed to import PIL: {e}")
    sys.exit(1)

try:
    import json
    print("✓ json imported successfully")
except ImportError as e:
    print(f"✗ Failed to import json: {e}")

# Try to load credentials
print("\nChecking credentials...")
cred_file = ".credentials"
if os.path.exists(cred_file):
    print(f"✓ Credentials file found: {cred_file}")
    with open(cred_file, 'r') as f:
        content = f.read()
        print(f"  Content preview: {content[:100]}...")
else:
    print(f"✗ Credentials file not found: {cred_file}")
    sys.exit(1)

# Check metadata file
metadata_file = "output/metadata.jsonl"
if os.path.exists(metadata_file):
    print(f"\n✓ Metadata file found: {metadata_file}")
    with open(metadata_file, 'r') as f:
        first_line = f.readline()
        print(f"  First entry: {first_line[:100]}...")
else:
    print(f"✗ Metadata file not found: {metadata_file}")

print("\n✓ All basic imports and checks passed!")
print("Ready to test GCP Vision API connection.")