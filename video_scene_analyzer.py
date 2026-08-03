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
import argparse
import base64
import re
import tempfile
import time
from datetime import datetime, timezone
import requests

PEGASUS_URL = "https://api.twelvelabs.io/v1.3/analyze"
PEGASUS_MODEL = "pegasus1.5"
DEFAULT_BATCH = "lore+zimageturbo"


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
    
    def save_metadata(self, scenes: List[Dict[str, Any]], batch_name: str = "legacy") -> Path:
        """Append scene metadata; never replace an existing metadata file."""
        print(f"\nAppending metadata to: {self.metadata_file}")
        
        # Create metadata entry for the entire analysis
        metadata = {
            'record_type': 'video_analysis',
            'batch_name': batch_name,
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
        with open(self.metadata_file, 'a', encoding='utf-8') as f:
            # Write main metadata as first line
            f.write(json.dumps(metadata) + '\n')
            
            # Write individual scene entries
            for scene in scenes:
                scene_entry = {
                    'record_type': 'clip',
                    'batch_name': batch_name,
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
        
        print(f"✓ Metadata appended ({len(scenes) + 1} entries)")
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


def _timecode(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    return f"{hours:02d}:{minutes:02d}:{seconds % 60:06.3f}"


def _seconds(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"(\d+):(\d+):(\d+(?:\.\d+)?)", str(value))
    if not match:
        raise ValueError(f"Invalid timecode: {value!r}")
    return int(match[1]) * 3600 + int(match[2]) * 60 + float(match[3])


def _credential(path: Path) -> str:
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("TWELVELABS_API_KEY="):
            return line.split("=", 1)[1].strip().strip("\"'")
    raise RuntimeError(f"TWELVELABS_API_KEY is missing from {path}")


def _chunk_prompt(chunk_start: float, chunk_end: float) -> str:
    return f"""Analyze this movie segment. It represents global movie time { _timecode(chunk_start) } through { _timecode(chunk_end) }.
Identify every visible editorial cut and every coherent story sequence. A cut is a
shot/edit boundary; a sequence is one or more consecutive shots that form one
coherent story step. Return ONLY valid JSON with this exact shape:
{{"cuts":[{{"start_timecode":"HH:MM:SS.mmm","end_timecode":"HH:MM:SS.mmm","sentence":"Exactly one sentence describing this shot."}}],"sequences":[{{"start_timecode":"HH:MM:SS.mmm","end_timecode":"HH:MM:SS.mmm","sentence":"Exactly one sentence describing this coherent story step."}}]}}
Use GLOBAL movie timecodes, not segment-relative timecodes. Include a cut for
every shot, preserve chronological order, and keep boundaries accurate to the
visible edit. Every cut and sequence must have exactly one non-empty sentence;
do not put multiple sentences in a field. Do not include markdown or commentary."""


def _parse_response(response: requests.Response) -> dict[str, Any]:
    try:
        body = response.json()
        raw = body.get("data", body)
    except ValueError:
        fragments = []
        for line in response.text.splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            fragments.append(str(event.get("text") or event.get("data") or ""))
        raw = "".join(fragments) or response.text
    if isinstance(raw, str):
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip(), flags=re.I)
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            # Some responses contain a JSON object followed by a newline/event.
            start = raw.find("{")
            if start < 0:
                raise
            raw, _ = json.JSONDecoder().raw_decode(raw[start:])
    if not isinstance(raw, dict) or not isinstance(raw.get("cuts"), list) or not isinstance(raw.get("sequences"), list):
        raise RuntimeError("Pegasus response must contain cuts and sequences arrays")
    return raw


def _upload_asset(chunk: Path, api_key: str, timeout: float) -> str:
    """Upload a local chunk (avoids the 30 MB base64 limit) and wait until ready."""
    response = requests.post(
        "https://api.twelvelabs.io/v1.3/assets",
        headers={"x-api-key": api_key},
        data={"method": "direct"},
        files={"file": (chunk.name, chunk.open("rb"), "video/mp4")},
        timeout=(60, timeout),
    )
    if not response.ok:
        raise RuntimeError(f"asset upload HTTP {response.status_code}: {response.text[:500]}")
    asset_id = response.json().get("_id") or response.json().get("id")
    if not asset_id:
        raise RuntimeError("asset upload returned no asset id")
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status_response = requests.get(
            f"https://api.twelvelabs.io/v1.3/assets/{asset_id}",
            headers={"x-api-key": api_key}, timeout=(30, 60),
        )
        status_response.raise_for_status()
        status = status_response.json()
        if status.get("status") == "ready":
            return str(asset_id)
        if status.get("status") == "failed":
            raise RuntimeError(f"asset processing failed: {status.get('error', 'unknown error')}")
        time.sleep(5)
    raise RuntimeError(f"asset {asset_id} did not become ready before timeout")


def _one_sentence(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text)).strip()
    parts = re.split(r"(?<=[.!?])\s+", text)
    return parts[0].strip() if parts else text


def _slug(text: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", text.lower())[:3]
    return "-".join(words) or "untitled"


def _append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def run_pegasus_workflow(video_path: Path, output_dir: Path, args: argparse.Namespace) -> None:
    """Run/resume chunk calls, reconcile overlap duplicates, extract named media, append metadata."""
    if args.overlap_seconds >= args.chunk_seconds:
        raise ValueError("overlap must be shorter than chunk duration")
    if not video_path.is_file():
        raise FileNotFoundError(video_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    chunks_dir = output_dir / "pegasus_input_chunks"
    clips_dir = output_dir / "clips"
    sequences_dir = output_dir / "sequences"
    raw_path = output_dir / "pegasus_timecodes_raw.jsonl"
    final_path = output_dir / "pegasus_timecodes_reconciled.json"
    chunks_dir.mkdir(exist_ok=True)
    clips_dir.mkdir(exist_ok=True)
    sequences_dir.mkdir(exist_ok=True)
    duration = float(subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)
    ], text=True).strip())
    chunks = []
    start = 0.0
    index = 1
    while start < duration:
        end = min(duration, start + args.chunk_seconds)
        chunks.append((index, start, end))
        if end >= duration:
            break
        start += args.chunk_seconds - args.overlap_seconds
        index += 1
    existing = {}
    if raw_path.exists():
        for line in raw_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                existing[int(record["chunk_index"])] = record
    api_key = _credential(Path(args.credentials))
    for chunk_index, chunk_start, chunk_end in chunks:
        chunk = chunks_dir / f"chunk_{chunk_index:04d}.mp4"
        if not chunk.exists():
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(chunk_start), "-i", str(video_path),
                            "-t", str(chunk_end - chunk_start), "-c", "copy", str(chunk)], check=True)
        if chunk_index in existing and existing[chunk_index].get("status") == "success":
            continue
        asset_id = _upload_asset(chunk, api_key, args.timeout)
        payload = {"model_name": PEGASUS_MODEL,
                   "video": {"type": "asset_id", "asset_id": asset_id},
                   "prompt": _chunk_prompt(chunk_start, chunk_end), "temperature": 0.1, "max_tokens": 8000}
        print(f"Pegasus chunk {chunk_index}/{len(chunks)}: {_timecode(chunk_start)}-{_timecode(chunk_end)}", flush=True)
        try:
            response = requests.post(PEGASUS_URL, headers={"x-api-key": api_key, "Content-Type": "application/json", "Accept": "application/json"}, json=payload, timeout=(60, args.timeout))
            if not response.ok:
                detail = response.text[:1000].replace(api_key, "[REDACTED]")
                raise RuntimeError(f"HTTP {response.status_code}: {detail}")
            analysis = _parse_response(response)
            record = {"chunk_index": chunk_index, "chunk_start_seconds": chunk_start, "chunk_end_seconds": chunk_end,
                      "status": "success", "model": PEGASUS_MODEL, "analysis": analysis,
                      "updated_at": datetime.now(timezone.utc).isoformat()}
        except Exception as exc:
            record = {"chunk_index": chunk_index, "chunk_start_seconds": chunk_start, "chunk_end_seconds": chunk_end,
                      "status": "retryable_error", "error": str(exc)[:500], "updated_at": datetime.now(timezone.utc).isoformat()}
        existing[chunk_index] = record
        _append_jsonl(raw_path, [record])
        if record["status"] != "success":
            raise RuntimeError(record["error"])
    if len([r for r in existing.values() if r.get("status") == "success"]) != len(chunks):
        raise RuntimeError("Not all Pegasus chunks completed; rerun to resume")
    # De-duplicate overlap detections, preferring the record with the narrowest range.
    def reconcile(kind: str) -> list[dict[str, Any]]:
        candidates = []
        for record in existing.values():
            for item in record["analysis"].get(kind, []):
                try:
                    start_time, end_time = _seconds(item["start_timecode"]), _seconds(item["end_timecode"])
                except (KeyError, ValueError):
                    continue
                if end_time <= start_time:
                    continue
                candidates.append({"start_time_seconds": start_time, "end_time_seconds": end_time,
                                   "sentence": _one_sentence(item.get("sentence", ""))})
        candidates.sort(key=lambda x: (x["start_time_seconds"], x["end_time_seconds"]))
        merged = []
        for item in candidates:
            duplicate = next((old for old in merged if abs(old["start_time_seconds"] - item["start_time_seconds"]) <= 0.75 and abs(old["end_time_seconds"] - item["end_time_seconds"]) <= 1.5), None)
            if duplicate:
                if len(item["sentence"]) > len(duplicate["sentence"]):
                    duplicate.update(item)
            else:
                merged.append(item)
        return merged
    cuts, sequences = reconcile("cuts"), reconcile("sequences")
    # Enforce the five-second maximum by deterministic subdivisions.
    bounded_cuts = []
    for cut in cuts:
        start_time = cut["start_time_seconds"]
        while cut["end_time_seconds"] - start_time > args.max_cut_seconds:
            bounded_cuts.append({**cut, "start_time_seconds": start_time, "end_time_seconds": start_time + args.max_cut_seconds})
            start_time += args.max_cut_seconds
        bounded_cuts.append({**cut, "start_time_seconds": start_time})
    cuts = bounded_cuts
    final = {"video_file": str(video_path), "batch_name": args.batch_name, "model": PEGASUS_MODEL,
             "chunk_seconds": args.chunk_seconds, "overlap_seconds": args.overlap_seconds,
             "cuts": cuts, "sequences": sequences, "updated_at": datetime.now(timezone.utc).isoformat()}
    final_path.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    rows = []
    for kind, items, directory in (("clip", cuts, clips_dir), ("sequence", sequences, sequences_dir)):
        for number, item in enumerate(items, 1):
            prefix = f"{number:04d}_{args.batch_name}_{kind}_{_slug(item['sentence'])}"
            media = directory / f"{prefix}.mp4"
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(item["start_time_seconds"]), "-i", str(video_path), "-t", str(item["end_time_seconds"] - item["start_time_seconds"]), "-c", "copy", str(media)], check=True)
            rows.append({"record_type": kind, "batch_name": args.batch_name, "name": prefix,
                         "clip_file": str(media.relative_to(output_dir).as_posix()),
                         "start_time": round(item["start_time_seconds"], 3), "end_time": round(item["end_time_seconds"], 3),
                         "duration": round(item["end_time_seconds"] - item["start_time_seconds"], 3),
                         "start_timecode": _timecode(item["start_time_seconds"]), "end_timecode": _timecode(item["end_time_seconds"]),
                         "sentence": item["sentence"]})
    _append_jsonl(output_dir / "metadata.jsonl", rows)
    print(f"Appended {len(rows)} {args.batch_name} records to {output_dir / 'metadata.jsonl'}")


def main():
    """Run local detection or the overlapping TwelveLabs cut/sequence workflow."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", nargs="?", default="./CradleAnimatic.mp4")
    parser.add_argument("--output-dir", default="output")
    parser.add_argument("--batch-name", default=DEFAULT_BATCH)
    parser.add_argument("--pegasus", action="store_true",
                        help="Split into overlapping 15-minute chunks, analyze, reconcile, and append records")
    parser.add_argument("--chunk-seconds", type=float, default=900.0)
    parser.add_argument("--overlap-seconds", type=float, default=120.0)
    parser.add_argument("--max-cut-seconds", type=float, default=5.0)
    parser.add_argument("--timeout", type=float, default=1800.0)
    parser.add_argument("--credentials", default=".credentials")
    args = parser.parse_args()
    if args.pegasus:
        run_pegasus_workflow(Path(args.video), Path(args.output_dir), args)
        return
    video_path = args.video
    output_dir = args.output_dir
    
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
