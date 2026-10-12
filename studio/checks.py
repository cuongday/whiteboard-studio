import importlib.util
import shutil
from . import config

def run_checks() -> list[dict]:
    out = []
    def add(name, ok, hint): out.append({"name": name, "ok": bool(ok), "hint": "" if ok else hint})
    add("ffmpeg", shutil.which("ffmpeg"), "Cài ffmpeg: sudo apt install ffmpeg")
    add("node/npx", shutil.which("npx"), "Cài Node.js >= 18")
    add("remotion", (config.COMPOSER_DIR / "node_modules" / "remotion").exists(), "Chạy: cd composer && npm install")
    add("vieneu", importlib.util.find_spec("vieneu"), "Chạy: pip install -e '.[voice]'")
    add("GOOGLE_CLOUD_PROJECT", config.GCP_PROJECT, "Đặt GOOGLE_CLOUD_PROJECT trong file .env")
    if config.ADC_PATH:
        from pathlib import Path
        add("ADC_HOST_PATH", Path(config.ADC_PATH).is_file(), f"Không thấy file ADC: {config.ADC_PATH}")
    try:
        import google.auth
        google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        adc = True
    except Exception:  # noqa: BLE001
        adc = False
    add("ADC", adc, "Chạy: gcloud auth application-default login")
    return out
