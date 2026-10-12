import os
from pathlib import Path

ASPECTS = {"16:9": (1920, 1080), "9:16": (1080, 1920)}
SCENE_SECONDS = {"16:9": (20, 35), "9:16": (8, 15)}
FPS = 30
PROJECTS_DIR = Path(os.environ.get("STUDIO_PROJECTS_DIR", "projects")).resolve()
ROOT = Path(__file__).resolve().parent.parent
COMPOSER_DIR = ROOT / "composer"
TEXT_MODEL = os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.5-flash")
IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
GCP_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")
GCP_LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
