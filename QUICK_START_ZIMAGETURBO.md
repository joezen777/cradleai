# Z-Image Turbo Integration Quick Start Guide

Complete quick start guide for the integrated GCP Vision + Z-Image Turbo workflow.

## Setup Instructions

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Verify ComfyUI is Running

```bash
curl http://127.0.0.1:8188/system_stats
```

Expected response: JSON with system information

### 3. Verify GPU Setup

```bash
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}'); print(f'GPU: {torch.cuda.get_device_name(0) if torch.cuda.is_available() else None}')"
```

## Quick Start Examples

### Single Scene Processing

**Method 1: Direct Python**
```python
from integrated_workflow import IntegratedWorkflowProcessor

processor = IntegratedWorkflowProcessor()

result = processor.process_single_scene(
    frame_path="output/frames/scene_001_first_frame.png",
    num_generations=3,
    scene_index=1
)
```

**Method 2: Command Line**
```bash
python integrated_workflow.py single \
  --frame output/frames/scene_001_first_frame.png \
  -n 3
```

### Batch Processing

**Method 1: Direct Python**
```python
from integrated_workflow import IntegratedWorkflowProcessor

processor = IntegratedWorkflowProcessor()

result = processor.process_batch_from_metadata(
    metadata_file="output/metadata.jsonl",
    num_scenes=5,
    num_generations_per_scene=3,
    start_scene=1
)
```

**Method 2: Command Line**
```bash
python integrated_workflow.py batch \
  --metadata output/metadata.jsonl \
  --num_scenes 5 \
  --num_generations 3 \
  --start_scene 1
```

### Custom Prompt + Batch Generation

```python
from zimageturbo_batch_generator import ComfyUIWorkflowProcessor

processor = ComfyUIWorkflowProcessor()

results = processor.batch_generate(
    prompt_text="A cinematic scene showing a dramatic temple interior",
    num_generations=5,
    batch_name="custom_prompt_test",
    clip_file="clips/scene_001.webm",
    frame_file="frames/scene_001_first_frame.png",
    scene_index=1
)
```

## Common Workflows

### Workflow 1: Test Single Scene

Perfect for testing setup and verifying everything works:

```bash
python integrated_workflow.py single \
  --frame output/frames/scene_001_first_frame.png \
  -n 1 \
  -b "test_setup"
```

**Expected Output:**
- 1 generated image in `output/frames/test_setup/`
- 1 metadata entry in `output/metadatagen.jsonl`
- Similarity score against original frame

### Workflow 2: Process First 5 Scenes

Good initial batch to test performance:

```bash
python integrated_workflow.py batch \
  --metadata output/metadata.jsonl \
  --num_scenes 5 \
  --num_generations 3 \
  --start_scene 1
```

**Expected Output:**
- 15 generated images (3 per scene) in separate folders
- 15 metadata entries with similarity scores
- Processing time: ~2-5 minutes

### Workflow 3: Continue from Scene 10

Resume processing from where you left off:

```bash
python integrated_workflow.py batch \
  --metadata output/metadata.jsonl \
  --num_scenes 10 \
  --num_generations 3 \
  --start_scene 10
```

### Workflow 4: Custom Prompt with GCP Vision

Get a prompt from GCP Vision, then generate variations:

```python
from gcp_vision_prompt import GCPVisionPrompter
from zimageturbo_batch_generator import ComfyUIWorkflowProcessor

# Get prompt from GCP Vision
gcp = GCPVisionPrompter()
gcp_result = gcp.generate_prompt("output/frames/scene_001_first_frame.png")

if gcp_result["success"]:
    prompt = gcp_result["response_text"]
    print(f"Generated prompt: {prompt[:100]}...")
    
    # Generate variations
    comfy = ComfyUIWorkflowProcessor()
    results = comfy.batch_generate(
        prompt_text=prompt,
        num_generations=5,
        batch_name="gcp_vision_test"
    )
```

## Output Locations

### Generated Images
```
output/frames/{batch_name}/
├── 2026-07-24_998257779057607.png
├── 2026-07-24_123456789012345.png
└── 2026-07-24_987654321098765.png
```

### Metadata
```
output/metadatagen.jsonl
```
Each line is a JSON object with generation details.

## Understanding Results

### Success Criteria

**Individual Generation:**
```python
result["success"]  # True if image was generated
result["similarity_score"]  # 0-100% structural similarity
result["gen_filename"]  # Path to generated image
```

**Batch Processing:**
```python
result["successful_scenes"]  # Number of successfully processed scenes
result["total_generations"]  # Total images generated
result["average_similarity"]  # Average similarity across all generations
```

### Similarity Score Interpretation

