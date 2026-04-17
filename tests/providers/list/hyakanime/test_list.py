"""Tests for the HyakAnime list provider."""

from logging import getLogger
from typing import cast

import pytest
from anibridge.list import ListStatus
from anibridge.utils.types import ProviderLogger

from anibridge.app.models.schemas.anilist import Media, MediaFormat, MediaTitle
from anibridge.providers.list.hyakanime.list import (
    HyakAnimeListEntry,
    HyakAnimeListProvider,
)
from anibridge.providers.list.hyakanime.models import (
    HyakAnimeAnime,
    HyakAnimeProgression,
    HyakAnimeProgressionItem,
    HyakAnimeRefreshResponse,
)


def _provider() -> HyakAnimeListProvider:
    return HyakAnimeListProvider(
        logger=cast(ProviderLogger, getLogger("test")),
        config={"token": "test-token"},
    )


@pytest.mark.asyncio
async def test_resolve_mapping_descriptors_keeps_direct_hyakanime_ids() -> None:
    """Direct HyakAnime descriptors should resolve without extra API calls."""
    provider = _provider()

    targets = await provider.resolve_mapping_descriptors(
        [("hyakanime", "3022", None), ("other", "9", None)]
    )

    assert [(target.descriptor[0], target.media_key) for target in targets] == [
        ("hyakanime", "3022")
    ]


@pytest.mark.asyncio
async def test_resolve_mapping_descriptors_matches_anilist_results_by_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AniList descriptors should resolve through HyakAnime title search."""
    provider = _provider()
    queries: list[str] = []

    async def fake_batch_get_anime(_ids: list[int]) -> list[Media]:
        return [
            Media(
                id=146323,
                format=MediaFormat.TV,
                title=MediaTitle(
                    user_preferred="Spy Classroom",
                    english="Spy Classroom",
                    romaji="Spy Kyoushitsu",
                ),
            )
        ]

    async def fake_search(query: str) -> list[HyakAnimeAnime]:
        queries.append(query)
        return [
            HyakAnimeAnime(
                id=3022,
                title="Spy Classroom",
                id_anilist=146323,
                id_mal=51252,
                total_episodes=12,
                type="TV",
            )
        ]

    monkeypatch.setattr(
        provider._anilist_client,
        "batch_get_anime",
        fake_batch_get_anime,
    )
    monkeypatch.setattr(provider._client, "search_anime", fake_search)

    targets = await provider.resolve_mapping_descriptors([("anilist", "146323", None)])

    assert [target.media_key for target in targets] == ["3022"]
    assert queries == ["Spy Classroom"]


@pytest.mark.asyncio
async def test_get_entry_returns_placeholder_when_progression_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An existing anime without user progress should still produce an entry."""
    provider = _provider()

    async def fake_get_anime(_anime_id: int) -> HyakAnimeAnime:
        return HyakAnimeAnime(
            id=3022, title="Spy Classroom", total_episodes=12, type="TV"
        )

    async def fake_get_progression(_anime_id: int):
        return None

    monkeypatch.setattr(provider._client, "get_anime", fake_get_anime)
    monkeypatch.setattr(provider._client, "get_progression", fake_get_progression)

    entry = await provider.get_entry("3022")

    assert entry is not None
    assert entry.media().key == "3022"
    assert entry.status is None
    assert entry.progress == 0
    assert entry.total_units == 12


@pytest.mark.asyncio
async def test_update_entry_writes_status_and_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """V1 updates should send only HyakAnime status and progress."""
    provider = _provider()
    written: list[dict[str, int]] = []
    anime = HyakAnimeAnime(id=3022, title="Spy Classroom", total_episodes=12, type="TV")
    persisted = HyakAnimeProgression(anime_id=3022, progression=0, status=2)

    async def fake_get_entry(_key: str) -> HyakAnimeListEntry:
        return HyakAnimeListEntry(provider, anime, persisted)

    async def fake_write_progression(*, anime_id: int, progression: int, status: int):
        written.append(
            {"anime_id": anime_id, "progression": progression, "status": status}
        )
        persisted.anime_id = anime_id
        persisted.progression = progression
        persisted.status = status
        return {"ok": True}

    monkeypatch.setattr(provider, "get_entry", fake_get_entry)
    monkeypatch.setattr(provider._client, "write_progression", fake_write_progression)

    entry = HyakAnimeListEntry(provider, anime, HyakAnimeProgression(anime_id=3022))
    entry.status = ListStatus.COMPLETED
    entry.progress = 8

    updated = await provider.update_entry("3022", entry)

    assert written == [{"anime_id": 3022, "progression": 12, "status": 3}]
    assert updated is not None
    assert updated.status is ListStatus.COMPLETED
    assert updated.progress == 12


def test_entry_status_mapping_roundtrip() -> None:
    """HyakAnime status values should map cleanly to AniBridge statuses."""
    provider = _provider()
    anime = HyakAnimeAnime(id=3022, title="Spy Classroom")
    entry = HyakAnimeListEntry(
        provider,
        anime,
        HyakAnimeProgression(anime_id=3022, progression=3, status=1),
    )

    assert entry.status is ListStatus.CURRENT

    entry.status = ListStatus.REPEATING

    assert entry.status is ListStatus.REPEATING
    assert entry._progression.status == 6


def test_refresh_response_accepts_string_uid() -> None:
    """HyakAnime auth refresh can return UUID-like string user identifiers."""
    response = HyakAnimeRefreshResponse.model_validate(
        {
            "isValid": True,
            "uid": "dbb3478f-1373-48f6-afa4-ceb33b82c10a",
            "username": "BotDiscord",
        }
    )

    assert response.is_valid is True
    assert response.uid == "dbb3478f-1373-48f6-afa4-ceb33b82c10a"


def test_progression_item_accepts_partial_media_payloads() -> None:
    """Progression payloads can omit title and include null alternate titles."""
    item = HyakAnimeProgressionItem.model_validate(
        {
            "progression": {
                "animeID": 4654,
                "progression": 0,
                "status": 1,
            },
            "media": {
                "id": 4654,
                "titleJP": "五等分の花嫁*",
                "alt": ["The Quintessential Quintuplets*", None],
                "romanji": "Go-toubun no Hanayome *",
                "titleEN": "",
            },
        }
    )

    assert item.media.title is None
    assert item.media.alt == ["The Quintessential Quintuplets*"]
    assert item.media.best_title() == "Go-toubun no Hanayome *"
