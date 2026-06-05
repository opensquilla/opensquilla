#!/usr/bin/env python3
"""OpenRouter audio entrypoint for meta-skill ``skill_exec`` steps."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import sys
import wave
from collections.abc import Iterable
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

SAMPLE_RATE = 24_000


def _safe_filename(value: str, default: str) -> str:
    name = Path(value or default).name
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip(".-")
    if not name:
        name = default
    if not name.lower().endswith(".wav"):
        name = re.sub(r"\.[A-Za-z0-9]+$", "", name) + ".wav"
    return name


def _preview(text: str) -> str:
    return " ".join(text.split())[:80]


def _clean_script(value: object) -> str:
    text = str(value or "").strip()
    text = re.sub(r"^```(?:text|markdown)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _audio_messages(raw: str) -> tuple[list[dict[str, str]], str]:
    text = raw.strip()
    if text:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            script = _clean_script(
                payload.get("script")
                or payload.get("transcript")
                or payload.get("narration")
                or payload.get("text")
            )
            if script:
                return (
                    [
                        {
                            "role": "system",
                            "content": (
                                "You are a text-to-speech renderer. Return and speak exactly the "
                                "provided narration transcript. Do not acknowledge the request. "
                                "Do not say you understand. Do not add introductions, titles, "
                                "stage directions, markdown, file names, or closing remarks."
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                "Speak this exact narration transcript and no other words:\n\n"
                                + script
                            ),
                        },
                    ],
                    script,
                )

    prompt = text or "Create a short, clear narration for this webpage."
    return (
        [
            {
                "role": "system",
                "content": (
                    "You produce finished webpage narration audio. Respond only with the "
                    "spoken narration itself. Never acknowledge the request, never say "
                    "you understand, and never describe what you will create."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        prompt,
    )


def _print_record(label: str, payload: dict[str, object]) -> None:
    print(f"{label}: {json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}")


def _failure(label: str, filename: str, **extra: object) -> None:
    payload: dict[str, object] = {
        "replacement_slot": f"project/assets/audio/{filename}",
    }
    payload.update(extra)
    _print_record(label, payload)


def _failure_reason(exc: BaseException) -> str:
    if isinstance(exc, URLError):
        return exc.reason.__class__.__name__
    return exc.__class__.__name__


def _iter_sse_audio_chunks(response: Iterable[bytes]) -> bytes:
    pcm = bytearray()
    for raw in response:
        line = raw.decode("utf-8", "replace").strip()
        if not line.startswith("data:"):
            continue
        payload = line[5:].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            obj = json.loads(payload)
        except json.JSONDecodeError:
            continue
        for choice in obj.get("choices") or []:
            delta = choice.get("delta") or {}
            message = choice.get("message") or {}
            audio = delta.get("audio") or message.get("audio") or {}
            data_b64 = audio.get("data")
            if isinstance(data_b64, str) and data_b64:
                pcm.extend(base64.b64decode(data_b64))
    return bytes(pcm)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--base-url", default="https://openrouter.ai/api/v1")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--api-key-env", default="OPENROUTER_API_KEY")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--filename", default="narration.wav")
    parser.add_argument("--voice", default="cedar")
    args = parser.parse_args()

    filename = _safe_filename(args.filename, "narration.wav")
    messages, script_text = _audio_messages(sys.stdin.read())

    api_key_env = args.api_key_env.strip() or "OPENROUTER_API_KEY"
    key = str(args.api_key.strip() or os.environ.get(api_key_env, ""))
    missing = []
    if not key:
        missing.append(api_key_env)
    if not args.model:
        missing.append("awesome_webpage.openrouter.models.audio_generation")
    if not args.output_dir:
        missing.append("awesome_webpage.output_dir")
    if missing:
        _failure("AUDIO_CONFIG_NEEDED", filename, missing=missing)
        return 0

    output_dir = Path(args.output_dir).expanduser()
    output_path = output_dir / filename
    local_path = f"project/assets/audio/{filename}"
    base_url = args.base_url.rstrip("/")

    body = json.dumps(
        {
            "model": args.model,
            "stream": True,
            "modalities": ["text", "audio"],
            "audio": {"voice": args.voice, "format": "pcm16"},
            "messages": messages,
        }
    ).encode("utf-8")
    req = Request(
        f"{base_url}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        },
        method="POST",
    )

    try:
        with urlopen(req, timeout=180) as resp:
            pcm = _iter_sse_audio_chunks(resp)
    except HTTPError as exc:
        _failure("AUDIO_GENERATION_FAILED", filename, status=exc.code)
        return 0
    except (URLError, TimeoutError) as exc:
        _failure("AUDIO_GENERATION_FAILED", filename, reason=_failure_reason(exc))
        return 0

    if not pcm:
        _failure("AUDIO_MODEL_UNSUPPORTED", filename, reason="no_audio_pcm")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    with wave.open(str(output_path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(SAMPLE_RATE)
        wav.writeframes(pcm)

    _print_record(
        "AUDIO_READY",
        {
            "local_path": local_path,
            "mime": "audio/wav",
            "duration_s": round(len(pcm) / 2 / SAMPLE_RATE, 2),
            "voice": args.voice,
            "script_preview": _preview(script_text),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
