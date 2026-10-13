import json
from types import SimpleNamespace
import pytest
from studio import llm

class FakeModels:
    def __init__(self, responses): self.responses = list(responses); self.calls = []
    def generate_content(self, model, contents, config=None):
        self.calls.append((model, contents, config))
        r = self.responses.pop(0)
        if isinstance(r, Exception): raise r
        return r

def text_resp(obj): return SimpleNamespace(text=json.dumps(obj, ensure_ascii=False), candidates=[])

GOOD = {"scenes": [
    {"text": "Lạm phát là khi giá tăng.", "key_idea": "định nghĩa",
     "visual_description": "giỏ hàng và mũi tên đi lên",
     "elements": [{"label": "giỏ hàng", "say": "giá"}, {"label": "mũi tên", "say": "tăng"}]},
]}

def test_segment_parses_and_ids():
    fake = SimpleNamespace(models=FakeModels([text_resp(GOOD)]))
    scenes = llm.segment_script("Lạm phát là khi giá tăng.", "16:9", client=fake)
    assert [s.id for s in scenes] == ["01"]
    assert scenes[0].elements[1].say == "tăng"
    assert "#F5EBD7" in scenes[0].image_prompt
    prompt = fake.models.calls[0][1]
    assert "20" in prompt and "35" in prompt   # 16:9 duration hint

def test_segment_retries_bad_json():
    fake = SimpleNamespace(models=FakeModels([SimpleNamespace(text="not json", candidates=[]), text_resp(GOOD)]))
    assert len(llm.segment_script("x", "9:16", client=fake)) == 1

def test_segment_gives_up():
    bad = SimpleNamespace(text="{}", candidates=[])
    fake = SimpleNamespace(models=FakeModels([bad, bad, bad]))
    with pytest.raises(llm.LLMError):
        llm.segment_script("x", "16:9", client=fake)

def test_generate_image_writes_png(tmp_path):
    part = SimpleNamespace(inline_data=SimpleNamespace(data=b"\x89PNGfake", mime_type="image/png"), text=None)
    resp = SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))])
    fake = SimpleNamespace(models=FakeModels([resp]))
    out = llm.generate_image("p", "9:16", tmp_path / "image.png", client=fake)
    assert out.read_bytes() == b"\x89PNGfake"
    assert fake.models.calls[0][2].image_config.aspect_ratio == "9:16"

def test_generate_image_cache_and_fresh(tmp_path):
    part = SimpleNamespace(inline_data=SimpleNamespace(data=b"\x89PNGfake", mime_type="image/png"), text=None)
    resp = SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))])
    fake = SimpleNamespace(models=FakeModels([resp, resp]))
    llm.generate_image("p", "16:9", tmp_path / "a.png", client=fake, model="m")
    llm.generate_image("p", "16:9", tmp_path / "b.png", client=fake, model="m")
    assert len(fake.models.calls) == 1 and (tmp_path / "b.png").read_bytes() == b"\x89PNGfake"
    llm.generate_image("p", "16:9", tmp_path / "c.png", client=fake, model="m", fresh=True)
    assert len(fake.models.calls) == 2
