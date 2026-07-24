#!/usr/bin/env python3
"""
Example usage of Z-Image Turbo Batch Generator
Demonstrates how to use the batch generator with metadata from video scenes
"""

import json
from pathlib import Path
from zimageturbo_batch_generator import ComfyUIWorkflowProcessor


def process_single_scene():
    """Example: Process a single scene from metadata.jsonl"""
    
    # Initialize processor
    processor = ComfyUIWorkflowProcessor(
        workflow_file="zimageturbo_cinematic.json",
        endpoint="http://127.0.0.1:8188"
    )
    
    # Example prompt text (you could also get this from GCP Vision API)
    prompt_text = """A horizontal 16:9 eye-level medium shot captures a dramatic indoor temple scene. Centered in the frame, a tall elderly Asian master with a long white beard and stern expression stands in dark navy silk robes, raising his clenched fists. In the right foreground, seen from behind, a young girl with twin pigtails reaches toward a glowing cerulean liquid inside a wide geometric marble basin. Key light at 5500K originates from the upper left, while a strong cool blue bioluminescent glow emanates upward from the basin, casting sharp rim lighting across the figures."""
    
    # Generate 5 variations
    results = processor.batch_generate(
        prompt_text=prompt_text,
        num_generations=5,
        output_dir="output/frames",
        batch_name="temple_scene_test",
        clip_file="clips/scene_001.webm",
        frame_file="frames/scene_001_first_frame.png",
        scene_index=1,
        metadata_file="output/metadatagen.jsonl"
    )
    
    print(f"Generated {len(results)} images")


def process_from_metadata(metadata_file="output/metadata.jsonl", num_scenes=1):
    """
    Example: Process scenes from metadata.jsonl file
    
    Args:
        metadata_file: Path to metadata.jsonl file
        num_scenes: Number of scenes to process
    """
    
    processor = ComfyUIWorkflowProcessor()
    
    # Read scenes from metadata.jsonl
    scenes = []
    with open(metadata_file, 'r') as f:
        for line in f:
            try:
                data = json.loads(line)
                if 'scene_index' in data:  # Individual scene entry
                    scenes.append(data)
            except json.JSONDecodeError:
                continue
    
    print(f"Found {len(scenes)} scenes in metadata")
    
    # Process first N scenes
    for i, scene in enumerate(scenes[:num_scenes]):
        scene_index = scene.get('scene_index')
        clip_file = scene.get('clip_file')
        frame_file = scene.get('first_frame_file') or scene.get('last_frame_file')
        
        # Create batch name with date
        from datetime import datetime
        date_str = datetime.now().strftime("%Y%m%d")
        batch_name = f"scene_{scene_index:03d}_zimageturbo_{date_str}"
        
        # Example prompt - in real usage, you'd get this from GCP Vision API
        # by calling gcp_vision_prompt.py with the frame_file
        example_prompt = f"""A cinematic scene showing the key elements from scene {scene_index}. Detailed photographic description with realistic lighting and materials."""
        
        print(f"\nProcessing scene {scene_index}: {clip_file}")
        
        results = processor.batch_generate(
            prompt_text=example_prompt,
            num_generations=3,  # Generate 3 variations per scene
            output_dir="output/frames",
            batch_name=batch_name,
            clip_file=clip_file,
            frame_file=frame_file,
            scene_index=scene_index,
            metadata_file="output/metadatagen.jsonl"
        )
        
        print(f"Completed scene {scene_index}: {len(results)} images generated")


def integrate_with_gcp_vision():
    """Example: Integrate with GCP Vision API for prompt generation"""
    from gcp_vision_prompt import GCPVisionPrompter
    
    # Initialize both processors
    gcp_prompter = GCPVisionPrompter()
    comfy_processor = ComfyUIWorkflowProcessor()
    
    # Get prompt from GCP Vision API
    frame_path = "output/frames/scene_001_first_frame.png"
    gcp_result = gcp_prompter.generate_prompt(frame_path)
    
    if gcp_result["success"]:
        prompt_text = gcp_result["response_text"]
        print(f"Generated prompt from GCP Vision API:\n{prompt_text}\n")
        
        # Use this prompt for ComfyUI generation
        results = comfy_processor.batch_generate(
            prompt_text=prompt_text,
            num_generations=3,
            output_dir="output/frames",
            batch_name="gcp_vision_generated",
            clip_file="clips/scene_001.webm",
            frame_file="frames/scene_001_first_frame.png",
            scene_index=1
        )
        
        print(f"Generated {len(results)} images using GCP Vision API prompt")
    else:
        print(f"Failed to get prompt from GCP Vision API: {gcp_result['error']}")


if __name__ == "__main__":
    print("Choose an example to run:")
    print("1. Process single scene with example prompt")
    print("2. Process scenes from metadata.jsonl")
    print("3. Integrate with GCP Vision API")
    
    choice = input("Enter choice (1-3): ").strip()
    
    if choice == "1":
        process_single_scene()
    elif choice == "2":
        num = input("How many scenes to process? (default 1): ").strip()
        num_scenes = int(num) if num.isdigit() else 1
        process_from_metadata(num_scenes=num_scenes)
    elif choice == "3":
        integrate_with_gcp_vision()
    else:
        print("Invalid choice")