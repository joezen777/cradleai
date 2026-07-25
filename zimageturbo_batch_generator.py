#!/usr/bin/env python3
"""
Z-Image Turbo Batch Generator for ComfyUI
Processes prompts through ComfyUI workflow with batch support, seed management, and similarity scoring
"""

import os
import json
import requests
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
import random
import numpy as np
from PIL import Image
import io

import torch
import torch.nn.functional as F
import torchvision.transforms as transforms
from torchvision.models import vgg16
import cv2
import lpips

# ComfyUI endpoint
COMFYUI_ENDPOINT = "http://127.0.0.1:8188"


class NeuralEdgeExtractor:
    """Extracts clean line art from images using PiDiNet or HED"""
    
    def __init__(self, device: str = "cuda"):
        """
        Initialize neural edge extractor
        
        Args:
            device: Device to run inference on (cuda/cpu)
        """
        self.device = device
        self.model = None
        self._setup_model()
    
    def _setup_model(self):
        """Load the installed PyTorch PiDiNet model, with Canny as fallback."""
        try:
            from types import SimpleNamespace
            import models as pidinet_models

            repo_root = Path(pidinet_models.__file__).resolve().parent.parent
            weights_path = Path(os.environ.get(
                "PIDINET_WEIGHTS",
                repo_root / "trained_models" / "table5_pidinet.pth",
            ))
            if not weights_path.is_file():
                raise FileNotFoundError(f"PiDiNet weights not found: {weights_path}")

            args = SimpleNamespace(config="carv4", sa=True, dil=True)
            model = pidinet_models.pidinet(args)
            checkpoint = torch.load(weights_path, map_location="cpu", weights_only=False)
            state_dict = checkpoint.get("state_dict", checkpoint)
            state_dict = {
                key.removeprefix("module."): value
                for key, value in state_dict.items()
            }
            model.load_state_dict(state_dict)
            model.to(self.device).eval()

            self.model = model
            self.use_pidinet = True
            self.pidinet_weights = str(weights_path)
            print(f"PiDiNet enabled: {weights_path.name} on {self.device}")
        except Exception as exc:
            self.model = None
            self.use_pidinet = False
            print(f"PiDiNet unavailable ({type(exc).__name__}: {exc}); falling back to Canny")

    def _extract_pidinet_edges(self, image: np.ndarray) -> np.ndarray:
        """Run PiDiNet inference for an RGB uint8 image."""
        tensor = torch.from_numpy(np.ascontiguousarray(image)).permute(2, 0, 1)
        tensor = tensor.float().div(255.0)
        mean = tensor.new_tensor([0.485, 0.456, 0.406])[:, None, None]
        std = tensor.new_tensor([0.229, 0.224, 0.225])[:, None, None]
        tensor = tensor.sub(mean).div(std).unsqueeze(0).to(self.device)

        with torch.inference_mode():
            edge_probability = self.model(tensor)[-1]
        edges = edge_probability.squeeze(0).squeeze(0).float().cpu().numpy()
        return np.clip(edges * 255.0, 0, 255).astype(np.uint8)
    
    def extract_edges(self, image: np.ndarray) -> np.ndarray:
        """
        Extract edges from image
        
        Args:
            image: Input image as numpy array (H, W, 3) in RGB format
            
        Returns:
            Edge map as numpy array (H, W) in grayscale
        """
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        else:
            gray = image
        
        if self.use_pidinet:
            edges = self._extract_pidinet_edges(image)
        else:
            # Fall back to Canny edge detection
            edges = cv2.Canny(gray, 50, 150)
        
        return edges
    
    def preprocess_for_comparison(self, image_path: str, target_size: Tuple[int, int] = None) -> torch.Tensor:
        """
        Preprocess image for similarity comparison
        
        Args:
            image_path: Path to image file
            target_size: Target size for padding/cropping to ensure divisibility by 32
            
        Returns:
            Preprocessed tensor (1, 1, H, W)
        """
        image = Image.open(image_path).convert('RGB')
        image_np = np.array(image)
        
        # Extract edges
        edges = self.extract_edges(image_np)
        
        # Convert to tensor
        edges_tensor = torch.from_numpy(edges).float() / 255.0
        edges_tensor = edges_tensor.unsqueeze(0).unsqueeze(0)  # (1, 1, H, W)
        
        # Ensure dimensions are divisible by 32 for deep network compatibility
        if target_size:
            h, w = edges_tensor.shape[-2:]
            target_h, target_w = target_size
            
            # Pad or crop to target dimensions
            if h < target_h or w < target_w:
                # Pad
                pad_h = max(0, target_h - h)
                pad_w = max(0, target_w - w)
                edges_tensor = F.pad(edges_tensor, (0, pad_w, 0, pad_h))
            elif h > target_h or w > target_w:
                # Center crop
                start_h = (h - target_h) // 2
                start_w = (w - target_w) // 2
                edges_tensor = edges_tensor[:, :, start_h:start_h+target_h, start_w:start_w+target_w]
        
        return edges_tensor


