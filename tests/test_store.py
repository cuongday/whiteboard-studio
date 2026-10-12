from studio import store
from studio.models import Settings, Scene

def test_create_load_roundtrip():
    p = store.create_project("Thử", Settings(aspect="9:16"), "xin chào")
    p.scenes.append(Scene(id="01", text="a"))
    store.save(p)
    q = store.load(p.id)
    assert q.settings.aspect == "9:16"
    assert q.scenes[0].status == {"image": "pending", "voice": "pending", "draw": "pending"}
    assert [x.id for x in store.list_projects()] == [p.id]

def test_scene_dir_created():
    p = store.create_project("x", Settings(), "")
    assert store.scene_dir(p.id, "01").is_dir()

def test_list_projects_skips_corrupt():
    good = store.create_project("ok", Settings(), "abc")
    bad = store.create_project("bad", Settings(), "abc")
    (store.project_dir(bad.id) / "project.json").write_text("{not json", encoding="utf-8")
    ids = [p.id for p in store.list_projects()]
    assert good.id in ids and bad.id not in ids
