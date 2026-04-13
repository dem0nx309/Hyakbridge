"""HyakAnime provider configuration."""

from pydantic import BaseModel, Field


class HyakAnimeListProviderConfig(BaseModel):
    """Configuration for the HyakAnime list provider."""

    token: str = Field(
        default=...,
        description="HyakAnime authentication token used for private write actions.",
    )
