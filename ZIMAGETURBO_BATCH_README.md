# Z-Image Turbo Batch Generator for ComfyUI

Comprehensive batch processing system for Z-Image Turbo image generation with similarity scoring, metadata tracking, and GPU optimization.

## Features

- **Batch Processing**: Generate multiple images with different seeds in one run
- **ComfyUI Integration**: Full integration with ComfyUI workflow system
- **GPU Optimization**: Optimized for NVIDIA RTX 5070 with TensorFloat-32 acceleration
- **Similarity Scoring**: Neural edge extraction + LPIPS for perceptual similarity
- **Metadata Tracking**: Comprehensive JSONL metadata logging for all generations
- **Flexible Workflow**: Support for custom workflows and parameters

## Installation

Install required dependencies:

```bash
pip install -r requirements.txt
```

### GPU Requirements

- **Minimum**: NVIDIA GPU with CUDA support
- **Recommended**: NVIDIA RTX 5070 (12GB VRAM) or better
- **CUDA Version**: 12.8 or newer
- **PyTorch**: Built with CUDA support

## Usage

### Command Line

**Basic usage:**
```bash
python zimageturbo_batch_generator.py "Your prompt text here" -n 5
```

**With batch name and scene metadata:**
```bash
python zimageturbo_batch_generator.py "Your prompt text here" \
  -n 3 \
  -b "temple_scene_001" \
  -c "clips/scene_001.webm" \
  -f "frames/scene_001_first_frame.png" \
  -s 1
```

**Full options:**
```bash
python zimageturbo_batch_generator.py "Prompt text" \
  -n 5 \
  -b "batch_name" \
  -c "clip_file" \
  -f "frame_file" \
  -s 1 \
  -w "workflow.json" \
  -e "http://127.0.0.1:8188" \
  -o "output/frames" \
  -m "output/metadatagen.jsonl"
```

### Python API

```python
from zimageturbo_batch_generator import ComfyUIWorkflowProcessor

# Initialize processor
processor = ComfyUIWorkflowProcessor(
    workflow_file="zimageturbo_cinematic.json",
    endpoint="http://127.0.0.1:8188"
)

# Generate batch
results = processor.batch_generate(
    prompt_text="Your prompt text",
    num_generations=5,
    output_dir="output/frames",
    batch_name="my_batch",
    clip_file="clips/scene_001.webm",
    frame_file="frames/scene_001_first_frame.png",
    scene_index=1,
    metadata_file="output/metadatagen.jsonl"
)

# Check results
for result in results:
    if result["success"]:
        print(f"Generated: {result['gen_filename']}")
        print(f"Seed: {result['seed']}")
        print(f"Similarity: {result['similarity_score']}%")
```

## Command Line Arguments

- `prompt_text` (required): Prompt text for image generation
- `-n, --num_generations`: Number of images to generate (default: 1)
- `-b, --batch_name`: Batch name for output folder (default: "gens")
- `-c, --clip_file`: Reference to clip file in metadata.jsonl
- `-f, --frame_file`: Reference to frame file in metadata.jsonl
- `-s, --scene_index`: Scene index from metadata.jsonl
- `-w, --workflow`: ComfyUI workflow file (default: "zimageturbo_cinematic.json")
- `-e, --endpoint`: ComfyUI API endpoint (default: "http://127.0.0.1:8188")
- `-o, --output_dir`: Output directory (default: "output/frames")
- `-m, --metadata_file`: Metadata output file (default: "output/metadatagen.jsonl")

## Output Structure

Generated images are saved as:
```
output/frames/{batch_name}/
├── 2026-07-24_998257779057607.png
├── 2026-07-24_123456789012345.png
└── 2026-07-24_987654321098765.png
```

## Metadata Format

Each generation is logged to `metadatagen.jsonl` with the following schema:

```json
{
  "batch_name": "temple_scene_001",
  "clip_file": "clips/scene_001.webm",
  "frame_file": "frames/scene_001_first_frame.png",
  "scene_index": 1,
  "prompt_text": "A horizontal 16:9 eye-level medium shot captures...",
  "seed": 998257779057607,
  "similarity_score": 85.42,
  "gen_sequence": 1,
  "gen_filename": "output/frames/temple_scene_001/2026-07-24_998257779057607.png",
  "timestamp": "2026-07-24T10:30:45.123456"
}
```

### Metadata Fields

- `batch_name`: Identifier for the batch (e.g., "zimageturboqwen20260724")
- `clip_file`: Reference to clip file in metadata.jsonl
- `frame_file`: Reference to frame file (first_frame_file or last_frame_file)
- `scene_index`: Scene index from metadata.jsonl
- `prompt_text`: The prompt used for generation
- `seed`: Random seed used for generation
- `similarity_score`: Structural similarity percentage (0-100)
- `gen_sequence`: Sequence number in batch (1-N)
- `gen_filename`: Full path to generated image
- `timestamp`: ISO format timestamp

