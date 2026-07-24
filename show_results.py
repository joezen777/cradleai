#!/usr/bin/env python3
"""
Results Summary Script for Video Scene Analysis
Shows statistics and sample data from the analysis.
"""

import json
from pathlib import Path
from collections import Counter


def main():
    metadata_file = Path("output/metadata.jsonl")
    
    if not metadata_file.exists():
        print("✗ Analysis results not found. Run video_scene_analyzer.py first.")
        return
    
    print("="*60)
    print("Video Scene Analysis Results")
    print("="*60)
    
    # Read metadata
    with open(metadata_file, 'r') as f:
        main_metadata = json.loads(f.readline())
        scene_entries = [json.loads(line) for line in f]
    
    # Display main information
    print(f"\nVideo: {main_metadata['video_file']}")
    print(f"Resolution: {main_metadata['resolution']}")
    print(f"Duration: {main_metadata['duration']:.2f} seconds ({main_metadata['total_frames']} frames)")
    print(f"FPS: {main_metadata['fps']:.1f}")
    print(f"Total Scenes Detected: {main_metadata['total_scenes']}")
    
    # Calculate scene statistics
    durations = [scene['duration'] for scene in scene_entries]
    frame_counts = [scene['end_frame'] - scene['start_frame'] + 1 for scene in scene_entries]
    
    print(f"\nScene Statistics:")
    print(f"  Average Duration: {sum(durations)/len(durations):.2f} seconds")
    print(f"  Shortest Scene: {min(durations):.2f} seconds")
    print(f"  Longest Scene: {max(durations):.2f} seconds")
    print(f"  Average Frames per Scene: {sum(frame_counts)/len(frame_counts):.0f}")
    print(f"  Scene Duration Distribution:")
    
    # Duration categories
    duration_categories = Counter()
    for duration in durations:
        if duration < 2:
            duration_categories['< 2s'] += 1
        elif duration < 5:
            duration_categories['2-5s'] += 1
        elif duration < 10:
            duration_categories['5-10s'] += 1
        elif duration < 30:
            duration_categories['10-30s'] += 1
        else:
            duration_categories['> 30s'] += 1
    
    for category, count in sorted(duration_categories.items()):
        percentage = (count / len(scene_entries)) * 100
        print(f"    {category}: {count} scenes ({percentage:.1f}%)")
    
    # Check output files
    print(f"\nOutput Files:")
    audio_file = Path("output/audio.wav")
    clips_dir = Path("output/clips")
    frames_dir = Path("output/frames")
    
    print(f"  Audio: {'✓' if audio_file.exists() else '✗'} {audio_file}")
    print(f"  Audio Size: {audio_file.stat().st_size / 1024 / 1024:.1f} MB" if audio_file.exists() else "")
    print(f"  Clips Directory: {len(list(clips_dir.glob('*.webm')))} files")
    print(f"  Frames Directory: {len(list(frames_dir.glob('*.png')))} files")
    
    # Show sample scenes
    print(f"\nSample Scenes (First 10):")
    print(f"  {'Scene':<6} {'Start':<10} {'End':<10} {'Duration':<10} {'Clip File':<20}")
    print(f"  {'-'*6} {'-'*10} {'-'*10} {'-'*10} {'-'*20}")
    
    for scene in scene_entries[:10]:
        print(f"  {scene['scene_index']:<6} {scene['start_time']:<10.2f} {scene['end_time']:<10.2f} {scene['duration']:<10.2f} {scene['clip_file']:<20}")
    
    # Show longest scenes
    print(f"\nLongest Scenes (Top 5):")
    sorted_by_duration = sorted(scene_entries, key=lambda x: x['duration'], reverse=True)
    for i, scene in enumerate(sorted_by_duration[:5], 1):
        print(f"  {i}. Scene {scene['scene_index']}: {scene['duration']:.2f}s "
              f"({scene['start_time']:.2f}s - {scene['end_time']:.2f}s)")
    
    # Show shortest scenes  
    print(f"\nShortest Scenes (Top 5):")
    sorted_by_duration = sorted(scene_entries, key=lambda x: x['duration'])
    for i, scene in enumerate(sorted_by_duration[:5], 1):
        print(f"  {i}. Scene {scene['scene_index']}: {scene['duration']:.2f}s "
              f"({scene['start_time']:.2f}s - {scene['end_time']:.2f}s)")
    
    # Calculate total disk usage
    clips_size = sum(f.stat().st_size for f in clips_dir.glob('*.webm')) / 1024 / 1024
    frames_size = sum(f.stat().st_size for f in frames_dir.glob('*.png')) / 1024 / 1024
    total_size = clips_size + frames_size + (audio_file.stat().st_size / 1024 / 1024 if audio_file.exists() else 0)
    
    print(f"\nDisk Usage:")
    print(f"  Clips: {clips_size:.1f} MB")
    print(f"  Frames: {frames_size:.1f} MB") 
    print(f"  Audio: {audio_file.stat().st_size / 1024 / 1024:.1f} MB" if audio_file.exists() else "")
    print(f"  Total: {total_size:.1f} MB")
    
    print(f"\n✓ Analysis Complete!")
    print(f"All data is organized in the 'output/' directory for easy reconstruction.")
    print(f"The metadata.jsonl file contains all timing and file information.")
    print("="*60)


if __name__ == "__main__":
    main()