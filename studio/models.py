from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field
from . import config

StepState = Literal["pending", "running", "done", "error"]
STEPS = ("image", "voice", "draw")

class Element(BaseModel):
    label: str
    say: str

class Scene(BaseModel):
    id: str
    text: str
    narration: str = ""              # what TTS reads; empty = read `text` (the subtitle)
    key_idea: str = ""
    visual_description: str = ""
    elements: list[Element] = Field(default_factory=list)
    image_prompt: str = ""
    status: dict[str, StepState] = Field(default_factory=lambda: {s: "pending" for s in STEPS})
    error: str | None = None
    duration_ms: int | None = None
    image_model: str | None = None   # model that drew the current image.png

class VersionScene(BaseModel):
    voice: str | None = None         # per-scene voice override; None = version voice
    status: dict[str, StepState] = Field(default_factory=lambda: {"voice": "pending", "draw": "pending"})
    error: str | None = None
    duration_ms: int | None = None
    composed: bool = False           # clip is part of the version's current final.mp4

class Version(BaseModel):
    id: str
    label: str
    voice: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    scenes: dict[str, VersionScene] = Field(default_factory=dict)
    final: str | None = None
    timings: dict[str, float] = Field(default_factory=dict)

class Settings(BaseModel):
    aspect: Literal["16:9", "9:16"] = "16:9"
    voice: str = "Hải Đăng"
    captions: bool = True
    music: bool = False
    music_file: str | None = None
    text_model: str = Field(default_factory=lambda: config.TEXT_MODEL)
    image_model: str = Field(default_factory=lambda: config.IMAGE_MODEL)

class Project(BaseModel):
    id: str
    title: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    settings: Settings = Field(default_factory=Settings)
    source_text: str = ""
    stage: Literal["input", "scenes", "images", "rendering", "done"] = "input"
    scenes: list[Scene] = Field(default_factory=list)
    final: str | None = None
    versions: list[Version] = Field(default_factory=list)
    active_version: str = "v1"
    job_error: str | None = None
    timings: dict[str, float] = Field(default_factory=dict)   # seconds of the last run per job kind
