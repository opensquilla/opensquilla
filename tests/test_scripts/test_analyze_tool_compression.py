from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path


def _load_script():
    script_path = Path(__file__).resolve().parents[2] / "scripts" / "experiments" / (
        "analyze_tool_compression.py"
    )
    spec = importlib.util.spec_from_file_location("analyze_tool_compression", script_path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")


def _write_store_record(
    record_dir: Path,
    *,
    handle: str,
    tool_use_id: str,
    content: str,
) -> None:
    record_dir.mkdir(parents=True)
    payload = content.encode("utf-8")
    # The raw-store contract is byte-oriented (the analyzer reads content.txt
    # with read_bytes and hashes the raw payload). Write bytes so text-mode
    # newline translation on Windows cannot skew the sha256/char counts below.
    (record_dir / "content.txt").write_bytes(payload)
    _write_json(
        record_dir / "meta.json",
        {
            "handle": handle,
            "tool_use_id": tool_use_id,
            "tool_name": "exec_command",
            "size_bytes": len(payload),
            "stored_size_bytes": len(payload),
            "storage_encoding": "utf-8",
            "content_file": "content.txt",
            "sha256": hashlib.sha256(payload).hexdigest(),
        },
    )


def test_summarize_instance_classifies_projection_risks(tmp_path: Path) -> None:
    mod = _load_script()
    inst = tmp_path / "run-a" / "repo__issue-1"
    inst.mkdir(parents=True)
    _write_json(
        inst / "metadata.json",
        {
            "instance_id": "repo__issue-1",
            "run_id": "run-a",
            "model": "qwen3.6-flash",
            "state": "patch_collected",
            "patch_empty": False,
        },
    )
    _write_json(
        inst / "usage.json",
        {
            "input_tokens": 1000,
            "cached_tokens": 900,
            "request_count": 3,
            "cost_usd": 0.01,
        },
    )
    _write_jsonl(
        inst / "runtime_events.jsonl",
        [
            {
                "feature": "tool_result_projection",
                "tool_name": "grep_search",
                "outcome": "applied",
                "reason": "tokenjuice",
                "original_chars": 1_200_000,
                "projected_chars": 1000,
                "saved_chars": 1_199_000,
                "tool_result_handle_present": True,
            },
            {
                "feature": "tool_result_projection",
                "tool_name": "exec_command",
                "outcome": "noop",
                "reason": "store_budget_exceeded",
                "original_chars": 50_000,
                "tool_result_handle_present": False,
            },
            {
                "feature": "tool_result_projection",
                "tool_name": "read_file",
                "outcome": "noop",
                "reason": "semantic_read_file_preserved",
                "original_chars": 2000,
                "tool_result_handle_present": False,
            },
        ],
    )
    _write_jsonl(
        inst / "transcript.jsonl",
        [
            {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "name": "retrieve_tool_result",
                            "arguments": {"handle": "tr-abc", "mode": "query"},
                        }
                    ],
                }
            }
        ],
    )
    store_dir = inst / "opensquilla_state" / "media" / "tool-results" / "s" / "session"
    record_dir = store_dir / "ab" / "tr-abc"
    record_dir.mkdir(parents=True)
    _write_json(
        record_dir / "meta.json",
        {
            "handle": "tr-abc",
            "size_bytes": 1_200_000,
            "stored_size_bytes": 5000,
            "storage_encoding": "gzip+utf-8",
        },
    )
    (inst / "git.patch").write_text(
        "diff --git a/src/main.py b/src/main.py\n"
        "diff --git a/fix.py b/fix.py\n",
        encoding="utf-8",
    )

    summary = mod.summarize_instance(inst)

    assert summary["usage"]["kv_cache_hit_rate"] == 0.9
    assert summary["projection"]["events"] == 3
    assert summary["projection"]["applied"] == 1
    assert summary["projection"]["semantic_preserves"] == 1
    assert summary["projection"]["categories"]["huge_grep_log"] == 1
    assert summary["projection"]["categories"]["store_budget_exceeded"] == 1
    assert "retrieval_unused" not in summary["projection"]["categories"]
    assert summary["retrieval"]["calls"] == 1
    assert summary["raw_store"]["records"] == 1
    assert summary["raw_store"]["compressed_records"] == 1
    assert summary["patch"]["scratch_paths"] == ["fix.py"]


