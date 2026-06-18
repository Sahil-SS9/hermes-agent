"""Tests for imagery_transplant — orchestration + fallbacks (all deps mocked)."""
import imagery_transplant as it


def test_build_edit_prompt_contains_parts():
    p = it.build_edit_prompt("MY TITLE", "label one; label two", "navy bg #0A1A2F")
    assert "MY TITLE" in p and "label one" in p and "navy bg #0A1A2F" in p
    assert "FIRST" in p and "SECOND" in p  # preserve-then-add structure


def test_build_scene_prompt_textless_and_subject():
    p = it.build_scene_prompt("My Title", "a transformer's attention as constellations",
                              "an abstract conceptual illustration", "navy bg", "none")
    assert "constellations" in p and "NO TEXT" in p.upper()
    p2 = it.build_scene_prompt("My Title", "x", "a mythic hero", "navy", "title_only")
    assert "My Title" in p2


def test_generate_scene_happy_path(monkeypatch, tmp_path):
    anchor = tmp_path / "abstract_34.jpeg"; anchor.write_bytes(b"x")
    recipe = {"kind": "scene", "palette": "cyber_neon", "archetype": "abstract",
              "anchor_path": anchor, "hex": "navy", "light": False, "aspect": "4:5",
              "desc": "an abstract illustration", "text_rule": "none"}
    monkeypatch.setattr(it.lib, "select_recipe", lambda *a, **k: recipe)
    monkeypatch.setattr(it.budget, "can_spend", lambda c, **k: True)
    rec = []
    monkeypatch.setattr(it.budget, "record", lambda c, label="", **k: rec.append(label))
    monkeypatch.setattr(it.fal_client, "upload_file", lambda p, **k: f"http://u/{p}")
    raw = tmp_path / "raw.png"; raw.write_bytes(b"x")
    captured = {}
    def fake_edit(prompt, urls, **k):
        captured["urls"] = urls; return str(raw)
    monkeypatch.setattr(it.fal_client, "generate_image_edit", fake_edit)
    monkeypatch.setattr(it.pp, "finish_file", lambda r, o, light=False: o)
    monkeypatch.setattr(it.gemini_vision, "available", lambda: False)  # single attempt
    out = it.generate({"title": "t", "id": "s1", "body_text": "b"}, "sahil_twitter", out_dir=tmp_path)
    assert out and out.endswith("transplant_sahil_twitter_s1_0.png")
    assert len(captured["urls"]) == 1  # scene = single anchor
    assert rec and "abstract" in rec[0]


def test_model_for_tiers():
    assert it._model_for({"kind": "infographic"})[0] == it.IMAGERY_EDIT_MODEL
    assert it._model_for({"kind": "scene", "ctype": "scene"})[0] == it.IMAGERY_SCENE_MODEL
    assert it._model_for({"kind": "scene", "ctype": "hero"})[0] == it.IMAGERY_HERO_MODEL
    # scene default is cheaper than infographic/hero
    assert it._model_for({"kind": "scene", "ctype": "scene"})[1] < it._model_for({"kind": "infographic"})[1]


def test_generate_scene_uses_cheaper_model(monkeypatch, tmp_path):
    anchor = tmp_path / "a.jpeg"; anchor.write_bytes(b"x")
    recipe = {"kind": "scene", "palette": "cyber_neon", "archetype": "abstract",
              "anchor_path": anchor, "hex": "navy", "light": False, "aspect": "4:5",
              "desc": "abstract", "text_rule": "none", "ctype": "scene"}
    monkeypatch.setattr(it.lib, "select_recipe", lambda *a, **k: recipe)
    monkeypatch.setattr(it.budget, "can_spend", lambda c, **k: True)
    monkeypatch.setattr(it.budget, "record", lambda c, label="", **k: None)
    monkeypatch.setattr(it.fal_client, "upload_file", lambda p, **k: "http://u")
    raw = tmp_path / "raw.png"; raw.write_bytes(b"x")
    seen = {}
    def fake_edit(prompt, urls, model=None, **k):
        seen["model"] = model; return str(raw)
    monkeypatch.setattr(it.fal_client, "generate_image_edit", fake_edit)
    monkeypatch.setattr(it.pp, "finish_file", lambda r, o, light=False: o)
    it.generate({"title": "t", "id": "s1"}, "sahil_twitter", out_dir=tmp_path)
    assert seen["model"] == it.IMAGERY_SCENE_MODEL  # non-pro for default scenes


