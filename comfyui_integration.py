#!/usr/bin/env python3
"""
ComfyUI Integration for Video Scene Analysis
Functions to interact with ComfyUI server and trigger image workflows
"""

import requests
import json
import uuid
from pathlib import Path
from typing import Dict, Any, Optional, Tuple
import time


class ComfyUIIntegration:
    """Main class for interacting with ComfyUI server"""
    
    def __init__(self, server_url: str = "http://127.0.0.1:8188"):
        self.server_url = server_url
        self.client_id = str(uuid.uuid4())
        self.session = requests.Session()
        
    def check_server_status(self) -> bool:
        """Check if ComfyUI server is running"""
        try:
            response = self.session.get(f"{self.server_url}/system_stats")
            return response.status_code == 200
        except requests.exceptions.RequestException:
            return False
    
    def get_history(self, prompt_id: Optional[str] = None) -> Dict[str, Any]:
        """Get execution history from ComfyUI"""
        if prompt_id:
            url = f"{self.server_url}/history/{prompt_id}"
        else:
            url = f"{self.server_url}/history"
        
        response = self.session.get(url)
        response.raise_for_status()
        return response.json()
    
    def get_queue_info(self) -> Dict[str, Any]:
        """Get current queue information"""
        response = self.session.get(f"{self.server_url}/queue")
        response.raise_for_status()
        return response.json()
    
    def upload_image(self, image_path: Path, overwrite: bool = True) -> Dict[str, Any]:
        """Upload an image to ComfyUI server"""
        if not image_path.exists():
            raise FileNotFoundError(f"Image not found: {image_path}")
        
        filename = image_path.name
        files = {
            'image': (filename, open(image_path, 'rb'), 'image/png'),
            'overwrite': (None, str(overwrite).lower())
        }
        
        try:
            response = self.session.post(f"{self.server_url}/upload/image", files=files)
            response.raise_for_status()
            return response.json()
        finally:
            files['image'][1].close()
    
    def load_workflow(self, workflow_path: Path) -> Dict[str, Any]:
        """Load workflow from JSON file"""
        if not workflow_path.exists():
            raise FileNotFoundError(f"Workflow file not found: {workflow_path}")
        
        with open(workflow_path, 'r') as f:
            workflow = json.load(f)
        
        return workflow
    
    def modify_workflow_image_input(self, workflow: Dict[str, Any], image_filename: str) -> Dict[str, Any]:
        """
        Modify workflow to use a specific input image
        Finds LoadImage nodes and updates their filename input
        """
        modified_workflow = json.loads(json.dumps(workflow))  # Deep copy
        
        for node_id, node_data in modified_workflow.items():
            if node_data.get('class_type') == 'LoadImage':
                if 'inputs' in node_data and 'image' in node_data['inputs']:
                    node_data['inputs']['image'] = image_filename
                    print(f"✓ Updated LoadImage node {node_id} to use: {image_filename}")
        
        return modified_workflow
    
    def modify_workflow_output_prefix(self, workflow: Dict[str, Any], prefix: str) -> Dict[str, Any]:
        """Modify workflow output filename prefix"""
        modified_workflow = json.loads(json.dumps(workflow))  # Deep copy
        
        for node_id, node_data in modified_workflow.items():
            if node_data.get('class_type') == 'SaveImage':
                if 'inputs' in node_data and 'filename_prefix' in node_data['inputs']:
                    node_data['inputs']['filename_prefix'] = prefix
                    print(f"✓ Updated SaveImage node {node_id} prefix to: {prefix}")
        
        return modified_workflow
    
    def execute_workflow(self, workflow: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
        """
        Execute a workflow on the ComfyUI server
        Returns tuple of (prompt_id, initial_response)
        """
        # Prepare the payload
        payload = {
            'prompt': workflow,
            'client_id': self.client_id
        }
        
        # Execute the workflow
        response = self.session.post(
            f"{self.server_url}/prompt",
            json=payload,
            headers={'Content-Type': 'application/json'}
        )
        response.raise_for_status()
        
        result = response.json()
        prompt_id = result.get('prompt_id')
        
        print(f"✓ Workflow submitted with prompt_id: {prompt_id}")
        
        return prompt_id, result
    
    def wait_for_completion(self, prompt_id: str, timeout: int = 300, check_interval: int = 2) -> Dict[str, Any]:
        """
        Wait for workflow execution to complete
        Returns the final execution history
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            history = self.get_history(prompt_id)
            
            if prompt_id in history:
                execution_data = history[prompt_id]
                
                # Check if execution is complete
                if execution_data.get('status', {}).get('completed', False):
                    print(f"✓ Workflow {prompt_id} completed successfully")
                    return execution_data
                
                # Check for errors
                if execution_data.get('status', {}).get('messages', {}).get('error'):
                    error_msg = execution_data['status']['messages']['error']
                    raise Exception(f"Workflow execution failed: {error_msg}")
            
            time.sleep(check_interval)
        
        raise TimeoutError(f"Workflow execution timed out after {timeout} seconds")
    
    def get_output_images(self, execution_data: Dict[str, Any]) -> list:
        """Extract output images from execution data"""
        output_images = []
        
        for node_id, node_output in execution_data.get('outputs', {}).items():
            if 'images' in node_output:
                for image_info in node_output['images']:
                    output_images.append({
                        'filename': image_info['filename'],
                        'subfolder': image_info.get('subfolder', ''),
                        'type': image_info.get('type', 'output'),
                        'node_id': node_id
                    })
        
        return output_images
    
    def download_image(self, image_info: Dict[str, Any], save_path: Path) -> Path:
        """Download an output image from ComfyUI server"""
        filename = image_info['filename']
        subfolder = image_info.get('subfolder', '')
        image_type = image_info.get('type', 'output')
        
        # Construct download URL
        params = {
            'filename': filename,
            'subfolder': subfolder,
            'type': image_type
        }
        
        response = self.session.get(
            f"{self.server_url}/view",
            params=params
        )
        response.raise_for_status()
        
        # Save the image
        save_path.parent.mkdir(parents=True, exist_ok=True)
        with open(save_path, 'wb') as f:
            f.write(response.content)
        
        print(f"✓ Downloaded image to: {save_path}")
        return save_path
    
    def process_image_workflow(
        self,
        workflow_path: Path,
        input_image_path: Path,
        output_prefix: str,
        output_dir: Path
    ) -> Dict[str, Any]:
        """
        Complete workflow to process an image through ComfyUI
        """
        print(f"Processing image: {input_image_path.name}")
        print(f"Using workflow: {workflow_path.name}")
        
        # Check server status
        if not self.check_server_status():
            raise ConnectionError("ComfyUI server is not running")
        
        print("✓ ComfyUI server is running")
        
        # Upload input image
        print(f"Uploading input image...")
        upload_result = self.upload_image(input_image_path)
        print(f"✓ Image uploaded: {upload_result}")
        
        # Load workflow
        print(f"Loading workflow...")
        workflow = self.load_workflow(workflow_path)
        
        # Modify workflow for input image
        print(f"Modifying workflow for input image...")
        workflow = self.modify_workflow_image_input(workflow, input_image_path.name)
        
        # Modify output prefix
        print(f"Setting output prefix: {output_prefix}")
        workflow = self.modify_workflow_output_prefix(workflow, output_prefix)
        
        # Execute workflow
        print(f"Executing workflow...")
        prompt_id, _ = self.execute_workflow(workflow)
        
        # Wait for completion
        print(f"Waiting for completion...")
        execution_data = self.wait_for_completion(prompt_id)
        
        # Get output images
        output_images = self.get_output_images(execution_data)
        print(f"✓ Generated {len(output_images)} output image(s)")
        
        # Download output images
        downloaded_images = []
        for i, image_info in enumerate(output_images):
            output_filename = f"{output_prefix}_{image_info['filename']}"
            save_path = output_dir / output_filename
            
            downloaded_image = self.download_image(image_info, save_path)
            downloaded_images.append(downloaded_image)
        
        return {
            'prompt_id': prompt_id,
            'input_image': str(input_image_path),
            'output_images': [str(img) for img in downloaded_images],
            'execution_time': execution_data.get('status', {}).get('exec_info', {}).get('execution_remaining', 0)
        }


def process_scene_frames_comfyui(
    scene_index: int,
    first_frame_path: Path,
    last_frame_path: Path,
    workflow_path: Path,
    output_base_dir: Path,
    server_url: str = "http://127.0.0.1:8188"
) -> Dict[str, Any]:
    """
    Process both first and last frames of a scene through ComfyUI
    """
    comfyui = ComfyUIIntegration(server_url)
    
    results = {
        'scene_index': scene_index,
        'first_frame': None,
        'last_frame': None
    }
    
    # Create output directory for this scene
    scene_output_dir = output_base_dir / f"scene_{scene_index:03d}"
    
    # Process first frame
    if first_frame_path.exists():
        print(f"\n{'='*60}")
        print(f"Processing first frame for scene {scene_index}")
        print(f"{'='*60}")
        
        try:
            first_result = comfyui.process_image_workflow(
                workflow_path=workflow_path,
                input_image_path=first_frame_path,
                output_prefix=f"scene_{scene_index:03d}_first_colorized",
                output_dir=scene_output_dir
            )
            results['first_frame'] = first_result
        except Exception as e:
            print(f"✗ Error processing first frame: {e}")
            results['first_frame'] = {'error': str(e)}
    
    # Process last frame
    if last_frame_path.exists():
        print(f"\n{'='*60}")
        print(f"Processing last frame for scene {scene_index}")
        print(f"{'='*60}")
        
        try:
            last_result = comfyui.process_image_workflow(
                workflow_path=workflow_path,
                input_image_path=last_frame_path,
                output_prefix=f"scene_{scene_index:03d}_last_colorized",
                output_dir=scene_output_dir
            )
            results['last_frame'] = last_result
        except Exception as e:
            print(f"✗ Error processing last frame: {e}")
            results['last_frame'] = {'error': str(e)}
    
    return results


def batch_process_scenes(
    metadata_path: Path,
    workflow_path: Path,
    output_base_dir: Path,
    scene_indices: Optional[list] = None,
    server_url: str = "http://127.0.0.1:8188"
) -> Dict[int, Dict[str, Any]]:
    """
    Batch process multiple scenes through ComfyUI
    """
    # Load metadata
    with open(metadata_path, 'r') as f:
        lines = f.readlines()
    
    main_metadata = json.loads(lines[0])
    scene_entries = [json.loads(line) for line in lines[1:]]
    
    # Filter scenes if specific indices provided
    if scene_indices:
        scene_entries = [s for s in scene_entries if s['scene_index'] in scene_indices]
    
    print(f"Processing {len(scene_entries)} scenes through ComfyUI")
    print(f"Workflow: {workflow_path}")
    print(f"Output directory: {output_base_dir}")
    
    results = {}
    
    for scene in scene_entries:
        scene_index = scene['scene_index']
        
        # Get frame paths
        first_frame_path = Path("output") / scene['first_frame_file']
        last_frame_path = Path("output") / scene['last_frame_file']
        
        # Process scene
        try:
            scene_result = process_scene_frames_comfyui(
                scene_index=scene_index,
                first_frame_path=first_frame_path,
                last_frame_path=last_frame_path,
                workflow_path=workflow_path,
                output_base_dir=output_base_dir,
                server_url=server_url
            )
            results[scene_index] = scene_result
            
        except Exception as e:
            print(f"✗ Error processing scene {scene_index}: {e}")
            results[scene_index] = {'error': str(e)}
    
    return results


def main():
    """Example usage and testing"""
    import sys
    
    print("="*60)
    print("ComfyUI Integration Test")
    print("="*60)
    
    # Initialize ComfyUI integration
    comfyui = ComfyUIIntegration()
    
    # Check server status
    print(f"\nChecking ComfyUI server at {comfyui.server_url}...")
    if comfyui.check_server_status():
        print("✓ ComfyUI server is running")
    else:
        print("✗ ComfyUI server is not running")
        print("Please start ComfyUI and try again")
        return
    
    # Check queue status
    try:
        queue_info = comfyui.get_queue_info()
        print(f"✓ Current queue status: {queue_info}")
    except Exception as e:
        print(f"⚠ Could not get queue info: {e}")
    
    # Example workflow paths
    workflow_path = Path("cradleColorize.json")
    if not workflow_path.exists():
        print(f"\n✗ Workflow file not found: {workflow_path}")
        return
    
    print(f"✓ Found workflow file: {workflow_path}")
    
    # Load and inspect workflow
    try:
        workflow = comfyui.load_workflow(workflow_path)
        print(f"✓ Loaded workflow with {len(workflow)} nodes")
        
        # Find key nodes
        load_image_nodes = [k for k, v in workflow.items() if v.get('class_type') == 'LoadImage']
        save_image_nodes = [k for k, v in workflow.items() if v.get('class_type') == 'SaveImage']
        
        print(f"  LoadImage nodes: {load_image_nodes}")
        print(f"  SaveImage nodes: {save_image_nodes}")
        
    except Exception as e:
        print(f"✗ Error loading workflow: {e}")
        return
    
    print("\n" + "="*60)
    print("ComfyUI integration is ready!")
    print("="*60)
    print("\nAvailable functions:")
    print("  - process_scene_frames_comfyui(): Process individual scene frames")
    print("  - batch_process_scenes(): Batch process multiple scenes")
    print("  - ComfyUIIntegration class: Direct ComfyUI server interaction")


if __name__ == "__main__":
    import json
    main()