"""Unit tests for opensquilla.contrib.swebench.prediction."""

import json

from opensquilla.contrib.swebench.prediction import (
    append_prediction,
    format_prediction,
    validate_prediction_file,
    write_predictions,
)


def test_format_prediction():
    pred = format_prediction("inst-1", "some patch", "model-x")
    assert pred == {
        "instance_id": "inst-1",
        "model_patch": "some patch",
        "model_name_or_path": "model-x",
    }


def test_write_and_validate_roundtrip(tmp_path):
    path = tmp_path / "predictions.jsonl"
    preds = [
        format_prediction("inst-1", "patch one", "model-x"),
        format_prediction("inst-2", "patch two", "model-x"),
    ]
    write_predictions(preds, path)
    assert validate_prediction_file(path) == []
    lines = path.read_text().strip().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["instance_id"] == "inst-1"


def test_append_prediction(tmp_path):
    path = tmp_path / "predictions.jsonl"
    append_prediction(format_prediction("inst-1", "p", "m"), path)
    append_prediction(format_prediction("inst-2", "p", "m"), path)
    assert validate_prediction_file(path) == []
    assert len(path.read_text().strip().splitlines()) == 2


def test_validate_missing_file(tmp_path):
    errors = validate_prediction_file(tmp_path / "nope.jsonl")
    assert len(errors) == 1
    assert "not found" in errors[0]


def test_validate_duplicate_ids(tmp_path):
    path = tmp_path / "predictions.jsonl"
    append_prediction(format_prediction("inst-1", "p", "m"), path)
    append_prediction(format_prediction("inst-1", "p", "m"), path)
    errors = validate_prediction_file(path)
    assert any("duplicate" in e for e in errors)


def test_validate_missing_fields(tmp_path):
    path = tmp_path / "predictions.jsonl"
    path.write_text(json.dumps({"instance_id": "inst-1"}) + "\n")
    errors = validate_prediction_file(path)
    assert any("model_patch" in e for e in errors)
    assert any("model_name_or_path" in e for e in errors)


def test_validate_expected_ids_coverage(tmp_path):
    path = tmp_path / "predictions.jsonl"
    append_prediction(format_prediction("inst-1", "p", "m"), path)
    errors = validate_prediction_file(path, expected_ids={"inst-1", "inst-2"})
    assert any("Missing 1 instance" in e for e in errors)
