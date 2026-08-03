#!/usr/bin/env python3
"""
Complete Pipeline: Phase 1 (local grounded variants) + Phase 2 (Z-Image Turbo)
Runs both phases sequentially with proper error handling and logging
"""

import sys
import argparse
from pathlib import Path
from generate_prompts_from_metadata import PromptGenerationPhase1
from generate_images_from_metadata import ImageGenerationPhase2


def run_pipeline(
    metadata_file: str = "output/metadata.jsonl",
    metadatagen_file: str = "output/metadatagen.jsonl",
    batch_name: str = "zimageturbo",
    num_copies: int = 10,
    max_frames: int = None,
    max_clips: int = None,
    skip_phase1: bool = False,
    skip_phase2: bool = False,
    workflow_file: str = "zimageturbo_cinematic.json",
    endpoint: str = "http://127.0.0.1:8188",
    log_file: str = "image_generation_errors.log",
    ground_enhance: bool = True,
    grounding_confirmations_file: str = "lore_graph/grounding_confirmations.json",
):
    """
    Run complete pipeline with both phases
    
    Args:
        metadata_file: Input metadata file
        metadatagen_file: Generated metadata file
        batch_name: Batch name for generations
        num_copies: Number of copies per frame
        max_frames: Maximum frames for Phase 1 (testing)
        max_clips: Maximum clips for Phase 2 (testing)
        skip_phase1: Skip Phase 1 if True
        skip_phase2: Skip Phase 2 if True
        workflow_file: ComfyUI workflow file
        endpoint: ComfyUI API endpoint
        log_file: Error log file
    """
    print("="*80)
    print("COMPLETE PIPELINE: Local grounded prompt variants + Z-Image Turbo")
    print("="*80)
    print(f"Batch name: {batch_name}")
    print(f"Generations per frame: {num_copies}")
    print(f"Output file: {metadatagen_file}")
    
    # Phase 1: Generate prompts
    if not skip_phase1:
        print("\n" + "="*80)
        print("STARTING PHASE 1: Local Prompt Variation Generation")
        print("="*80)
        
        phase1_processor = PromptGenerationPhase1(
            metadata_file=metadata_file,
            metadatagen_file=metadatagen_file,
            batch_name=batch_name,
            num_copies=num_copies,
            ground_enhance=ground_enhance,
            grounding_confirmations_file=grounding_confirmations_file,
        )
        
        try:
            phase1_result = phase1_processor.process_all_frames(
                max_frames=max_frames,
                resume=True
            )
        finally:
            phase1_processor.close()
        
        if not phase1_result["success"]:
            print("\n❌ Phase 1 failed. Pipeline stopped.")
            print(f"Last successful frame: {phase1_result.get('last_successful_frame')}")
            return {
                "success": False,
                "phase1_result": phase1_result,
                "phase2_result": None
            }
        
        print(f"\n✅ Phase 1 completed successfully!")
        print(f"   Total frames: {phase1_result['total_frames']}")
        print(f"   Processed: {phase1_result['successful']}")
        print(f"   Failed: {phase1_result['failed']}")
        
    else:
        print("\n⏭️ Skipping Phase 1 (already completed)")
        phase1_result = {"success": True, "skipped": True}
    
    # Phase 2: Generate images
    if not skip_phase2:
        print("\n" + "="*80)
        print("STARTING PHASE 2: Z-Image Turbo Image Generation")
        print("="*80)
        
        # Check if metadatagen file exists and has prompts
        if not Path(metadatagen_file).exists():
            print(f"❌ Metadata file not found: {metadatagen_file}")
            return {
                "success": False,
                "error": "Metadata file not found",
                "phase1_result": phase1_result,
                "phase2_result": None
            }
        
        phase2_processor = ImageGenerationPhase2(
            metadatagen_file=metadatagen_file,
            workflow_file=workflow_file,
            endpoint=endpoint,
            log_file=log_file
        )
        
        phase2_result = phase2_processor.process_all_clips(
            max_clips=max_clips,
            save_interval=5,
            num_copies=num_copies,
        )
        
        if not phase2_result["success"]:
            print("\n❌ Phase 2 failed.")
            print(f"Last successful frame: {phase2_result.get('last_successful_frame')}")
            print(f"Check {log_file} for error details.")
            return {
                "success": False,
                "phase1_result": phase1_result,
                "phase2_result": phase2_result
            }
        
        print(f"\n✅ Phase 2 completed successfully!")
        print(f"   Total entries: {phase2_result['total_entries']}")
        print(f"   Successful: {phase2_result['successful_generations']}")
        print(f"   Failed: {phase2_result['failed_generations']}")
        
    else:
        print("\n⏭️ Skipping Phase 2 (already completed)")
        phase2_result = {"success": True, "skipped": True}
    
    # Complete success
    print("\n" + "="*80)
    print("🎉 PIPELINE COMPLETED SUCCESSFULLY!")
    print("="*80)
    
    return {
        "success": True,
        "phase1_result": phase1_result,
        "phase2_result": phase2_result
    }