def test_summarize_instance_flags_root_apply_helper_patch_artifacts(
    tmp_path: Path,
) -> None:
    mod = _load_script()
    inst = tmp_path / "run-helper" / "repo__issue-helper"
    inst.mkdir(parents=True)
    _write_json(inst / "metadata.json", {"patch_empty": False})
    (inst / "git.patch").write_text(
        "diff --git a/apply_fix.py b/apply_fix.py\n"
        "diff --git a/apply_util_fix.py b/apply_util_fix.py\n"
        "diff --git a/include/pkg/util.h b/include/pkg/util.h\n",
        encoding="utf-8",
    )

    summary = mod.summarize_instance(inst)
    aggregate = mod.aggregate([summary])

    assert summary["patch"]["scratch_paths"] == [
        "apply_fix.py",
        "apply_util_fix.py",
    ]
    assert aggregate["scratch_patch_instances"] == 1


def test_summarize_instance_reports_raw_store_integrity_and_duplicates(
    tmp_path: Path,
    capsys,
) -> None:
    mod = _load_script()
    inst = tmp_path / "run-integrity" / "repo__issue-raw"
    inst.mkdir(parents=True)
    _write_json(inst / "metadata.json", {"patch_empty": False})
    _write_jsonl(
        inst / "runtime_events.jsonl",
        [
            {
                "feature": "tool_result_projection",
                "tool_use_id": "call-1",
                "tool_name": "exec_command",
                "outcome": "noop",
                "reason": "no_reduction",
            },
            {
                "feature": "tool_result_projection",
                "tool_use_id": "call-2",
                "tool_name": "exec_command",
                "outcome": "applied",
                "reason": "tokenjuice",
                "tool_result_handle": "tr-missing",
                "tool_result_handle_present": True,
            },
        ],
    )
    store_root = inst / "opensquilla_state" / "media" / "tool-results" / "s" / "session"
    _write_store_record(
        store_root / "aa" / "tr-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        handle="tr-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        tool_use_id="call-1",
        content="first snapshot",
    )
    _write_store_record(
        store_root / "bb" / "tr-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        handle="tr-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        tool_use_id="call-1",
        content="duplicate snapshot",
    )

    summary = mod.summarize_instance(inst)
    aggregate = mod.aggregate([summary])

    assert summary["raw_store"]["records"] == 2
    assert summary["raw_store"]["unique_tool_use_ids"] == 1
    assert summary["raw_store"]["duplicate_tool_use_records"] == 1
    assert summary["raw_store"]["content_missing"] == 0
    assert summary["raw_store"]["hash_mismatches"] == 0
    assert summary["raw_store"]["size_mismatches"] == 0
    assert summary["raw_store"]["projection_tool_use_ids"] == 2
    assert summary["raw_store"]["projection_tool_use_ids_covered"] == 1
    assert summary["raw_store"]["projection_tool_use_ids_missing"] == 1
    assert summary["raw_store"]["projection_handles_missing"] == 1
    assert aggregate["raw_store_duplicate_tool_use_records"] == 1
    assert aggregate["raw_store_integrity_bad"] == 0
    assert aggregate["raw_store_projection_tool_use_ids_missing"] == 1
    assert aggregate["raw_store_projection_handles_missing"] == 1
    assert aggregate["raw_store_projection_links_missing"] == 2

    mod._print_table([summary])
    table = capsys.readouterr().out.splitlines()
    header = table[0].split("\t")
    row = table[1].split("\t")
    assert "raw_missing" not in header
    assert header[header.index("raw_bad")] == "raw_bad"
    assert header[header.index("raw_link_missing")] == "raw_link_missing"
    assert row[header.index("raw_bad")] == "0"
    assert row[header.index("raw_link_missing")] == "2"
    assert header[header.index("replay_bad")] == "replay_bad"


