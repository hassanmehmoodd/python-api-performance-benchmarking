"""CLI safety exits."""

from __future__ import annotations

import socket

from bench.cli import main


def test_cli_refuses_a_remote_target_before_writing_output(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.delenv("BENCH_ALLOW_REMOTE", raising=False)
    monkeypatch.delenv("BENCH_ACKNOWLEDGE_REMOTE", raising=False)
    scenario = tmp_path / "remote.yaml"
    scenario.write_text(
        "\n".join(
            [
                "name: remote",
                "base_url: http://example.com",
                "concurrency_levels: [1]",
                "requests_per_level: 1",
                "endpoints:",
                "  - name: health",
                "    path: /health",
            ]
        ),
        encoding="utf-8",
    )
    code = main(["run", "--scenario", str(scenario), "--output-dir", str(tmp_path / "out")])
    captured = capsys.readouterr()
    assert code == 1
    assert "authorized" in captured.err
    assert not (tmp_path / "out").exists()


def test_cli_connection_failure_is_a_result_not_a_crash(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("BENCH_ALLOW_REMOTE", raising=False)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    scenario = tmp_path / "closed.yaml"
    scenario.write_text(
        "\n".join(
            [
                "name: closed",
                f"base_url: http://127.0.0.1:{port}",
                "concurrency_levels: [1]",
                "requests_per_level: 2",
                "timeout_seconds: 0.5",
                "endpoints:",
                "  - name: health",
                "    path: /health",
            ]
        ),
        encoding="utf-8",
    )
    output = tmp_path / "out"
    code = main(
        [
            "run",
            "--scenario",
            str(scenario),
            "--output-dir",
            str(output),
            "--no-charts",
        ]
    )
    assert code == 2
    assert (output / "summary.json").is_file()
    assert (output / "summary.csv").is_file()
    assert (output / "report.md").is_file()
    assert (output / "report.html").is_file()
