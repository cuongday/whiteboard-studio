import pytest
from studio import config

@pytest.fixture(autouse=True)
def tmp_projects(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "PROJECTS_DIR", tmp_path / "projects")
    return tmp_path / "projects"

@pytest.fixture(autouse=True)
def tmp_image_cache(tmp_path, monkeypatch):
    from studio import llm
    monkeypatch.setattr(llm, "IMAGE_CACHE", tmp_path / "image-cache")
