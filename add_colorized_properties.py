#!/usr/bin/env python3
"""
Add colorized frame properties to metadata database
Adds four new properties to each scene object in metadata.jsonl
"""

import json
from pathlib import Path
import shutil


def add_colorized_properties():
    """Add colorized frame properties to all scene entries in metadata"""
    
    metadata_file = Path("output/metadata.jsonl")
    backup_file = Path("output/metadata.jsonl.backup")
    
    # Create backup
    print("Creating backup of original metadata file...")
    shutil.copy2(metadata_file, backup_file)
    print(f"✓ Backup created: {backup_file}")
    
    # Read existing metadata
    print("Reading metadata file...")
    with open(metadata_file, 'r') as f:
        lines = f.readlines()
    
    # Parse first line (main metadata)
    main_metadata = json.loads(lines[0])
    
    # Parse scene entries (lines 1+)
    scene_entries = [json.loads(line) for line in lines[1:]]
    
    print(f"Found {len(scene_entries)} scene entries")
    
    # Define new properties to add
    new_properties = {
        'colorizedFirstFrame': None,
        'colorizedLastFrame': None,
        'colorizedWithContextFirstFrame': None,
        'colorizedWithContextLastFrame': None
    }
    
    # Update main metadata scenes array
    if 'scenes' in main_metadata:
        print("Updating scenes array in main metadata...")
        for scene in main_metadata['scenes']:
            scene.update(new_properties)
    
    # Update individual scene entries
    print("Updating individual scene entries...")
    updated_entries = []
    for scene in scene_entries:
        # Add new properties
        updated_scene = {**scene, **new_properties}
        updated_entries.append(updated_scene)
    
    # Write updated metadata
    print("Writing updated metadata file...")
    with open(metadata_file, 'w') as f:
        # Write main metadata
        f.write(json.dumps(main_metadata) + '\n')
        
        # Write individual scene entries
        for scene in updated_entries:
            f.write(json.dumps(scene) + '\n')
    
    print(f"✓ Metadata file updated successfully")
    print(f"✓ Added 4 new properties to {len(updated_entries)} scenes")
    
    return True


def verify_update():
    """Verify that the new properties were added correctly"""
    
    metadata_file = Path("output/metadata.jsonl")
    
    print("\nVerifying update...")
    
    with open(metadata_file, 'r') as f:
        lines = f.readlines()
    
    # Check main metadata
    main_metadata = json.loads(lines[0])
    if 'scenes' in main_metadata and len(main_metadata['scenes']) > 0:
        first_scene = main_metadata['scenes'][0]
        required_props = ['colorizedFirstFrame', 'colorizedLastFrame', 
                         'colorizedWithContextFirstFrame', 'colorizedWithContextLastFrame']
        
        all_present = all(prop in first_scene for prop in required_props)
        
        if all_present:
            print("✓ Main metadata scenes array updated correctly")
        else:
            print("✗ Some properties missing from main metadata")
            return False
    
    # Check individual entries
    scene_entries = [json.loads(line) for line in lines[1:]]
    sample_scene = scene_entries[0] if scene_entries else None
    
    if sample_scene:
        required_props = ['colorizedFirstFrame', 'colorizedLastFrame', 
                         'colorizedWithContextFirstFrame', 'colorizedWithContextLastFrame']
        
        all_present = all(prop in sample_scene for prop in required_props)
        
        if all_present:
            print("✓ Individual scene entries updated correctly")
            print(f"✓ Sample scene properties:")
            for prop in required_props:
                value = sample_scene.get(prop)
                print(f"    {prop}: {value}")
        else:
            print("✗ Some properties missing from scene entries")
            return False
    
    # Check total count
    print(f"✓ Total scene entries: {len(scene_entries)}")
    
    return True


def show_sample_structure():
    """Show the updated structure of a sample scene entry"""
    
    metadata_file = Path("output/metadata.jsonl")
    
    print("\n" + "="*60)
    print("Updated Scene Entry Structure")
    print("="*60)
    
    with open(metadata_file, 'r') as f:
        lines = f.readlines()
    
    # Show first scene entry as example
    scene_entries = [json.loads(line) for line in lines[1:]]
    if scene_entries:
        sample_scene = scene_entries[0]
        
        print("\nSample Scene Entry (Scene 1):")
        print(json.dumps(sample_scene, indent=2))
        
        print("\n" + "="*60)
        print("New Properties Added:")
        print("="*60)
        print("1. colorizedFirstFrame - Colorized version of first frame")
        print("2. colorizedLastFrame - Colorized version of last frame")
        print("3. colorizedWithContextFirstFrame - First frame with context visualization")
        print("4. colorizedWithContextLastFrame - Last frame with context visualization")
        print("\nAll initialized to None - ready to be populated with actual file paths")


def main():
    """Main function"""
    
    print("="*60)
    print("Add Colorized Properties to Metadata")
    print("="*60)
    
    # Check if metadata file exists
    metadata_file = Path("output/metadata.jsonl")
    if not metadata_file.exists():
        print("✗ Metadata file not found. Run video_scene_analyzer.py first.")
        return False
    
    try:
        # Add new properties
        success = add_colorized_properties()
        
        if success:
            # Verify the update
            verify_update()
            
            # Show sample structure
            show_sample_structure()
            
            print("\n" + "="*60)
            print("✓ Process Complete!")
            print("="*60)
            print("\nThe metadata file has been updated with 4 new properties:")
            print("  - colorizedFirstFrame")
            print("  - colorizedLastFrame")
            print("  - colorizedWithContextFirstFrame")
            print("  - colorizedWithContextLastFrame")
            print("\nOriginal file backed up to: output/metadata.jsonl.backup")
            print("\nThese properties are now ready to be populated with actual")
            print("file paths or data for colorized frame visualizations.")
            
            return True
        else:
            print("\n✗ Process failed")
            return False
            
    except Exception as e:
        print(f"\n✗ Error: {str(e)}")
        
        # Restore from backup if error occurred
        backup_file = Path("output/metadata.jsonl.backup")
        if backup_file.exists():
            print("Restoring from backup...")
            shutil.copy2(backup_file, metadata_file)
            print("✓ Restored original metadata file")
        
        return False


if __name__ == "__main__":
    main()