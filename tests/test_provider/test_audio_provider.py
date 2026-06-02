from __future__ import annotations

import json

import httpx
import pytest

from opensquilla.provider.audio import (
    ElevenLabsAudioProductionProvider,
    ElevenLabsSharedVoicesRequest,
    ElevenLabsSpeechToTextRequest,
    ElevenLabsTextToSpeechRequest,
    MusicGenerationRequest,
    VoiceCloneRequest,
)


@pytest.mark.anyio
async def test_elevenlabs_text_to_speech_posts_json_and_returns_audio() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.path == "/v1/text-to-speech/voice_123"
        assert request.url.params["output_format"] == "mp3_44100_128"
        assert request.headers["xi-api-key"] == "el-test"
        payload = json.loads(request.content)
        assert payload == {
            "text": "hello",
            "model_id": "eleven_multilingual_v2",
            "language_code": "zh",
            "voice_settings": {
                "stability": 0.65,
                "similarity_boost": 0.8,
                "style": 0.0,
                "use_speaker_boost": True,
                "speed": 0.92,
            },
        }
        return httpx.Response(
            200,
            content=b"speech-audio",
            headers={"Content-Type": "audio/mpeg", "X-Generation-Id": "gen_123"},
        )

    provider = ElevenLabsAudioProductionProvider(
        api_key="el-test",
        transport=httpx.MockTransport(handler),
    )

    result = await provider.text_to_speech(
        ElevenLabsTextToSpeechRequest(
            text="hello",
            voice="voice_123",
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
            language_code="zh",
            voice_settings={
                "stability": 0.65,
                "similarity_boost": 0.8,
                "style": 0.0,
                "use_speaker_boost": True,
                "speed": 0.92,
            },
        )
    )

    assert len(requests) == 1
    assert result.audio_bytes == b"speech-audio"
    assert result.provider == "elevenlabs"
    assert result.voice == "voice_123"
    assert result.mime_type == "audio/mpeg"
    assert result.generation_id == "gen_123"


@pytest.mark.anyio
async def test_elevenlabs_clone_voice_posts_multipart_sample() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/voices/add"
        body = request.content
        assert b"sample.mp3" in body
        assert b"voice sample" in body
        assert b"Demo voice" in body
        return httpx.Response(200, json={"voice_id": "voice_new", "name": "Demo voice"})

    provider = ElevenLabsAudioProductionProvider(
        api_key="el-test",
        transport=httpx.MockTransport(handler),
    )

    result = await provider.clone_voice(
        VoiceCloneRequest(
            sample_audio_bytes=b"voice sample",
            sample_filename="sample.mp3",
            sample_mime_type="audio/mpeg",
            name="Demo voice",
        )
    )

    assert result.provider == "elevenlabs"
    assert result.voice_id == "voice_new"
    assert result.name == "Demo voice"


@pytest.mark.anyio
async def test_elevenlabs_generate_music_posts_prompt_and_returns_audio() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/music"
        assert request.url.params["output_format"] == "mp3_44100_128"
        assert request.headers["xi-api-key"] == "el-test"
        payload = json.loads(request.content)
        assert payload == {
            "prompt": "cinematic intro",
            "model_id": "music_v1",
            "force_instrumental": True,
            "music_length_ms": 12000,
        }
        return httpx.Response(200, content=b"music-audio", headers={"Content-Type": "audio/mpeg"})

    provider = ElevenLabsAudioProductionProvider(
        api_key="el-test",
        transport=httpx.MockTransport(handler),
    )

    result = await provider.generate_music(
        MusicGenerationRequest(
            prompt="cinematic intro",
            model_id="music_v1",
            output_format="mp3_44100_128",
            duration_seconds=12,
        )
    )

    assert result.audio_bytes == b"music-audio"
    assert result.model == "music_v1"
    assert result.response_format == "mp3_44100_128"


@pytest.mark.anyio
async def test_elevenlabs_transcribe_audio_posts_multipart_and_returns_text() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/speech-to-text"
        assert request.headers["xi-api-key"] == "el-test"
        body = request.content
        assert b"model_id" in body
        assert b"scribe_v2" in body
        assert b"voice.webm" in body
        assert b"audio/webm" in body
        assert b"spoken bytes" in body
        return httpx.Response(
            200,
            json={
                "text": "请帮我生成一段语音",
                "language_code": "zh",
                "language_probability": 0.97,
                "words": [{"text": "请", "start": 0, "end": 0.2}],
            },
        )

    provider = ElevenLabsAudioProductionProvider(
        api_key="el-test",
        transport=httpx.MockTransport(handler),
    )

    result = await provider.transcribe_audio(
        ElevenLabsSpeechToTextRequest(
            audio_bytes=b"spoken bytes",
            filename="voice.webm",
            mime_type="audio/webm",
            model_id="scribe_v2",
        )
    )

    assert result.provider == "elevenlabs"
    assert result.model == "scribe_v2"
    assert result.text == "请帮我生成一段语音"
    assert result.language_code == "zh"
    assert result.language_probability == 0.97
    assert result.words[0]["text"] == "请"


@pytest.mark.anyio
async def test_elevenlabs_search_shared_voices_filters_language_and_accent() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/shared-voices"
        assert request.url.params["language"] == "zh"
        assert request.url.params["accent"] == "beijing mandarin"
        assert request.url.params["page_size"] == "3"
        assert request.headers["xi-api-key"] == "el-test"
        return httpx.Response(
            200,
            json={
                "voices": [
                    {
                        "name": "Mandarin Narrator",
                        "voice_id": "voice_zh",
                        "public_owner_id": "owner_123",
                        "language": "zh",
                        "accent": "beijing mandarin",
                        "gender": "female",
                        "category": "professional",
                    }
                ],
                "has_more": False,
            },
        )

    provider = ElevenLabsAudioProductionProvider(
        api_key="el-test",
        transport=httpx.MockTransport(handler),
    )

    result = await provider.search_shared_voices(
        ElevenLabsSharedVoicesRequest(
            language="zh",
            accent="beijing mandarin",
            page_size=3,
        )
    )

    assert result.provider == "elevenlabs"
    assert result.voices[0]["voice_id"] == "voice_zh"
    assert result.raw["has_more"] is False
