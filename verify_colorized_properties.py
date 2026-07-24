#!/usr/bin/env python3
"""
Quick verification script for colorized properties in metadata
"""

import json
from pathlib import Path

def main():
    metadata_file = Path("output/metadata.jsonl")
    
    print("Verifying colorized properties in metadata...")
    print("="*60)
    
    with open(metadata_file, 'r') as f:
        lines = f.readlines()
    
    # Check main metadata
    main_metadata = json.loads(lines[0])
    if 'scenes' in main_metadata:
        sample_main_scene = main_metadata['scenes'][0]
        required_props = ['colorizedFirstFrame', 'colorizedLastFrame', 
                         'colorizedWithContextFirstFrame', 'colorizedWithContextLastFrame']
        main_has_all = all(prop in sample_main_scene for prop in required_props)
        print(f"Main metadata scenes array: {'✓ All properties present' if main_has_all else '✗ Missing properties'}")
    
    # Check individual entries
    scene_entries = [json.loads(line) for line in lines[1:]]
    required_props = ['colorizedFirstFrame', 'colorizedLastFrame', 
                     'colorizedWithContextFirstFrame', 'colorizedWithContextLastFrame']
    
    print(f"\nChecking {len(scene_entries)} scene entries...")
    
    # Check specific scenes
    test_scenes = [1, 50, 100, 500, 830]
    for scene_num in test_scenes:
        scene = next((s for s in scene_entries if s['scene_index'] == scene_num), None)
        if scene:
            has_all = all(prop in scene for prop in required_props)
            print(f"Scene {scene_num:3d}: {'✓' if has_all else '✗'}")
        else:
            print(f"Scene {scene_num:3d}: ✗ Not found")
    
    # Summary
    all_valid = True
    for scene in scene_entries:
        if not all(prop in scene for prop in required_props):
            all_valid = False
            break
    
    print("\n" + "="*60)
    print(f"Overall Status: {'✓ All scenes have colorized properties' if all_valid else '✗ Some scenes missing properties'}")
    print("="*60)

if __name__ == "__main__":
    main()