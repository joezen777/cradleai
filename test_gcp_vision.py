#!/usr/bin/env python3
"""
Example usage of GCP Vision Prompter
"""

from gcp_vision_prompt import GCPVisionPrompter
from pathlib import Path


def example_usage():
    """Demonstrate basic usage of GCP Vision Prompter"""
    
    # Initialize the prompter (will auto-detect .credentials file)
    prompter = GCPVisionPrompter()
    
    # Example: Process an image file
    image_path = "path/to/your/image.png"  # Replace with your image path
    
    if Path(image_path).exists():
        # Generate prompt using default system prompt
        result = prompter.generate_prompt(image_path)
        
        if result["success"]:
            print("Generated Response:")
            print(result["response_text"])
        else:
            print(f"Error: {result['error']}")
    else:
        print(f"Image file not found: {image_path}")
    
    # Example with custom prompt
    # custom_prompt = "Describe what's in this image in detail"
    # result = prompter.generate_prompt(image_path, prompt=custom_prompt)


if __name__ == "__main__":
    example_usage()