#!/usr/bin/env python3
"""
Integrated Workflow: GCP Vision Prompt Generation + Z-Image Turbo Batch Generation
Complete pipeline for automated video scene enhancement
"""

import json
import argparse
from pathlib import Path
from datetime import datetime
from gcp_vision_prompt import GCPVisionPrompter
from zimageturbo_batch_generator import ComfyUIWorkflowProcessor


class IntegratedWorkflowProcessor:
    """Integrated pipeline for GCP Vision + Z-Image Turbo workflow"""
    
    def __init__(
        self, 
        workflow_file: str = "zimageturbo_cinematic.json",
        comfyui_endpoint: str = "http://127.0.0.1:8188"
    ):
        """
        Initialize integrated workflow processor
        
        Args:
            workflow_file: ComfyUI workflow JSON file
            comfyui_endpoint: ComfyUI API endpoint
        """
        self.gcp_prompter = GCPVisionPrompter()
        self.comfy_processor = ComfyUIWorkflowProcessor(
            workflow_file=workflow_file,
            endpoint=comfyui_endpoint
        )
    
    def process_single_scene(
        self,
        frame_path: str,
        num_generations: int = 3,
        batch_name: Optional[str] = None,
        clip_file: Optional[str] = None,
        scene_index: Optional[int] = None,
        output_dir: str = "output/frames",
        metadata_file: str = "output/metadatagen.jsonl"
    ) -> dict:
        """
        Process a single scene: Generate prompt with GCP Vision, then generate images with Z-Image Turbo
        
        Args:
            frame_path: Path to frame image for prompt generation
            num_generations: Number of image variations to generate
            batch_name: Batch name for output folder
            clip_file: Reference to clip file in metadata
            scene_index: Scene index from metadata
            output_dir: Output directory for images
            metadata_file: Metadata output file
            
        Returns:
            Processing results dictionary
        """
        print(f"Processing scene from: {frame_path}")
        
        # Generate default batch name if not provided
        if batch_name is None:
            date_str = datetime.now().strftime("%Y%m%d")
            scene_num = scene_index if scene_index else "unknown"
            batch_name = f"scene_{scene_num:03d}_zimageturbo_{date_str}"
        
        # Step 1: Generate prompt using GCP Vision API
        print(f"Step 1: Generating prompt with GCP Vision API...")
        gcp_result = self.gcp_prompter.generate_prompt(frame_path)
        
        if not gcp_result["success"]:
            return {
                "success": False,
                "error": f"GCP Vision API failed: {gcp_result.get('error')}",
                "scene_index": scene_index
            }
        
        prompt_text = gcp_result["response_text"]
        print(f"✓ Prompt generated successfully ({len(prompt_text)} characters)")
        print(f"  Preview: {prompt_text[:150]}...")
        
        # Step 2: Generate images using Z-Image Turbo
        print(f"Step 2: Generating {num_generations} image variations with Z-Image Turbo...")
        
        # Determine frame_file for similarity scoring
        frame_file = None
        if frame_path:
            # Convert to relative path from output directory
            abs_path = Path(frame_path).resolve()
            output_abs = Path(output_dir).resolve()
            try:
                frame_file = str(abs_path.relative_to(output_abs.parent))
            except ValueError:
                frame_file = str(abs_path.relative_to(Path.cwd()))
        
        generation_results = self.comfy_processor.batch_generate(
            prompt_text=prompt_text,
            num_generations=num_generations,
            output_dir=output_dir,
            batch_name=batch_name,
            clip_file=clip_file,
            frame_file=frame_file,
            scene_index=scene_index,
            metadata_file=metadata_file
        )
        
        successful = sum(1 for r in generation_results if r["success"])
        
        return {
            "success": successful > 0,
            "scene_index": scene_index,
            "batch_name": batch_name,
            "prompt_text": prompt_text,
            "generations": generation_results,
            "successful_count": successful,
            "total_count": num_generations
        }
    
    def process_batch_from_metadata(
        self,
        metadata_file: str = "output/metadata.jsonl",
        num_scenes: int = 1,
        num_generations_per_scene: int = 3,
        start_scene: int = 1,
        output_dir: str = "output/frames",
        output_metadata: str = "output/metadatagen.jsonl"
    ) -> dict:
        """
        Process multiple scenes from metadata.jsonl file
        
        Args:
            metadata_file: Path to metadata.jsonl file
            num_scenes: Number of scenes to process
            num_generations_per_scene: Number of variations per scene
            start_scene: Starting scene index
            output_dir: Output directory for images
            output_metadata: Output metadata file
            
        Returns:
            Batch processing results
        """
        print(f"Reading scenes from: {metadata_file}")
        
        # Read scenes from metadata.jsonl
        scenes = []
        with open(metadata_file, 'r') as f:
            for line in f:
                try:
                    data = json.loads(line)
                    if 'scene_index' in data and 'first_frame_file' in data:
                        scenes.append(data)
                except json.JSONDecodeError:
                    continue
        
        print(f"Found {len(scenes)} scenes in metadata")
        
        # Filter scenes based on start_scene and num_scenes
        filtered_scenes = [
            s for s in scenes 
            if s.get('scene_index', 0) >= start_scene
        ][:num_scenes]
        
        print(f"Processing {len(filtered_scenes)} scenes (starting from scene {start_scene})")
        
        # Process each scene
        results = []
        successful_count = 0
        
        for i, scene in enumerate(filtered_scenes):
            scene_index = scene.get('scene_index')
            clip_file = scene.get('clip_file')
            frame_file = scene.get('first_frame_file') or scene.get('last_frame_file')
            
            print(f"\n{'='*80}")
            print(f"Scene {scene_index} ({i+1}/{len(filtered_scenes)})")
            print(f"{'='*80}")
            
            # Resolve full path to frame file
            frame_path = Path(output_dir) / frame_file
            if not frame_path.exists():
                frame_path = Path(frame_file)
            
            if not frame_path.exists():
                print(f"⚠ Frame file not found: {frame_path}")
                results.append({
                    "success": False,
                    "error": "Frame file not found",
                    "scene_index": scene_index
                })
                continue
            
            # Process scene
            result = self.process_single_scene(
                frame_path=str(frame_path),
                num_generations=num_generations_per_scene,
                clip_file=clip_file,
                scene_index=scene_index,
                output_dir=output_dir,
                metadata_file=output_metadata
            )
            
            results.append(result)
            
            if result["success"]:
                successful_count += 1
                print(f"✓ Successfully processed scene {scene_index}")
            else:
                print(f"✗ Failed to process scene {scene_index}: {result.get('error')}")
        
        # Summary
        print(f"\n{'='*80}")
        print("BATCH PROCESSING COMPLETE")
        print(f"{'='*80}")
        print(f"Total scenes: {len(filtered_scenes)}")
        print(f"Successful: {successful_count}")
        print(f"Failed: {len(filtered_scenes) - successful_count}")
        
        total_generations = sum(r.get("successful_count", 0) for r in results if r.get("success"))
        print(f"Total images generated: {total_generations}")
        
        # Calculate average similarity scores
        similarity_scores = []
        for result in results:
            if result.get("success"):
                for gen in result.get("generations", []):
                    if gen.get("similarity_score") is not None:
                        similarity_scores.append(gen["similarity_score"])
        
        if similarity_scores:
            avg_similarity = sum(similarity_scores) / len(similarity_scores)
            print(f"Average similarity score: {avg_similarity:.2f}%")
        
        return {
            "success": successful_count > 0,
            "total_scenes": len(filtered_scenes),
            "successful_scenes": successful_count,
            "total_generations": total_generations,
            "average_similarity": sum(similarity_scores) / len(similarity_scores) if similarity_scores else None,
            "results": results
        }


