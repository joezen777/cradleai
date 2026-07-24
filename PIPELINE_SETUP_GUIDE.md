# Complete Pipeline Setup and Execution Guide

## Overview

The complete pipeline consists of two phases:

1. **Phase 1 (GCP Vision)**: Generate prompts from frame images using GCP Gemini Vision API
2. **Phase 2 (Z-Image Turbo)**: Generate images using the prompts and ComfyUI

## Files Created

### Core Pipeline Files
- **[run_complete_pipeline.py](run_complete_pipeline.py)** - Main orchestrator for both phases
- **[generate_prompts_from_metadata.py](generate_prompts_from_metadata.py)** - Phase 1: GCP Vision prompt generation
- **[generate_images_from_metadata.py](generate_images_from_metadata.py)** - Phase 2: Z-Image Turbo image generation

### Supporting Files
- **[gcp_vision_prompt.py](gcp_vision_prompt.py)** - GCP Vision API integration
- **[zimageturbo_batch_generator.py](zimageturbo_batch_generator.py)** - ComfyUI batch processor
- **[integrated_workflow.py](integrated_workflow.py)** - Alternative integrated workflow

## Environment Setup

### 1. Install Required Packages

```bash
pip install -r requirements.txt
```

Required packages:
```
opencv-python>=4.8.0
numpy>=1.24.0
google-cloud-vision>=3.7.0
google-cloud-storage>=2.10.0
Pillow>=10.0.0
torch>=2.0.0
torchvision>=0.15.0
lpips>=0.1.4
requests>=2.31.0
google-generativeai
```

### 2. Verify ComfyUI is Running

```bash
curl http://127.0.0.1:8188/system_stats
```

Expected response: JSON with system information including your RTX 5070

### 3. Verify GCP Credentials

Check that [`.credentials`](.credentials) file exists with proper format:
```
GCP ACCESS KEY:
   your_access_key_here

GCP SERVICE ACCOUNT NAME:
   your-service-account@project.iam.gserviceaccount.com
```

## Pipeline Features

### Phase 1: GCP Vision Prompt Generation

**Key Features:**
- ✅ Processes all `first_frame_file` and `last_frame_file` from [metadata.jsonl](output/metadata.jsonl)
- ✅ Calls GCP Gemini API **once per frame** (not 10 times)
- ✅ Creates 10 duplicate entries with `gen_sequence` 1-10 for each frame
- ✅ Exponential backoff retry for rate limiting
- ✅ Progressive saving - saves as it processes
- ✅ Resumable - can resume from interruptions
- ✅ Fills in metadata fields from [metadata.jsonl](output/metadata.jsonl)

**Output Schema:**
```json
{
  "batch_name": "zimageturbo",
  "clip_file": "clips/scene_001.webm",
  "frame_file": "frames/scene_001_first_frame.png",
  "frame_type": "first_frame_file",
  "scene_index": 1,
  "prompt_text": "generated prompt from GCP Vision...",
  "seed": null,
  "similarity_score": null,
  "gen_sequence": 1,
  "gen_filename": null,
  "timestamp": "2026-07-24T10:30:45.123456",
  "gcp_success": true,
  "gcp_error": null
}
```

### Phase 2: Z-Image Turbo Image Generation

**Key Features:**
- ✅ Groups entries by `clip_file` for efficient processing
- ✅ Uses `prompt_text` from `gen_sequence=1` for all generations
- ✅ Sequential processing - one at a time
- ✅ Updates existing [metadatagen.jsonl](output/metadatagen.jsonl) entries
- ✅ Saves progress every 5 generations
- ✅ Generates unique seeds for each generation
- ✅ Calculates similarity scores against original frames
- ✅ Comprehensive error logging to file
- ✅ Stops on errors with detailed failure information

**Error Handling:**
- Errors logged to `image_generation_errors.log`
- Last successful frame tracked
- Progress saved incrementally
- Can resume from interruptions