def test_summarize_instance_verifies_transcript_projection_replay(
    tmp_path: Path,
) -> None:
    mod = _load_script()
    inst = tmp_path / "run-replay" / "repo__issue-replay"
    inst.mkdir(parents=True)
    _write_json(inst / "metadata.json", {"patch_empty": False})
    content = "raw output\n重要 detail\n"
    handle = "tr-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    _write_store_record(
        inst / "opensquilla_state" / "media" / "tool-results" / "s" / "session" / "aa" / handle,
        handle=handle,
        tool_use_id="call-1",
        content=content,
    )
    envelope = (
        "[tool_result_projection]\n"
        f"tool_result_handle: {handle}\n"
        f"sha256: {hashlib.sha256(content.encode('utf-8')).hexdigest()}\n"
        f"original_chars: {len(content)}\n"
        "retrieve_hint: this result is incomplete.\n"
        "[tokenjuice]\nsummary"
    )
    _write_jsonl(
        inst / "transcript.jsonl",
        [
            {
                "message": {
                    "role": "toolResult",
                    "toolName": "exec_command",
                    "content": [{"type": "text", "text": envelope}],
                }
            }
        ],
    )

    summary = mod.summarize_instance(inst)
    aggregate = mod.aggregate([summary])

    assert summary["transcript_projection"]["events"] == 1
    assert summary["transcript_projection"]["handle_present"] == 1
    assert summary["transcript_projection"]["replay_bad"] == 0
    assert aggregate["transcript_projection_events"] == 1
    assert aggregate["transcript_projection_replay_bad"] == 0


def test_summarize_instance_flags_transcript_projection_replay_failures(
    tmp_path: Path,
    capsys,
) -> None:
    mod = _load_script()
    inst = tmp_path / "run-replay-bad" / "repo__issue-replay-bad"
    inst.mkdir(parents=True)
    _write_json(inst / "metadata.json", {"patch_empty": False})
    content = "raw output\n"
    handle = "tr-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    _write_store_record(
        inst / "opensquilla_state" / "media" / "tool-results" / "s" / "session" / "aa" / handle,
        handle=handle,
        tool_use_id="call-1",
        content=content,
    )
    bad_sha = "0" * 64
    envelopes = [
        (
            "[tool_result_projection]\n"
            f"tool_result_handle: {handle}\n"
            f"sha256: {bad_sha}\n"
            "original_chars: 999\n"
            "[tokenjuice]\nsummary"
        ),
        (
            "[tool_result_projection]\n"
            "tool_result_handle: tr-missing\n"
            f"sha256: {bad_sha}\n"
            "original_chars: 1\n"
            "[tokenjuice]\nsummary"
        ),
    ]
    _write_jsonl(
        inst / "transcript.jsonl",
        [
            {
                "message": {
                    "role": "toolResult",
                    "toolName": "exec_command",
                    "content": [{"type": "text", "text": envelope}],
                }
            }
            for envelope in envelopes
        ],
    )

    summary = mod.summarize_instance(inst)
    aggregate = mod.aggregate([summary])

    assert summary["transcript_projection"]["events"] == 2
    assert summary["transcript_projection"]["handles_missing"] == 1
    assert summary["transcript_projection"]["sha_mismatches"] == 1
    assert summary["transcript_projection"]["size_mismatches"] == 1
    assert summary["transcript_projection"]["replay_bad"] == 3
    assert aggregate["transcript_projection_replay_bad"] == 3
    assert aggregate["categories"]["transcript_projection_handle_missing"] == 1
    assert aggregate["categories"]["transcript_projection_sha_mismatch"] == 1
    assert aggregate["categories"]["transcript_projection_size_mismatch"] == 1

    mod._print_table([summary])
    table = capsys.readouterr().out.splitlines()
    header = table[0].split("\t")
    row = table[1].split("\t")
    categories = row[header.index("categories")]
    assert "transcript_projection_handle_missing:1" in categories
    assert "transcript_projection_sha_mismatch:1" in categories
    assert "transcript_projection_size_mismatch:1" in categories


