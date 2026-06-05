import json
import os
import re
import sys
from pathlib import Path

workspace = Path(os.environ["WORKSPACE_DIR"]).expanduser().resolve()
project_root = Path(os.environ["PROJECT_ROOT"]).expanduser().resolve()
project_root.relative_to(workspace)

raw_env = os.environ.get("WEBPAGE_SOURCE_JSON")
raw_payload_source = raw_env if raw_env is not None else (
    "" if sys.stdin.isatty() else sys.stdin.read()
)
try:
    raw_payload = json.loads(raw_payload_source)
except json.JSONDecodeError as exc:
    raise SystemExit(f"WEBPAGE_WRITE_FAILED: invalid source JSON payload: {exc}") from exc

def require_object(value):
    if isinstance(value, dict):
        return value
    raise ValueError("source must be a JSON object")

def parse_json_object(text):
    text = text.strip()
    errors = []
    if not text:
        raise ValueError("empty source JSON")

    candidates = [text]
    candidates.extend(match.group(1).strip() for match in re.finditer(
        r"```(?:json)?\s*(\{.*?\})\s*```",
        text,
        re.S,
    ))

    for candidate in candidates:
        try:
            return require_object(json.loads(candidate))
        except (json.JSONDecodeError, ValueError) as exc:
            errors.append(str(exc))

    depth = 0
    start = None
    in_string = False
    escape = False
    for idx, char in enumerate(text):
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            if depth == 0:
                start = idx
            depth += 1
        elif char == "}" and depth:
            depth -= 1
            if depth == 0 and start is not None:
                candidate = text[start : idx + 1]
                try:
                    return require_object(json.loads(candidate))
                except (json.JSONDecodeError, ValueError) as exc:
                    errors.append(str(exc))

    raise ValueError(errors[-1] if errors else "no JSON object found")

if isinstance(raw_payload, str):
    try:
        data = parse_json_object(raw_payload)
    except ValueError as exc:
        raise SystemExit(f"WEBPAGE_WRITE_FAILED: invalid source JSON: {exc}") from exc
elif isinstance(raw_payload, dict):
    data = raw_payload
else:
    raise SystemExit("WEBPAGE_WRITE_FAILED: source must be a JSON object")

required = {
    "index_html": "index.html",
    "style_css": "style.css",
    "script_js": "script.js",
}
missing = [key for key in required if not str(data.get(key, "")).strip()]
if missing:
    raise SystemExit("WEBPAGE_WRITE_FAILED: missing keys " + ",".join(missing))

project_dir = project_root / "project"
for rel in [
    "assets/images",
    "assets/audio",
    "assets/video",
]:
    (project_dir / rel).mkdir(parents=True, exist_ok=True)

written = []
for key, filename in required.items():
    target = (project_dir / filename).resolve()
    target.relative_to(project_dir.resolve())
    target.write_text(str(data[key]), encoding="utf-8")
    written.append(str(target))

print(json.dumps({
    "status": "WEBPAGE_FILES_WRITTEN",
    "project_root": str(project_root),
    "files": written,
    "summary": str(data.get("summary", ""))[:500],
}, ensure_ascii=True, separators=(",", ":")))