def main():
    """Main function for command-line usage"""
    parser = argparse.ArgumentParser(description="Integrated GCP Vision + Z-Image Turbo Workflow")
    
    # Mode selection
    parser.add_argument("mode", choices=["single", "batch"], help="Processing mode")
    
    # Single scene arguments
    parser.add_argument("--frame", help="Path to frame image (single mode)")
    parser.add_argument("-n", "--num_generations", type=int, default=3, help="Number of variations per scene")
    parser.add_argument("-b", "--batch_name", help="Batch name for output folder")
    
    # Batch processing arguments
    parser.add_argument("--metadata", default="output/metadata.jsonl", help="Metadata file (batch mode)")
    parser.add_argument("--num_scenes", type=int, default=1, help="Number of scenes to process")
    parser.add_argument("--start_scene", type=int, default=1, help="Starting scene index")
    
    # Common arguments
    parser.add_argument("--output_dir", default="output/frames", help="Output directory")
    parser.add_argument("--metadata_output", default="output/metadatagen.jsonl", help="Output metadata file")
    parser.add_argument("--workflow", default="zimageturbo_cinematic.json", help="ComfyUI workflow file")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8188", help="ComfyUI API endpoint")
    
    args = parser.parse_args()
    
    # Initialize integrated processor
    processor = IntegratedWorkflowProcessor(
        workflow_file=args.workflow,
        comfyui_endpoint=args.endpoint
    )
    
    if args.mode == "single":
        if not args.frame:
            print("Error: --frame argument required for single mode")
            return 1
        
        result = processor.process_single_scene(
            frame_path=args.frame,
            num_generations=args.num_generations,
            batch_name=args.batch_name,
            output_dir=args.output_dir,
            metadata_file=args.metadata_output
        )
        
        if result["success"]:
            print(f"\n✓ Successfully processed scene")
            print(f"  Generated {result['successful_count']}/{result['total_count']} images")
            return 0
        else:
            print(f"\n✗ Failed: {result.get('error')}")
            return 1
    
    else:  # batch mode
        result = processor.process_batch_from_metadata(
            metadata_file=args.metadata,
            num_scenes=args.num_scenes,
            num_generations_per_scene=args.num_generations,
            start_scene=args.start_scene,
            output_dir=args.output_dir,
            output_metadata=args.metadata_output
        )
        
        if result["success"]:
            print(f"\n✓ Batch processing complete")
            return 0
        else:
            print(f"\n✗ Batch processing failed")
            return 1


if __name__ == "__main__":
    import sys
    sys.exit(main())