def test_generate_none_when_no_recipe(monkeypatch):
    monkeypatch.setattr(it.lib, "select_recipe", lambda *a, **k: None)
    assert it.generate({"brand": "sahil_twitter"}, "sahil_twitter") is None


def test_generate_skips_when_over_budget(monkeypatch):
    monkeypatch.setattr(it.lib, "select_recipe", lambda *a, **k: {
        "hex": "x", "light": False, "aspect": "4:5", "layout_path": "L",
        "style_path": "S", "palette": "p", "layout": "l"})
    monkeypatch.setattr(it.budget, "can_spend", lambda c, **k: False)
    assert it.generate({"brand": "sahil_twitter", "title": "t"}, "sahil_twitter") is None


def test_generate_none_when_upload_fails(monkeypatch):
    monkeypatch.setattr(it.lib, "select_recipe", lambda *a, **k: {
        "hex": "x", "light": False, "aspect": "4:5", "layout_path": "L",
        "style_path": "S", "palette": "p", "layout": "l"})
    monkeypatch.setattr(it.budget, "can_spend", lambda c, **k: True)
    monkeypatch.setattr(it.fal_client, "upload_file", lambda p, **k: None)
    assert it.generate({"brand": "sahil_twitter", "title": "t"}, "sahil_twitter") is None


def test_generate_happy_path(monkeypatch, tmp_path):
    recipe = {"hex": "navy", "light": False, "aspect": "4:5",
              "layout_path": tmp_path / "L.webp", "style_path": tmp_path / "S.webp",
              "palette": "cyber_neon", "layout": "iceberg"}
    monkeypatch.setattr(it.lib, "select_recipe", lambda *a, **k: recipe)
    monkeypatch.setattr(it.budget, "can_spend", lambda c, **k: True)
    rec = []
    monkeypatch.setattr(it.budget, "record", lambda c, label="", **k: rec.append((c, label)))
    monkeypatch.setattr(it.fal_client, "upload_file", lambda p, **k: f"http://u/{p}")
    raw = tmp_path / "raw.png"; raw.write_bytes(b"x")
    monkeypatch.setattr(it.fal_client, "generate_image_edit", lambda *a, **k: str(raw))
    fin = []
    monkeypatch.setattr(it.pp, "finish_file",
                        lambda r, o, light=False: fin.append((r, o, light)) or o)
    monkeypatch.setattr(it.gemini_vision, "available", lambda: False)  # single attempt
    out = it.generate({"brand": "sahil_twitter", "title": "t", "id": "d1"},
                      "sahil_twitter", out_dir=tmp_path)
    assert out and out.endswith("transplant_sahil_twitter_d1_0.png")
    assert rec and "cyber_neon" in rec[0][1] and "iceberg" in rec[0][1]
    assert fin and fin[0][2] is False  # finished with light=False


