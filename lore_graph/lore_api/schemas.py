from __future__ import annotations

from pydantic import BaseModel, Field, model_validator


class LocationInBook(BaseModel):
    book_id: str
    book_title: str
    chapter_number: int
    chapter_label: str
    passage_id: str
    page_start: int
    page_end: int
    surrounding_paragraph: str
    chapter_summary: str
    confidence_rating: float = Field(ge=0.0, le=1.0)


class CharacterContext(BaseModel):
    character_name: str
    character_name_normalized: str
    visual_description_source: list[str]
    aggregate_character_visual_description: str
    appearance_changes: list[str]
    character_interactions: list[str]
    character_dialog: list[str]
    first_mentioned: LocationInBook | None = None


class SceneryContext(BaseModel):
    weather: str
    time_of_day: str
    climate: str
    setting: str = Field(pattern="^(interior|exterior|space|black|unknown)$")
    location: str
    location_name_normalized: str
    backdrop: str
    visual_description_source: list[str]
    first_mentioned: LocationInBook | None = None
    macro_scenery_context: list["MacroSceneryContext"] = []


class MacroSceneryContext(BaseModel):
    region_name: str
    region_name_normalized: str
    aggregate_region_description: str
    inherited_backdrop: str
    source_descriptions: list[str]
    source_locations: list[LocationInBook]
    applicability: str


class PropContext(BaseModel):
    character_name_normalized: str | None
    placement: str
    source_description: list[str]
    prop_name: str
    prop_name_normalized: str
    first_mentioned: LocationInBook | None = None


class LoreContextResult(BaseModel):
    location_in_book: LocationInBook
    characters: dict[str, CharacterContext]
    scenery_source: dict[str, SceneryContext]
    props: list[PropContext]


class LocateLoreRequest(BaseModel):
    frame_image: str | None = Field(
        default=None,
        description="Relative/absolute local image path, base64 string, or data URI",
    )
    transcript: str | None = None
    pegasus_chapter_summary: str | None = None
    highlighted_summary: str | None = None
    description: str | None = None
    max_locations: int = Field(default=3, ge=1, le=10)

    @model_validator(mode="after")
    def require_grounding(self):
        if not any((
            self.frame_image,
            self.transcript,
            self.pegasus_chapter_summary,
            self.highlighted_summary,
            self.description,
        )):
            raise ValueError("Provide a frame, transcript, Pegasus summary, or description")
        return self


class LocateLoreResponse(BaseModel):
    matches: list[LoreContextResult]
    query_interpretation: str
    cache_hit: bool


class CharacterLookupRequest(BaseModel):
    character_name_normalized: str | None = None
    description: str | None = None
    max_results: int = Field(default=10, ge=1, le=10)

    @model_validator(mode="after")
    def require_query(self):
        if not self.character_name_normalized and not self.description:
            raise ValueError("Provide character_name_normalized or description")
        return self


class SceneryLookupRequest(BaseModel):
    scenery_name_normalized: str | None = None
    description: str | None = None
    max_results: int = Field(default=10, ge=1, le=10)

    @model_validator(mode="after")
    def require_query(self):
        if not self.scenery_name_normalized and not self.description:
            raise ValueError("Provide scenery_name_normalized or description")
        return self


class PropLookupRequest(BaseModel):
    prop_name_normalized: str | None = None
    description: str | None = None
    max_results: int = Field(default=10, ge=1, le=10)

    @model_validator(mode="after")
    def require_query(self):
        if not self.prop_name_normalized and not self.description:
            raise ValueError("Provide prop_name_normalized or description")
        return self
