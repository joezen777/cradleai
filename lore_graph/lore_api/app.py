from __future__ import annotations

import contextlib
import threading
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from mcp.server.fastmcp import FastMCP

from .schemas import (
    CharacterContext, CharacterLookupRequest, LocateLoreRequest,
    LocateLoreResponse, PropContext, PropLookupRequest, SceneryContext,
    SceneryLookupRequest, GroundEnhanceRequest, GroundEnhanceResponse,
)
from .service import LoreService

ROOT = Path(__file__).resolve().parents[1]
_service = None
_service_lock = threading.Lock()


def service() -> LoreService:
    global _service
    if _service is None:
        with _service_lock:
            if _service is None:
                _service = LoreService(ROOT)
    return _service


mcp = FastMCP(
    "Cradle Source Lore",
    instructions=(
        "Locate source-grounded events, characters, scenery, props, wardrobe, "
        "dialogue, and visual descriptions in locally indexed copies of "
        "Unsouled and Soulsmith. Results contain passage and page citations."
    ),
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
)


@mcp.tool()
def ground_enhance(
    frame_image: str,
    pegasus_chapter_context: str,
    highlighted_summary: str | None = None,
    transcript: str | None = None,
    visual_reference_description: str | None = None,
    confirmed_passage_ids: list[str] | None = None,
    max_locations: int = 5,
) -> dict:
    """Ground and enhance a frame through a confirmation-gated local pipeline.

    Call first without `confirmed_passage_ids` to receive ranked, cited book
    locations. After selecting the correct passage IDs, call again with those
    IDs to run Pegasus, character, scenery, prop, and Z-Image Turbo stages.
    """
    request = GroundEnhanceRequest(
        frame_image=frame_image,
        pegasus_chapter_context=pegasus_chapter_context,
        highlighted_summary=highlighted_summary,
        transcript=transcript,
        visual_reference_description=visual_reference_description,
        confirmed_passage_ids=confirmed_passage_ids or [],
        max_locations=max_locations,
    )
    return service().ground_enhance(request).model_dump(mode="json")


@mcp.tool()
def locate_lore_context(
    frame_image: str | None = None,
    transcript: str | None = None,
    pegasus_chapter_summary: str | None = None,
    highlighted_summary: str | None = None,
    description: str | None = None,
    max_locations: int = 3,
) -> dict:
    """Match frame/transcript/Pegasus/description evidence to cited book locations.

    `highlighted_summary` should contain the Pegasus chapter-summary portion
    corresponding to this frame. `frame_image` accepts a project-local path or
    base64 data URI. Returns one or more complete lore-context records.
    """
    request = LocateLoreRequest(
        frame_image=frame_image, transcript=transcript,
        pegasus_chapter_summary=pegasus_chapter_summary,
        highlighted_summary=highlighted_summary, description=description,
        max_locations=max_locations,
    )
    return service().locate_lore(request).model_dump(mode="json")


@mcp.tool()
def locate_character_context(
    character_name_normalized: str | None = None,
    description: str | None = None,
    max_results: int = 10,
) -> list[dict]:
    """Find characters by deterministic normalized ID or visual description."""
    request = CharacterLookupRequest(
        character_name_normalized=character_name_normalized,
        description=description, max_results=max_results,
    )
    return [row.model_dump(mode="json") for row in service().locate_characters(request)]


@mcp.tool()
def locate_scenery_context(
    scenery_name_normalized: str | None = None,
    description: str | None = None,
    max_results: int = 10,
) -> list[dict]:
    """Find scenery by normalized location ID or descriptive evidence."""
    request = SceneryLookupRequest(
        scenery_name_normalized=scenery_name_normalized,
        description=description, max_results=max_results,
    )
    return [row.model_dump(mode="json") for row in service().locate_scenery(request)]


@mcp.tool()
def locate_prop_context(
    prop_name_normalized: str | None = None,
    description: str | None = None,
    max_results: int = 10,
) -> list[dict]:
    """Return up to ten portable prop/wardrobe matches and first appearances."""
    request = PropLookupRequest(
        prop_name_normalized=prop_name_normalized,
        description=description, max_results=max_results,
    )
    return [row.model_dump(mode="json") for row in service().locate_props(request)]


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    async with mcp.session_manager.run():
        yield


app = FastAPI(
    title="Cradle Source Lore API",
    version="1.0.0",
    description="Local cited lore retrieval over Unsouled and Soulsmith",
    lifespan=lifespan,
)


@app.exception_handler(ValueError)
async def invalid_input(_request: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


@app.exception_handler(RuntimeError)
async def unavailable(_request: Request, exc: RuntimeError) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.get("/health")
def health() -> dict:
    index = ROOT / "data" / "service_index.json"
    marker = ROOT / "data" / "processing_complete.json"
    return {
        "status": "ready" if index.is_file() and marker.is_file() else "processing",
        "index": str(index),
        "completion_marker": str(marker),
    }


@app.post("/v1/lore/locate", response_model=LocateLoreResponse)
def locate_lore_http(request: LocateLoreRequest) -> dict:
    return service().locate_lore(request).model_dump(mode="json")


@app.post("/v1/lore/ground-enhance", response_model=GroundEnhanceResponse)
def ground_enhance_http(request: GroundEnhanceRequest) -> dict:
    return service().ground_enhance(request).model_dump(mode="json")


@app.post("/v1/characters/locate", response_model=list[CharacterContext])
def locate_character_http(request: CharacterLookupRequest) -> list[dict]:
    return [row.model_dump(mode="json") for row in service().locate_characters(request)]


@app.post("/v1/scenery/locate", response_model=list[SceneryContext])
def locate_scenery_http(request: SceneryLookupRequest) -> list[dict]:
    return [row.model_dump(mode="json") for row in service().locate_scenery(request)]


@app.post("/v1/props/locate", response_model=list[PropContext])
def locate_prop_http(request: PropLookupRequest) -> list[dict]:
    return [row.model_dump(mode="json") for row in service().locate_props(request)]


app.mount("/mcp", mcp.streamable_http_app())
