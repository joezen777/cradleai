#!/usr/bin/env python3
"""
Phase 2: Generate images using Z-Image Turbo based on prompts from metadatagen.jsonl
Sequentially processes each generation and updates metadata with results
"""

import json
import os
import random
from pathlib import Path
from typing import Dict, List, Tuple
from datetime import datetime
from zimageturbo_batch_generator import ComfyUIWorkflowProcessor
import logging


class ImageGenerationPhase2:
    """Phase 2: Generate images using prompts from metadatagen.jsonl"""
    
    def __init__(
        self,
        metadatagen_file: str = "output/metadatagen.jsonl",
        workflow_file: str = "zimageturbo_cinematic.json",
        endpoint: str = "http://127.0.0.1:8188",
        log_file: str = "image_generation_errors.log"
    ):
        """
        Initialize Phase 2 processor
        
        Args:
            metadatagen_file: Input/output metadata file
            workflow_file: ComfyUI workflow file
            endpoint: ComfyUI API endpoint
            log_file: Error log file
        """
        self.metadatagen_file = metadatagen_file
        self.workflow_file = workflow_file
        self.endpoint = endpoint
        self.log_file = log_file
        
        # Setup logging
        logging.basicConfig(
            filename=log_file,
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s'
        )
        self.logger = logging.getLogger('Phase2')
        
        # Initialize ComfyUI processor (without metadata writing)
        self.comfy_processor = ComfyUIWorkflowProcessor(
            workflow_file=workflow_file,
            endpoint=endpoint
        )
    
    def _load_metadatagen(self) -> List[Dict]:
        """Load all entries from metadatagen.jsonl"""
        entries = []
        if Path(self.metadatagen_file).exists():
            with open(self.metadatagen_file, 'r') as f:
                for line in f:
                    try:
                        entries.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return entries
    
    def _save_metadatagen(self, entries: List[Dict]):
        """Save all entries to metadatagen.jsonl"""
        with open(self.metadatagen_file, 'w') as f:
            for entry in entries:
                f.write(json.dumps(entry) + '\n')
    
    def _get_pending_entries(self, entries: List[Dict]) -> List[Dict]:
        """Get entries that still need image generation"""
        return [e for e in entries if e.get('prompt_text') and not e.get('gen_filename')]
    
    def _group_by_clip_file(self, entries: List[Dict]) -> Dict[str, List[Dict]]:
        """Group entries by clip_file"""
        grouped = {}
        for entry in entries:
            clip_file = entry.get('clip_file', 'unknown')
            if clip_file not in grouped:
                grouped[clip_file] = []
            grouped[clip_file].append(entry)
        return grouped
    
    def _generate_single_image(
        self, 
        entry: Dict, 
        frame_path: str,
        batch_output_dir: str
    ) -> Dict:
        """
        Generate a single image and update entry with results
        
        Args:
            entry: Metadata entry to update
            frame_path: Path to original frame for similarity scoring
            batch_output_dir: Output directory for images
            
        Returns:
            Updated entry with generation results
        """
        prompt_text = entry['prompt_text']
        batch_name = entry['batch_name']
        gen_sequence = entry['gen_sequence']
        
        # Generate random seed
        seed = random.randint(0, 2**32 - 1)
        
        print(f"    Generating sequence {gen_sequence} with seed {seed}...")
        
        try:
            # Generate image using ComfyUI
            result = self.comfy_processor.generate_image(
                prompt_text=prompt_text,
                seed=seed,
                output_dir=batch_output_dir,
                gen_sequence=gen_sequence,
                original_frame_path=frame_path
            )
            
            if result["success"]:
                entry['seed'] = seed
                entry['gen_filename'] = result['gen_filename']
                entry['similarity_score'] = result.get('similarity_score')
                entry['generation_success'] = True
                entry['generation_error'] = None
                entry['generation_timestamp'] = datetime.now().isoformat()
                
                print(f"      ✓ Generated: {result['gen_filename']}")
                if result.get('similarity_score'):
                    print(f"      ✓ Similarity: {result['similarity_score']:.2f}%")
                
            else:
                error = result.get('error', 'Unknown error')
                entry['seed'] = seed
                entry['gen_filename'] = None
                entry['similarity_score'] = None
                entry['generation_success'] = False
                entry['generation_error'] = error
                entry['generation_timestamp'] = datetime.now().isoformat()
                
                print(f"      ✗ Failed: {error}")
                self.logger.error(f"Failed to generate for {entry['frame_file']}: {error}")
                
        except Exception as e:
            error = str(e)
            entry['seed'] = seed
            entry['gen_filename'] = None
            entry['similarity_score'] = None
            entry['generation_success'] = False
            entry['generation_error'] = error
            entry['generation_timestamp'] = datetime.now().isoformat()
            
            print(f"      ✗ Exception: {error}")
            self.logger.error(f"Exception generating for {entry['frame_file']}: {error}")
        
        return entry
    
    def process_all_clips(
        self, 
        max_clips: int = None,
        save_interval: int = 10
    ) -> Dict:
        """
        Process all clip files and generate images
        
        Args:
            max_clips: Maximum number of clips to process (for testing)
            save_interval: Save metadata every N generations
            
        Returns:
            Processing results
        """
        print("="*80)
        print("PHASE 2: Generating images from prompts")
        print("="*80)
        
        # Load all entries
        print(f"\nLoading metadata from {self.metadatagen_file}...")
        all_entries = self._load_metadatagen()
        print(f"Loaded {len(all_entries)} entries")
        
        # Get pending entries
        pending_entries = self._get_pending_entries(all_entries)
        print(f"Found {len(pending_entries)} pending entries")
        
        if len(pending_entries) == 0:
            print("No pending entries. Phase 2 complete!")
            return {
                "success": True,
                "total_entries": len(all_entries),
                "processed_entries": 0,
                "successful_generations": 0,
                "failed_generations": 0
            }
        
        # Group by clip_file
        grouped = self._group_by_clip_file(pending_entries)
        print(f"Found {len(grouped)} distinct clip files")
        
        # Apply max_clips limit if specified
        clip_files = list(grouped.keys())
        if max_clips:
            clip_files = clip_files[:max_clips]
        
        print(f"Processing {len(clip_files)} clip files")
        
        # Process each clip file
        successful_generations = 0
        failed_generations = 0
        total_processed = 0
        last_successful_frame = None
        
        for i, clip_file in enumerate(clip_files, 1):
            clip_entries = grouped[clip_file]
            
            # Get batch name and prompt from first entry (gen_sequence=1)
            first_entry = None
            for entry in clip_entries:
                if entry.get('gen_sequence') == 1:
                    first_entry = entry
                    break
            
            if not first_entry:
                print(f"\n[{i}/{len(clip_files)}] ⚠ No gen_sequence=1 entry for {clip_file}")
                continue
            
            batch_name = first_entry.get('batch_name', 'gens')
            prompt_text = first_entry.get('prompt_text')
            
            print(f"\n[{i}/{len(clip_files)}] Processing clip: {clip_file}")
            print(f"  Batch: {batch_name}")
            print(f"  Generations: {len(clip_entries)}")
            print(f"  Prompt preview: {prompt_text[:100] if prompt_text else 'None'}...")
            
            if not prompt_text:
                print(f"  ⚠ No prompt text available, skipping clip")
                for entry in clip_entries:
                    entry['generation_success'] = False
                    entry['generation_error'] = 'No prompt text available'
                    entry['generation_timestamp'] = datetime.now().isoformat()
                    failed_generations += 1
                continue
            
            # Setup output directory
            batch_output_dir = os.path.join("output/frames", batch_name)
            os.makedirs(batch_output_dir, exist_ok=True)
            
            # Process each entry (generation sequence)
            for entry in clip_entries:
                frame_file = entry.get('frame_file')
                
                # Resolve frame path for similarity scoring
                frame_path = os.path.join("output", frame_file) if frame_file else None
                if not frame_path or not os.path.exists(frame_path):
                    frame_path = None
                
                # Generate image and update entry
                updated_entry = self._generate_single_image(
                    entry, frame_path, batch_output_dir
                )
                
                # Update in all_entries
                for j, all_entry in enumerate(all_entries):
                    if all_entry.get('frame_file') == entry.get('frame_file') and \
                       all_entry.get('gen_sequence') == entry.get('gen_sequence'):
                        all_entries[j] = updated_entry
                        break
                
                total_processed += 1
                
                # Update counters
                if updated_entry.get('generation_success'):
                    successful_generations += 1
                    last_successful_frame = frame_file
                else:
                    failed_generations += 1
                
                # Save periodically
                if total_processed % save_interval == 0:
                    print(f"  💾 Saving progress ({total_processed} entries processed)...")
                    self._save_metadatagen(all_entries)
            
            # Save after each clip
            print(f"  💾 Saving progress after clip {i}...")
            self._save_metadatagen(all_entries)
        
        # Final save
        print(f"\n💾 Final save...")
        self._save_metadatagen(all_entries)
        
        # Summary
        print("\n" + "="*80)
        print("PHASE 2 COMPLETE")
        print("="*80)
        print(f"Total entries: {len(all_entries)}")
        print(f"Processed: {total_processed}")
        print(f"Successful: {successful_generations}")
        print(f"Failed: {failed_generations}")
        print(f"Output file: {self.metadatagen_file}")
        
        if last_successful_frame:
            print(f"Last successful frame: {last_successful_frame}")
        
        return {
            "success": failed_generations == 0,
            "total_entries": len(all_entries),
            "processed_entries": total_processed,
            "successful_generations": successful_generations,
            "failed_generations": failed_generations,
            "last_successful_frame": last_successful_frame
        }


def main():
    """Main function for command-line usage"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Phase 2: Generate images from prompts")
    parser.add_argument("--metadatagen", default="output/metadatagen.jsonl", help="Metadata file")
    parser.add_argument("--workflow", default="zimageturbo_cinematic.json", help="ComfyUI workflow")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8188", help="ComfyUI endpoint")
    parser.add_argument("--log_file", default="image_generation_errors.log", help="Error log file")
    parser.add_argument("--max_clips", type=int, help="Maximum clips to process (for testing)")
    parser.add_argument("--save_interval", type=int, default=10, help="Save every N generations")
    
    args = parser.parse_args()
    
    processor = ImageGenerationPhase2(
        metadatagen_file=args.metadatagen,
        workflow_file=args.workflow,
        endpoint=args.endpoint,
        log_file=args.log_file
    )
    
    result = processor.process_all_clips(
        max_clips=args.max_clips,
        save_interval=args.save_interval
    )
    
    if result["success"]:
        print("\n✓ All generations completed successfully!")
        return 0
    else:
        print(f"\n✗ Some generations failed. Check {args.log_file} for details.")
        return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())