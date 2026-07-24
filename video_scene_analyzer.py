#!/usr/bin/env python3
"""
Video Scene Analyzer
Extracts audio, detects scene changes, extracts clips, and manages metadata.
"""

import json
import os
import subprocess
import cv2
import numpy as np
from pathlib import Path
from typing import List, Dict, Any
import shutil


class VideoSceneAnalyzer:
    def __init__(self, video_path: str, output_dir: str = "output"):
        self.video_path = Path(video_path)
        self.output_dir = Path(output_dir)
        self.metadata_file = self.output_dir / "metadata.jsonl"
        self.audio_file = self.output_dir / "audio.wav"
        self.clips_dir = self.output_dir / "clips"
        self.frames_dir = self.output_dir / "frames"
        
        # Create output directories
        self.output_dir.mkdir(exist_ok=True)
        self.clips_dir.mkdir(exist_ok=True)
        self.frames_dir.mkdir(exist_ok=True)
        
        # Video properties
        self.cap = cv2.VideoCapture(str(self.video_path))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.duration = self.total_frames / self.fps
        
        print(f"Video loaded: {self.video_path.name}")
        print(f"Resolution: {self.width}x{self.height}")
        print(f"FPS: {self.fps:.2f}")
        print(f"Duration: {self.duration:.2f}s ({self.total_frames} frames)")
    
    def extract_audio(self) -> Path:
        """Extract audio from video file using ffmpeg."""
        print(f"\nExtracting audio to: {self.audio_file}")
        
        try:
            # Use ffmpeg to extract audio
            cmd = [
                'ffmpeg', '-i', str(self.video_path),
                '-vn',  # No video
                '-acodec', 'pcm_s16le',  # Uncompressed audio
                '-ar', '44100',  # Sample rate
                '-ac', '2',  # Stereo
                '-y',  # Overwrite output file
                str(self.audio_file)
            ]
            
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                print(f"✓ Audio extracted successfully")
                return self.audio_file
            else:
                print(f"✗ Error extracting audio: {result.stderr}")
                raise Exception(f"Audio extraction failed: {result.stderr}")
                
        except FileNotFoundError:
            print("✗ ffmpeg not found. Please install ffmpeg.")
            raise
        except Exception as e:
            print(f"✗ Error extracting audio: {str(e)}")
            raise
    
    def detect_scene_changes(self, threshold: float = 30.0, min_scene_length: float = 1.0) -> List[Dict[str, Any]]:
        """
        Detect scene changes using histogram difference algorithm.
        
        Args:
            threshold: Difference threshold for scene change detection
            min_scene_length: Minimum scene length in seconds
        """
        print(f"\nDetecting scene changes (threshold={threshold}, min_scene_length={min_scene_length}s)...")
        
        scenes = []
        prev_frame = None
        prev_hist = None
        frame_num = 0
        min_frames = int(min_scene_length * self.fps)
        last_scene_start = 0
        
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
        
        while True:
            ret, frame = self.cap.read()
            if not ret:
                break
            
            # Convert to grayscale and calculate histogram
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            hist = cv2.calcHist([gray], [0], None, [256], [0, 256])
            hist = cv2.normalize(hist, hist).flatten()
            
            if prev_hist is not None:
                # Calculate histogram difference
                diff = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CHISQR)
                
                # Check if difference exceeds threshold and minimum scene length
                if diff > threshold and (frame_num - last_scene_start) >= min_frames:
                    start_time = last_scene_start / self.fps
                    end_time = frame_num / self.fps
                    
                    scene_info = {
                        'start_frame': last_scene_start,
                        'end_frame': frame_num - 1,
                        'start_time': round(start_time, 3),
                        'end_time': round(end_time, 3),
                        'duration': round(end_time - start_time, 3),
                        'scene_index': len(scenes) + 1
                    }
                    
                    scenes.append(scene_info)
                    last_scene_start = frame_num
                    
                    print(f"  Scene {len(scenes)}: {start_time:.2f}s - {end_time:.2f}s (diff: {diff:.2f})")
            
            prev_frame = frame
            prev_hist = hist
            frame_num += 1
            
            # Progress indicator
            if frame_num % 100 == 0:
                print(f"  Processing: {frame_num}/{self.total_frames} frames ({100*frame_num/self.total_frames:.1f}%)")
        
        # Add the last scene
        if last_scene_start < self.total_frames - 1:
            start_time = last_scene_start / self.fps
            end_time = self.total_frames / self.fps
            
            scene_info = {
                'start_frame': last_scene_start,
                'end_frame': self.total_frames - 1,
                'start_time': round(start_time, 3),
                'end_time': round(end_time, 3),
                'duration': round(end_time - start_time, 3),
                'scene_index': len(scenes) + 1
            }
            scenes.append(scene_info)
            print(f"  Scene {len(scenes)}: {start_time:.2f}s - {end_time:.2f}s (final scene)")
        
        print(f"\n✓ Detected {len(scenes)} scenes")
        return scenes
    
    def extract_clips(self, scenes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract video clips for each detected scene."""
        print(f"\nExtracting clips to: {self.clips_dir}")
        
        for scene in scenes:
            scene_index = scene['scene_index']
            start_time = scene['start_time']
            end_time = scene['end_time']
            duration = scene['duration']
            
            clip_filename = f"scene_{scene_index:03d}.webm"
            clip_path = self.clips_dir / clip_filename
            
            print(f"  Extracting scene {scene_index}: {start_time:.2f}s - {end_time:.2f}s (duration: {duration:.2f}s)")
            
            try:
                # Use ffmpeg to extract clip
                cmd = [
                    'ffmpeg', '-i', str(self.video_path),
                    '-ss', str(start_time),
                    '-t', str(duration),
                    '-c:v', 'copy',  # Copy video stream without re-encoding
                    '-c:a', 'copy',  # Copy audio stream without re-encoding
                    '-y',
                    str(clip_path)
                ]
                
                result = subprocess.run(cmd, capture_output=True, text=True)
                
                if result.returncode == 0:
                    scene['clip_file'] = str(clip_path.relative_to(self.output_dir))
                    print(f"    ✓ Saved: {clip_filename}")
                else:
                    print(f"    ✗ Error: {result.stderr}")
                    scene['clip_file'] = None
                    
            except Exception as e:
                print(f"    ✗ Error extracting scene {scene_index}: {str(e)}")
                scene['clip_file'] = None
        
        print(f"\n✓ Extracted {len(scenes)} clips")
        return scenes
    
    def extract_first_last_frames(self, scenes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Extract first and last frames for each scene."""
        print(f"\nExtracting first and last frames to: {self.frames_dir}")
        
        for scene in scenes:
            scene_index = scene['scene_index']
            start_frame = scene['start_frame']
            end_frame = scene['end_frame']
            
            first_frame_filename = f"scene_{scene_index:03d}_first_frame.png"
            last_frame_filename = f"scene_{scene_index:03d}_last_frame.png"
            
            first_frame_path = self.frames_dir / first_frame_filename
            last_frame_path = self.frames_dir / last_frame_filename
            
            print(f"  Processing scene {scene_index}: frames {start_frame} - {end_frame}")
            
            try:
                # Extract first frame
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
                ret, first_frame = self.cap.read()
                if ret:
                    cv2.imwrite(str(first_frame_path), first_frame)
                    scene['first_frame_file'] = str(first_frame_path.relative_to(self.output_dir))
                    print(f"    ✓ First frame: {first_frame_filename}")
                else:
                    scene['first_frame_file'] = None
                    print(f"    ✗ Error reading first frame")
                
                # Extract last frame
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, end_frame)
                ret, last_frame = self.cap.read()
                if ret:
                    cv2.imwrite(str(last_frame_path), last_frame)
                    scene['last_frame_file'] = str(last_frame_path.relative_to(self.output_dir))
                    print(f"    ✓ Last frame: {last_frame_filename}")
                else:
                    scene['last_frame_file'] = None
                    print(f"    ✗ Error reading last frame")
                    
            except Exception as e:
                print(f"    ✗ Error extracting frames for scene {scene_index}: {str(e)}")
                scene['first_frame_file'] = None
                scene['last_frame_file'] = None
        
        print(f"\n✓ Extracted frames for {len(scenes)} scenes")
        return scenes
    
    def save_metadata(self, scenes: List[Dict[str, Any]]) -> Path:
        """Save scene metadata to JSONL file."""
        print(f"\nSaving metadata to: {self.metadata_file}")
        
        # Create metadata entry for the entire analysis
        metadata = {
            'video_file': str(self.video_path),
            'total_scenes': len(scenes),
            'fps': self.fps,
            'total_frames': self.total_frames,
            'duration': self.duration,
            'resolution': f"{self.width}x{self.height}",
            'audio_file': str(self.audio_file.relative_to(self.output_dir)) if self.audio_file.exists() else None,
            'scenes': scenes
        }
        
        # Write to JSONL file (one JSON object per line)
        with open(self.metadata_file, 'w') as f:
            # Write main metadata as first line
            f.write(json.dumps(metadata) + '\n')
            
            # Write individual scene entries
            for scene in scenes:
                scene_entry = {
                    'scene_index': scene['scene_index'],
                    'clip_file': scene.get('clip_file'),
                    'first_frame_file': scene.get('first_frame_file'),
                    'last_frame_file': scene.get('last_frame_file'),
                    'start_time': scene['start_time'],
                    'end_time': scene['end_time'],
                    'duration': scene['duration'],
                    'start_frame': scene['start_frame'],
                    'end_frame': scene['end_frame']
                }
                f.write(json.dumps(scene_entry) + '\n')
        
        print(f"✓ Metadata saved ({len(scenes) + 1} entries)")
        return self.metadata_file
    
    def process_video(self, scene_threshold: float = 30.0, min_scene_length: float = 1.0) -> Path:
        """
        Process the entire video: extract audio, detect scenes, extract clips and frames.
        
        Args:
            scene_threshold: Threshold for scene change detection
            min_scene_length: Minimum scene length in seconds
        
        Returns:
            Path to the metadata file
        """
        try:
            # Step 1: Extract audio
            self.extract_audio()
            
            # Step 2: Detect scene changes
            scenes = self.detect_scene_changes(threshold=scene_threshold, min_scene_length=min_scene_length)
            
            # Step 3: Extract clips
            scenes = self.extract_clips(scenes)
            
            # Step 4: Extract first and last frames
            scenes = self.extract_first_last_frames(scenes)
            
            # Step 5: Save metadata
            metadata_path = self.save_metadata(scenes)
            
            print(f"\n{'='*60}")
            print(f"✓ Video processing complete!")
            print(f"  Total scenes: {len(scenes)}")
            print(f"  Metadata file: {metadata_path}")
            print(f"  Audio file: {self.audio_file}")
            print(f"  Clips directory: {self.clips_dir}")
            print(f"  Frames directory: {self.frames_dir}")
            print(f"{'='*60}")
            
            return metadata_path
            
        except Exception as e:
            print(f"\n✗ Error processing video: {str(e)}")
            raise
        finally:
            self.cap.release()


def main():
    """Main function to run the video scene analyzer."""
    video_path = "./CradleAnimatic.webm"
    output_dir = "output"
    
    print("="*60)
    print("Video Scene Analyzer")
    print("="*60)
    
    # Check if video file exists
    if not Path(video_path).exists():
        print(f"✗ Error: Video file not found: {video_path}")
        return
    
    # Create analyzer instance
    analyzer = VideoSceneAnalyzer(video_path, output_dir)
    
    # Process the video
    try:
        metadata_path = analyzer.process_video(
            scene_threshold=30.0,  # Adjust based on your video content
            min_scene_length=1.0   # Minimum 1 second per scene
        )
        print(f"\n✓ Analysis complete! Check {metadata_path} for results.")
        
    except Exception as e:
        print(f"\n✗ Analysis failed: {str(e)}")


if __name__ == "__main__":
    main()