def main():
    """Main function for command-line usage"""
    parser = argparse.ArgumentParser(
        description="Complete Pipeline: local grounded variants + Z-Image Turbo",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Test with 10 frames
  python run_complete_pipeline.py --max_frames 10 --max_clips 10
  
  # Run full pipeline
  python run_complete_pipeline.py --batch_name zimageturbo --num_copies 10
  
  # Resume from Phase 2 only (Phase 1 already done)
  python run_complete_pipeline.py --skip_phase1
  
  # Run Phase 1 only for testing
  python run_complete_pipeline.py --skip_phase2 --max_frames 5
        """
    )
    
    # File paths
    parser.add_argument("--metadata", default="output/metadata.jsonl", help="Input metadata file")
    parser.add_argument("--metadatagen", default="output/metadatagen.jsonl", help="Generated metadata file")
    parser.add_argument("--workflow", default="zimageturbo_cinematic.json", help="ComfyUI workflow")
    parser.add_argument("--endpoint", default="http://127.0.0.1:8188", help="ComfyUI endpoint")
    parser.add_argument("--log_file", default="image_generation_errors.log", help="Error log file")
    
    # Processing parameters
    parser.add_argument("--batch_name", default="zimageturbo", help="Batch name for generations")
    parser.add_argument("--num_copies", type=int, default=10, help="Generations per frame")
    
    # Testing limits
    parser.add_argument("--max_frames", type=int, help="Maximum frames for Phase 1 (testing)")
    parser.add_argument("--max_clips", type=int, help="Maximum clips for Phase 2 (testing)")
    
    # Phase control
    parser.add_argument("--skip_phase1", action="store_true", help="Skip Phase 1")
    parser.add_argument("--skip_phase2", action="store_true", help="Skip Phase 2")
    parser.add_argument(
        "--ground-enhance", action=argparse.BooleanOptionalAction, default=True,
        help="Generate Phase 1 prompts through confirmation-gated lore grounding (default: enabled)",
    )
    parser.add_argument(
        "--grounding-confirmations",
        default="lore_graph/grounding_confirmations.json",
        help="JSON map of frame paths to confirmed lore passage IDs",
    )
    
    args = parser.parse_args()
    
    # Run pipeline
    result = run_pipeline(
        metadata_file=args.metadata,
        metadatagen_file=args.metadatagen,
        batch_name=args.batch_name,
        num_copies=args.num_copies,
        max_frames=args.max_frames,
        max_clips=args.max_clips,
        skip_phase1=args.skip_phase1,
        skip_phase2=args.skip_phase2,
        workflow_file=args.workflow,
        endpoint=args.endpoint,
        log_file=args.log_file,
        ground_enhance=args.ground_enhance,
        grounding_confirmations_file=args.grounding_confirmations,
    )
    
    if result["success"]:
        print("\n✨ All operations completed successfully!")
        return 0
    else:
        print("\n💥 Pipeline encountered errors.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