## Similarity Scoring

The system uses a sophisticated similarity scoring approach:

### Method: Neural Edge Extraction + LPIPS

1. **Edge Extraction**: Uses PiDiNet or Canny edge detection to extract clean line art
2. **Perceptual Similarity**: LPIPS (Learned Perceptual Image Patch Similarity) for structural comparison
3. **GPU Optimization**: TensorFloat-16 and mixed precision for RTX 5070

### Hardware Optimization

```python
# TensorFloat-32 for Blackwell architecture
torch.backends.cuda.matmul.allow_tf32 = True
torch.backends.cudnn.allow_tf32 = True

# Mixed precision inference
with torch.autocast(device_type='cuda', dtype=torch.bfloat16):
    # Similarity calculation
```

### Resolution Handling

- Native 720p (1280x720): Works directly
- Native 768p (1366x768): Auto-padded to 1376 or cropped to 1344
- Ensures dimensions divisible by 32 for deep network compatibility

### Score Interpretation

- **90-100%**: Excellent structural fidelity
- **75-89%**: Good structural preservation
- **60-74%**: Moderate structural similarity
- **Below 60%**: Significant structural differences

## Workflow Customization

The system works with any ComfyUI workflow JSON. To customize:

1. Ensure your workflow has these nodes:
   - KSampler node with seed input
   - SaveImage node with filename_prefix input
   - CLIP Text Encode node with text input

2. The system automatically modifies:
   - Seed in KSampler node
   - filename_prefix in SaveImage node
   - Text in CLIP Text Encode node

## GPU Memory Management

The system is optimized for 12GB VRAM (RTX 5070):

- **Memory per similarity calculation**: ~2GB
- **Maximum concurrent operations**: 4-5 similarity scores
- **Precision**: BFloat16 reduces memory by 50%
- **Resolution**: Native 720p/768p keeps memory usage low

## Performance Considerations

### Speed
- Single generation: ~2-5 seconds (depending on complexity)
- Similarity calculation: ~0.5-1 seconds per image
- Batch of 10: ~30-60 seconds total

### Optimization Tips

1. **Batch size**: Process 5-10 images at a time for best performance
2. **Resolution**: Use native 720p for faster similarity scoring
3. **GPU**: Enable TensorFloat-32 for 2x speed improvement
4. **Network**: Fast local connection to ComfyUI reduces latency

## Integration with GCP Vision API

Combine with the GCP Vision prompt generator:

```python
from gcp_vision_prompt import GCPVisionPrompter
from zimageturbo_batch_generator import ComfyUIWorkflowProcessor

# Get prompt from GCP Vision
gcp_prompter = GCPVisionPrompter()
gcp_result = gcp_prompter.generate_prompt("path/to/frame.png")

if gcp_result["success"]:
    # Use prompt for ComfyUI generation
    processor = ComfyUIWorkflowProcessor()
    processor.batch_generate(
        prompt_text=gcp_result["response_text"],
        num_generations=5,
        batch_name="gcp_vision_batch"
    )
```

## Troubleshooting

### ComfyUI Connection Issues

```bash
# Check if ComfyUI is running
curl http://127.0.0.1:8188/system_stats

# Restart ComfyUI if needed
# (depends on your ComfyUI installation method)
```

### GPU Memory Issues

```python
# Reduce memory usage by processing fewer images at once
results = processor.batch_generate(
    num_generations=3,  # Reduce batch size
    prompt_text=prompt
)
```

### Edge Detection Issues

```python
# System falls back to Canny if PiDiNet unavailable
# Check OpenCV installation
import cv2
print(cv2.__version__)  # Should be >= 4.5.0
```

## Examples

See [test_zimageturbo_batch.py](test_zimageturbo_batch.py) for comprehensive examples:

1. Single scene processing
2. Batch processing from metadata.jsonl
3. Integration with GCP Vision API

## File Dependencies

Required files:
- `zimageturbo_cinematic.json`: ComfyUI workflow definition
- `.credentials`: GCP credentials (if using GCP Vision API)
- `output/metadata.jsonl`: Scene metadata (if processing scenes)

Generated files:
- `output/frames/{batch_name}/`: Generated images
- `output/metadatagen.jsonl`: Generation metadata

## Cost Estimation

For processing 1,660 frames with 3 variations each:
- **ComfyUI generations**: ~5,000 images
- **Similarity calculations**: ~5,000 comparisons
- **Total time**: ~4-8 hours on RTX 5070
- **GPU cost**: Electricity only (local processing)

## License

Part of the CradleAI project for automated video scene enhancement.