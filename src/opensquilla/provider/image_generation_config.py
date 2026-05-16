"""Configuration DTOs for image generation providers."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class ImageGenerationOpenAIProviderConfig(BaseModel):
    base_url: str = "https://api.openai.com/v1"
    api_key: str = ""
    api_key_env: str = "OPENAI_API_KEY"


class ImageGenerationOpenRouterProviderConfig(BaseModel):
    base_url: str = "https://openrouter.ai/api/v1"
    api_key: str = ""
    api_key_env: str = "OPENROUTER_API_KEY"


class ImageGenerationProvidersConfig(BaseModel):
    openai: ImageGenerationOpenAIProviderConfig = Field(
        default_factory=ImageGenerationOpenAIProviderConfig
    )
    openrouter: ImageGenerationOpenRouterProviderConfig = Field(
        default_factory=ImageGenerationOpenRouterProviderConfig
    )


class ImageGenerationConfig(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="OPENSQUILLA_IMAGE_GENERATION_",
        env_nested_delimiter="__",
    )

    enabled: bool = False
    primary: str = "openai/gpt-image-1"
    fallbacks: list[str] = Field(default_factory=list)
    size: str = "1024x1024"
    timeout_seconds: float = 180.0
    output_format: Literal["png", "jpeg", "webp"] = "png"
    providers: ImageGenerationProvidersConfig = Field(
        default_factory=ImageGenerationProvidersConfig
    )
