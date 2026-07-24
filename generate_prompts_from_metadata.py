#!/usr/bin/env python3
"""
Phase 1: Generate prompts from GCP Vision API for all frames in metadata.jsonl
Creates multiple entries per frame with different gen_sequence values
"""

import json
import time
import random
from pathlib import Path
from typing import Dict, List, Set
from datetime import datetime
from gcp_vision_prompt import GCPVisionPrompter


class PromptGenerationPhase1:
    """Phase 1: Generate prompts using GCP Vision API with exponential backoff"""
    
    def __init__(
        self,
        metadata_file: str = "output/metadata.jsonl",
        metadatagen_file: str = "output/metadatagen.jsonl",
        batch_name: str = "zimageturbo",
        num_copies: int = 10
    ):
        """
        Initialize Phase 1 processor
        
        Args:
            metadata_file: Input metadata file with scene information
            metadatagen_file: Output file for generated metadata
            batch_name: Batch name for all generations
            num_copies: Number of copies per frame (gen_sequence values)
        """
        self.metadata_file = metadata_file
        self.metadatagen_file = metadatagen_file
        self.batch_name = batch_name
        self.num_copies = num_copies
        self.gcp_prompter = GCPVisionPrompter()
        
        # Create output directory if needed
        Path(metadatagen_file).parent.mkdir(parents=True, exist_ok=True)
    
    def _load_metadata(self) -> List[Dict]:
        """Load scenes from metadata.jsonl"""
        scenes = []
        with open(self.metadata_file, 'r') as f:
            for line in f:
                try:
                    data = json.loads(line)
                    if 'scene_index' in data:
                        scenes.append(data)
                except json.JSONDecodeError:
                    continue
        return scenes
    
    def _get_processed_frames(self) -> Set[str]:
        """Get set of frame files already processed"""
        processed = set()
        if Path(self.metadatagen_file).exists():
            with open(self.metadatagen_file, 'r') as f:
                for line in f:
                    try:
                        data = json.loads(line)
                        frame_file = data.get('frame_file')
                        if frame_file:
                            processed.add(frame_file)
                    except json.JSONDecodeError:
                        continue
        return processed
    
    def _get_unique_frames(self, scenes: List[Dict]) -> List[Dict]:
        """Get unique frame files from scenes (first_frame_file and last_frame_file)"""
        seen_frames = set()
        unique_frames = []
        
        for scene in scenes:
            for frame_type in ['first_frame_file', 'last_frame_file']:
                frame_file = scene.get(frame_type)
                if frame_file and frame_file not in seen_frames:
                    seen_frames.add(frame_file)
                    unique_frames.append({
                        'scene': scene,
                        'frame_type': frame_type,
                        'frame_file': frame_file
                    })
        
        return unique_frames
    
    def _call_gcp_with_backoff(self, frame_path: str, max_retries: int = 5) -> Dict:
        """
        Call GCP Vision API with exponential backoff retry
        
        Args:
            frame_path: Path to frame image
            max_retries: Maximum number of retry attempts
            
        Returns:
            GCP API response
        """
        base_delay = 1.0  # Initial delay in seconds
        max_delay = 60.0  # Maximum delay in seconds
        
        for attempt in range(max_retries):
            try:
                print(f"  Attempt {attempt + 1}/{max_retries} for {frame_path}")
                result = self.gcp_prompter.generate_prompt(frame_path)
                
                if result["success"]:
                    return result
                else:
                    error = result.get('error', 'Unknown error')
                    # Check if error is rate limiting
                    if '429' in str(error) or 'rate limit' in error.lower():
                        print(f"  Rate limited: {error}")
                        raise Exception(f"Rate limit: {error}")
                    else:
                        print(f"  API error: {error}")
                        # Don't retry on permanent errors
                        if '401' in str(error) or '403' in str(error):
                            raise Exception(f"Permanent error: {error}")
                        
            except Exception as e:
                if attempt == max_retries - 1:
                    raise
                
                # Calculate exponential backoff with jitter
                delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
                print(f"  Retrying in {delay:.1f} seconds...")
                time.sleep(delay)
        
        return {"success": False, "error": "Max retries exceeded"}
    
    def _write_metadata_entries(self, entries: List[Dict]):
        """Write metadata entries to file"""
        with open(self.metadatagen_file, 'a') as f:
            for entry in entries:
                f.write(json.dumps(entry) + '\n')
    
    def process_all_frames(
        self, 
        max_frames: int = None,
        resume: bool = True
    ) -> Dict:
        """
        Process all frames to generate prompts
        
        Args:
            max_frames: Maximum number of frames to process (for testing)
            resume: Whether to resume from existing metadatagen file
            
        Returns:
            Processing results
        """
        print("="*80)
        print("PHASE 1: Generating prompts from GCP Vision API")
        print("="*80)
        
        # Load scenes
        print(f"\nLoading scenes from {self.metadata_file}...")
        scenes = self._load_metadata()
        print(f"Found {len(scenes)} scenes")
        
        # Get unique frames
        print("\nExtracting unique frames...")
        unique_frames = self._get_unique_frames(scenes)
        print(f"Found {len(unique_frames)} unique frames to process")
        
        # Get already processed frames if resuming
        processed_frames = set()
        if resume:
            processed_frames = self._get_processed_frames()
            print(f"Found {len(processed_frames)} already processed frames")
        
        # Filter to process only unprocessed frames
        frames_to_process = [f for f in unique_frames 
                           if f['frame_file'] not in processed_frames]
        
        # Apply max_frames limit if specified
        if max_frames:
            frames_to_process = frames_to_process[:max_frames]
        
        print(f"\nWill process {len(frames_to_process)} frames ({self.num_copies} copies each)")
        
        if len(frames_to_process) == 0:
            print("No frames to process. Phase 1 complete!")
            return {
                "success": True,
                "total_frames": len(unique_frames),
                "processed_frames": len(processed_frames),
                "new_frames": 0
            }
        
        # Process frames
        successful = 0
        failed = 0
        last_successful_frame = None
        
        for i, frame_info in enumerate(frames_to_process, 1):
            scene = frame_info['scene']
            frame_type = frame_info['frame_type']
            frame_file = frame_info['frame_file']
            
            # Resolve frame path
            frame_path = Path("output") / frame_file.replace("\\", "/")
            if not frame_path.exists():
                frame_path = Path(frame_file)
            
            print(f"\n[{i}/{len(frames_to_process)}] Processing: {frame_file}")
            print(f"  Scene: {scene.get('scene_index')}, Type: {frame_type}")
            print(f"  Path: {frame_path}")
            
            if not frame_path.exists():
                print(f"  ⚠ Frame file not found, skipping")
                failed += 1
                continue
            
            try:
                # Call GCP Vision API with backoff
                gcp_result = self._call_gcp_with_backoff(str(frame_path))
                
                if gcp_result["success"]:
                    prompt_text = gcp_result["response_text"]
                    print(f"  ✓ Prompt generated ({len(prompt_text)} chars)")
                    
                    # Create multiple entries with different gen_sequence values
                    entries = []
                    for gen_sequence in range(1, self.num_copies + 1):
                        entry = {
                            "batch_name": self.batch_name,
                            "clip_file": scene.get('clip_file'),
                            "frame_file": frame_file,
                            "frame_type": frame_type,
                            "scene_index": scene.get('scene_index'),
                            "prompt_text": prompt_text,
                            "seed": None,  # Will be set in Phase 2
                            "similarity_score": None,  # Will be set in Phase 2
                            "gen_sequence": gen_sequence,
                            "gen_filename": None,  # Will be set in Phase 2
                            "timestamp": datetime.now().isoformat(),
                            "gcp_success": True,
                            "gcp_error": None
                        }
                        entries.append(entry)
                    
                    # Write entries to file
                    self._write_metadata_entries(entries)
                    
                    successful += 1
                    last_successful_frame = frame_file
                    print(f"  ✓ Created {len(entries)} metadata entries")
                    
                else:
                    error = gcp_result.get('error', 'Unknown error')
                    print(f"  ✗ Failed: {error}")
                    
                    # Create error entries for all gen_sequence values
                    entries = []
                    for gen_sequence in range(1, self.num_copies + 1):
                        entry = {
                            "batch_name": self.batch_name,
                            "clip_file": scene.get('clip_file'),
                            "frame_file": frame_file,
                            "frame_type": frame_type,
                            "scene_index": scene.get('scene_index'),
                            "prompt_text": None,
                            "seed": None,
                            "similarity_score": None,
                            "gen_sequence": gen_sequence,
                            "gen_filename": None,
                            "timestamp": datetime.now().isoformat(),
                            "gcp_success": False,
                            "gcp_error": error
                        }
                        entries.append(entry)
                    
                    self._write_metadata_entries(entries)
                    failed += 1
                    
            except Exception as e:
                print(f"  ✗ Exception: {e}")
                
                # Create error entries
                entries = []
                for gen_sequence in range(1, self.num_copies + 1):
                    entry = {
                        "batch_name": self.batch_name,
                        "clip_file": scene.get('clip_file'),
                        "frame_file": frame_file,
                        "frame_type": frame_type,
                        "scene_index": scene.get('scene_index'),
                        "prompt_text": None,
                        "seed": None,
                        "similarity_score": None,
                        "gen_sequence": gen_sequence,
                        "gen_filename": None,
                        "timestamp": datetime.now().isoformat(),
                        "gcp_success": False,
                        "gcp_error": str(e)
                    }
                    entries.append(entry)
                
                self._write_metadata_entries(entries)
                failed += 1
        
        # Summary
        print("\n" + "="*80)
        print("PHASE 1 COMPLETE")
        print("="*80)
        print(f"Total unique frames: {len(unique_frames)}")
        print(f"Successfully processed: {successful}")
        print(f"Failed: {failed}")
        print(f"Total entries created: {(successful + failed) * self.num_copies}")
        print(f"Output file: {self.metadatagen_file}")
        
        if last_successful_frame:
            print(f"Last successful frame: {last_successful_frame}")
        
        return {
            "success": failed == 0,
            "total_frames": len(unique_frames),
            "processed_frames": len(processed_frames),
            "new_frames": len(frames_to_process),
            "successful": successful,
            "failed": failed,
            "last_successful_frame": last_successful_frame
        }


def main():
    """Main function for command-line usage"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Phase 1: Generate prompts from GCP Vision API")
    parser.add_argument("--metadata", default="output/metadata.jsonl", help="Input metadata file")
    parser.add_argument("--metadatagen", default="output/metadatagen.jsonl", help="Output metadata file")
    parser.add_argument("--batch_name", default="zimageturbo", help="Batch name")
    parser.add_argument("--num_copies", type=int, default=10, help="Number of copies per frame")
    parser.add_argument("--max_frames", type=int, help="Maximum frames to process (for testing)")
    parser.add_argument("--no_resume", action="store_true", help="Don't resume from existing file")
    
    args = parser.parse_args()
    
    processor = PromptGenerationPhase1(
        metadata_file=args.metadata,
        metadatagen_file=args.metadatagen,
        batch_name=args.batch_name,
        num_copies=args.num_copies
    )
    
    result = processor.process_all_frames(
        max_frames=args.max_frames,
        resume=not args.no_resume
    )
    
    return 0 if result["success"] else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())