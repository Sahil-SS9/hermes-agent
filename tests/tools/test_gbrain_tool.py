import json

from tools import gbrain


def test_gbrain_search_limits_results(monkeypatch):
    monkeypatch.setattr(
        gbrain,
        "_run_gbrain",
        lambda args, **kwargs: ("[0.9] people/sahil -- Sahil\n[0.8] projects/kensei -- Kensei\n", "", 0),
    )

    data = json.loads(gbrain.gbrain_search({"query": "sahil", "limit": 1}))

    assert data["query"] == "sahil"
    assert data["results"] == ["[0.9] people/sahil -- Sahil"]
    assert data["total"] == 2
    assert data["limit"] == 1


def test_gbrain_get_returns_content(monkeypatch):
    monkeypatch.setattr(gbrain, "_run_gbrain", lambda args, **kwargs: ("# Page\n", "", 0))

    data = json.loads(gbrain.gbrain_get({"slug": "people/sahil-saghir.md"}))

    assert data == {"slug": "people/sahil-saghir", "content": "# Page\n"}


def test_gbrain_search_error_on_missing_query():
    data = json.loads(gbrain.gbrain_search({"query": ""}))

    assert "error" in data
    assert "query is required" in data["error"]


def test_gbrain_graph_bounds_depth(monkeypatch):
    seen = {}

    def fake_run(args, **kwargs):
        seen["args"] = args
        return ("graph output", "", 0)

    monkeypatch.setattr(gbrain, "_run_gbrain", fake_run)

    data = json.loads(gbrain.gbrain_graph({"slug": "people/sahil-saghir", "depth": 99}))

    assert seen["args"] == ["graph-query", "people/sahil-saghir", "--depth", "5"]
    assert data["depth"] == 5
    assert data["output"] == "graph output"
