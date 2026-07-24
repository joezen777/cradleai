# Pipeline Execution Summary

## What I've Built

I've created a complete 2-phase pipeline that exactly matches your requirements:

### Phase 1: GCP Vision Prompt Generation
**File**: [generate_prompts_from_metadata.py](generate_prompts_from_metadata.py)

✅ **Calls GCP Vision API ONCE per frame** (not 10 times)  
✅ **Creates 10 duplicate entries** with `gen_sequence` 1-10 for each frame  
✅ **Exponential backoff retry** for rate limiting (up to 5 attempts, max 60s delay)  
✅ **Progressive saving** - saves to [metadatagen.jsonl](output/metadatagen.jsonl) as it processes  
✅ **Resumable** - can resume from interruptions  
✅ **Links to metadata.jsonl** - fills in clip_file, scene_index, frame_file  
✅ **Output fields**: batch_name, clip_file, frame_file, frame_type, scene_index, prompt_text, seed (null), similarity_score (null), gen_sequence (1-10), gen_filename (null)  

### Phase 2: Image Generation from Prompts  
**File**: [generate_images_from_metadata.py](generate_images_from_metadata.py)

✅ **Groups by clip_file** - processes each distinct clip file  
✅ **Uses prompt_text from gen_sequence=1** for all generations  
✅ **Sequential processing** - one generation at a time  
✅ **Updates existing entries** - doesn't overwrite, only updates respective rows  
✅ **Saves progress** every 5 generations  
✅ **Stops on errors** with detailed logging  
✅ **Logs failures** to [image_generation_errors.log](image_generation_errors.log)  
✅ **Tracks last successful frame** for recovery  

### Complete Pipeline Orchestrator
**File**: [run_complete_pipeline.py](run_complete_pipeline.py)

✅ Runs both phases sequentially  
✅ Proper error handling and reporting  
✅ Progress tracking  
✅ Command-line interface for testing

## Quick Start Commands

### 1. Test with Small Batch (3 frames, 3 clips)
```bash
python run_complete_pipeline.py --max_frames 3 --max_clips 3 --batch_name zimageturbo --num_copies 10
```

### 2. Test Phase 1 Only (GCP Connection)
```bash
python run_complete_pipeline.py --skip_phase2 --max_frames 3 --batch_name zimageturbo --num_copies 10
```

### 3. Resume Phase 2 Only (after Phase 1 complete)
```bash
python run_complete_pipeline.py --skip_phase1
```

### 4. Full Pipeline (all 830 scenes)
```bash
python run_complete_pipeline.py --batch_name zimageturbo --num_copies 10
```

## Expected Workflow

### Initial Test Run (Recommended)
1. **Run Phase 1 test** (3 frames):
   ```bash
   python run_complete_pipeline.py --skip_phase2 --max_frames 3 --batch_name zimageturbo --num_copies 10
   ```
   - Should process 3 frames (first and last from first 2-3 scenes)
   - Creates ~60 entries in metadatagen.jsonl
   - Takes ~1-3 minutes

2. **Review Phase 1 output**:
   ```bash
   head -5 output/metadatagen.jsonl
   ```
   - Check prompt_text is generated
   - Verify gen_sequence values 1-10
   - Confirm links to metadata.jsonl fields

3. **Run Phase 2 test** (same 3 frames):
   ```bash
   python run_complete_pipeline.py --skip_phase1 --max_clips 3
   ```
   - Should generate ~60 images
   - Takes ~5-10 minutes
   - Updates gen_filename and similarity_score

4. **Verify outputs**:
   - Check generated images in `output/frames/zimageturbo/`
   - Verify similarity scores in metadatagen.jsonl
   - Review error log if any failures

### Full Pipeline (After Testing)
```bash
python run_complete_pipeline.py --batch_name zimageturbo --num_copies 10
```

**Expected Results:**
- **Phase 1**: ~3,320 frames processed → 33,200 entries created
- **Phase 2**: ~33,200 images generated
- **Total time**: 4-6 hours
- **Cost**: $1.00-$1.58 (GCP API only)

## Key Features Implemented