def test_summarize_instance_separates_raw_integrity_from_projection_links(
    tmp_path: Path,
) -> None:
    mod = _load_script()
    inst = tmp_path / "run-integrity-bad" / "repo__issue-raw-bad"
    inst.mkdir(parents=True)
    _write_json(inst / "metadata.json", {"patch_empty": False})
    _write_jsonl(
        inst / "runtime_events.jsonl",
        [
            {
                "feature": "tool_result_projection",
                "tool_use_id": "call-1",
                "tool_name": "exec_command",
                "outcome": "applied",
                "reason": "tokenjuice",
                "tool_result_handle": "tr-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "tool_result_handle_present": True,
            }
        ],
    )
    store_root = inst / "opensquilla_state" / "media" / "tool-results" / "s" / "session"
    record_dir = store_root / "aa" / "tr-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    _write_store_record(
        record_dir,
        handle="tr-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        tool_use_id="call-1",
        content="raw snapshot",
    )
    meta_path = record_dir / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["sha256"] = "0" * 64
    _write_json(meta_path, meta)

    summary = mod.summarize_instance(inst)
    aggregate = mod.aggregate([summary])

    assert summary["raw_store"]["hash_mismatches"] == 1
    assert summary["raw_store"]["projection_tool_use_ids_missing"] == 0
    assert summary["raw_store"]["projection_handles_missing"] == 0
    assert aggregate["raw_store_integrity_bad"] == 1
    assert aggregate["raw_store_projection_links_missing"] == 0


def test_summarize_instance_reports_dispatch_truncated_raw_snapshot(
    tmp_path: Path,
    capsys,
) -> None:
    mod = _load_script()
    inst = tmp_path / "run-trunc" / "repo__issue-trunc"
    inst.mkdir(parents=True)
    _write_json(inst / "metadata.json", {"patch_empty": False})
    _write_jsonl(inst / "runtime_events.jsonl", [])
    truncated = {
        "result_truncated": True,
        "result_original_chars": 1_500_000,
        "result_omitted_chars": 1_490_000,
        "tool": "exec_command",
        "preview": "HEAD",
        "tail": "TAIL",
        "tool_result_handle": "tr-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "retrieve_hint": "Use retrieve_tool_result with tool_result_handle.",
    }
    _write_jsonl(
        inst / "transcript.jsonl",
        [
            {
                "message": {
                    "role": "toolResult",
                    "toolName": "exec_command",
                    "content": [{"type": "text", "text": json.dumps(truncated)}],
                }
            }
        ],
    )
    store_root = inst / "opensquilla_state" / "media" / "tool-results" / "s" / "session"
    _write_store_record(
        store_root / "aa" / "tr-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        handle="tr-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        tool_use_id="call-large",
        content="HEAD" + ("x" * 1024) + "TAIL",
    )

    summary = mod.summarize_instance(inst)
    aggregate = mod.aggregate([summary])

    assert summary["dispatch_truncation"]["events"] == 1
    assert summary["dispatch_truncation"]["huge_events"] == 1
    assert summary["dispatch_truncation"]["handle_present"] == 1
    assert summary["dispatch_truncation"]["handles_missing"] == 0
    assert summary["dispatch_truncation"]["tools"] == {"exec_command": 1}
    assert aggregate["dispatch_truncation_events"] == 1
    assert aggregate["dispatch_truncation_huge_events"] == 1
    assert aggregate["dispatch_truncation_handles_missing"] == 0
    assert aggregate["categories"]["dispatch_huge_exec_log"] == 1

    mod._print_table([summary])
    table = capsys.readouterr().out.splitlines()
    header = table[0].split("\t")
    row = table[1].split("\t")
    assert "dispatch_huge_exec_log:1" in row[header.index("categories")]


