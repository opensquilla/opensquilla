from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_script():
    script_path = (
        Path(__file__).resolve().parents[2]
        / "scripts"
        / "experiments"
        / "check_treatment_delivery.py"
    )
    spec = importlib.util.spec_from_file_location("check_treatment_delivery", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _glm_request(effort: str = "high", proof_budget: int = 650_000) -> dict:
    return {
        "event": "llm.request",
        "metadata": {"request_proof": {"proof_budget": proof_budget}},
        "payload": {"reasoning": {"effort": effort}},
    }


def _dashscope_request(thinking_budget: int = 24_000, proof_budget: int = 650_000) -> dict:
    return {
        "event": "llm.request",
        "metadata": {"request_proof": {"proof_budget": proof_budget}},
        "payload": {"enable_thinking": True, "thinking_budget": thinking_budget},
    }


def _write_calls(instance_dir: Path, records: list[dict]) -> None:
    instance_dir.mkdir(parents=True, exist_ok=True)
    (instance_dir / "llm_calls.jsonl").write_text(
        "".join(json.dumps(record) + "\n" for record in records),
        encoding="utf-8",
    )


def test_uniform_treatment_passes(tmp_path, capsys) -> None:
    script = _load_script()
    _write_calls(tmp_path / "demo__repo-1", [_glm_request(), _glm_request()])

    rc = script.main(
        [
            "--run-dir",
            str(tmp_path),
            "--expected-proof-budget",
            "650000",
            "--expected-reasoning-effort",
            "high",
        ]
    )

    assert rc == 0
    out = capsys.readouterr().out
    assert "instance=demo__repo-1 requests=2 proof_budget=650000" in out
    assert "checked=1 errors=0" in out


def test_treatment_mismatch_fails(tmp_path, capsys) -> None:
    script = _load_script()
    _write_calls(
        tmp_path / "demo__repo-1",
        [_glm_request(effort="high"), _glm_request(effort="xhigh")],
    )

    rc = script.main(
        [
            "--run-dir",
            str(tmp_path),
            "--expected-reasoning-effort",
            "high",
        ]
    )

    assert rc == 1
    assert "reasoning_effort_mismatch: demo__repo-1" in capsys.readouterr().err


def test_stream_timeout_fallback_excluded_from_proof_budget(tmp_path, capsys) -> None:
    # The non-stream retry of a stream timeout re-sends the same payload but
    # records no request_proof; it must not fail the proof-budget assertion.
    script = _load_script()
    stream_fallback = {
        "event": "llm.request",
        "metadata": {"fallback_from": "stream_timeout", "stream_error": "ReadTimeout"},
        "payload": {"reasoning": {"effort": "high"}},
    }
    _write_calls(tmp_path / "demo__repo-1", [_glm_request(), stream_fallback, _glm_request()])

    rc = script.main(
        [
            "--run-dir",
            str(tmp_path),
            "--expected-proof-budget",
            "650000",
            "--expected-reasoning-effort",
            "high",
        ]
    )

    assert rc == 0
    out = capsys.readouterr().out
    assert "requests=3" in out
    assert "stream_fallbacks=1" in out


def test_dashscope_thinking_disable_fallback_excluded_and_gated(tmp_path, capsys) -> None:
    # The one-shot thinking-disable retry on DashScope carries
    # enable_thinking=false and no thinking_budget; it must not fail the
    # thinking-budget assertion, but stays gated by --allow-reasoning-fallbacks.
    script = _load_script()
    thinking_disabled = {
        "event": "llm.request",
        "metadata": {"request_proof": {"proof_budget": 650_000}},
        "payload": {"enable_thinking": False},
    }
    _write_calls(
        tmp_path / "demo__repo-1",
        [_dashscope_request(), thinking_disabled, _dashscope_request()],
    )
    argv = [
        "--run-dir",
        str(tmp_path),
        "--expected-proof-budget",
        "650000",
        "--expected-thinking-budget",
        "24000",
    ]

    strict_rc = script.main(argv)
    strict_err = capsys.readouterr().err
    tolerant_rc = script.main([*argv, "--allow-reasoning-fallbacks", "1"])
    tolerant_out = capsys.readouterr().out

    assert strict_rc == 1
    assert "reasoning_fallback_exceeded: demo__repo-1 count=1 allowed=0" in strict_err
    assert tolerant_rc == 0
    assert "thinking_budget=24000" in tolerant_out
    assert "reasoning_fallbacks=1" in tolerant_out


def test_openrouter_thinking_disable_fallback_excluded_from_effort(tmp_path, capsys) -> None:
    script = _load_script()
    thinking_disabled = {
        "event": "llm.request",
        "metadata": {"request_proof": {"proof_budget": 650_000}},
        "payload": {"reasoning": {"enabled": False}},
    }
    _write_calls(tmp_path / "demo__repo-1", [_glm_request(), thinking_disabled])

    rc = script.main(
        [
            "--run-dir",
            str(tmp_path),
            "--expected-reasoning-effort",
            "high",
            "--allow-reasoning-fallbacks",
            "1",
        ]
    )

    assert rc == 0
    out = capsys.readouterr().out
    assert "reasoning_effort=high " in out
    assert "reasoning_fallbacks=1" in out


def test_unparsed_request_line_fails(tmp_path, capsys) -> None:
    script = _load_script()
    instance_dir = tmp_path / "demo__repo-1"
    _write_calls(instance_dir, [_glm_request()])
    with (instance_dir / "llm_calls.jsonl").open("a", encoding="utf-8") as handle:
        handle.write('{"event": "llm.request", "payload": {"truncat\n')

    rc = script.main(
        [
            "--run-dir",
            str(tmp_path),
            "--expected-proof-budget",
            "650000",
        ]
    )

    assert rc == 1
    assert "unparsed_request_lines: demo__repo-1 count=1" in capsys.readouterr().err
