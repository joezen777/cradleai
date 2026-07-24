# GCP Vision API Integration

This module provides a Python script to call Google Cloud Platform Vision API with image inputs to generate text prompts optimized for SDXL sketch-to-photo workflows.

## Features

- **Automatic credential detection**: Reads from `.credentials` file or accepts custom credentials
- **Flexible image input**: Supports file paths, Path objects, or PIL Image objects
- **Custom prompts**: Use the built-in SDXL-optimized prompt or provide your own
- **Multiple models**: Supports various Gemini Vision models (gemini-1.5-flash, gemini-1.5-pro, etc.)
- **Error handling**: Comprehensive error handling and response formatting

## Installation

Install the required dependencies:

```bash
pip install -r requirements.txt
```

## Credentials Setup

The script automatically looks for credentials in three ways (in order):

1. **Credentials file path**: Pass a path to a service account JSON file
2. **Access key**: Pass a GCP API access key directly
3. **.credentials file**: Automatically reads from `.credentials` in workspace root

### .credentials file format

The `.credentials` file should contain:

```
GCP ACCESS KEY:
   your_access_key_here

GCP SERVICE ACCOUNT NAME:
   your-service-account@project.iam.gserviceaccount.com
```

## Usage

### Command Line

Basic usage with default SDXL-optimized prompt:

```bash
python gcp_vision_prompt.py path/to/image.png
```

With custom model:

```bash
python gcp_vision_prompt.py path/to/image.png --model gemini-1.5-pro
```

Save output to file:

```bash
python gcp_vision_prompt.py path/to/image.png --output response.json
```

### Python API

```python
from gcp_vision_prompt import GCPVisionPrompter
from PIL import Image

# Initialize prompter (auto-detects credentials)
prompter = GCPVisionPrompter()

# Generate prompt from image file
result = prompter.generate_prompt("path/to/image.png")

if result["success"]:
    print(result["response_text"])
else:
    print(f"Error: {result['error']}")

# Use with PIL Image
pil_image = Image.open("path/to/image.png")
result = prompter.generate_prompt(pil_image)

# Use custom prompt
custom_prompt = "Describe this image in detail for a medical report"
result = prompter.generate_prompt("path/to/image.png", prompt=custom_prompt)

# Specify model
result = prompter.generate_prompt(
    "path/to/image.png",
    model="gemini-1.5-pro"
)
```

## Default Prompt

The script includes a carefully crafted default prompt optimized for SDXL Base and Refiner sketch-to-photo workflows. The prompt:

- Strips artistic medium descriptors (sketch, drawing, etc.)
- Avoids synthetic buzzwords (photorealistic, 4k, 8k, etc.)
- Uses optic-centric parameters (camera settings, lens, aperture)
- Injects color and texture descriptions
- Provides dual-encoder structure for SDXL (OpenCLIP and CLIP-L)

## Response Format

The function returns a dictionary with:

```python
{
    "success": True/False,
    "model": "model_name_used",
    "prompt_used": "the_prompt_that_was_used",
    "response_text": "generated_text_response",
    "full_response": full_api_response_object,  # on success
    "error": "error_message"  # on failure
}
```

## Supported Models

- `gemini-1.5-flash` (default, faster)
- `gemini-1.5-pro` (more capable)
- Other Gemini Vision models as available

## Examples

See [test_gcp_vision.py](test_gcp_vision.py) for example usage patterns.

## Error Handling

The script handles various error conditions:
- Missing credentials
- Invalid image formats
- API rate limits
- Network issues
- Invalid model names

Check the `success` field in the response and handle `error` field appropriately.

## Notes

- The `.credentials` file is automatically detected in the workspace root
- Images are converted to PNG format internally for API compatibility
- Large images may be resized or compressed automatically
- API calls count toward your GCP Vision API quota