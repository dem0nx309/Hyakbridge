"""Tests for the HyakAnime HTTP client."""

from logging import getLogger
from typing import cast

import pytest
from anibridge.utils.types import ProviderLogger

from anibridge.app.models.schemas.anilist import Media, MediaTitle
from anibridge.providers.list.hyakanime.client import HyakAnimeClient
from anibridge.providers.list.hyakanime.models import HyakAnimeAnime


@pytest.mark.asyncio
async def test_search_anime_url_encodes_slashes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Search queries should be encoded as a single path segment."""
    client = HyakAnimeClient(
        token="test-token", logger=cast(ProviderLogger, getLogger("test"))
    )
    requested: list[tuple[str, str]] = []

    async def fake_request(method: str, path: str, **_kwargs):
        requested.append((method, path))
        return []

    monkeypatch.setattr(client, "_request", fake_request)

    results = await client.search_anime("22/7")

    assert results == ()
    assert requested == [("GET", "search/anime/22%2F7")]


@pytest.mark.asyncio
async def test_resolve_anilist_media_matches_by_anilist_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AniList media resolution should reuse search results and match by AniList ID."""
    client = HyakAnimeClient(
        token="test-token", logger=cast(ProviderLogger, getLogger("test"))
    )
    searched: list[str] = []

    async def fake_search_anime(query: str):
        searched.append(query)
        return [
            HyakAnimeAnime.model_validate(
                {"id": 321, "title": "Sakamoto Days", "idAnilist": 123}
            )
        ]

    monkeypatch.setattr(client, "search_anime", fake_search_anime)

    media = Media(id=123, title=MediaTitle(romaji="Sakamoto Days"))
    first = await client.resolve_anilist_media(media)
    second = await client.resolve_anilist_media(media)

    assert first is not None
    assert first.id == 321
    assert second is first
    assert searched == ["Sakamoto Days"]