def test_eval_report_merge_uses_run_id_hint_to_avoid_status_conflicts(
    tmp_path: Path,
) -> None:
    mod = _load_script()
    inst = tmp_path / "run-qwen" / "repo__issue-1"
    inst.mkdir(parents=True)
    _write_json(
        inst / "metadata.json",
        {
            "instance_id": "repo__issue-1",
            "run_id": "run-qwen",
            "patch_empty": False,
        },
    )
    qwen_report = tmp_path / "model.run-qwen-eval.json"
    glm_report = tmp_path / "model.run-glm-eval.json"
    _write_json(qwen_report, {"resolved_ids": ["repo__issue-1"]})
    _write_json(glm_report, {"unresolved_ids": ["repo__issue-1"]})

    reports = mod._load_eval_reports([qwen_report, glm_report])
    instances = mod._annotate_eval_status([mod.summarize_instance(inst)], reports)
    aggregate = mod.aggregate(instances)

    assert instances[0]["eval"]["status"] == "resolved"
    assert aggregate["eval_total"] == 1
    assert aggregate["eval_resolved"] == 1
    assert aggregate["eval_resolved_rate"] == 1.0
    assert aggregate["eval_statuses"] == {"resolved": 1}


def test_aggregate_flags_projection_without_retrieval(tmp_path: Path) -> None:
    mod = _load_script()
    inst = tmp_path / "run-b" / "repo__issue-2"
    inst.mkdir(parents=True)
    _write_json(inst / "metadata.json", {"patch_empty": True})
    _write_jsonl(
        inst / "runtime_events.jsonl",
        [
            {
                "feature": "tool_result_projection",
                "tool_name": "exec_command",
                "outcome": "applied",
                "reason": "tokenjuice",
                "original_chars": 9000,
                "projected_chars": 500,
                "command": "sed -n '1,120p' src/lib.rs",
                "tool_arguments": {"command": "sed -n '1,120p' src/lib.rs"},
                "tool_result_handle_present": True,
            }
        ],
    )

    summary = mod.summarize_instance(inst)
    aggregate = mod.aggregate([summary])

    assert summary["projection"]["categories"]["projection_without_retrieve"] == 1
    assert summary["projection"]["categories"]["retrieval_unused"] == 1
    assert summary["projection"]["categories"]["source_lost"] == 1
    assert aggregate["empty_patches"] == 1
    assert aggregate["projection_applied"] == 1


