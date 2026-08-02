# Qwen CUDA Media Chat

For the complete two-process MCP and lore-grounded chat guide, see
[`README_QWEN_LORE_CHAT.md`](README_QWEN_LORE_CHAT.md).

`qwen_media_chat.py` is an interactive terminal chatbot that switches among five local models on CUDA. It accepts ordinary conversation plus relative paths to images and videos when the active model supports them.

The default model is Qwen2.5-VL 3B, loaded with 4-bit NF4 quantization. All configured models fit the available 12 GB NVIDIA GPU in their 4-bit forms.

## Switch models

Enter `/model` to list the five configured models. The active model is marked with `*`:

```text
/model
```

Switch by alias:

```text
/model qwen3-vl-8b
```

Available aliases:

| Alias | Model | Media input |
|---|---|---|
| `qwen2.5-vl-3b` | Qwen2.5-VL 3B | Images and video |
| `qwen3-vl-8b` | Qwen3-VL 8B | Images and video |
| `gemma3-12b` | Gemma 3 12B | Images |
| `qwen3-14b` | Qwen3 14B | Text only |
| `mistral-nemo-12b` | Mistral NeMo 12B | Text only |

Before loading a replacement, the program moves the current model off CUDA when possible, removes its Python references, runs garbage collection, clears the CUDA allocator cache, and releases cached CUDA IPC blocks. Conversation history is cleared because tokenizers, chat templates, and media capabilities differ across models. If the requested model fails to load, the program attempts to reload the previous model.

Choose the initial model from the command line with:

```bash
.venv/bin/python qwen_media_chat.py --model mistral-nemo-12b
```

## Start the chatbot

From the repository root:

```bash
.venv/bin/python qwen_media_chat.py
```

Start the local lore MCP server in a separate terminal first:

```bash
.venv/bin/python lore_graph/serve.py --host 127.0.0.1 --port 8765
```

Lore grounding is enabled by default. Each ordinary question is sent to the
local `locate_lore_context` MCP tool first, and its cited result is supplied to
the active chat model as authoritative context. Attached media remains with the
active chat model and is not sent to the lore server's separate vision model,
avoiding duplicate CUDA model use.

Use `/lore` to inspect the connection, `/lore off` or `/lore on` to toggle
automatic grounding, and `/lore <question>` to print a raw MCP result without
invoking the chat model:

```text
/lore What does Lindon's wooden badge look like and where does he wear it?
```

To start with automatic retrieval disabled or use another endpoint:

```bash
.venv/bin/python qwen_media_chat.py --no-lore
.venv/bin/python qwen_media_chat.py --lore-mcp-url http://192.168.1.10:8765/mcp/
```

`--lore-max-locations` controls how many cited locations are returned, from 1
through 10; the default is 3. If the server is unavailable, the chatbot reports
the connection failure and continues using the local model without lore context.

While a response is being generated, an animated `thinking` indicator remains
visible. Press Up/Down to revisit prompts from earlier sessions launched in the
same working directory. History is stored under
`$XDG_STATE_HOME/cradleai/qwen_media_chat/` (or `~/.local/state/...`) using a
working-directory-specific filename.

Type `@` followed by part of a relative file path and press Tab for Bash-style
completion. Tab inserts the longest common prefix when several entries match
and completes the full path when only one remains. Spaces can be quoted or
backslash-escaped. Ordinary apostrophes and unmatched quotation marks in a
question are treated as prose and do not cause shell-parsing errors.

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

- `/model` lists models and marks the active selection.
- `/model <alias>` unloads the active model and loads another.
- `/lore` reports lore MCP status and its endpoint.
- `/lore on` and `/lore off` toggle automatic source grounding.
- `/lore <question>` prints a direct `locate_lore_context` MCP result.
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

The optional `--no-4bit` flag affects the two full-weight Qwen VL repositories. The other three configured repositories are already quantized. BF16 is not recommended on a 12 GB GPU and may run out of memory.

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