class SimilarityScorer:
    """Calculates perceptual similarity scores using LPIPS"""
    
    def __init__(self, device: str = "cuda"):
        """
        Initialize LPIPS similarity scorer
        
        Args:
            device: Device to run inference on (cuda/cpu)
        """
        self.device = device
        self._setup_gpu_optimization()
        self.edge_extractor = NeuralEdgeExtractor(device)
        
        # Initialize LPIPS model
        self.lpips_model = lpips.LPIPS(net='vgg').to(device)
        self.lpips_model.eval()
    
    def _setup_gpu_optimization(self):
        """Setup GPU optimization for NVIDIA RTX 5070 (Blackwell architecture)"""
        if self.device == "cuda":
            # Enable TensorFloat-32 for Blackwell tensor cores
            torch.backends.cuda.matmul.allow_tf32 = True
            torch.backends.cudnn.allow_tf32 = True
            
            print(f"GPU optimization enabled for CUDA {torch.version.cuda}")
            print(f"Device: {torch.cuda.get_device_name(0)}")
            print(f"TensorFloat-32: Enabled")
    
    def calculate_similarity_score(self, original_image_path: str, generated_image_path: str) -> float:
        """
        Calculate similarity score between original and generated images
        
        Args:
            original_image_path: Path to original stencil/frame image
            generated_image_path: Path to generated colorized image
            
        Returns:
            Similarity score as percentage (0-100)
        """
        try:
            # Get dimensions from original image for padding/cropping
            original_img = Image.open(original_image_path)
            orig_h, orig_w = original_img.size[1], original_img.size[0]
            
            # Ensure dimensions are divisible by 32
            target_h = ((orig_h + 31) // 32) * 32
            target_w = ((orig_w + 31) // 32) * 32
            
            # Extract edges from both images
            with torch.no_grad():
                with torch.autocast(device_type='cuda', dtype=torch.bfloat16):
                    original_edges = self.edge_extractor.preprocess_for_comparison(
                        original_image_path, (target_h, target_w)
                    ).to(self.device)
                    
                    generated_edges = self.edge_extractor.preprocess_for_comparison(
                        generated_image_path, (target_h, target_w)
                    ).to(self.device)
                    
                    # Calculate LPIPS distance
                    # Repeat single channel to 3 channels for LPIPS
                    original_edges_3ch = original_edges.repeat(1, 3, 1, 1)
                    generated_edges_3ch = generated_edges.repeat(1, 3, 1, 1)
                    
                    lpips_distance = self.lpips_model(original_edges_3ch, generated_edges_3ch)
                    
                    # Convert LPIPS distance to similarity percentage
                    # LPIPS ranges from 0 (identical) to higher values (more different)
                    # We'll use an exponential decay function to convert to 0-100 scale
                    similarity_score = max(0, min(100, 100 * (1 - lpips_distance.item())))
            
            return similarity_score
            
        except Exception as e:
            print(f"Error calculating similarity score: {e}")
            return 0.0


class ComfyUIWorkflowProcessor:
    """Handles ComfyUI workflow processing with batch support"""
    
    def __init__(self, workflow_file: str = "zimageturbo_cinematic.json", endpoint: str = COMFYUI_ENDPOINT):
        """
        Initialize ComfyUI workflow processor
        
        Args:
            workflow_file: Path to ComfyUI workflow JSON file
            endpoint: ComfyUI API endpoint
        """
        self.workflow_file = workflow_file
        self.endpoint = endpoint
        self.workflow = self._load_workflow()
        self.similarity_scorer = SimilarityScorer()
    
    def _load_workflow(self) -> Dict:
        """Load ComfyUI workflow from JSON file"""
        with open(self.workflow_file, 'r') as f:
            return json.load(f)
    
    def _modify_workflow(self, prompt_text: str, seed: int, filename_prefix: str) -> Dict:
        """
        Modify workflow with user parameters
        
        Args:
            prompt_text: Prompt text for text encoding
            seed: Random seed for generation
            filename_prefix: Output filename prefix
            
        Returns:
            Modified workflow dictionary
        """
        modified_workflow = json.loads(json.dumps(self.workflow))  # Deep copy
        
        # Update prompt text in CLIP Text Encode node (57:27)
        if "57:27" in modified_workflow:
            modified_workflow["57:27"]["inputs"]["text"] = prompt_text
        
        # Update seed in KSampler node (57:3)
        if "57:3" in modified_workflow:
            modified_workflow["57:3"]["inputs"]["seed"] = seed
        
        # Update filename prefix in SaveImage node (9)
        if "9" in modified_workflow:
            modified_workflow["9"]["inputs"]["filename_prefix"] = filename_prefix
        
        return modified_workflow
    
    def _upload_image(self, image_path: str) -> str:
        """
        Upload image to ComfyUI
        
        Args:
            image_path: Path to image file
            
        Returns:
            Image filename in ComfyUI
        """
        with open(image_path, 'rb') as f:
            response = requests.post(
                f"{self.endpoint}/upload/image",
                files={'image': f}
            )
        
        if response.status_code == 200:
            return response.json().get('name')
        else:
            raise Exception(f"Failed to upload image: {response.text}")
    
    def _queue_prompt(self, workflow: Dict) -> str:
        """
        Queue workflow for execution in ComfyUI
        
        Args:
            workflow: Modified workflow dictionary
            
        Returns:
            Prompt ID
        """
        prompt_request = {
            "prompt": workflow,
            "client_id": "zimageturbo_batch_generator"
        }
        
        response = requests.post(
            f"{self.endpoint}/prompt",
            json=prompt_request
        )
        
        if response.status_code == 200:
            return response.json().get('prompt_id')
        else:
            raise Exception(f"Failed to queue prompt: {response.text}")
    
    def _wait_for_completion(self, prompt_id: str, timeout: int = 300) -> Dict:
        """
        Wait for workflow execution to complete
        
        Args:
            prompt_id: Prompt ID to wait for
            timeout: Maximum wait time in seconds
            
        Returns:
            Execution results
        """
        import time
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            response = requests.get(
                f"{self.endpoint}/history/{prompt_id}"
            )
            
            if response.status_code == 200:
                history = response.json()
                if prompt_id in history:
                    return history[prompt_id]
            
            time.sleep(0.5)
        
        raise Exception(f"Timeout waiting for prompt {prompt_id}")
    
    def _get_output_image(self, prompt_id: str) -> str:
        """
        Get the output image from ComfyUI
        
        Args:
            prompt_id: Prompt ID
            
        Returns:
            Path to downloaded image
        """
        history = self._wait_for_completion(prompt_id)
        outputs = history.get('outputs', {})
        
        for node_id, node_output in outputs.items():
            if 'images' in node_output and len(node_output['images']) > 0:
                image_info = node_output['images'][0]
                
                # Download image
                image_url = f"{self.endpoint}/view?filename={image_info['filename']}&subfolder={image_info.get('subfolder', '')}&type={image_info['type']}"
                response = requests.get(image_url)
                
                if response.status_code == 200:
                    return image_info['filename']
        
        raise Exception("No output image found")
    
    def generate_image(
        self, 
        prompt_text: str, 
        seed: int, 
        output_dir: str,
        gen_sequence: int,
        original_frame_path: Optional[str] = None
    ) -> Dict:
        """
        Generate a single image using ComfyUI workflow
        
        Args:
            prompt_text: Prompt text for generation
            seed: Random seed
            output_dir: Output directory for images
            gen_sequence: Generation sequence number
            original_frame_path: Path to original frame for similarity scoring
            
        Returns:
            Generation results dictionary
        """
        # Create output directory if it doesn't exist
        os.makedirs(output_dir, exist_ok=True)
        
        # Generate filename prefix with wildcards for seed
        date_str = datetime.now().strftime("%Y-%m-%d")
        filename_prefix = f"zimageturbo/{date_str}_"
        
        # Modify workflow
        modified_workflow = self._modify_workflow(prompt_text, seed, filename_prefix)
        
        try:
            # Queue and execute workflow
            prompt_id = self._queue_prompt(modified_workflow)
            output_filename = self._get_output_image(prompt_id)
            
            # Download and save image to output directory
            image_url = f"{self.endpoint}/view?filename={output_filename}&subfolder=zimageturbo&type=output"
            response = requests.get(image_url)
            
            if response.status_code == 200:
                # Save with proper filename including seed
                local_filename = output_filename.replace("zimageturbo/", "")
                local_path = os.path.join(output_dir, local_filename)
                
                with open(local_path, 'wb') as f:
                    f.write(response.content)
                
                # Calculate similarity score if original frame provided
                similarity_score = None
                if original_frame_path and os.path.exists(original_frame_path):
                    similarity_score = self.similarity_scorer.calculate_similarity_score(
                        original_frame_path, local_path
                    )
                
                return {
                    "success": True,
                    "gen_filename": local_path,
                    "seed": seed,
                    "gen_sequence": gen_sequence,
                    "similarity_score": similarity_score,
                    "output_filename": output_filename
                }
            else:
                raise Exception(f"Failed to download image: {response.text}")
                
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "seed": seed,
                "gen_sequence": gen_sequence
            }
    
    def batch_generate(
        self,
        prompt_text: str,
        num_generations: int,
        output_dir: str,
        batch_name: str = "gens",
        clip_file: Optional[str] = None,
        frame_file: Optional[str] = None,
        scene_index: Optional[int] = None,
        metadata_file: str = "output/metadatagen.jsonl"
    ) -> List[Dict]:
        """
        Generate multiple images with different seeds
        
        Args:
            prompt_text: Prompt text for generation
            num_generations: Number of images to generate
            output_dir: Output directory for images
            batch_name: Batch name for output folder
            clip_file: Reference to clip file in metadata.jsonl
            frame_file: Reference to frame file in metadata.jsonl
            scene_index: Scene index from metadata.jsonl
            metadata_file: Output metadata file
            
        Returns:
            List of generation results
        """
        # Create output directory structure
        output_path = os.path.join(output_dir, batch_name)
        os.makedirs(output_path, exist_ok=True)
        
        results = []
        original_frame_path = None
        
        # Resolve frame file path for similarity scoring
        if frame_file:
            original_frame_path = os.path.join(output_dir, "..", frame_file)
            if not os.path.exists(original_frame_path):
                # Try relative path from current directory
                original_frame_path = os.path.join("output", frame_file)
        
        # Generate images with different seeds
        for gen_sequence in range(1, num_generations + 1):
            # Generate random seed
            seed = random.randint(0, 2**32 - 1)
            
            print(f"Generating image {gen_sequence}/{num_generations} with seed {seed}...")
            
            result = self.generate_image(
                prompt_text=prompt_text,
                seed=seed,
                output_dir=output_path,
                gen_sequence=gen_sequence,
                original_frame_path=original_frame_path
            )
            
            if result["success"]:
                # Prepare metadata entry
                metadata_entry = {
                    "batch_name": batch_name,
                    "clip_file": clip_file,
                    "frame_file": frame_file,
                    "scene_index": scene_index,
                    "prompt_text": prompt_text,
                    "seed": result["seed"],
                    "similarity_score": result.get("similarity_score"),
                    "gen_sequence": result["gen_sequence"],
                    "gen_filename": result["gen_filename"],
                    "timestamp": datetime.now().isoformat()
                }
                
                # Write to metadata file
                with open(metadata_file, 'a') as f:
                    f.write(json.dumps(metadata_entry) + '\n')
                
                print(f"Successfully generated: {result['gen_filename']}")
                if result.get("similarity_score") is not None:
                    print(f"  Similarity score: {result['similarity_score']:.2f}%")
            else:
                print(f"Failed to generate image: {result.get('error')}")
            
            results.append(result)
        
        # Summary
        successful = sum(1 for r in results if r["success"])
        print(f"\nBatch complete: {successful}/{num_generations} images generated successfully")
        
        if successful > 0:
            avg_similarity = np.mean([r.get("similarity_score", 0) for r in results if r.get("similarity_score") is not None])
            if avg_similarity > 0:
                print(f"Average similarity score: {avg_similarity:.2f}%")
        
        return results


def main():
    """Main function for command-line usage"""
    parser = argparse.ArgumentParser(description="Z-Image Turbo Batch Generator for ComfyUI")
    
    # Required arguments
    parser.add_argument("prompt_text", help="Prompt text for image generation")
    parser.add_argument("-n", "--num_generations", type=int, default=1, help="Number of images to generate")
    
    # Optional arguments
    parser.add_argument("-b", "--batch_name", default="gens", help="Batch name for output folder")
    parser.add_argument("-c", "--clip_file", help="Reference to clip file in metadata.jsonl")
    parser.add_argument("-f", "--frame_file", help="Reference to frame file in metadata.jsonl")
    parser.add_argument("-s", "--scene_index", type=int, help="Scene index from metadata.jsonl")
    parser.add_argument("-w", "--workflow", default="zimageturbo_cinematic.json", help="ComfyUI workflow file")
    parser.add_argument("-e", "--endpoint", default=COMFYUI_ENDPOINT, help="ComfyUI API endpoint")
    parser.add_argument("-o", "--output_dir", default="output/frames", help="Output directory")
    parser.add_argument("-m", "--metadata_file", default="output/metadatagen.jsonl", help="Metadata output file")
    
    args = parser.parse_args()
    
    # Initialize processor
    processor = ComfyUIWorkflowProcessor(
        workflow_file=args.workflow,
        endpoint=args.endpoint
    )
    
    # Run batch generation
    results = processor.batch_generate(
        prompt_text=args.prompt_text,
        num_generations=args.num_generations,
        output_dir=args.output_dir,
        batch_name=args.batch_name,
        clip_file=args.clip_file,
        frame_file=args.frame_file,
        scene_index=args.scene_index,
        metadata_file=args.metadata_file
    )
    
    return 0 if all(r["success"] for r in results) else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())