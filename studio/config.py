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

# Models verified to work through Vertex/ADC on this project (2026-10-12). The env defaults
# are always offered even if not listed here.
TEXT_MODELS = [
    ("gemini-2.5-flash", "Gemini 2.5 Flash — cân bằng"),
    ("gemini-2.5-flash-lite", "Gemini 2.5 Flash Lite — nhanh, rẻ"),
    ("gemini-2.5-pro", "Gemini 2.5 Pro — chia cảnh kỹ hơn"),
    ("gemini-3-flash-preview", "Gemini 3 Flash (preview)"),
    ("gemini-3.1-flash-lite", "Gemini 3.1 Flash Lite"),
    ("gemini-3.5-flash", "Gemini 3.5 Flash"),
    ("gemini-3.5-flash-lite", "Gemini 3.5 Flash Lite"),
    ("gemini-3.6-flash", "Gemini 3.6 Flash"),
    ("gemini-3.7-flash", "Gemini 3.7 Flash"),
    ("gemini-3.8-flash", "Gemini 3.8 Flash — mới nhất"),
]
IMAGE_MODELS = [
    ("gemini-2.5-flash-image", "Gemini 2.5 Flash Image — ~7 giây/ảnh"),
    ("gemini-3.1-flash-lite-image", "Gemini 3.1 Flash Lite Image — nhanh nhất, ~4 giây"),
    ("gemini-3.1-flash-image", "Gemini 3.1 Flash Image — ~16 giây"),
    ("gemini-nano-banana-2.1", "Nano Banana 2.1 — ~14 giây"),
    ("gemini-3-pro-image", "Gemini 3 Pro Image — chất lượng cao nhất, ~20 giây"),
]

def _with_default(models, default):
    return models if any(m == default for m, _ in models) else [(default, default)] + models

TEXT_MODELS = _with_default(TEXT_MODELS, TEXT_MODEL)
IMAGE_MODELS = _with_default(IMAGE_MODELS, IMAGE_MODEL)
GCP_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT")
# Gemini text + image calls use the image location; video location reserved for future video models
GCP_LOCATION = os.environ.get("GOOGLE_IMAGE_LOCATION") or os.environ.get("GOOGLE_CLOUD_LOCATION", "global")
GCP_VIDEO_LOCATION = os.environ.get("GOOGLE_VIDEO_LOCATION", "us-central1")
