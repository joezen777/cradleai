# Qwen Chat with the Cradle Lore MCP Server

The Qwen media chat and Cradle lore server run as two separate processes:

1. The lore MCP server searches the locally indexed text of *Unsouled* and
   *Soulsmith* and returns source-cited context.
2. The chat program runs the selected Qwen, Gemma, or Mistral model on the local
   CUDA GPU and uses the MCP results to ground its answers.

Keeping them separate lets the MCP server remain available to other clients and
allows the chat model to be restarted or switched without reopening the lore
database.

## Prerequisites

Run all commands from the repository root:

```bash
cd /home/joezen777/cradleai
```

The lore processing pipeline must already have produced:

```text
lore_graph/data/service_index.json
lore_graph/data/processing_complete.json
```

Install dependencies if the virtual environment has not already been prepared:

```bash
.venv/bin/pip install -r lore_graph/requirements.txt
.venv/bin/pip install -r requirements-iconic-optimizer.txt
```

## Terminal 1: start the lore MCP server

```bash
.venv/bin/python lore_graph/serve.py --host 127.0.0.1 --port 8765
```

Leave this process running. A successful startup ends with a message similar to:

```text
Uvicorn running on http://127.0.0.1:8765
```

Verify readiness from another terminal:

```bash
curl -sS http://127.0.0.1:8765/health
```

The response should contain:

```json
{"status":"ready"}
```

The service interfaces are:

- MCP Streamable HTTP: `http://127.0.0.1:8765/mcp/`
- REST API documentation: `http://127.0.0.1:8765/docs`
- Health check: `http://127.0.0.1:8765/health`

The MCP server exposes these tools:

- `locate_lore_context`
- `locate_character_context`
- `locate_scenery_context`
- `locate_prop_context`

## Terminal 2: start the chat program

With the MCP server still running, open a second terminal and run:

```bash
cd /home/joezen777/cradleai
.venv/bin/python qwen_media_chat.py
```

By default, the chat connects to:

```text
http://127.0.0.1:8765/mcp/
```

It also enables automatic lore grounding. For each ordinary question, the chat
program:

1. Calls `locate_lore_context` through MCP.
2. Retrieves up to three matching, source-cited book locations.
3. Adds that material to the active model's prompt as authoritative context.
4. Asks the local chat model to answer the original question.

For example:

```text
you> What does Lindon's wooden badge look like and where does he wear it?
```

The program reports how many lore locations were attached before generating the
answer. When appropriate, ask the model to include the returned book, chapter,
page, or passage citations in its answer.

## Lore commands inside chat

Show the current MCP URL and whether automatic grounding is enabled:

```text
/lore
```

Disable automatic lore lookup temporarily:

```text
/lore off
```

Enable it again:

```text
/lore on
```

Query the MCP server directly and print its raw JSON response without asking the
chat model to interpret it:

```text
/lore Elder Whisper in the tower
```

Direct `/lore <question>` queries are useful for checking retrieval accuracy,
citations, character records, scenery, props, and macro-scenery data.

## Chat commands

- `/model` lists the available local models.
- `/model <alias>` unloads the current model and loads another.
- `/lore` shows lore connection status.
- `/lore on` and `/lore off` toggle automatic lore grounding.
- `/lore <question>` prints a direct raw lore result.
- `/clear` clears the current model conversation.
- `/help` displays an abbreviated command guide.
- `/quit`, `/exit`, or `/q` exits gracefully and releases model memory.

Examples of switching models:

```text
/model
/model qwen3-vl-8b
```

## Using images and video with lore grounding

Attach project-local media with an `@` reference:

```text
you> Identify the characters and compare this frame with the book scene. @output/frame.png
```

Paths containing spaces may be quoted:

```text
you> Describe the action in this clip. @'media/my clip.mp4'
```

Press Tab after typing `@` and part of a path for filesystem completion. Press
Up or Down to recall prompts from this working directory's persistent history.

The attached media is processed by the active visual chat model. The chat sends
the written question to the lore MCP server, but it deliberately does not send
the image or video to the lore server's separate vision interpreter. This avoids
loading a second vision model and competing for the same 12 GB of VRAM.

For the most accurate match, include visible or narrative clues in the written
question:

```text
you> This is Lindon and Kelsa practicing the Empty Palm in the Shi family gardens. Compare the flowers, characters, and distant Sacred Valley scenery with the source. @frame.png
```

## Startup options

Start with a particular model:

```bash
.venv/bin/python qwen_media_chat.py --model qwen3-vl-8b
```

Start without automatic lore retrieval:

```bash
.venv/bin/python qwen_media_chat.py --no-lore
```

Change the number of source locations retrieved for each question:

```bash
.venv/bin/python qwen_media_chat.py --lore-max-locations 5
```

The allowed range is 1 through 10; the default is 3.

Connect to a lore MCP server at another address:

```bash
.venv/bin/python qwen_media_chat.py \
  --lore-mcp-url http://192.168.1.10:8765/mcp/
```

If another machine must reach the server, bind it to the network interface:

```bash
.venv/bin/python lore_graph/serve.py --host 0.0.0.0 --port 8765
```

Only expose this server on a trusted network. Its responses can contain source
passages from the locally indexed books. Use firewall restrictions and an
authenticated TLS reverse proxy before exposing it beyond that network.

## Running the MCP server with `uv`

The existing virtual environment is the simplest way to run the server. It can
also be launched with `uv` without changing the repository packaging:

```bash
uv run --with-requirements lore_graph/requirements.txt \
  lore_graph/serve.py --host 127.0.0.1 --port 8765
```

The chat program still runs separately in its own terminal.

For Codex and other coding agents, the same project also provides a stdio MCP
entry point that can be launched directly with `uvx`. See the
[`lore_graph` README](lore_graph/README.md#local-uvxstdio-mcp-package-for-coding-agents)
for the Codex configuration. The stdio and HTTP surfaces expose the same tools;
the Qwen chat continues to use the HTTP surface.

## Troubleshooting

### Chat says `Lore MCP unavailable`

Confirm Terminal 1 is still running, then check:

```bash
curl -sS http://127.0.0.1:8765/health
```

Make sure the chat URL includes the trailing MCP path:

```text
http://127.0.0.1:8765/mcp/
```

The chat continues without lore context when the MCP connection fails, so a
connection error does not terminate the local model session.

### Health reports `processing`

Finish or resume the lore ingestion pipeline before querying it:

```bash
.venv/bin/python lore_graph/resume_processing.py
```

Stop the lore server before rebuilding its database, then restart it after the
pipeline completes.

### Port 8765 is already in use

Choose another port for both processes:

```bash
.venv/bin/python lore_graph/serve.py --host 127.0.0.1 --port 8877
.venv/bin/python qwen_media_chat.py --lore-mcp-url http://127.0.0.1:8877/mcp/
```

### The direct lore result is correct but the model's answer is not

Use `/lore <question>` to inspect the source result. Clear stale conversation
context with `/clear`, phrase the question with distinguishing event details,
and ask the model to rely only on the supplied source context. The MCP result is
the grounding evidence; the chat model can still misunderstand or summarize it
incorrectly.

## Shutdown

Exit the chat first:

```text
/quit
```

This gracefully unloads the model and clears CUDA memory. Then return to the MCP
server terminal and press Ctrl-C. Start the MCP server again after any lore graph
rebuild so it loads the current service index and corpus fingerprint.
