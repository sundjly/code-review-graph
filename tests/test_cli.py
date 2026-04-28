"""Tests for CLI helpers."""

import logging
from importlib.metadata import PackageNotFoundError

from code_review_graph import cli


def test_get_version_logs_and_falls_back_to_dev(monkeypatch, caplog):
    def _raise_package_not_found(_dist_name: str) -> str:
        raise PackageNotFoundError("code-review-graph")

    monkeypatch.setattr(cli, "pkg_version", _raise_package_not_found)

    with caplog.at_level(logging.DEBUG, logger="code_review_graph.cli"):
        version = cli._get_version()

    assert version == "dev"
    assert "Package metadata unavailable" in caplog.text


def test_cli_token_savings(monkeypatch, capsys):
    from unittest.mock import MagicMock
    from code_review_graph import cli
    import sys

    # Mock argv to simulate `code-review-graph token-savings`
    monkeypatch.setattr(sys, "argv", ["code-review-graph", "token-savings"])

    # Mock GraphStore to avoid creating actual db
    import code_review_graph.graph
    mock_store_cls = MagicMock()
    mock_store_instance = MagicMock()
    mock_store_cls.return_value = mock_store_instance
    monkeypatch.setattr(code_review_graph.graph, "GraphStore", mock_store_cls)

    # Mock incremental tools to avoid accessing real files
    import code_review_graph.incremental
    monkeypatch.setattr(code_review_graph.incremental, "find_project_root", MagicMock(return_value="."))
    monkeypatch.setattr(code_review_graph.incremental, "get_db_path", MagicMock(return_value="memory:"))

    # Mock run_token_benchmark
    mock_run = MagicMock(return_value={
        "naive_corpus_tokens": 1000,
        "per_question": [{"question": "test q", "graph_tokens": 10, "reduction_ratio": 100.0}],
        "average_reduction_ratio": 100.0,
        "summary": "Mock summary"
    })
    
    # We must patch token_benchmark.run_token_benchmark but since it's locally imported
    # in the elif block, we can patch the module after importing it.
    import code_review_graph.token_benchmark
    monkeypatch.setattr(code_review_graph.token_benchmark, "run_token_benchmark", mock_run)

    # Call main
    cli.main()

    # Verify run_token_benchmark was called
    mock_run.assert_called_once()

    # Verify print outputs
    captured = capsys.readouterr()
    assert "Running token reduction benchmark on current repository..." in captured.out
    assert "Naive corpus tokens: 1000" in captured.out
    assert "Average reduction ratio: 100.0x" in captured.out
    assert "Mock summary" in captured.out
    assert "test q" in captured.out
