# ComfyUI Integration Guide

## Overview

This integration allows you to process video scene frames through ComfyUI for colorization and enhancement workflows.

## Quick Start

### 1. Start ComfyUI Server

Make sure your ComfyUI server is running at `http://127.0.0.1:8188`

```bash
# Navigate to your ComfyUI installation
cd path/to/ComfyUI

# Start the server
python main.py --listen 127.0.0.1 --port 8188
```

### 2. Test the Connection

```bash
python3 comfyui_integration.py
```

### 3. Inspect Your Workflow

```bash
python3 test_comfyui_workflow.py inspect
```

## Workflow Details

### Your Workflow: `cradleColorize.json`

**Analysis Results:**
- **Total Nodes**: 24
- **Model Type**: Flux2 image generation
- **Input Node**: Node 46 (LoadImage)
- **Output Node**: Node 9 (SaveImage)
- **Default Input**: `scene_006_last_frame.png`
- **Default Output Prefix**: `Flux2`

**Node Types:**
- LoadImage: Image input
- SaveImage: Image output
- UNETLoader: Model loading
- VAELoader/VAEDecode: Latent processing
- Flux2Scheduler: Sampling configuration
- Various control and processing nodes

## Usage Examples

### Example 1: Process a Single Frame

```python
from pathlib import Path
from comfyui_integration import ComfyUIIntegration

# Initialize ComfyUI client
comfyui = ComfyUIIntegration()

# Process a single frame
result = comfyui.process_image_workflow(
    workflow_path=Path("cradleColorize.json"),
    input_image_path=Path("output/frames/scene_001_first_frame.png"),
    output_prefix="scene_001_first_colorized",
    output_dir=Path("output/colorized")
)

print(f"Generated images: {result['output_images']}")
```

### Example 2: Process Complete Scene (First & Last Frames)

```python
from pathlib import Path
from comfyui_integration import process_scene_frames_comfyui

result = process_scene_frames_comfyui(
    scene_index=1,
    first_frame_path=Path("output/frames/scene_001_first_frame.png"),
    last_frame_path=Path("output/frames/scene_001_last_frame.png"),
    workflow_path=Path("cradleColorize.json"),
    output_base_dir=Path("output/colorized_scenes")
)

print(f"Scene 1 results: {result}")
```

### Example 3: Batch Process Multiple Scenes

```python
from pathlib import Path
from comfyui_integration import batch_process_scenes

# Process first 5 scenes
results = batch_process_scenes(
    metadata_path=Path("output/metadata.jsonl"),
    workflow_path=Path("cradleColorize.json"),
    output_base_dir=Path("output/colorized_batch"),
    scene_indices=[1, 2, 3, 4, 5]
)

# Check results
for scene_idx, result in results.items():
    if 'error' not in result:
        print(f"Scene {scene_idx}: ✓ Success")
    else:
        print(f"Scene {scene_idx}: ✗ {result['error']}")
```

### Example 4: Process All Scenes

```python
from pathlib import Path
from comfyui_integration import batch_process_scenes

# Process all 830 scenes
results = batch_process_scenes(
    metadata_path=Path("output/metadata.jsonl"),
    workflow_path=Path("cradleColorize.json"),
    output_base_dir=Path("output/colorized_all_scenes")
)

# Summary
successful = sum(1 for r in results.values() if 'error' not in r)
print(f"Processed {successful}/{len(results)} scenes successfully")
```

## Advanced Usage

### Custom Workflow Modification

```python
from comfyui_integration import ComfyUIIntegration

comfyui = ComfyUIIntegration()

# Load workflow
workflow = comfyui.load_workflow(Path("cradleColorize.json"))

# Modify input image
workflow = comfyui.modify_workflow_image_input(workflow, "my_custom_frame.png")

# Modify output prefix
workflow = comfyui.modify_workflow_output_prefix(workflow, "custom_output")

# Execute
prompt_id, _ = comfyui.execute_workflow(workflow)

# Wait for completion
execution_data = comfyui.wait_for_completion(prompt_id)

# Get output images
output_images = comfyui.get_output_images(execution_data)

# Download images
for image_info in output_images:
    save_path = Path("output") / image_info['filename']
    comfyui.download_image(image_info, save_path)
```

