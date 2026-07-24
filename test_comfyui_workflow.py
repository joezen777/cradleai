#!/usr/bin/env python3
"""
Test script for ComfyUI workflow execution
Demonstrates how to process scene frames through ComfyUI
"""

import json
from pathlib import Path
from comfyui_integration import (
    ComfyUIIntegration,
    process_scene_frames_comfyui,
    batch_process_scenes
)


def test_single_frame():
    """Test processing a single frame"""
    print("="*60)
    print("Test: Single Frame Processing")
    print("="*60)
    
    # Initialize ComfyUI
    comfyui = ComfyUIIntegration()
    
    # Check server
    if not comfyui.check_server_status():
        print("✗ ComfyUI server not running. Please start it first.")
        return False
    
    print("✓ ComfyUI server is running")
    
    # Define paths
    workflow_path = Path("cradleColorize.json")
    test_image_path = Path("output/frames/scene_001_first_frame.png")
    output_dir = Path("output/colorized_test")
    
    # Check files exist
    if not workflow_path.exists():
        print(f"✗ Workflow not found: {workflow_path}")
        return False
    
    if not test_image_path.exists():
        print(f"✗ Test image not found: {test_image_path}")
        return False
    
    print(f"✓ Workflow found: {workflow_path}")
    print(f"✓ Test image found: {test_image_path}")
    
    try:
        # Process the image
        result = comfyui.process_image_workflow(
            workflow_path=workflow_path,
            input_image_path=test_image_path,
            output_prefix="test_scene_001_first",
            output_dir=output_dir
        )
        
        print("\n" + "="*60)
        print("✓ Test completed successfully!")
        print("="*60)
        print(f"Prompt ID: {result['prompt_id']}")
        print(f"Output images: {len(result['output_images'])}")
        for img_path in result['output_images']:
            print(f"  - {img_path}")
        
        return True
        
    except Exception as e:
        print(f"\n✗ Test failed: {e}")
        return False


def test_scene_processing():
    """Test processing a complete scene (first and last frames)"""
    print("\n" + "="*60)
    print("Test: Complete Scene Processing")
    print("="*60)
    
    workflow_path = Path("cradleColorize.json")
    output_dir = Path("output/colorized_scenes")
    
    # Test with scene 1
    scene_index = 1
    first_frame = Path("output/frames/scene_001_first_frame.png")
    last_frame = Path("output/frames/scene_001_last_frame.png")
    
    print(f"Processing scene {scene_index}")
    print(f"  First frame: {first_frame}")
    print(f"  Last frame: {last_frame}")
    
    try:
        result = process_scene_frames_comfyui(
            scene_index=scene_index,
            first_frame_path=first_frame,
            last_frame_path=last_frame,
            workflow_path=workflow_path,
            output_base_dir=output_dir
        )
        
        print("\n" + "="*60)
        print("✓ Scene processing completed!")
        print("="*60)
        print(f"Scene {scene_index} results:")
        print(f"  First frame: {'✓ Processed' if result['first_frame'] else '✗ Failed'}")
        print(f"  Last frame: {'✓ Processed' if result['last_frame'] else '✗ Failed'}")
        
        return True
        
    except Exception as e:
        print(f"\n✗ Scene processing failed: {e}")
        return False


def test_batch_processing():
    """Test batch processing multiple scenes"""
    print("\n" + "="*60)
    print("Test: Batch Processing (First 3 scenes)")
    print("="*60)
    
    metadata_path = Path("output/metadata.jsonl")
    workflow_path = Path("cradleColorize.json")
    output_dir = Path("output/colorized_batch")
    
    # Process first 3 scenes
    scene_indices = [1, 2, 3]
    
    print(f"Processing scenes: {scene_indices}")
    
    try:
        results = batch_process_scenes(
            metadata_path=metadata_path,
            workflow_path=workflow_path,
            output_base_dir=output_dir,
            scene_indices=scene_indices
        )
        
        print("\n" + "="*60)
        print("✓ Batch processing completed!")
        print("="*60)
        
        successful = sum(1 for r in results.values() if 'error' not in r)
        failed = sum(1 for r in results.values() if 'error' in r)
        
        print(f"Results:")
        print(f"  Successful: {successful}/{len(results)}")
        print(f"  Failed: {failed}/{len(results)}")
        
        for scene_idx, result in results.items():
            status = "✓ Success" if 'error' not in result else "✗ Failed"
            print(f"  Scene {scene_idx}: {status}")
        
        return successful == len(results)
        
    except Exception as e:
        print(f"\n✗ Batch processing failed: {e}")
        return False


def inspect_workflow():
    """Inspect the workflow structure"""
    print("="*60)
    print("Workflow Inspection")
    print("="*60)
    
    workflow_path = Path("cradleColorize.json")
    
    if not workflow_path.exists():
        print(f"✗ Workflow not found: {workflow_path}")
        return
    
    comfyui = ComfyUIIntegration()
    workflow = comfyui.load_workflow(workflow_path)
    
    print(f"\nWorkflow loaded: {len(workflow)} nodes\n")
    
    # Categorize nodes by type
    node_types = {}
    for node_id, node_data in workflow.items():
        class_type = node_data.get('class_type', 'Unknown')
        if class_type not in node_types:
            node_types[class_type] = []
        node_types[class_type].append(node_id)
    
    print("Node types found:")
    for class_type, node_ids in sorted(node_types.items()):
        print(f"  {class_type}: {len(node_ids)} node(s) - {node_ids[:3]}{'...' if len(node_ids) > 3 else ''}")
    
    # Find key nodes
    print("\n" + "-"*60)
    print("Key Nodes:")
    print("-"*60)
    
    load_image_nodes = [k for k, v in workflow.items() if v.get('class_type') == 'LoadImage']
    save_image_nodes = [k for k, v in workflow.items() if v.get('class_type') == 'SaveImage']
    
    print(f"\nLoadImage nodes (input): {load_image_nodes}")
    for node_id in load_image_nodes:
        node = workflow[node_id]
        image_input = node.get('inputs', {}).get('image', 'N/A')
        print(f"  Node {node_id}: image = '{image_input}'")
    
    print(f"\nSaveImage nodes (output): {save_image_nodes}")
    for node_id in save_image_nodes:
        node = workflow[node_id]
        prefix = node.get('inputs', {}).get('filename_prefix', 'N/A')
        print(f"  Node {node_id}: filename_prefix = '{prefix}'")


def main():
    """Main test menu"""
    import sys
    
    print("="*60)
    print("ComfyUI Integration Test Suite")
    print("="*60)
    
    if len(sys.argv) > 1:
        test_type = sys.argv[1]
        
        if test_type == "inspect":
            inspect_workflow()
        elif test_type == "single":
            test_single_frame()
        elif test_type == "scene":
            test_scene_processing()
        elif test_type == "batch":
            test_batch_processing()
        else:
            print(f"Unknown test: {test_type}")
            print("Available: inspect, single, scene, batch")
    else:
        print("\nAvailable tests:")
        print("  python test_comfyui_workflow.py inspect   - Inspect workflow structure")
        print("  python test_comfyui_workflow.py single    - Test single frame processing")
        print("  python test_comfyui_workflow.py scene     - Test complete scene processing")
        print("  python test_comfyui_workflow.py batch     - Test batch processing")
        print("\nExample usage:")
        print("  python test_comfyui_workflow.py inspect")


if __name__ == "__main__":
    main()