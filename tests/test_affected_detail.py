from __future__ import annotations

import networkx as nx

from graphify.affected import format_affected


def _graph(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "Service.kt").write_text(
        "class Service(private val repo: Repo) {\n    fun run() {\n        repo.save(\"1\")\n    }\n}\n",
        encoding="utf-8",
    )
    graph = nx.DiGraph()
    graph.add_node("repo_save", label=".save()", source_file="app/Repo.kt", source_location="L2")
    graph.add_node("service", label="Service", source_file="app/Service.kt", source_location="L1")
    graph.add_node("service_run", label=".run()", source_file="app/Service.kt", source_location="L2")
    graph.add_edge("service", "service_run", relation="method")
    graph.add_edge(
        "service_run", "repo_save", relation="calls", source_file="app/Service.kt", source_location="L3",
    )
    return graph


def test_default_output_is_unchanged(tmp_path, monkeypatch):
    monkeypatch.delenv("GRAPHIFY_AFFECTED_DETAIL", raising=False)
    out = format_affected(_graph(tmp_path), ".save()", depth=1, root=tmp_path, seed="repo_save")
    assert "- .run() [calls] app/Service.kt:L3" in out
    assert "|" not in out


def test_detail_adds_the_owner_class_and_the_call_line(tmp_path, monkeypatch):
    monkeypatch.setenv("GRAPHIFY_AFFECTED_DETAIL", "1")
    out = format_affected(_graph(tmp_path), ".save()", depth=1, root=tmp_path, seed="repo_save")
    assert "- Service.run() [calls] app/Service.kt:L3  | repo.save(\"1\")" in out
