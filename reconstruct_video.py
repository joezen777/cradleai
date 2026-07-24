#!/usr/bin/env python3
"""
Video Reconstruction Script
Demonstrates how to reconstruct the original video using the metadata and clips.
"""

import json
import subprocess
from pathlib import Path


def reconstruct_video(output_file="reconstructed_video.mp4"):
    """
    Reconstruct the video by concatenating all clips in order.
    """
    metadata_file = Path("output/metadata.jsonl")
    
    if not metadata_file.exists():
        print("✗ Metadata file not found. Run video_scene_analyzer.py first.")
        return False
    
    print("="*60)
    print("Video Reconstruction")
    print("="*60)
    
    # Read metadata
    with open(metadata_file, 'r') as f:
        lines = f.readlines()
        main_metadata = json.loads(lines[0])
        scene_entries = [json.loads(line) for line in lines[1:]]
    
    print(f"\nVideo Information:")
    print(f"  Original: {main_metadata['video_file']}")
    print(f"  Scenes: {main_metadata['total_scenes']}")
    print(f"  Duration: {main_metadata['duration']:.2f}s")
    
    # Create file list for ffmpeg concat
    concat_file = Path("output/concat_list.txt")
    with open(concat_file, 'w') as f:
        for scene in scene_entries:
            clip_path = Path("output") / scene['clip_file']
            if clip_path.exists():
                f.write(f"file '{clip_path.absolute()}'\n")
            else:
                print(f"Warning: Clip not found: {clip_path}")
                return False
    
    print(f"\nReconstructing video to: {output_file}")
    print("This may take a few minutes...")
    
    # Use ffmpeg to concatenate clips
    try:
        cmd = [
            'ffmpeg', '-f', 'concat', '-safe', '0',
            '-i', str(concat_file),
            '-c', 'copy',  # Copy streams without re-encoding
            '-y',
            output_file
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"✓ Video reconstructed successfully: {output_file}")
            
            # Get file size
            output_size = Path(output_file).stat().st_size / 1024 / 1024
            print(f"  File size: {output_size:.1f} MB")
            
            return True
        else:
            print(f"✗ Error reconstructing video: {result.stderr}")
            return False
            
    except FileNotFoundError:
        print("✗ ffmpeg not found. Please install ffmpeg.")
        return False


def create_scene_report():
    """
    Create a human-readable report of all scenes.
    """
    metadata_file = Path("output/metadata.jsonl")
    
    if not metadata_file.exists():
        print("✗ Metadata file not found.")
        return False
    
    print("\n" + "="*60)
    print("Scene Report")
    print("="*60)
    
    # Read metadata
    with open(metadata_file, 'r') as f:
        lines = f.readlines()
        scene_entries = [json.loads(line) for line in lines[1:]]
    
    report_file = Path("output/scene_report.txt")
    
    with open(report_file, 'w') as f:
        f.write("="*60 + "\n")
        f.write("Video Scene Analysis Report\n")
        f.write("="*60 + "\n\n")
        
        f.write(f"Total Scenes: {len(scene_entries)}\n\n")
        
        f.write("Scene Details:\n")
        f.write("-" * 60 + "\n")
        f.write(f"{'Scene':<6} {'Start':<10} {'End':<10} {'Duration':<10} {'Frames':<10}\n")
        f.write("-" * 60 + "\n")
        
        for scene in scene_entries:
            frame_count = scene['end_frame'] - scene['start_frame'] + 1
            f.write(f"{scene['scene_index']:<6} "
                   f"{scene['start_time']:<10.2f} "
                   f"{scene['end_time']:<10.2f} "
                   f"{scene['duration']:<10.2f} "
                   f"{frame_count:<10}\n")
    
    print(f"✓ Scene report created: {report_file}")
    return True


def show_metadata_examples():
    """
    Show how to use the metadata for various operations.
    """
    metadata_file = Path("output/metadata.jsonl")
    
    if not metadata_file.exists():
        print("✗ Metadata file not found.")
        return False
    
    print("\n" + "="*60)
    print("Metadata Usage Examples")
    print("="*60)
    
    # Read metadata
    with open(metadata_file, 'r') as f:
        lines = f.readlines()
        main_metadata = json.loads(lines[0])
        scene_entries = [json.loads(line) for line in lines[1:]]
    
    print("\n1. Access scene by time:")
    target_time = 100.0  # 100 seconds into video
    for scene in scene_entries:
        if scene['start_time'] <= target_time <= scene['end_time']:
            print(f"   Scene at {target_time}s: Scene {scene['scene_index']}")
            print(f"   Clip: {scene['clip_file']}")
            print(f"   Frames: {scene['first_frame_file']} to {scene['last_frame_file']}")
            break
    
    print("\n2. Get scene by index:")
    scene_num = 100
    scene = next((s for s in scene_entries if s['scene_index'] == scene_num), None)
    if scene:
        print(f"   Scene {scene_num}:")
        print(f"   Time: {scene['start_time']:.2f}s - {scene['end_time']:.2f}s")
        print(f"   Duration: {scene['duration']:.2f}s")
        print(f"   Clip file: {scene['clip_file']}")
    
    print("\n3. Find scenes longer than 30 seconds:")
    long_scenes = [s for s in scene_entries if s['duration'] > 30]
    print(f"   Found {len(long_scenes)} scenes longer than 30 seconds:")
    for scene in long_scenes[:5]:  # Show first 5
        print(f"   - Scene {scene['scene_index']}: {scene['duration']:.2f}s")
    
    print("\n4. Find scenes shorter than 2 seconds:")
    short_scenes = [s for s in scene_entries if s['duration'] < 2]
    print(f"   Found {len(short_scenes)} scenes shorter than 2 seconds:")
    for scene in short_scenes[:5]:  # Show first 5
        print(f"   - Scene {scene['scene_index']}: {scene['duration']:.2f}s")
    
    print("\n5. Access first/last frames:")
    print(f"   First scene (Scene 1):")
    first_scene = scene_entries[0]
    print(f"   First frame: {first_scene['first_frame_file']}")
    print(f"   Last frame: {first_scene['last_frame_file']}")
    
    print(f"\n   Last scene (Scene {len(scene_entries)}):")
    last_scene = scene_entries[-1]
    print(f"   First frame: {last_scene['first_frame_file']}")
    print(f"   Last frame: {last_scene['last_frame_file']}")


def main():
    """Main function with menu options."""
    import sys
    
    print("="*60)
    print("Video Reconstruction and Metadata Tools")
    print("="*60)
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "reconstruct":
            reconstruct_video()
        elif command == "report":
            create_scene_report()
        elif command == "examples":
            show_metadata_examples()
        elif command == "all":
            reconstruct_video()
            create_scene_report()
            show_metadata_examples()
        else:
            print("Unknown command. Available: reconstruct, report, examples, all")
    else:
        print("\nAvailable commands:")
        print("  python reconstruct_video.py reconstruct  - Reconstruct video from clips")
        print("  python reconstruct_video.py report       - Create scene report")
        print("  python reconstruct_video.py examples     - Show metadata usage examples")
        print("  python reconstruct_video.py all          - Run all operations")
        print("\nExample: python reconstruct_video.py all")


if __name__ == "__main__":
    main()