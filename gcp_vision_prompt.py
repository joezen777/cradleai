#!/usr/bin/env python3
"""
GCP Vision API Integration for Image-to-Text Prompts
Supports Gemini Vision API with image inputs
"""

import os
import json
from pathlib import Path
from typing import Union, Optional
from PIL import Image
import io
import google.generativeai as genai
from google.oauth2 import service_account
from google.auth.transport.requests import Request


# Default prompt text for vision-to-text generation
DEFAULT_PROMPT = """You are an expert vision-to-prompt AI engineered for SDXL Base and Refiner sketch-to-photo workflows. Analyze the uploaded sketch, line art, or stencil image, and generate the optimal text prompts needed to render it as a realistic photograph while preserving its exact composition.
Strictly adhere to the following guidelines:

STYLE STRIPPING: Completely strip away all artistic medium descriptors. Never use terms like "sketch," "drawing," "line art," "pencil art," "black and white," "stencil," or "illustration." Describe the visual elements solely as a real-world photograph.
NO SYNTHETIC BUZZWORDS: Absolutely ban quality buzzwords such as "photorealistic," "hyperrealistic," "4k," "8k," or "masterpiece," as these trigger synthetic 3D-rendered biases in SDXL.
OPTIC-CENTRIC PARAMETERS: Anchor the scene in photographic reality using precise camera and optical settings (e.g., 35mm prime lens, f/2.8 aperture, ISO 400, Kodachrome/Portra film stock, natural window side-lighting, depth of field).
COLOR & TEXTURE INJECTION: Because the sketch lacks color and spectral data, explicitly specify realistic color palettes, surface micro-textures (e.g., visible skin pores, woven fabric, brushed steel, weathered wood), and specular highlights for every element in the layout.
DUAL-ENCODER STRUCTURE: Separate the description into two tailored outputs for SDXL's dual text encoders.
Output Format:
[GLOBAL_LAYOUT_PROMPT (OpenCLIP / text_g)]
(Write 1-2 descriptive, natural language sentences detailing the full scene composition, subject positioning, global environment, and spatial layout.)
[TECHNICAL_TAGS_PROMPT (CLIP-L / text_l)]
(Provide a concise, comma-separated list of camera specs, lens length, aperture, lighting setup, color palette, micro-textures, and fine visual details.)"""


