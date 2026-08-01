# Qwen CUDA Media Chat

`qwen_media_chat.py` is an interactive terminal chatbot that runs Qwen2.5-VL locally on CUDA. It accepts ordinary conversation plus relative paths to images and videos.

The default model is `Qwen/Qwen2.5-VL-3B-Instruct`, loaded with 4-bit NF4 quantization. This is the same local model used by the iconic portrait experiment and is suitable for the available 12 GB NVIDIA GPU.

## Start the chatbot

From the repository root:

```bash
.venv/bin/python qwen_media_chat.py
```

The default media root is the directory from which the command is run. To use another directory:

```bash
.venv/bin/python qwen_media_chat.py --media-root /path/to/project
```

The model has already been downloaded on this machine. On another machine, the first launch downloads it from Hugging Face.

## Attach media

Prefix a relative file path with `@` anywhere in the message:

```text
you> Describe this character's expression and precise gaze direction. @output/frames/scene_108_last_frame.png
```

Multiple files can be supplied together:

```text
you> Compare the pose and framing in these images. @reference.png @candidate.png
```

Quote paths containing spaces:

```text
you> Summarize the visible action. @'media/test clip.mp4'
```

Existing bare relative media paths are also recognized, but the `@` form is recommended because missing files and unsupported extensions produce explicit errors.

Paths must remain inside `--media-root`. Absolute paths and `..` paths that escape the media root are rejected.

## Supported media

Images:

```text
bmp, gif, jpeg, jpg, png, tif, tiff, webp
```

Videos:

```text
avi, m4v, mkv, mov, mp4, mpeg, mpg, webm
```

Qwen2.5-VL does not directly analyze audio. For video files, the chatbot samples visual frames at 1 FPS by default; it does not transcribe or listen to the soundtrack.

## Commands and graceful exit

- `/clear` removes conversation and prior media from the active context.
- `/help` prints a short usage reminder.
- `/quit`, `/exit`, or `/q` exits normally.
- Ctrl-D exits normally.
- Ctrl-C at the input prompt exits normally.
- Ctrl-C during generation cancels that response and returns to the prompt.

Every normal exit path performs best-effort cleanup:

1. Moves the model off the GPU when possible.
2. Deletes model and processor references.
3. Runs Python garbage collection.
4. Clears the CUDA allocator cache.
5. Releases CUDA interprocess cached blocks when supported.

Turn-local tensors are deleted and the CUDA cache is cleared after every response. The model itself remains loaded between responses for responsive conversation and is unloaded when the program exits.

If the process is forcibly killed with `kill -9`, it cannot run its cleanup handler. The operating system and CUDA driver will still reclaim the process's memory after termination.

## Memory controls

Conversation history retains up to eight user/assistant pairs by default. Media in retained turns must be processed again on later turns, so clear old context or lower the limit for large inputs:

```bash
.venv/bin/python qwen_media_chat.py --max-history-turns 3
```

Control response length with:

```bash
.venv/bin/python qwen_media_chat.py --max-new-tokens 256
```

The program downsizes image tokenization and samples videos conservatively to control VRAM consumption. Very long or high-resolution videos should still be trimmed before use.

The optional `--no-4bit` flag loads BF16 weights. It is not recommended on a 12 GB GPU and may run out of memory.

## Dependencies

The required packages are already listed in `requirements-iconic-optimizer.txt`:

```bash
.venv/bin/pip install -r requirements-iconic-optimizer.txt
```

CUDA must be visible to PyTorch. Check it with:

```bash
.venv/bin/python -c "import torch; print(torch.cuda.is_available(), torch.cuda.get_device_name(0))"
```

## Accuracy warning

This model can confidently invent facts from its training data. In our direct test it claimed familiarity with Will Wight's *Unsouled* and then fabricated the protagonist and plot. Treat it as a visual and conversational assistant, not as an authoritative source of Cradle lore. Supply trusted text or media context whenever factual accuracy matters.
