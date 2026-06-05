from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPT = (
    REPO
    / "src"
    / "opensquilla"
    / "skills"
    / "bundled"
    / "nano-banana-pro-openrouter"
    / "scripts"
    / "openrouter_image.py"
)


def _module():
    spec = importlib.util.spec_from_file_location("openrouter_image", SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_extract_slots_keeps_field_block_contract() -> None:
    mod = _module()

    slots = mod._extract_slots(
        """
        slot_id: hero-visual
        modality: image
        subject: ocean plastic across a shoreline
        prompt_hint: wide documentary photo
        search_keywords: ocean plastic pollution

        slot_id: narration
        modality: audio
        subject: short narration
        """
    )

    assert slots == [
        {
            "slot_id": "hero-visual",
            "subject": "ocean plastic across a shoreline",
            "prompt_hint": "wide documentary photo",
            "keywords": "ocean plastic pollution",
        }
    ]


def test_extract_slots_reads_markdown_table_and_ignores_non_images() -> None:
    mod = _module()

    slots = mod._extract_slots(
        """
        | slot_id | modality | subject | prompt_hint | search_keywords |
        | --- | --- | --- | --- | --- |
        | hero | image | turtle near plastic | documentary hero | turtle plastic |
        | narration | audio | spoken intro | warm narration | |
        | impact-visual | image | microplastics | science diagram | microplastic |
        | intro-video | video | quick explainer | motion | |
        """
    )

    assert [slot["slot_id"] for slot in slots] == ["hero", "impact-visual"]
    assert slots[0]["subject"] == "turtle near plastic"
    assert slots[0]["prompt_hint"] == "documentary hero"
    assert slots[0]["keywords"] == "turtle plastic"
    assert slots[1]["subject"] == "microplastics"


def test_extract_slots_reads_cjk_markdown_table_headers() -> None:
    mod = _module()

    slots = mod._extract_slots(
        """
        | 槽位 | 媒体类型 | 画面主题 | 描述 | 关键词 |
        | --- | --- | --- | --- | --- |
        | science-hero | 图片 | 海洋塑料污染主视觉 | 适合首屏 | 海洋 塑料 污染 |
        | voiceover | 音频 | 旁白 | 60秒 | |
        """
    )

    assert slots == [
        {
            "slot_id": "science-hero",
            "subject": "海洋塑料污染主视觉",
            "prompt_hint": "适合首屏",
            "keywords": "海洋 塑料 污染",
        }
    ]


def test_extract_slots_reads_inline_slot_lines() -> None:
    mod = _module()

    slots = mod._extract_slots(
        "- slot_id: fallback-map, modality: image, subject: current cleanup hotspots"
    )

    assert slots[0]["slot_id"] == "fallback-map"


def test_target_slots_prefers_explicit_media_slots_json() -> None:
    mod = _module()

    slots = mod._target_slots(
        {
            "media_slots": json.dumps(
                {
                    "slots": [
                        {
                            "slot_id": "hero-visual",
                            "modality": "image",
                            "subject": "ocean cleanup hero",
                            "prompt_hint": "wide documentary photo",
                            "search_keywords": ["ocean", "plastic"],
                        },
                        {
                            "slot_id": "narration-audio",
                            "modality": "audio",
                            "subject": "voiceover",
                        },
                    ]
                }
            ),
            "page_outline": "no parseable image slot here",
        },
        6,
    )

    assert slots == [
        {
            "slot_id": "hero-visual",
            "subject": "ocean cleanup hero",
            "prompt_hint": "wide documentary photo",
            "keywords": "ocean plastic",
        }
    ]


def test_target_slots_accepts_exec_command_wrapped_media_slots_json() -> None:
    mod = _module()
    media_slots = json.dumps(
        {
            "slots": [
                {
                    "slot_id": "normalized-cn-visual",
                    "modality": "图片",
                    "subject": "规范化后的中文图片槽位",
                }
            ]
        }
    )

    slots = mod._target_slots(
        {
            "media_slots": f"exit_code=0\n{media_slots}\n",
            "page_outline": "no parseable image slot here",
        },
        6,
    )

    assert slots == [
        {
            "slot_id": "normalized-cn-visual",
            "subject": "规范化后的中文图片槽位",
            "prompt_hint": "",
            "keywords": "",
        }
    ]


def test_target_slots_synthesizes_fallback_when_requested_images_have_no_slots() -> None:
    mod = _module()

    slots = mod._target_slots(
        {
            "requirement_framing": "主题: 海洋塑料污染科普网页",
            "page_outline": "| section_id | title |\n| --- | --- |\n| hero | 海洋塑料污染 |",
            "include_images": "YES",
        },
        6,
    )

    assert [slot["slot_id"] for slot in slots] == ["hero-visual", "supporting-visual"]
    assert "海洋塑料污染" in slots[0]["subject"]


def test_target_slots_does_not_synthesize_when_images_are_declined() -> None:
    mod = _module()

    slots = mod._target_slots(
        {
            "requirement_framing": "主题: text-only page",
            "page_outline": "no image slots",
            "include_images": "NO",
        },
        6,
    )

    assert slots == []


def test_decode_image_auth_stays_on_openrouter_origin(monkeypatch) -> None:
    mod = _module()
    opened_headers: list[dict[str, str]] = []

    class FakeHeaders:
        def get_content_type(self) -> str:
            return "image/png"

    class FakeResponse:
        headers = FakeHeaders()

        def __enter__(self):
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b"image-bytes"

    def fake_urlopen(req, timeout: float = 45.0):
        del timeout
        opened_headers.append({key.lower(): value for key, value in req.header_items()})
        return FakeResponse()

    monkeypatch.setattr(mod.urllib.request, "urlopen", fake_urlopen)

    assert mod._decode_image(
        "https://storage.example/image.png",
        "sk-or-secret",
        base_url="https://openrouter.ai/api/v1",
    ) == ("image/png", b"image-bytes")
    assert "authorization" not in opened_headers[-1]

    assert mod._decode_image(
        "https://openrouter.ai/api/v1/images/result.png",
        "sk-or-secret",
        base_url="https://openrouter.ai/api/v1",
    ) == ("image/png", b"image-bytes")
    assert opened_headers[-1]["authorization"] == "Bearer sk-or-secret"