### Monitor Queue Status

```python
from comfyui_integration import ComfyUIIntegration

comfyui = ComfyUIIntegration()

# Check current queue
queue_info = comfyui.get_queue_info()
print(f"Queue status: {queue_info}")

# Get execution history
history = comfyui.get_history()
print(f"Total executions: {len(history)}")

# Get specific execution
if prompt_id:
    execution_data = comfyui.get_history(prompt_id)
    print(f"Execution status: {execution_data}")
```

## Integration with Metadata

### Update Metadata with Colorized Frames

```python
import json
from pathlib import Path
from comfyui_integration import batch_process_scenes

# Process scenes
results = batch_process_scenes(
    metadata_path=Path("output/metadata.jsonl"),
    workflow_path=Path("cradleColorize.json"),
    output_base_dir=Path("output/colorized_scenes"),
    scene_indices=[1, 2, 3]  # Process first 3 scenes
)

# Update metadata
metadata_file = Path("output/metadata.jsonl")
with open(metadata_file, 'r') as f:
    lines = f.readlines()

main_metadata = json.loads(lines[0])
scene_entries = [json.loads(line) for line in lines[1:]]

# Update scene entries with colorized paths
for scene in scene_entries:
    scene_idx = scene['scene_index']
    if scene_idx in results and 'error' not in results[scene_idx]:
        result = results[scene_idx]
        
        # Update colorized frame paths
        if result.get('first_frame') and result['first_frame'].get('output_images'):
            scene['colorizedFirstFrame'] = result['first_frame']['output_images'][0]
        
        if result.get('last_frame') and result['last_frame'].get('output_images'):
            scene['colorizedLastFrame'] = result['last_frame']['output_images'][0]

# Write updated metadata
with open(metadata_file, 'w') as f:
    f.write(json.dumps(main_metadata) + '\n')
    for scene in scene_entries:
        f.write(json.dumps(scene) + '\n')

print("✓ Metadata updated with colorized frame paths")
```

## Error Handling

```python
from comfyui_integration import ComfyUIIntegration
import time

comfyui = ComfyUIIntegration()

try:
    # Check server status
    if not comfyui.check_server_status():
        raise ConnectionError("ComfyUI server is not running")
    
    # Process workflow
    result = comfyui.process_image_workflow(
        workflow_path=Path("cradleColorize.json"),
        input_image_path=Path("test_frame.png"),
        output_prefix="test",
        output_dir=Path("output")
    )
    
    print("✓ Processing successful")
    
except ConnectionError as e:
    print(f"Connection error: {e}")
    print("Please ensure ComfyUI server is running at http://127.0.0.1:8188")
    
except FileNotFoundError as e:
    print(f"File not found: {e}")
    
except TimeoutError as e:
    print(f"Processing timeout: {e}")
    print("Try increasing timeout or checking queue status")
    
except Exception as e:
    print(f"Unexpected error: {e}")
```

## Performance Tips

### 1. Batch Processing
```python
# Process multiple scenes in sequence
scene_indices = list(range(1, 11))  # First 10 scenes
results = batch_process_scenes(
    metadata_path=Path("output/metadata.jsonl"),
    workflow_path=Path("cradleColorize.json"),
    output_base_dir=Path("output/colorized_batch"),
    scene_indices=scene_indices
)
```

