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
DEFAULT_PROMPT = """You are an expert AI prompt engineer specializing in Diffusion Transformers (specifically Z-Image Turbo and the Qwen 3 4B LLM text encoder inside ComfyUI).

YOUR TASK:
Analyze the attached image (sketch, line art, wireframe, or grayscale photo) and generate a single, highly structured, dense descriptive prompt. Your output must preserve the exact subject layout, composition, pose, and framing of the original image while fully translating all visual elements into a vibrant, full-color, hyper-photorealistic photograph.

GUIDELINES FOR DESCRIPTION:

1. Aspect Ratio & Framing Anchor:
   - Begin immediately with the image orientation and camera angle (e.g., "A horizontal 16:9 eye-level medium shot...").
   - Explicitly define subject placement using direct spatial coordinates (e.g., "positioned in the left foreground", "centered in the frame").

2. Strict Noun-Attribute Binding (Color Bleed Prevention):
   - To prevent color bleeding in LLM text encoders, ALWAYS pair color and material adjectives directly with the exact target noun (e.g., write "a deep crimson wool cloak" instead of "crimson color, wool cloak").
   - Translate all line art or grayscale areas into realistic, physical real-world materials (e.g., subsurface scattering on human skin, metallic brushed aluminum, woven cotton fabric, natural mahogany wood grain).

3. Lighting Geometry & Shadow Direction:
   - Define the physical direction and color temperature of light sources (e.g., "key light originates from the upper-left at 5500K, casting soft diagonal shadows toward the bottom right").
   - Detail secondary bounce lighting, ambient specular highlights, and edge lighting to give 2D sketches true 3D depth.

4. Camera Optics & Realistic Depth:
   - Specify photographic lens characteristics rather than generic buzzwords (e.g., "shot on an 85mm prime lens at f/1.8 aperture").
   - Describe focal plane clarity, realistic shallow depth of field, natural background bokeh, and subtle 35mm film grain.

5. Embedded Text & Graphic Handling:
   - If the original sketch or image contains visible text, logos, or written signage, explicitly include the exact text wrapped in double quotes (e.g., "featuring written text 'COFFEE' in crisp white serif lettering across the mug").

CRITICAL EXCLUSION & FORMATTING RULES:
- Output ONLY the final raw prompt text paragraph.
- Target Length: 120 to 180 words maximum (to avoid Qwen 3 4B token truncation and attention degradation).
- Absolute Positivity Rule: DO NOT use negative words like "no", "not", "without", "lack of", or "free from" (transformer attention layers often misinterpret negation and generate the forbidden object).
- DO NOT include conversational intros or outros (e.g., do NOT say "Here is your prompt:").
- DO NOT use markdown code blocks, quotes, or XML/think tags like <think>.
- AVOID generic buzzwords (e.g., "4K", "8K", "masterpiece", "trending on artstation", "photorealistic"). Describe photorealism strictly through physical lighting, material optics, and camera specifications.
- ONLY OUTPUT TEXT"""


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
                elif 'access_key' in cred_data or 'gcp_access_key' in cred_data:
                    genai.configure(api_key=cred_data.get('access_key') or cred_data.get('gcp_access_key'))
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
        model: str = "gemini-1.5-pro"
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
            pil_image = self.load_image(image_input)
            
            # Generate content
            response = gemini_model.generate_content([prompt, pil_image])
            
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