- **90-100%**: Excellent - structural elements preserved
- **75-89%**: Good - main elements present, some variations
- **60-74%**: Moderate - significant changes but recognizable
- **Below 60%**: Poor - major structural differences

## Performance Benchmarks

On NVIDIA RTX 5070 (12GB VRAM):

| Operation | Time | Memory Usage |
|-----------|------|--------------|
| GCP Vision Prompt | 1-3s | N/A (cloud) |
| Single Z-Image Generation | 2-5s | ~6GB |
| Similarity Score | 0.5-1s | ~2GB |
| Complete Scene (3 generations) | 8-18s | ~8GB |

**Batch Processing:**
- 5 scenes (15 images): ~2-5 minutes
- 50 scenes (150 images): ~15-25 minutes
- All 830 scenes (2,490 images): ~4-6 hours

## Troubleshooting

### ComfyUI Connection Failed

**Problem:**
```
ConnectionError: Failed to connect to 127.0.0.1:8188
```

**Solution:**
```bash
# Check if ComfyUI is running
curl http://127.0.0.1:8188/system_stats

# If not running, start ComfyUI
# (depends on your installation)
python main.py --listen 127.0.0.1 --port 8188
```

### GPU Memory Error

**Problem:**
```
RuntimeError: CUDA out of memory
```

**Solution:**
```python
# Reduce batch size
results = processor.process_single_scene(
    frame_path="frame.png",
    num_generations=2  # Reduce from 3 to 2
)
```

### GCP Vision API Error

**Problem:**
```
Error: Invalid credentials
```

**Solution:**
```bash
# Check .credentials file exists
cat .credentials

# Verify format:
# GCP ACCESS KEY:
#    your_access_key_here
```

### Frame File Not Found

**Problem:**
```
⚠ Frame file not found: output/frames/scene_999_first_frame.png
```

**Solution:**
```python
# List available scenes
import json

with open("output/metadata.jsonl", 'r') as f:
    for line in f:
        scene = json.loads(line)
        if 'scene_index' in scene:
            print(f"Scene {scene['scene_index']}: {scene.get('first_frame_file')}")
```

## Advanced Usage

### Custom Workflow

```python
# Use custom ComfyUI workflow
processor = ComfyUIWorkflowProcessor(
    workflow_file="my_custom_workflow.json"
)
```

### Custom Output Directory

```bash
python integrated_workflow.py batch \
  --output_dir "/path/to/custom/output" \
  --metadata_output "/path/to/custom/metadata.jsonl"
```

### Process Specific Scenes

```python
# Process scenes 1, 5, 10, 15
scene_indices = [1, 5, 10, 15]

for scene_idx in scene_indices:
    result = processor.process_batch_from_metadata(
        start_scene=scene_idx,
        num_scenes=1,
        num_generations_per_scene=3
    )
```

## Integration Examples

### Process with Custom Prompt Template

```python
def custom_prompt_generator(scene_metadata):
    """Generate custom prompt based on scene metadata"""
    template = f"""
    A cinematic {scene_metadata['resolution']} scene showing 
    frame {scene_metadata['start_frame']} to {scene_metadata['end_frame']}
    of the original video. Maintain exact composition and subject placement
    while enhancing with realistic lighting and materials.
    """
    return template.strip()

# Use with metadata
with open("output/metadata.jsonl", 'r') as f:
    scene = json.loads(f.readline())
    
    prompt = custom_prompt_generator(scene)
    
    results = processor.batch_generate(
        prompt_text=prompt,
        num_generations=3,
        scene_index=scene['scene_index']
    )
```

### Analyze Results

```python
import json
import pandas as pd

# Read metadata
metadata = []
with open("output/metadatagen.jsonl", 'r') as f:
    for line in f:
        metadata.append(json.loads(line))

# Create DataFrame
df = pd.DataFrame(metadata)

# Analyze
print(f"Total generations: {len(df)}")
print(f"Average similarity: {df['similarity_score'].mean():.2f}%")
print(f"Best similarity: {df['similarity_score'].max():.2f}%")
print(f"\nTop 5 generations by similarity:")
print(df.nlargest(5, 'similarity_score')[['batch_name', 'gen_sequence', 'similarity_score']])
```

## Next Steps

1. **Test single scene**: Verify setup works correctly
2. **Process small batch**: Test performance with 5-10 scenes
3. **Analyze results**: Check similarity scores and output quality
4. **Scale up**: Process all 830 scenes if results are satisfactory
5. **Iterate**: Adjust prompts and parameters based on results

## Support

For detailed documentation:
- [GCP Vision README](GCP_VISION_README.md)
- [Z-Image Turbo README](ZIMAGETURBO_BATCH_README.md)
- [Example scripts](test_zimageturbo_batch.py)