### 2. Progress Monitoring
```python
import time
from comfyui_integration import ComfyUIIntegration

comfyui = ComfyUIIntegration()
prompt_id, _ = comfyui.execute_workflow(workflow)

# Monitor progress
start_time = time.time()
while True:
    history = comfyui.get_history(prompt_id)
    if prompt_id in history:
        status = history[prompt_id].get('status', {})
        if status.get('completed'):
            break
        
        # Show progress
        elapsed = time.time() - start_time
        print(f"Processing... Elapsed: {elapsed:.1f}s")
    
    time.sleep(2)
```

### 3. Queue Management
```python
from comfyui_integration import ComfyUIIntegration

comfyui = ComfyUIIntegration()

# Check queue before submitting
queue_info = comfyui.get_queue_info()
queue_running = queue_info.get('queue_running', [])
queue_pending = queue_info.get('queue_pending', [])

print(f"Currently running: {len(queue_running)} jobs")
print(f"Pending: {len(queue_pending)} jobs")

# Only submit if queue is not full
if len(queue_pending) < 5:
    print("✓ Queue available, submitting workflow...")
    # Submit workflow
else:
    print("⏳ Queue full, waiting...")
```

## Testing

### Run Test Suite

```bash
# Inspect workflow structure
python3 test_comfyui_workflow.py inspect

# Test single frame processing
python3 test_comfyui_workflow.py single

# Test complete scene processing
python3 test_comfyui_workflow.py scene

# Test batch processing
python3 test_comfyui_workflow.py batch
```

## Troubleshooting

### Server Not Running
```
✗ ComfyUI server is not running
```
**Solution**: Start ComfyUI server: `python main.py --listen 127.0.0.1 --port 8188`

### Workflow Not Found
```
✗ Workflow file not found: cradleColorize.json
```
**Solution**: Ensure `cradleColorize.json` is in the current directory

### Image Upload Failed
```
✗ Error uploading image: File not found
```
**Solution**: Check that the input frame images exist in `output/frames/`

### Timeout Error
```
✗ Workflow execution timed out
```
**Solution**: Increase timeout in `wait_for_completion()` or check if workflow is hanging

### Missing Dependencies
```
ModuleNotFoundError: No module named 'requests'
```
**Solution**: Install dependencies: `pip install requests`

## Files Created

1. **[comfyui_integration.py](comfyui_integration.py)** - Main ComfyUI integration class and functions
2. **[test_comfyui_workflow.py](test_comfyui_workflow.py)** - Test suite and examples
3. **[COMFYUI_INTEGRATION_GUIDE.md](COMFYUI_INTEGRATION_GUIDE.md)** - This documentation

## Next Steps

1. ✅ Start ComfyUI server
2. ✅ Test connection with `python3 comfyui_integration.py`
3. ✅ Inspect workflow with `python3 test_comfyui_workflow.py inspect`
4. ✅ Process single frame with `python3 test_comfyui_workflow.py single`
5. ✅ Batch process scenes as needed
6. ✅ Update metadata with colorized frame paths

## API Reference

### ComfyUIIntegration Class

**Methods:**
- `check_server_status()` - Check if ComfyUI server is running
- `get_history(prompt_id=None)` - Get execution history
- `get_queue_info()` - Get current queue status
- `upload_image(image_path)` - Upload image to server
- `load_workflow(workflow_path)` - Load workflow from JSON
- `modify_workflow_image_input(workflow, image_filename)` - Change input image
- `modify_workflow_output_prefix(workflow, prefix)` - Change output prefix
- `execute_workflow(workflow)` - Execute workflow on server
- `wait_for_completion(prompt_id, timeout, check_interval)` - Wait for completion
- `get_output_images(execution_data)` - Extract output images
- `download_image(image_info, save_path)` - Download output image
- `process_image_workflow(...)` - Complete image processing workflow

### Standalone Functions

- `process_scene_frames_comfyui(...)` - Process both frames of a scene
- `batch_process_scenes(...)` - Batch process multiple scenes

---

**Status**: ✅ Integration Complete  
**Workflow**: Analyzed and Ready  
**Server**: Waiting for ComfyUI startup  
**Tests**: Ready to run