## Usage Examples

### Test with Small Batch (Recommended First)

```bash
# Test with 3 frames and 3 clips
python run_complete_pipeline.py --max_frames 3 --max_clips 3 --batch_name zimageturbo --num_copies 10
```

### Run Phase 1 Only (Testing GCP Connection)

```bash
# Test GCP Vision API with 3 frames
python run_complete_pipeline.py --skip_phase2 --max_frames 3 --batch_name zimageturbo --num_copies 10
```

### Resume Phase 2 Only (After Phase 1 Complete)

```bash
# Skip Phase 1, run Phase 2 for all completed prompts
python run_complete_pipeline.py --skip_phase1
```

### Process Limited Number of Clips

```bash
# Process first 10 clips after Phase 1 is done
python run_complete_pipeline.py --skip_phase1 --max_clips 10
```

### Full Pipeline (All 830 Scenes)

```bash
# Process all scenes (will take several hours)
python run_complete_pipeline.py --batch_name zimageturbo --num_copies 10
```

## Command Line Arguments

### Main Pipeline

```bash
python run_complete_pipeline.py [options]
```

**Options:**
- `--metadata`: Input metadata file (default: "output/metadata.jsonl")
- `--metadatagen`: Generated metadata file (default: "output/metadatagen.jsonl")
- `--workflow`: ComfyUI workflow file (default: "zimageturbo_cinematic.json")
- `--endpoint`: ComfyUI API endpoint (default: "http://127.0.0.1:8188")
- `--log_file`: Error log file (default: "image_generation_errors.log")
- `--batch_name`: Batch name for generations (default: "zimageturbo")
- `--num_copies`: Number of copies per frame (default: 10)
- `--max_frames`: Maximum frames for Phase 1 testing
- `--max_clips`: Maximum clips for Phase 2 testing
- `--skip_phase1`: Skip Phase 1 (if already completed)
- `--skip_phase2`: Skip Phase 2 (if already completed)

### Phase 1 Only

```bash
python generate_prompts_from_metadata.py [options]
```

**Options:**
- `--metadata`: Input metadata file
- `--metadatagen`: Output metadata file
- `--batch_name`: Batch name
- `--num_copies`: Copies per frame
- `--max_frames`: Maximum frames to process
- `--no_resume`: Don't resume from existing file

### Phase 2 Only

```bash
python generate_images_from_metadata.py [options]
```

**Options:**
- `--metadatagen`: Metadata file
- `--workflow`: ComfyUI workflow
- `--endpoint`: ComfyUI endpoint
- `--log_file`: Error log file
- `--max_clips`: Maximum clips to process
- `--save_interval`: Save every N generations

## Output Structure

### Generated Images
```
output/frames/{batch_name}/
├── 2026-07-24_998257779057607.png
├── 2026-07-24_123456789012345.png
└── 2026-07-24_987654321098765.png
```

### Metadata Files
- **[metadatagen.jsonl](output/metadatagen.jsonl)** - Complete generation metadata
- **[image_generation_errors.log](image_generation_errors.log)** - Error log

## Expected Performance

On NVIDIA RTX 5070 (12GB VRAM):

| Operation | Time | Notes |
|-----------|------|-------|
| GCP Vision Prompt | 1-3s | Per frame (cloud API) |
| Single Image Generation | 2-5s | Z-Image Turbo |
| Similarity Score | 0.5-1s | Neural comparison |
| Complete Scene (10 generations) | 25-60s | Includes prompts |

**Estimated Times:**
- Test (3 scenes): ~2-5 minutes
- Small batch (10 scenes): ~8-15 minutes  
- Medium batch (50 scenes): ~30-60 minutes
- All 830 scenes: ~4-6 hours

## Cost Estimates

### GCP Vision API (Phase 1)
- **1,660 frames × 1 API call each**
- **Input**: ~$0.50-$0.83
- **Output**: ~$0.50-$0.75
- **Total**: **$1.00-$1.58** (using gemini-1.5-flash)

