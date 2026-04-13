"""HyakAnime HTTP client."""

import asyncio
import json
from collections.abc import Sequence
from typing import Any, ClassVar
from urllib.parse import quote

import aiohttp
from anibridge.utils.types import ProviderLogger

from anibridge.app import __version__
from anibridge.app.models.schemas.anilist import Media
from anibridge.providers.list.hyakanime.models import (
    HyakAnimeAnime,
    HyakAnimeProgressionItem,
    HyakAnimeRefreshResponse,
)

__all__ = ["HyakAnimeClient"]


class HyakAnimeClient:
    """Minimal HyakAnime API client for list reads and writes."""

    API_URL: ClassVar[str] = "https://api-v5.hyakanime.fr/"

    def __init__(self, *, token: str, logger: ProviderLogger) -> None:
        """Create the HyakAnime client."""
        self.log = logger
        self.token = token
        self.user: HyakAnimeRefreshResponse | None = None

        self._session: aiohttp.ClientSession | None = None
        self._anime_cache: dict[int, HyakAnimeAnime] = {}
        self._search_cache: dict[str, tuple[HyakAnimeAnime, ...]] = {}
        self._anilist_cache: dict[int, HyakAnimeAnime | None] = {}
        self._progressions_by_anime: dict[int, HyakAnimeProgressionItem] | None = None

    async def initialize(self) -> None:
        """Validate the token and load the authenticated user."""
        self.clear_cache()
        self.user = await self.refresh_user()
        if not self.user.is_valid or self.user.uid is None:
            raise RuntimeError("Failed to authenticate with HyakAnime")
        if self.user.token:
            self.token = self.user.token

    def clear_cache(self) -> None:
        """Clear cached anime, search, and progression responses."""
        self._anime_cache.clear()
        self._search_cache.clear()
        self._anilist_cache.clear()
        self._progressions_by_anime = None

    async def close(self) -> None:
        """Close the underlying HTTP session."""
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def refresh_user(self) -> HyakAnimeRefreshResponse:
        """Refresh and return the authenticated HyakAnime user."""
        data = await self._request("POST", "auth/refresh", authorized=True)
        user = HyakAnimeRefreshResponse.model_validate(data or {})
        self.log.debug(
            "HyakAnime refresh resolved user uid=%s username=%s",
            user.uid,
            user.username,
        )
        return user

    async def get_anime(self, anime_id: int) -> HyakAnimeAnime | None:
        """Fetch a single anime by its HyakAnime identifier."""
        cached = self._anime_cache.get(anime_id)
        if cached is not None:
            return cached

        try:
            data = await self._request("GET", f"anime/{anime_id}")
        except aiohttp.ClientResponseError as exc:
            if exc.status == 404:
                return None
            raise

        anime = HyakAnimeAnime.model_validate(data)
        self._anime_cache[anime.id] = anime
        return anime

    async def search_anime(self, query: str) -> Sequence[HyakAnimeAnime]:
        """Search HyakAnime by title."""
        normalized = query.strip().casefold()
        if not normalized:
            return ()

        cached = self._search_cache.get(normalized)
        if cached is not None:
            return cached

        encoded_query = quote(query.strip(), safe="")
        data = await self._request("GET", f"search/anime/{encoded_query}")
        results = tuple(HyakAnimeAnime.model_validate(item) for item in (data or []))
        for anime in results:
            self._anime_cache[anime.id] = anime
        self._search_cache[normalized] = results
        return results

    async def resolve_anilist_media(self, media: Media) -> HyakAnimeAnime | None:
        """Resolve an AniList media object into a matching HyakAnime anime."""
        cached = self._anilist_cache.get(media.id)
        if media.id in self._anilist_cache:
            return cached

        for title in self._candidate_titles(media):
            for result in await self.search_anime(title):
                if result.id_anilist == media.id:
                    self._anilist_cache[media.id] = result
                    return result

        self._anilist_cache[media.id] = None
        return None

    @staticmethod
    def _candidate_titles(media: Media) -> tuple[str, ...]:
        """Return deduplicated AniList titles to try against HyakAnime search."""
        title = media.title
        if title is None:
            return ()

        candidates: list[str] = []
        for value in (
            title.user_preferred,
            title.english,
            title.romaji,
            title.native,
        ):
            if not value:
                continue
            stripped = value.strip()
            if not stripped or stripped in candidates:
                continue
            candidates.append(stripped)

        return tuple(candidates)

    async def get_progressions(
        self, *, force_refresh: bool = False
    ) -> Sequence[HyakAnimeProgressionItem]:
        """Return the user's progression list keyed by anime id."""
        if self.user is None or self.user.uid is None:
            raise RuntimeError("HyakAnime client is not initialized")

        if self._progressions_by_anime is not None and not force_refresh:
            return tuple(self._progressions_by_anime.values())

        data = await self._request("GET", f"progression/anime/{self.user.uid}")
        items: list[HyakAnimeProgressionItem] = []
        cache: dict[int, HyakAnimeProgressionItem] = {}
        for raw_item in data or []:
            item = HyakAnimeProgressionItem.model_validate(raw_item)
            anime_id = item.progression.anime_id or item.media.id
            item.progression.anime_id = anime_id
            cache[anime_id] = item
            self._anime_cache[item.media.id] = item.media
            items.append(item)

        self._progressions_by_anime = cache
        return tuple(items)

    async def get_progression(
        self, anime_id: int, *, force_refresh: bool = False
    ) -> HyakAnimeProgressionItem | None:
        """Return the user's progression entry for a specific anime."""
        await self.get_progressions(force_refresh=force_refresh)
        if self._progressions_by_anime is None:
            return None
        return self._progressions_by_anime.get(anime_id)

    async def write_progression(
        self, *, anime_id: int, progression: int, status: int
    ) -> Any:
        """Persist a HyakAnime progression update."""
        payload = {
            "id": anime_id,
            "progression": progression,
            "status": status,
        }
        result = await self._request(
            "POST",
            "progression/anime/write",
            json_body=payload,
            authorized=True,
        )
        self._progressions_by_anime = None
        return result

    async def delete_progression(self, anime_id: int) -> None:
        """Delete a HyakAnime progression entry."""
        payloads = ({"id": anime_id}, {"animeID": anime_id})
        last_error: Exception | None = None

        for index, payload in enumerate(payloads):
            try:
                await self._request(
                    "DELETE",
                    "progression/anime/delete",
                    json_body=payload,
                    authorized=True,
                )
            except aiohttp.ClientResponseError as exc:
                last_error = exc
                if exc.status in {400, 404} and index == 0:
                    continue
                if exc.status == 404:
                    return
                raise
            else:
                self._progressions_by_anime = None
                return

        if last_error is not None:
            raise last_error

    async def _get_session(self) -> aiohttp.ClientSession:
        """Return a shared aiohttp session for HyakAnime requests."""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "User-Agent": f"AniBridge/{__version__}",
                }
            )
        return self._session

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        authorized: bool = False,
    ) -> Any:
        """Execute a HyakAnime API request with light retry handling."""
        session = await self._get_session()
        url = self.API_URL + path.lstrip("/")
        headers = {"Authorization": self.token} if authorized else None
        delay = 1.0

        for attempt in range(3):
            try:
                async with session.request(
                    method,
                    url,
                    headers=headers,
                    json=json_body,
                ) as response:
                    if response.status == 429 and attempt < 2:
                        retry_after = response.headers.get("Retry-After")
                        sleep_for = float(retry_after) if retry_after else delay
                        self.log.warning(
                            "HyakAnime rate limit hit for %s %s, retrying in %.1fs",
                            method,
                            path,
                            sleep_for,
                        )
                        await asyncio.sleep(max(sleep_for, 0))
                        delay *= 2
                        continue

                    if response.status in {500, 502, 503, 504} and attempt < 2:
                        self.log.warning(
                            "HyakAnime transient error %s for %s %s, retrying",
                            response.status,
                            method,
                            path,
                        )
                        await asyncio.sleep(delay)
                        delay *= 2
                        continue

                    response.raise_for_status()
                    text = await response.text()
                    if not text:
                        return None
                    return json.loads(text)
            except aiohttp.ClientError:
                if attempt >= 2:
                    raise
                await asyncio.sleep(delay)
                delay *= 2

        raise RuntimeError(f"HyakAnime request failed for {method} {path}")