def test_summarize_instance_reports_retrieval_result_continuations(
    tmp_path: Path,
    capsys,
) -> None:
    mod = _load_script()
    inst = tmp_path / "run-retrieve" / "repo__issue-retrieve"
    inst.mkdir(parents=True)
    _write_json(inst / "metadata.json", {"patch_empty": True})
    _write_jsonl(inst / "runtime_events.jsonl", [])
    _write_jsonl(
        inst / "transcript.jsonl",
        [
            {
                "message": {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "toolCall",
                            "name": "retrieve_tool_result",
                            "arguments": {"handle": "tr-abc", "query": "ERROR"},
                        }
                    ],
                }
            },
            {
                "message": {
                    "role": "toolResult",
                    "toolName": "retrieve_tool_result",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "[tool_result_retrieval]\n"
                                "handle: tr-abc\n"
                                "mode: query\n"
                                "---\n"
                                "[retrieve_tool_result truncated: "
                                "returned_chars=500, original_chars=5000]\n"
                                "continuation.next_call_strategy: "
                                "same_query_larger_max_chars\n"
                                'continuation.next_call: {"arguments": '
                                '{"handle": "tr-abc", "query": "ERROR"}}\n'
                            ),
                        }
                    ],
                }
            },
        ],
    )

    summary = mod.summarize_instance(inst)
    aggregate = mod.aggregate([summary])

    assert summary["retrieval"]["calls"] == 1
    assert summary["retrieval"]["results"] == 1
    assert summary["retrieval"]["modes"] == {"query": 1}
    assert summary["retrieval"]["result_modes"] == {"query": 1}
    assert summary["retrieval"]["truncated_results"] == 1
    assert summary["retrieval"]["continuation_suggestions"] == 1
    assert summary["retrieval"]["continuation_strategies"] == {
        "same_query_larger_max_chars": 1
    }
    assert aggregate["retrieve_results"] == 1
    assert aggregate["retrieve_truncated_results"] == 1
    assert aggregate["retrieve_continuation_suggestions"] == 1
    assert aggregate["retrieve_continuation_strategies"] == {
        "same_query_larger_max_chars": 1
    }
    assert "retrieval_result_missing" not in aggregate["categories"]
    assert "retrieval_truncated_without_continuation" not in aggregate["categories"]

    mod._print_table([summary])
    table = capsys.readouterr().out.splitlines()
    header = table[0].split("\t")
    row = table[1].split("\t")
    assert row[header.index("retrieve")] == "1"
    assert row[header.index("retrieval_results")] == "1"
    assert row[header.index("retrieval_continuations")] == "1"


def test_gate_violations_check_expansion_thresholds() -> None:
    mod = _load_script()
    aggregate = {
        "kv_cache_hit_rate": 0.875,
        "raw_store_integrity_bad": 1,
        "raw_store_projection_links_missing": 2,
        "empty_patches": 3,
        "dispatch_truncation_handles_missing": 4,
        "transcript_projection_replay_bad": 5,
        "eval_resolved_rate": 0.6,
        "categories": {"source_lost": 1},
    }

    assert mod._gate_violations(
        aggregate,
        min_kv_cache_hit_rate=0.87,
        max_raw_bad=1,
        max_raw_link_missing=2,
        max_empty_patches=3,
        max_dispatch_truncation_missing=4,
        max_transcript_replay_bad=5,
        min_eval_resolved_rate=0.6,
        max_categories={"source_lost": 1},
    ) == []
    assert mod._gate_violations(
        aggregate,
        min_kv_cache_hit_rate=0.88,
        max_raw_bad=0,
        max_raw_link_missing=1,
        max_empty_patches=2,
        max_dispatch_truncation_missing=3,
        max_transcript_replay_bad=4,
        min_eval_resolved_rate=0.7,
        max_categories={"source_lost": 0},
    ) == [
        "kv_cache_hit_rate 0.8750 < 0.8800",
        "raw_store_integrity_bad 1 > 0",
        "raw_store_projection_links_missing 2 > 1",
        "empty_patches 3 > 2",
        "dispatch_truncation_handles_missing 4 > 3",
        "transcript_projection_replay_bad 5 > 4",
        "eval_resolved_rate 0.6000 < 0.7000",
        "category source_lost 1 > 0",
    ]


def test_instance_dirs_ignore_empty_patch_recovery_artifacts(tmp_path: Path) -> None:
    mod = _load_script()
    inst = tmp_path / "run-c" / "repo__issue-3"
    recovery = inst / "empty_patch_recovery"
    recovery.mkdir(parents=True)
    _write_json(inst / "metadata.json", {"instance_id": "repo__issue-3"})
    _write_jsonl(inst / "runtime_events.jsonl", [])
    _write_jsonl(recovery / "runtime_events.jsonl", [])

    assert mod._instance_dirs([tmp_path / "run-c"]) == [inst.resolve()]
