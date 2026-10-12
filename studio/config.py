import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
# .env at repo root; real environment variables take precedence
load_dotenv(ROOT / ".env", override=False)

# ADC_HOST_PATH points at the gcloud ADC json; google-auth reads GOOGLE_APPLICATION_CREDENTIALS
ADC_PATH = os.environ.get("ADC_HOST_PATH")
if ADC_PATH and not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = ADC_PATH

ASPECTS = {"16:9": (1920, 1080), "9:16": (1080, 1920)}
SCENE_SECONDS = {"16:9": (20, 35), "9:16": (8, 15)}
FPS = 30
PROJECTS_DIR = Path(os.environ.get("STUDIO_PROJECTS_DIR", "projects")).resolve()
COMPOSER_DIR = ROOT / "composer"
TEXT_MODEL = os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.5-flash")
IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
GCP_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")
# Gemini text + image calls use the image location; video location reserved for future video models
GCP_LOCATION = os.environ.get("GOOGLE_IMAGE_LOCATION") or os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
GCP_VIDEO_LOCATION = os.environ.get("GOOGLE_VIDEO_LOCATION", "us-central1")
