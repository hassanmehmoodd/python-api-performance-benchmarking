"""Run history ordering."""

from __future__ import annotations

from bench.history import append_history, load_history
from tests.conftest import make_run


def test_history_is_loaded_oldest_first(tmp_path) -> None:
    late = make_run()
    late.run_id = "late"
    late.started_at = "2026-11-08T13:00:00.000Z"
    early = make_run()
    early.run_id = "early"
    early.started_at = "2026-11-08T12:00:00.000Z"
    append_history(tmp_path, late)
    append_history(tmp_path, early)
    loaded = load_history(tmp_path)
    assert [item["run_id"] for item in loaded] == ["early", "late"]
    assert loaded[0]["points"][0]["endpoint"] == "health"
    assert load_history(tmp_path / "missing") == []