### Z-Image Turbo (Phase 2)
- **16,600 images** (1,660 frames × 10 generations)
- **Local processing** - no cloud costs
- **Electricity only**

## Monitoring Progress

### During Phase 1
```
[1/20] Processing: frames/scene_001_first_frame.png
  Scene: 1, Type: first_frame_file
  Path: output/frames/scene_001_first_frame.png
  Attempt 1/5 for output/frames/scene_001_first_frame.png
  ✓ Prompt generated (423 chars)
  ✓ Created 10 metadata entries
```

### During Phase 2
```
[1/10] Processing clip: clips/scene_001.webm
  Batch: zimageturbo
  Generations: 20
  Prompt preview: A horizontal 16:9 eye-level medium shot...
    Generating sequence 1 with seed 998257779057607...
      ✓ Generated: output/frames/zimageturbo/2026-07-24_998257779057607.png
      ✓ Similarity: 85.42%
  💾 Saving progress (10 entries processed)...
```

## Error Recovery

### If Phase 1 Fails
1. Check [`.credentials`](.credentials) file
2. Check GCP API quota
3. Review error messages
4. Resume with same command (it will continue from last success)

### If Phase 2 Fails
1. Check ComfyUI is running: `curl http://127.0.0.1:8188/system_stats`
2. Review `image_generation_errors.log`
3. Check GPU memory usage
4. Resume with `--skip_phase1` to continue from Phase 2

### Common Issues

**GCP Rate Limiting:**
- Automatic exponential backoff with retry
- Maximum delay: 60 seconds
- Up to 5 retry attempts

**ComfyUI Connection:**
```
ConnectionError: Failed to connect to 127.0.0.1:8188
```
Solution: Ensure ComfyUI is running with `--listen 127.0.0.1 --port 8188`

**GPU Memory:**
```
RuntimeError: CUDA out of memory
```
Solution: Reduce concurrent operations (already sequential in this implementation)

## Verification

### Check Phase 1 Completion
```bash
# Count generated entries
wc -l output/metadatagen.jsonl

# Should be 16,600 lines (1,660 frames × 10 copies)
# Each frame has both first and last = 3,320 frames × 10 copies = 33,200 lines
```

### Check Phase 2 Completion
```bash
# Count completed generations
grep -c '"generation_success": true' output/metadatagen.jsonl

# Count failed generations
grep -c '"generation_success": false' output/metadatagen.jsonl
```

### Verify Output Files
```bash
# Check generated images
find output/frames/zimageturbo -name "*.png" | wc -l

# Should match number of successful generations
```

## Advanced Usage

### Custom Batch Name
```bash
python run_complete_pipeline.py --batch_name my_custom_batch_20260724
```

### Different Number of Generations
```bash
python run_complete_pipeline.py --num_copies 5  # Generate 5 variations instead of 10
```

### Process Specific Scene Range
```python
# Edit generate_prompts_from_metadata.py to filter by scene_index
# or use metadata filtering in Phase 2
```

## Next Steps

1. **Test with small batch**: Run with `--max_frames 3 --max_clips 3`
2. **Verify outputs**: Check generated prompts and images
3. **Scale up**: Process all 830 scenes if results are good
4. **Analyze results**: Review similarity scores and image quality
5. **Iterate**: Adjust prompts or parameters based on results

## Support Files

- [test_imports.py](test_imports.py) - Test environment setup
- [test_zimageturbo_batch.py](test_zimageturbo_batch.py) - Example usage scripts
- [QUICK_START_ZIMAGETURBO.md](QUICK_START_ZIMAGETURBO.md) - Quick start guide
- [ZIMAGETURBO_BATCH_README.md](ZIMAGETURBO_BATCH_README.md) - Detailed documentation
- [GCP_VISION_README.md](GCP_VISION_README.md) - GCP Vision API documentation