def _infographic_setup(monkeypatch, tmp_path, scores):
    """Wire generate() for the QA loop: returns (calls, raw_files) recorders.
    `scores` is the sequence qa_image returns per attempt."""
    recipe = {"hex": "navy", "light": False, "aspect": "4:5",
              "layout_path": tmp_path / "L.webp", "style_path": tmp_path / "S.webp",
              "palette": "cyber_neon", "layout": "iceberg"}
    monkeypatch.setattr(it.lib, "select_recipe", lambda *a, **k: recipe)
    monkeypatch.setattr(it.budget, "can_spend", lambda c, **k: True)
    monkeypatch.setattr(it.budget, "record", lambda c, label="", **k: None)
    monkeypatch.setattr(it.fal_client, "upload_file", lambda p, **k: "http://u")
    calls = {"n": 0}

    def fake_edit(prompt, urls, **k):
        calls["n"] += 1
        calls["last_prompt"] = prompt
        p = tmp_path / k["filename"]
        p.write_bytes(b"x")
        return str(p)
    monkeypatch.setattr(it.fal_client, "generate_image_edit", fake_edit)
    monkeypatch.setattr(it.pp, "finish_file", lambda r, o, light=False: o)
    monkeypatch.setattr(it.cfg, "IMAGERY_QA_ENABLED", True)
    monkeypatch.setattr(it.gemini_vision, "available", lambda: True)
    seq = iter(scores)

    def fake_qa(path, brief):
        s = next(seq)
        return {"passed": s >= 6, "score": s, "issues": ["fix text"] if s < 6 else [],
                "available": True, "raw": ""}
    monkeypatch.setattr(it.gemini_vision, "qa_image", fake_qa)
    return calls


def test_generate_qa_pass_first_attempt_no_retry(monkeypatch, tmp_path):
    calls = _infographic_setup(monkeypatch, tmp_path, scores=[8])
    out = it.generate({"title": "t", "id": "q1"}, "sahil_twitter", out_dir=tmp_path)
    assert calls["n"] == 1                       # passed, no retry
    assert out.endswith("transplant_sahil_twitter_q1_0.png")


def test_generate_qa_fail_then_pass_retries_with_feedback(monkeypatch, tmp_path):
    calls = _infographic_setup(monkeypatch, tmp_path, scores=[3, 8])
    out = it.generate({"title": "t", "id": "q2"}, "sahil_twitter", out_dir=tmp_path)
    assert calls["n"] == 2                       # one retry
    assert "FIX THESE ISSUES" in calls["last_prompt"]
    assert out.endswith("transplant_sahil_twitter_q2_1.png")  # the passing attempt


def test_generate_both_fail_returns_best_scoring(monkeypatch, tmp_path):
    # attempt 0 scores higher than attempt 1 -> return attempt 0's file
    calls = _infographic_setup(monkeypatch, tmp_path, scores=[5, 2])
    out = it.generate({"title": "t", "id": "q3"}, "sahil_twitter", out_dir=tmp_path)
    assert calls["n"] == 2
    assert out.endswith("transplant_sahil_twitter_q3_0.png")  # best of the two


def test_generate_returns_raw_when_finish_fails(monkeypatch, tmp_path):
    recipe = {"hex": "navy", "light": False, "aspect": "4:5",
              "layout_path": tmp_path / "L.webp", "style_path": tmp_path / "S.webp",
              "palette": "cyber_neon", "layout": "iceberg"}
    monkeypatch.setattr(it.lib, "select_recipe", lambda *a, **k: recipe)
    monkeypatch.setattr(it.budget, "can_spend", lambda c, **k: True)
    monkeypatch.setattr(it.budget, "record", lambda c, label="", **k: None)
    monkeypatch.setattr(it.fal_client, "upload_file", lambda p, **k: "http://u")
    raw = tmp_path / "raw.png"; raw.write_bytes(b"x")
    monkeypatch.setattr(it.fal_client, "generate_image_edit", lambda *a, **k: str(raw))
    def boom(*a, **k):
        raise RuntimeError("finish broke")
    monkeypatch.setattr(it.pp, "finish_file", boom)
    monkeypatch.setattr(it.gemini_vision, "available", lambda: False)  # single attempt
    out = it.generate({"brand": "sahil_twitter", "title": "t", "id": "d2"},
                      "sahil_twitter", out_dir=tmp_path)
    assert out == str(raw)  # degrades to raw rather than failing
