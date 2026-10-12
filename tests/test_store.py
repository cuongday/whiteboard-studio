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
