#!/usr/bin/env python3
"""
Phase 1: Generate prompts locally from Qwen3-VL, Pegasus, and Gemini cast lore.
Creates ten controlled prompt variations per source frame.
"""

import json
import os
import time
import random
import re
import tempfile
import copy
from pathlib import Path
from typing import Dict, List, Set
from datetime import datetime
from local_frame_prompt import DEFAULT_PROMPT, LocalFramePrompter
from prompt_variations import apply_variation
from retrieve_clip_lore_context import (
    load_clip_transcript,
    load_related_chapter,
    prepare_chapter_summary,
)


class PromptGenerationPhase1:
    """Phase 1: Generate grounded prompts using local CUDA models."""
    
    def __init__(
        self,
        metadata_file: str = "output/metadata.jsonl",
        metadatagen_file: str = "output/metadatagen.jsonl",
        batch_name: str = "zimageturbo",
        num_copies: int = 10,
        chapter_metadata_file: str = "output/pegasus_chapter_metadata.jsonl",
        cast_file: str = "output/gemini_chapter_cast.jsonl",
        transcript_file: str = "output/audiotranscript.jsonl",
        pegasus_metadata_file: str = "output/pegasus_metadata.jsonl",
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
        self.chapter_metadata_file = Path(chapter_metadata_file)
        self.cast_file = Path(cast_file)
        self.transcript_file = Path(transcript_file)
        self.pegasus_metadata_file = Path(pegasus_metadata_file)
        self.gcp_prompter = LocalFramePrompter()
        self.cast_records = self._load_indexed_jsonl(
            self.cast_file,
            "chapter_number",
        )
        self.pegasus_records = self._load_indexed_jsonl(
            self.pegasus_metadata_file,
            "scene_index",
        )
        with self.transcript_file.open("r", encoding="utf-8") as source:
            self.transcript_items = [
                json.loads(line) for line in source if line.strip()
            ]
        
        # Create output directory if needed
        Path(metadatagen_file).parent.mkdir(parents=True, exist_ok=True)

    def close(self) -> None:
        self.gcp_prompter.close()

    @staticmethod
    def _load_indexed_jsonl(path: Path, key: str) -> Dict[int, Dict]:
        if not path.is_file():
            raise FileNotFoundError(f"Required context file is missing: {path}")
        records = {}
        with path.open("r", encoding="utf-8") as source:
            for line in source:
                if not line.strip():
                    continue
                record = json.loads(line)
                if record.get(key) is not None:
                    records[int(record[key])] = record
        return records

    @staticmethod
    def _normalized_identity(value: str) -> str:
        normalized = re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()
        return normalized.replace("linden", "lindon")

    def _relevant_cast(
        self,
        cast_record: Dict,
        summary: str,
        transcript: str,
    ) -> List[Dict]:
        highlighted = " ".join(re.findall(r"\|\|(.*?)\|\|", summary))
        evidence = self._normalized_identity(
            f"{highlighted or summary}\n{transcript}"
        )
        processed = cast_record.get("processed_targets", [])
        relevant = []
        for index, character in enumerate(cast_record.get("cast", [])):
            source = processed[index] if index < len(processed) else {}
            names = {
                str(character.get("character_name") or ""),
                str(source.get("target_name") or ""),
                str(source.get("canonical_character_name") or ""),
            }
            normalized_names = {
                self._normalized_identity(name)
                for name in names
                if name and not name.casefold().startswith("unknown")
            }
            if not any(name and name in evidence for name in normalized_names):
                continue
            details = copy.deepcopy(character.get("character_details") or {})
            details.pop("pose_and_composition", None)
            relevant.append(
                {
                    "character_name": character.get("character_name"),
                    "character_details": details,
                }
            )
        return relevant

    def _contextual_image_prompt(self, scene: Dict) -> str:
        scene_index = int(scene["scene_index"])
        chapter = load_related_chapter(
            self.chapter_metadata_file,
            scene_index,
        )
        chapter_number = int(chapter["chapter_index"])
        cast_record = self.cast_records.get(chapter_number)
        if not cast_record or cast_record.get("status") != "complete":
            raise ValueError(
                f"Complete Gemini cast context is missing for chapter {chapter_number}"
            )
        summary = prepare_chapter_summary(
            chapter["chapter_summary"],
            float(scene["start_time"]),
            float(scene["end_time"]),
            timecode_offset=float(
                chapter.get("movie_start_time_seconds") or 0
            ),
        )
        speaker_names = {
            guess["speaker_id"]: guess["character_name_guess"]
            for guess in chapter.get("speaker_name_guesses", [])
            if guess.get("speaker_id") and guess.get("character_name_guess")
        }
        transcript = load_clip_transcript(
            self.transcript_file,
            float(scene["start_time"]),
            float(scene["end_time"]),
            speaker_names,
            transcript_items=self.transcript_items,
        )
        pegasus = self.pegasus_records.get(scene_index, {})
        clip_description = pegasus.get("description") or (
            "No Pegasus clip description is available; rely on the source "
            "frame and chapter continuity."
        )
        cast = self._relevant_cast(cast_record, summary, transcript)
        context = {
            "scene_index": scene_index,
            "chapter_number": chapter_number,
            "clip_description": clip_description,
            "chapter_summary": summary,
            "clip_transcript": transcript,
            "cast": cast,
        }
        return (
            DEFAULT_PROMPT
            + "\n\nUse the below JSON only as grounding context for identity, "
            "continuity, actions, scenery, and lore. The attached source image "
            "is authoritative for composition, framing, camera angle, pose, "
            "visible objects, and visible character count. The chapter-summary "
            "sentence surrounded by || is the portion relevant to this clip. "
            "Use character_details only for characters relevant and visible in "
            "the attached frame. Do not introduce off-screen characters or "
            "objects from surrounding chapter context.\n"
            + json.dumps(context, ensure_ascii=False)
        )
    
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
                        if (
                            frame_file
                            and str(data.get("prompt_text") or "").strip()
                            and data.get("gcp_success") is True
                        ):
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
    
    def _call_gcp_with_backoff(
        self,
        frame_path: str,
        scene_index: int,
        prompt: str,
        max_retries: int = 5
    ) -> Dict:
        """
        Call GCP Vision API with exponential backoff retry
        
        Args:
            frame_path: Path to frame image
            scene_index: Scene whose prompt text is being requested
            max_retries: Maximum number of retry attempts
            
        Returns:
            GCP API response
        """
        base_delay = 1.0  # Initial delay in seconds
        max_delay = 60.0  # Maximum delay in seconds
        
        for attempt in range(max_retries):
            print(f"  Attempt {attempt + 1}/{max_retries} for {frame_path}")
            try:
                result = self.gcp_prompter.generate_prompt(
                    frame_path,
                    prompt=prompt,
                )
                
                if result["success"]:
                    return result
                else:
                    error = result.get('error', 'Unknown error')
                    if not result.get("retryable", False):
                        print(f"  Permanent API error: {error}")
                        return result
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
        
        return {"success": False, "error": "Retryable API failure persisted after maximum attempts"}
    
    def _load_metadatagen_entries(self) -> List[Dict]:
        path = Path(self.metadatagen_file)
        if not path.is_file():
            return []
        with path.open("r", encoding="utf-8") as source:
            return [json.loads(line) for line in source if line.strip()]

    def _save_metadatagen_entries(self) -> None:
        path = Path(self.metadatagen_file)
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as destination:
            temporary_path = Path(destination.name)
            for entry in self._existing_entries:
                destination.write(
                    json.dumps(entry, ensure_ascii=False) + "\n"
                )
        os.replace(temporary_path, path)

    def _write_metadata_entries(self, entries: List[Dict]):
        """Update matching generation slots and persist atomically."""
        for entry in entries:
            key = (entry.get("frame_file"), entry.get("gen_sequence"))
            existing = self._existing_index.get(key)
            if existing is None:
                self._existing_entries.append(entry)
                self._existing_index[key] = entry
            else:
                existing.update(entry)
        self._save_metadatagen_entries()

    def _ensure_generation_slots(self, unique_frames: List[Dict]) -> int:
        """Backfill missing copy slots for frames that already have a prompt.

        ``num_copies`` is a target total per source frame. This lets a frame
        generated first with one copy be resumed later with ten copies without
        replacing sequence 1 or requesting the same base prompt again.
        """
        added_entries = []
        for frame_info in unique_frames:
            frame_file = frame_info["frame_file"]
            existing_for_frame = [
                entry
                for entry in self._existing_entries
                if entry.get("frame_file") == frame_file
            ]
            prompt_source = next(
                (
                    entry
                    for entry in existing_for_frame
                    if str(entry.get("prompt_text") or "").strip()
                    and entry.get("gcp_success") is True
                ),
                None,
            )
            if prompt_source is None:
                continue

            existing_sequences = {
                entry.get("gen_sequence") for entry in existing_for_frame
            }
            for gen_sequence in range(1, self.num_copies + 1):
                if gen_sequence in existing_sequences:
                    continue
                entry = copy.deepcopy(prompt_source)
                base_prompt = str(
                    prompt_source.get("base_prompt_text")
                    or prompt_source.get("prompt_text")
                )
                variant_prompt, variation_id = apply_variation(base_prompt, gen_sequence)
                entry.update(
                    {
                        "batch_name": self.batch_name,
                        "gen_sequence": gen_sequence,
                        "base_prompt_text": base_prompt,
                        "prompt_text": variant_prompt,
                        "variation_id": variation_id,
                        "seed": None,
                        "similarity_score": None,
                        "gen_filename": None,
                        "generation_success": None,
                        "generation_error": None,
                        "generation_timestamp": None,
                        "timestamp": datetime.now().isoformat(),
                    }
                )
                added_entries.append(entry)
                self._existing_entries.append(entry)
                self._existing_index[(frame_file, gen_sequence)] = entry
                existing_sequences.add(gen_sequence)

        if added_entries:
            self._save_metadatagen_entries()
        return len(added_entries)
    
    def process_all_frames(
        self, 
        max_frames: int = None,
        resume: bool = True,
        scene_filter: Set[int] | None = None,
        frame_filter: Set[str] | None = None,
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
        print("PHASE 1: Local Qwen3-VL prompts + Pegasus/Gemini grounding")
        print("="*80)
        
        # Load scenes
        print(f"\nLoading scenes from {self.metadata_file}...")
        scenes = self._load_metadata()
        print(f"Found {len(scenes)} scenes")
        self._existing_entries = self._load_metadatagen_entries()
        self._existing_index = {
            (entry.get("frame_file"), entry.get("gen_sequence")): entry
            for entry in self._existing_entries
        }
        
        # Get unique frames
        print("\nExtracting unique frames...")
        unique_frames = self._get_unique_frames(scenes)
        if scene_filter:
            unique_frames = [
                frame for frame in unique_frames
                if int(frame["scene"].get("scene_index", -1)) in scene_filter
            ]
        if frame_filter:
            unique_frames = [
                frame for frame in unique_frames
                if frame["frame_file"] in frame_filter
                or Path(frame["frame_file"]).name in frame_filter
            ]
        print(f"Found {len(unique_frames)} unique frames to process")

        added_slots = self._ensure_generation_slots(unique_frames)
        if added_slots:
            print(
                f"Added {added_slots} missing generation slots to reach "
                f"{self.num_copies} copies per previously prompted frame"
            )
        
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
                "new_frames": 0,
                "successful": 0,
                "failed": 0,
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
                contextual_prompt = self._contextual_image_prompt(scene)
                # Call the local Qwen3-VL provider with retry/backoff.
                gcp_result = self._call_gcp_with_backoff(
                    str(frame_path),
                    scene_index=scene.get("scene_index"),
                    prompt=contextual_prompt,
                )
                
                if gcp_result["success"]:
                    base_prompt_text = gcp_result["response_text"]
                    print(f"  ✓ Base prompt generated ({len(base_prompt_text)} chars)")
                    
                    # Create multiple entries with different gen_sequence values
                    entries = []
                    for gen_sequence in range(1, self.num_copies + 1):
                        prompt_text, variation_id = apply_variation(
                            base_prompt_text, gen_sequence
                        )
                        entry = {
                            "batch_name": self.batch_name,
                            "clip_file": scene.get('clip_file'),
                            "frame_file": frame_file,
                            "frame_type": frame_type,
                            "scene_index": scene.get('scene_index'),
                            "prompt_text": prompt_text,
                            "base_prompt_text": base_prompt_text,
                            "variation_id": variation_id,
                            "seed": None,  # Will be set in Phase 2
                            "similarity_score": None,  # Will be set in Phase 2
                            "gen_sequence": gen_sequence,
                            "gen_filename": None,  # Will be set in Phase 2
                            "timestamp": datetime.now().isoformat(),
                            "gcp_success": True,
                            "prompt_provider": "qwen3-vl-8b-local+mistral-nemo-lore+pegasus",
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
    
    parser = argparse.ArgumentParser(description="Phase 1: Generate local grounded prompt variants")
    parser.add_argument("--metadata", default="output/metadata.jsonl", help="Input metadata file")
    parser.add_argument("--metadatagen", default="output/metadatagen.jsonl", help="Output metadata file")
    parser.add_argument("--batch_name", default="zimageturbo", help="Batch name")
    parser.add_argument("--num_copies", type=int, default=10, help="Number of copies per frame")
    parser.add_argument("--max_frames", type=int, help="Maximum frames to process (for testing)")
    parser.add_argument("--no_resume", action="store_true", help="Don't resume from existing file")
    parser.add_argument("--scenes", nargs="*", type=int, help="Only process these scene indices")
    parser.add_argument(
        "--frames",
        nargs="*",
        help="Only process these exact frame paths or basenames",
    )
    
    args = parser.parse_args()
    
    processor = PromptGenerationPhase1(
        metadata_file=args.metadata,
        metadatagen_file=args.metadatagen,
        batch_name=args.batch_name,
        num_copies=args.num_copies
    )
    
    try:
        result = processor.process_all_frames(
            max_frames=args.max_frames,
            resume=not args.no_resume,
            scene_filter=set(args.scenes or []),
            frame_filter=set(args.frames or []),
        )
    finally:
        processor.close()
    
    return 0 if result["success"] else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
