#!/usr/bin/env python3
"""
Display the complete structure of metadata entries with new properties
"""

import json
from pathlib import Path

def main():
    metadata_file = Path("output/metadata.jsonl")
    
    print("="*60)
    print("Metadata Structure with New Colorized Properties")
    print("="*60)
    
    with open(metadata_file, 'r') as f:
        lines = f.readlines()
    
    # Show main metadata structure
    main_metadata = json.loads(lines[0])
    print("\nMain Metadata Keys:")
    main_keys = list(main_metadata.keys())
    for key in main_keys:
        value = main_metadata[key]
        if isinstance(value, (list, dict)):
            print(f"  {key}: {type(value).__name__} (length: {len(value)})")
        else:
            print(f"  {key}: {value}")
    
    # Show sample scene structure
    scene_entries = [json.loads(line) for line in lines[1:]]
    
    print("\n" + "="*60)
    print("Complete Scene Entry Structure (Scene 1):")
    print("="*60)
    
    if scene_entries:
        sample_scene = scene_entries[0]
        print(json.dumps(sample_scene, indent=2))
    
    # Show property summary
    print("\n" + "="*60)
    print("Property Summary:")
    print("="*60)
    
    original_props = [
        'scene_index', 'clip_file', 'first_frame_file', 'last_frame_file',
        'start_time', 'end_time', 'duration', 'start_frame', 'end_frame'
    ]
    
    new_props = [
        'colorizedFirstFrame', 'colorizedLastFrame',
        'colorizedWithContextFirstFrame', 'colorizedWithContextLastFrame'
    ]
    
    print(f"\nOriginal Properties ({len(original_props)}):")
    for prop in original_props:
        print(f"  - {prop}")
    
    print(f"\nNew Colorized Properties ({len(new_props)}):")
    for prop in new_props:
        print(f"  - {prop}")
    
    print(f"\nTotal Properties per Scene: {len(original_props) + len(new_props)}")
    print(f"Total Scenes: {len(scene_entries)}")
    
    # Show file sizes
    metadata_size = metadata_file.stat().st_size
    backup_size = Path("output/metadata.jsonl.backup").stat().st_size
    
    print("\n" + "="*60)
    print("File Information:")
    print("="*60)
    print(f"Updated metadata.jsonl: {metadata_size:,} bytes ({metadata_size/1024:.1f} KB)")
    print(f"Backup metadata.jsonl.backup: {backup_size:,} bytes ({backup_size/1024:.1f} KB)")
    print(f"Size increase: {metadata_size - backup_size:,} bytes")

if __name__ == "__main__":
    main()