"""Tests for the LLM chain (OpenGo primary + Ollama-Cloud fallback) and the
topic-leak sanitiser (no raw git commit subjects in topics/titles)."""
import llm_generate as lg
import topics as tp


# ── LLM chain ──────────────────────────────────────────────────────────────

def test_fallback_chain_is_opengo_then_ollama():
    bases = [(c["base"], c["model"]) for c in lg._FREE_FALLBACK_CHAIN]
    assert bases[0] == ("https://opencode.ai/zen/go/v1", "deepseek-v4-flash")
    assert bases[1] == ("https://ollama.com/v1", "gpt-oss:120b")


def test_key_for_provider(monkeypatch):
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-xyz")
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "go-abc")
    assert lg._key_for("ollama") == "ollama-xyz"
    assert lg._key_for("opencode") == "go-abc"


def test_llm_configs_attaches_right_keys(monkeypatch):
    monkeypatch.delenv("CONTENT_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("CONTENT_LLM_MODEL", raising=False)
    monkeypatch.setenv("OLLAMA_API_KEY", "ollama-xyz")
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "go-abc")
    cfgs = lg._llm_configs()
    by_base = {c["base"]: c for c in cfgs}
    assert by_base["https://opencode.ai/zen/go/v1"]["model"] == "deepseek-v4-flash"
    assert by_base["https://opencode.ai/zen/go/v1"]["key"] == "go-abc"
    assert by_base["https://ollama.com/v1"]["key"] == "ollama-xyz"


def test_longform_chain_uses_stronger_models(monkeypatch):
    monkeypatch.delenv("CONTENT_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("CONTENT_LLM_MODEL", raising=False)
    cfgs = lg._llm_configs(longform=True)
    models = [c["model"] for c in cfgs]
    assert models[0] == "minimax-m3"          # OpenGo primary for long-form
    assert "glm-5.2" in models                # Ollama-Cloud fallback
    # short tier must NOT leak into long-form
    assert "deepseek-v4-flash" not in models


def test_short_and_longform_differ(monkeypatch):
    monkeypatch.delenv("CONTENT_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("CONTENT_LLM_MODEL", raising=False)
    short = [c["model"] for c in lg._llm_configs(longform=False)]
    long = [c["model"] for c in lg._llm_configs(longform=True)]
    assert short[0] == "deepseek-v4-flash"
    assert long[0] == "minimax-m3"


def test_fabricated_numbers_catches_growth_metrics():
    import article_gates as ag
    # ungrounded audience/growth metrics -> flagged
    assert ag._fabricated_numbers("Just hit 1,000 users this week", "")
    assert ag._fabricated_numbers("200 downloads in a day", "")
    assert ag._fabricated_numbers("conversion rose 45%", "")
    # narrative integers -> NOT flagged (no false positives)
    assert not ag._fabricated_numbers("I cut 3 features in 2 weeks", "")
    # grounded number -> NOT flagged
    assert not ag._fabricated_numbers("we hit 1,000 users", "the launch reached 1,000 users")


def test_env_override_is_tried_first(monkeypatch):
    monkeypatch.setenv("CONTENT_LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("CONTENT_LLM_MODEL", "custom-model")
    cfgs = lg._llm_configs()
    assert (cfgs[0]["base"], cfgs[0]["model"]) == ("https://example.test/v1", "custom-model")
    # canonical chain still present as fallback
    assert any(c["model"] == "deepseek-v4-flash" for c in cfgs)
    assert any(c["model"] == "gpt-oss:120b" for c in cfgs)


# ── Topic-leak sanitiser ───────────────────────────────────────────────────

def test_strips_conventional_commit_prefix():
    assert tp._clean_topic_summary(
        "feat(content): non-infographic scene transplant") == "non-infographic scene transplant"
    assert tp._clean_topic_summary("fix: gateway crash loop") == "gateway crash loop"
    assert tp._clean_topic_summary("refactor(api)!: drop v1") == "drop v1"


def test_strips_trailer():
    assert tp._clean_topic_summary(
        "feat: add thing\n\nCo-Authored-By: X <x@y.z>") == "add thing"


def test_merge_commit_yields_empty():
    assert tp._clean_topic_summary("Merge branch 'main' into feature") == ""


def test_clean_passes_through_normal_text():
    assert tp._clean_topic_summary("How I cut agent context 99x") == "How I cut agent context 99x"


def test_no_commit_prefix_in_built_topic():
    # The educational topic text must never contain a conventional-commit prefix.
    cleaned = tp._clean_topic_summary("chore(deps): bump three to 0.184")
    assert not cleaned.lower().startswith("chore")
    assert cleaned == "bump three to 0.184"
