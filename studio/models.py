from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field

StepState = Literal["pending", "running", "done", "error"]
STEPS = ("image", "voice", "draw")

class Element(BaseModel):
    label: str
    say: str

class Scene(BaseModel):
    id: str
    text: str
    key_idea: str = ""
    visual_description: str = ""
    elements: list[Element] = Field(default_factory=list)
    image_prompt: str = ""
    status: dict[str, StepState] = Field(default_factory=lambda: {s: "pending" for s in STEPS})
    error: str | None = None
    duration_ms: int | None = None

class Settings(BaseModel):
    aspect: Literal["16:9", "9:16"] = "16:9"
    voice: str = "Hải Đăng"
    captions: bool = True
    music: bool = False
    music_file: str | None = None

class Project(BaseModel):
    id: str
    title: str
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    settings: Settings = Field(default_factory=Settings)
    source_text: str = ""
    stage: Literal["input", "scenes", "images", "rendering", "done"] = "input"
    scenes: list[Scene] = Field(default_factory=list)
    final: str | None = None
    job_error: str | None = None
