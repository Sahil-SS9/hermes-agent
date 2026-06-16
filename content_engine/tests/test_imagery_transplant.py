"""Tests for imagery_transplant — orchestration + fallbacks (all deps mocked)."""
import imagery_transplant as it


def test_build_edit_prompt_contains_parts():
    p = it.build_edit_prompt("MY TITLE", "label one; label two", "navy bg #0A1A2F")
    assert "MY TITLE" in p and "label one" in p and "navy bg #0A1A2F" in p
    assert "FIRST" in p and "SECOND" in p  # preserve-then-add structure


def test_generate_none_when_no_recipe(monkeypatch):
    monkeypatch.setattr(it.lib, "select_recipe", lambda *a, **k: None)
    assert it.generate({"brand": "sahil_twitter"}, "sahil_twitter") is None


def test_generate_skips_when_over_budget(monkeypatch):
    monkeypatch.setattr(it.lib, "select_recipe", lambda *a, **k: {
        "hex": "x", "light": False, "aspect": "4:5", "layout_path": "L",
        "style_path": "S", "palette": "p", "layout": "l"})
    monkeypatch.setattr(it.budget, "can_spend", lambda c: False)
    assert it.generate({"brand": "sahil_twitter", "title": "t"}, "sahil_twitter") is None


def test_generate_none_when_upload_fails(monkeypatch):
    monkeypatch.setattr(it.lib, "select_recipe", lambda *a, **k: {
        "hex": "x", "light": False, "aspect": "4:5", "layout_path": "L",
        "style_path": "S", "palette": "p", "layout": "l"})
    monkeypatch.setattr(it.budget, "can_spend", lambda c: True)
    monkeypatch.setattr(it.fal_client, "upload_file", lambda p, **k: None)
    assert it.generate({"brand": "sahil_twitter", "title": "t"}, "sahil_twitter") is None


def test_generate_happy_path(monkeypatch, tmp_path):
    recipe = {"hex": "navy", "light": False, "aspect": "4:5",
              "layout_path": tmp_path / "L.webp", "style_path": tmp_path / "S.webp",
              "palette": "cyber_neon", "layout": "iceberg"}
    monkeypatch.setattr(it.lib, "select_recipe", lambda *a, **k: recipe)
    monkeypatch.setattr(it.budget, "can_spend", lambda c: True)
    rec = []
    monkeypatch.setattr(it.budget, "record", lambda c, label="": rec.append((c, label)))
    monkeypatch.setattr(it.fal_client, "upload_file", lambda p, **k: f"http://u/{p}")
    raw = tmp_path / "raw.png"; raw.write_bytes(b"x")
    monkeypatch.setattr(it.fal_client, "generate_image_edit", lambda *a, **k: str(raw))
    fin = []
    monkeypatch.setattr(it.pp, "finish_file",
                        lambda r, o, light=False: fin.append((r, o, light)) or o)
    out = it.generate({"brand": "sahil_twitter", "title": "t", "id": "d1"},
                      "sahil_twitter", out_dir=tmp_path)
    assert out and out.endswith("transplant_sahil_twitter_d1.png")
    assert rec and "cyber_neon" in rec[0][1] and "iceberg" in rec[0][1]
    assert fin and fin[0][2] is False  # finished with light=False


def test_generate_returns_raw_when_finish_fails(monkeypatch, tmp_path):
    recipe = {"hex": "navy", "light": False, "aspect": "4:5",
              "layout_path": tmp_path / "L.webp", "style_path": tmp_path / "S.webp",
              "palette": "cyber_neon", "layout": "iceberg"}
    monkeypatch.setattr(it.lib, "select_recipe", lambda *a, **k: recipe)
    monkeypatch.setattr(it.budget, "can_spend", lambda c: True)
    monkeypatch.setattr(it.budget, "record", lambda c, label="": None)
    monkeypatch.setattr(it.fal_client, "upload_file", lambda p, **k: "http://u")
    raw = tmp_path / "raw.png"; raw.write_bytes(b"x")
    monkeypatch.setattr(it.fal_client, "generate_image_edit", lambda *a, **k: str(raw))
    def boom(*a, **k):
        raise RuntimeError("finish broke")
    monkeypatch.setattr(it.pp, "finish_file", boom)
    out = it.generate({"brand": "sahil_twitter", "title": "t", "id": "d2"},
                      "sahil_twitter", out_dir=tmp_path)
    assert out == str(raw)  # degrades to raw rather than failing