### Exponential Backoff Retry
```python
# Automatic retry with increasing delays
# Attempt 1: immediate
# Attempt 2: 1-2 seconds  
# Attempt 3: 2-4 seconds
# Attempt 4: 4-8 seconds
# Attempt 5: 8-16 seconds (max 60s)
```

### Error Handling
```python
# Phase 1 errors:
# - Creates entries with gcp_error field
# - Continues to next frame
# - Saves progress incrementally

# Phase 2 errors:
# - Logs to image_generation_errors.log
# - Records last successful frame
# - Stops processing (as requested)
# - Saves all progress so far
```

### Metadata Schema
```json
{
  "batch_name": "zimageturbo",
  "clip_file": "clips/scene_001.webm",
  "frame_file": "frames/scene_001_first_frame.png", 
  "frame_type": "first_frame_file",
  "scene_index": 1,
  "prompt_text": "generated from GCP Vision API...",
  "seed": 998257779057607,
  "similarity_score": 85.42,
  "gen_sequence": 1,
  "gen_filename": "output/frames/zimageturbo/2026-07-24_998257779057607.png",
  "timestamp": "2026-07-24T10:30:45.123456",
  "gcp_success": true,
  "gcp_error": null,
  "generation_success": true,
  "generation_error": null,
  "generation_timestamp": "2026-07-24T10:35:45.123456"
}
```

## Files Reference

### Main Pipeline Files
- **[run_complete_pipeline.py](run_complete_pipeline.py)** - Main orchestrator ⭐
- **[generate_prompts_from_metadata.py](generate_prompts_from_metadata.py)** - Phase 1 ⭐  
- **[generate_images_from_metadata.py](generate_images_from_metadata.py)** - Phase 2 ⭐

### Core Integration Files
- **[gcp_vision_prompt.py](gcp_vision_prompt.py)** - GCP Vision API client
- **[zimageturbo_batch_generator.py](zimageturbo_batch_generator.py)** - ComfyUI batch processor

### Documentation
- **[PIPELINE_SETUP_GUIDE.md](PIPELINE_SETUP_GUIDE.md)** - Complete setup guide ⭐
- **[QUICK_START_ZIMAGETURBO.md](QUICK_START_ZIMAGETURBO.md)** - Quick reference
- **[GCP_VISION_README.md](GCP_VISION_README.md)** - GCP API docs

## Troubleshooting

### Phase 1 Issues
**"GCP API rate limited"**
- ✅ Automatic retry with exponential backoff
- ✅ Wait and resume (it will continue from last success)

**"Credentials not found"**  
- ✅ Check [`.credentials`](.credentials) file exists
- ✅ Verify format matches example

### Phase 2 Issues
**"ComfyUI connection failed"**
- ✅ Check ComfyUI is running: `curl http://127.0.0.1:8188/system_stats`
- ✅ Verify endpoint is correct

**"Generation failed"**
- ✅ Check `image_generation_errors.log`
- ✅ Review last_successful_frame in output
- ✅ Resume with `--skip_phase1`

## Success Criteria

### Phase 1 Complete When:
- ✅ All frames processed (or max_frames reached)  
- ✅ All prompt_text fields filled (or gcp_error for failures)
- ✅ gen_sequence 1-10 created for each frame
- ✅ All metadata.jsonl fields properly linked

### Phase 2 Complete When:
- ✅ All pending entries processed
- ✅ gen_filename filled for successful generations
- ✅ similarity_score calculated for all
- ✅ All images in `output/frames/zimageturbo/`

## Cost & Performance

**GCP Vision API**: $1.00-$1.58 total  
**Z-Image Turbo**: Electricity only  
**Total Time**: 4-6 hours (830 scenes × 10 generations)

## Next Steps

1. **Install dependencies**: `pip install -r requirements.txt`
2. **Verify ComfyUI**: `curl http://127.0.0.1:8188/system_stats`
3. **Test with small batch**: `--max_frames 3 --max_clips 3`
4. **Review outputs**: Check prompts and images
5. **Scale up**: Run full pipeline if tests pass

---

**The pipeline is ready to run! Start with the test command above and verify results before scaling up to all 830 scenes.**