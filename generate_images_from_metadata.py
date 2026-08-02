#!/usr/bin/env python3
"""
Phase 2: Generate images using Z-Image Turbo based on prompts from metadatagen.jsonl
Sequentially processes each generation and updates metadata with results
"""

import json
import os
import random
import time
import tempfile
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
        path = Path(self.metadatagen_file)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as destination:
            temporary_path = Path(destination.name)
            for entry in entries:
                destination.write(
                    json.dumps(entry, ensure_ascii=False) + "\n"
                )
        os.replace(temporary_path, path)
    
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
        save_interval: int = 10,
        cooldown_seconds: float = 5.0,
        num_copies: int = None,
    ) -> Dict:
        """
        Generate one source frame batch at a time, then score it separately.

        For each source frame this queues every pending generation, waits for
        all ComfyUI jobs, releases ComfyUI VRAM, persists filenames, waits for
        the cooldown, calculates PiDiNet/LPIPS scores, persists again, and only
        then advances to the next source frame.
        """
        print("=" * 80)
        print("PHASE 2: Batched ComfyUI generation, then similarity scoring")
        print("=" * 80)

        all_entries = self._load_metadatagen()
        pending_entries = self._get_pending_entries(all_entries)
        if num_copies is not None:
            if num_copies < 1:
                raise ValueError("num_copies must be at least 1")
            pending_entries = [
                entry
                for entry in pending_entries
                if isinstance(entry.get("gen_sequence"), int)
                and 1 <= entry["gen_sequence"] <= num_copies
            ]
        print(f"Loaded {len(all_entries)} entries")
        print(f"Found {len(pending_entries)} pending entries")

        if not pending_entries:
            return {
                "success": True,
                "total_entries": len(all_entries),
                "processed_entries": 0,
                "successful_generations": 0,
                "failed_generations": 0,
            }

        grouped = self._group_by_clip_file(pending_entries)
        clip_files = list(grouped)
        if max_clips:
            clip_files = clip_files[:max_clips]
        print(f"Processing {len(clip_files)} clip files")

        successful_generations = 0
        failed_generations = 0
        total_processed = 0
        last_successful_frame = None

        for clip_number, clip_file in enumerate(clip_files, 1):
            clip_entries = grouped[clip_file]
            frame_groups = {}
            for entry in clip_entries:
                frame_groups.setdefault(entry.get("frame_file"), []).append(entry)

            print()
            print(f"[{clip_number}/{len(clip_files)}] Clip: {clip_file}")
            print(f"  Source-frame batches: {len(frame_groups)}")

            for frame_number, (frame_file, frame_entries) in enumerate(
                frame_groups.items(), 1
            ):
                frame_entries.sort(key=lambda item: item.get("gen_sequence", 0))
                normalized = frame_file.replace("\\", "/") if frame_file else None
                frame_path = os.path.join("output", normalized) if normalized else None
                if not frame_path or not os.path.exists(frame_path):
                    frame_path = None

                batch_name = frame_entries[0].get("batch_name", "gens")
                batch_output_dir = os.path.join("output/frames", batch_name)
                os.makedirs(batch_output_dir, exist_ok=True)
                print(
                    f"  Frame {frame_number}/{len(frame_groups)}: {frame_file} "
                    f"({len(frame_entries)} jobs)"
                )

                queued_jobs = []
                generated_entries = []

                # Phase A: queue every generation for this source frame.
                for entry in frame_entries:
                    seed = random.randint(0, 2**32 - 1)
                    sequence = entry.get("gen_sequence")
                    try:
                        queued = self.comfy_processor.queue_image(
                            prompt_text=entry["prompt_text"],
                            seed=seed,
                            output_dir=batch_output_dir,
                            gen_sequence=sequence,
                        )
                        queued_jobs.append((entry, queued))
                        print(
                            f"    Queued sequence {sequence}: "
                            f"{queued['prompt_id']}"
                        )
                    except Exception as exc:
                        entry["seed"] = seed
                        entry["gen_filename"] = None
                        entry["similarity_score"] = None
                        entry["generation_success"] = False
                        entry["generation_error"] = str(exc)
                        entry["generation_timestamp"] = datetime.now().isoformat()
                        failed_generations += 1
                        total_processed += 1
                        self.logger.error(
                            f"Queue failed for {frame_file}: {exc}"
                        )

                # Phase B: wait for and download every queued generation.
                for entry, queued in queued_jobs:
                    try:
                        result = self.comfy_processor.collect_queued_image(queued)
                        entry["seed"] = result["seed"]
                        entry["gen_filename"] = result["gen_filename"]
                        entry["similarity_score"] = None
                        entry["generation_success"] = True
                        entry["generation_error"] = None
                        entry["generation_timestamp"] = datetime.now().isoformat()
                        generated_entries.append(entry)
                        successful_generations += 1
                        last_successful_frame = frame_file
                        print(f"    Generated: {result['gen_filename']}")
                    except Exception as exc:
                        entry["seed"] = queued["seed"]
                        entry["gen_filename"] = None
                        entry["similarity_score"] = None
                        entry["generation_success"] = False
                        entry["generation_error"] = str(exc)
                        entry["generation_timestamp"] = datetime.now().isoformat()
                        failed_generations += 1
                        self.logger.error(
                            f"Generation failed for {frame_file}: {exc}"
                        )
                    total_processed += 1

                # Phase C: release generation models, cool down, then persist
                # filenames before any similarity model is loaded.
                self.comfy_processor.release_comfy_vram()
                print(f"  Cooling down for {cooldown_seconds:.1f} seconds")
                time.sleep(cooldown_seconds)
                self._save_metadatagen(all_entries)
                print("  Generated filenames saved")

                # Phase D: load PiDiNet/LPIPS only for this completed batch.
                if frame_path and generated_entries:
                    print("  Calculating PiDiNet similarities")
                    for entry in generated_entries:
                        score = self.comfy_processor.calculate_similarity(
                            frame_path,
                            entry["gen_filename"],
                        )
                        entry["similarity_score"] = score
                        print(
                            f"    Sequence {entry['gen_sequence']}: "
                            f"{score:.2f}%"
                        )
                    self.comfy_processor.release_similarity_models()
                    self._save_metadatagen(all_entries)
                    print("  Similarity scores saved")

                if total_processed % save_interval == 0:
                    self._save_metadatagen(all_entries)

        self._save_metadatagen(all_entries)
        print()
        print("=" * 80)
        print("PHASE 2 COMPLETE")
        print("=" * 80)
        print(f"Processed: {total_processed}")
        print(f"Successful: {successful_generations}")
        print(f"Failed: {failed_generations}")

        return {
            "success": failed_generations == 0,
            "total_entries": len(all_entries),
            "processed_entries": total_processed,
            "successful_generations": successful_generations,
            "failed_generations": failed_generations,
            "last_successful_frame": last_successful_frame,
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
    parser.add_argument("--num_copies", type=int, help="Maximum generations per frame")
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
        save_interval=args.save_interval,
        num_copies=args.num_copies,
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