class GCPVisionPrompter:
    """Handles GCP Vision API calls with image inputs"""
    
    def __init__(self, credentials_path: Optional[str] = None, access_key: Optional[str] = None):
        """
        Initialize GCP Vision API client
        
        Args:
            credentials_path: Path to service account JSON credentials file
            access_key: GCP API access key (alternative to credentials file)
        """
        self.project_id = None
        self.client = None
        self._setup_credentials(credentials_path, access_key)
        
    def _setup_credentials(self, credentials_path: Optional[str], access_key: Optional[str]):
        """Setup GCP credentials from file, access key, or .credentials file"""
        # Try credentials file first
        if credentials_path and os.path.exists(credentials_path):
            with open(credentials_path, 'r') as f:
                credentials_data = json.load(f)
            credentials = service_account.Credentials.from_service_account_info(
                credentials_data,
                scopes=['https://www.googleapis.com/auth/cloud-platform']
            )
            self.project_id = credentials_data.get('project_id')
            
        # Try access key
        elif access_key:
            genai.configure(api_key=access_key)
            
        # Try .credentials file in workspace
        else:
            workspace_root = Path(__file__).parent
            credentials_file = workspace_root / '.credentials'
            
            if credentials_file.exists():
                cred_data = self._parse_credentials_file(credentials_file)
                
                # Try to use as service account if we have full JSON
                if 'type' in cred_data:
                    credentials = service_account.Credentials.from_service_account_info(
                        cred_data,
                        scopes=['https://www.googleapis.com/auth/cloud-platform']
                    )
                    self.project_id = cred_data.get('project_id')
                # Otherwise use access key if available
                elif 'access_key' in cred_data:
                    genai.configure(api_key=cred_data['access_key'])
                    self.project_id = cred_data.get('project_id')
                else:
                    raise ValueError("No valid credentials found in .credentials file")
            else:
                raise FileNotFoundError("No credentials file found")
    
    def _parse_credentials_file(self, credentials_path: Path) -> dict:
        """Parse the custom .credentials file format"""
        cred_data = {}
        with open(credentials_path, 'r') as f:
            current_key = None
            current_value = []
            
            for line in f:
                line = line.strip()
                if line.endswith(':') and ':' not in line[:-1]:
                    # New key
                    if current_key:
                        cred_data[current_key.lower().replace(' ', '_')] = '\n'.join(current_value).strip()
                    current_key = line[:-1].strip().lower().replace(' ', '_')
                    current_value = []
                elif current_key:
                    current_value.append(line)
            
            # Don't forget the last key
            if current_key:
                cred_data[current_key] = '\n'.join(current_value).strip()
        
        return cred_data
    
    def load_image(self, image_input: Union[str, Path, Image.Image]) -> Image.Image:
        """
        Load image from file path or PIL Image object
        
        Args:
            image_input: File path string, Path object, or PIL Image
            
        Returns:
            PIL Image object
        """
        if isinstance(image_input, Image.Image):
            return image_input
        elif isinstance(image_input, (str, Path)):
            return Image.open(image_input)
        else:
            raise TypeError("image_input must be a file path (str/Path) or PIL Image")
    
    def image_to_bytes(self, image: Image.Image) -> bytes:
        """
        Convert PIL Image to bytes
        
        Args:
            image: PIL Image object
            
        Returns:
            Image data as bytes
        """
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format='PNG')
        img_byte_arr.seek(0)
        return img_byte_arr.getvalue()
    
    def generate_prompt(
        self, 
        image_input: Union[str, Path, Image.Image],
        prompt: Optional[str] = None,
        model: str = "gemini-1.5-flash"
    ) -> dict:
        """
        Generate text prompt from image using GCP Vision API
        
        Args:
            image_input: File path (str/Path) or PIL Image object
            prompt: Custom prompt text (uses DEFAULT_PROMPT if not provided)
            model: Gemini model to use (default: gemini-1.5-flash)
            
        Returns:
            Dictionary containing the generated response
        """
        # Use default prompt if none provided
        if prompt is None:
            prompt = DEFAULT_PROMPT
        
        # Load and prepare image
        pil_image = self.load_image(image_input)
        image_bytes = self.image_to_bytes(pil_image)
        
        try:
            # Initialize Gemini model
            gemini_model = genai.GenerativeModel(model)
            
            # Prepare image for Gemini
            image_part = {
                "mime_type": "image/png",
                "data": image_bytes
            }
            
            # Generate content
            response = gemini_model.generate_content([prompt, image_part])
            
            return {
                "success": True,
                "model": model,
                "prompt_used": prompt,
                "response_text": response.text,
                "full_response": response
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "model": model,
                "prompt_used": prompt
            }


def main():
    """Example usage of GCP Vision Prompter"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate text prompts from images using GCP Vision API")
    parser.add_argument("image", help="Path to input image file")
    parser.add_argument("--prompt", help="Custom prompt text (uses default if not provided)")
    parser.add_argument("--model", default="gemini-1.5-flash", help="Gemini model to use")
    parser.add_argument("--output", help="Output file to save response")
    
    args = parser.parse_args()
    
    # Initialize prompter
    prompter = GCPVisionPrompter()
    
    # Generate prompt from image
    result = prompter.generate_prompt(
        image_input=args.image,
        prompt=args.prompt,
        model=args.model
    )
    
    if result["success"]:
        print("=" * 80)
        print("GENERATED RESPONSE:")
        print("=" * 80)
        print(result["response_text"])
        print("=" * 80)
        
        # Save to file if requested
        if args.output:
            with open(args.output, 'w') as f:
                json.dump(result, f, indent=2, default=str)
            print(f"\nResponse saved to: {args.output}")
    else:
        print(f"Error: {result['error']}")


if __name__ == "__main__":
    main()