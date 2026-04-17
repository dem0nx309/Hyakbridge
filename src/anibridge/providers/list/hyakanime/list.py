"""HyakAnime list provider for AniBridge."""

import json
from collections.abc import Sequence
from datetime import datetime
from json import JSONDecodeError

from anibridge.list import (
    ListEntry,
    ListMedia,
    ListMediaType,
    ListProvider,
    ListStatus,
    ListTarget,
    ListUser,
)
from anibridge.utils.types import MappingDescriptor, ProviderLogger

from anibridge.app.core.anilist import AniListClient as PublicAniListClient
from anibridge.app.models.schemas.anilist import Media
from anibridge.providers.list.hyakanime.client import HyakAnimeClient
from anibridge.providers.list.hyakanime.config import HyakAnimeListProviderConfig
from anibridge.providers.list.hyakanime.models import (
    HyakAnimeAnime,
    HyakAnimeProgression,
)

__all__ = ["HyakAnimeListProvider"]

_HYAKANIME_TO_LIST_STATUS: dict[int, ListStatus] = {
    1: ListStatus.CURRENT,
    2: ListStatus.PLANNING,
    3: ListStatus.COMPLETED,
    4: ListStatus.PAUSED,
    5: ListStatus.DROPPED,
    6: ListStatus.REPEATING,
}
_LIST_STATUS_TO_HYAKANIME: dict[ListStatus, int] = {
    ListStatus.CURRENT: 1,
    ListStatus.PLANNING: 2,
    ListStatus.COMPLETED: 3,
    ListStatus.PAUSED: 4,
    ListStatus.DROPPED: 5,
    ListStatus.REPEATING: 6,
}


def _parse_datetime(value: datetime | str | None) -> datetime | None:
    """Parse a HyakAnime datetime value if one is present."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _score_to_hundred(value: float | None) -> int | None:
    """Convert a HyakAnime score to AniBridge's 0-100 scale."""
    if value is None:
        return None
    if value <= 10:
        return round(value * 10)
    if value <= 100:
        return round(value)
    return None


class HyakAnimeListMedia(ListMedia["HyakAnimeListProvider"]):
    """AniBridge media wrapper for HyakAnime anime resources."""

    def __init__(self, provider: HyakAnimeListProvider, anime: HyakAnimeAnime) -> None:
        """Initialize the HyakAnime media wrapper."""
        self._provider = provider
        self._anime = anime
        self._key = str(anime.id)
        self._title = anime.best_title()

    @property
    def labels(self) -> Sequence[str]:
        """Return display labels for the HyakAnime media."""
        labels: list[str] = []
        if self._anime.season:
            labels.append(self._anime.season)
        if self._anime.type:
            labels.append(self._anime.type)
        return labels

    @property
    def media_type(self) -> ListMediaType:
        """Return the AniBridge media type for the anime."""
        media_type = (self._anime.type or "").casefold()
        if media_type in {"movie", "film"}:
            return ListMediaType.MOVIE
        return ListMediaType.TV

    @property
    def poster_image(self) -> str | None:
        """Return the HyakAnime poster image URL if available."""
        return self._anime.image

    @property
    def total_units(self) -> int | None:
        """Return the number of episodes if known."""
        if self._anime.total_episodes:
            return self._anime.total_episodes
        if self.media_type is ListMediaType.MOVIE:
            return 1
        return None

    def provider(self) -> HyakAnimeListProvider:
        """Return the parent provider."""
        return self._provider


class HyakAnimeListEntry(ListEntry["HyakAnimeListProvider"]):
    """AniBridge list entry backed by HyakAnime progression data."""

    def __init__(
        self,
        provider: HyakAnimeListProvider,
        anime: HyakAnimeAnime,
        progression: HyakAnimeProgression | None = None,
    ) -> None:
        """Initialize the HyakAnime list entry."""
        self._provider = provider
        self._anime = anime
        self._media = HyakAnimeListMedia(provider, anime)
        self._progression = progression or HyakAnimeProgression(anime_id=anime.id)

        self._key = str(anime.id)
        self._title = anime.best_title()

        self._repeats = 0
        self._review = self._progression.comment
        self._user_rating = _score_to_hundred(self._progression.score)
        self._started_at = _parse_datetime(self._progression.start_date)
        self._finished_at = _parse_datetime(self._progression.end_date)

    @property
    def status(self) -> ListStatus | None:
        """Return the HyakAnime watch status as an AniBridge status."""
        if self._progression.status is None:
            return None
        return _HYAKANIME_TO_LIST_STATUS.get(self._progression.status)

    @status.setter
    def status(self, value: ListStatus | None) -> None:
        """Update the status stored on the entry."""
        if value is None:
            self._progression.status = None
            return
        self._progression.status = _LIST_STATUS_TO_HYAKANIME[value]

    @property
    def progress(self) -> int:
        """Return the number of watched episodes."""
        return self._progression.progression or 0

    @progress.setter
    def progress(self, value: int | None) -> None:
        """Update the watched episode count."""
        if value is None:
            self._progression.progression = None
            return
        if value < 0:
            raise ValueError("Progress cannot be negative.")
        self._progression.progression = value

    @property
    def repeats(self) -> int:
        """Return the repeat count if one is being tracked locally."""
        return self._repeats

    @repeats.setter
    def repeats(self, value: int | None) -> None:
        """Store the local repeat count."""
        if value is None:
            self._repeats = 0
            return
        if value < 0:
            raise ValueError("Repeat count cannot be negative.")
        self._repeats = value

    @property
    def review(self) -> str | None:
        """Return the stored review text."""
        return self._review

    @review.setter
    def review(self, value: str | None) -> None:
        """Store review text locally for compatibility."""
        self._review = value

    @property
    def user_rating(self) -> int | None:
        """Return the stored user rating on a 0-100 scale."""
        return self._user_rating

    @user_rating.setter
    def user_rating(self, value: int | None) -> None:
        """Store the user rating locally for compatibility."""
        if value is None:
            self._user_rating = None
            return
        if value < 0 or value > 100:
            raise ValueError("Ratings must be between 0 and 100.")
        self._user_rating = value

    @property
    def started_at(self) -> datetime | None:
        """Return the user start timestamp if available."""
        return self._started_at

    @started_at.setter
    def started_at(self, value: datetime | None) -> None:
        """Store the start timestamp locally for compatibility."""
        self._started_at = value

    @property
    def finished_at(self) -> datetime | None:
        """Return the user finish timestamp if available."""
        return self._finished_at

    @finished_at.setter
    def finished_at(self, value: datetime | None) -> None:
        """Store the finish timestamp locally for compatibility."""
        self._finished_at = value

    @property
    def total_units(self) -> int | None:
        """Return total units derived from the underlying media."""
        return self._media.total_units

    def media(self) -> HyakAnimeListMedia:
        """Return the media associated with the entry."""
        return self._media

    def provider(self) -> HyakAnimeListProvider:
        """Return the parent provider."""
        return self._provider


class HyakAnimeListProvider(ListProvider):
    """List provider backed by the HyakAnime API."""

    NAMESPACE = "hyakanime"
    MAPPING_PROVIDERS = frozenset({"hyakanime", "anilist"})

    def __init__(self, *, logger: ProviderLogger, config: dict | None = None) -> None:
        """Create the HyakAnime provider with the required token."""
        super().__init__(logger=logger, config=config)
        self.parsed_config = HyakAnimeListProviderConfig.model_validate(config or {})
        self._client = HyakAnimeClient(
            token=self.parsed_config.token,
            logger=self.log,
        )
        self._anilist_client = PublicAniListClient(anilist_token=None)
        self._resolved_anilist_keys: dict[int, str | None] = {}
        self._user: ListUser | None = None

    async def initialize(self) -> None:
        """Initialize the HyakAnime and public AniList clients."""
        self.log.debug("Initializing HyakAnime provider client")
        await self._client.initialize()
        await self._anilist_client.initialize()
        if self._client.user is None or self._client.user.uid is None:
            raise RuntimeError("HyakAnime provider initialized without a resolved user")
        self._user = ListUser(
            key=str(self._client.user.uid),
            title=self._client.user.username or str(self._client.user.uid),
        )

    async def backup_list(self) -> str:
        """Return a minimal JSON backup of HyakAnime progression entries."""
        entries = [
            item.progression.backup_payload()
            for item in await self._client.get_progressions()
            if item.progression.anime_id is not None
        ]
        return json.dumps(entries, separators=(",", ":"))

    async def delete_entry(self, key: str) -> None:
        """Delete a HyakAnime progression entry by anime id."""
        await self._client.delete_progression(int(key))
        self.log.debug("Deleted HyakAnime entry for anime id %s", key)

    async def get_entry(self, key: str) -> HyakAnimeListEntry | None:
        """Fetch a single HyakAnime entry by anime id."""
        anime = await self._client.get_anime(int(key))
        if anime is None:
            return None
        item = await self._client.get_progression(anime.id)
        progression = item.progression if item is not None else None
        return HyakAnimeListEntry(self, anime, progression)

    async def resolve_mapping_descriptors(
        self, descriptors: Sequence[MappingDescriptor]
    ) -> Sequence[ListTarget]:
        """Resolve direct HyakAnime ids and AniList-backed mappings."""
        targets: list[ListTarget] = []
        anilist_descriptors: list[MappingDescriptor] = []

        for provider, entry_id, scope in descriptors:
            if not entry_id:
                continue
            if provider == self.NAMESPACE:
                targets.append(
                    ListTarget(
                        descriptor=(provider, entry_id, scope),
                        media_key=entry_id,
                    )
                )
                continue
            if provider == "anilist":
                anilist_descriptors.append((provider, entry_id, scope))

        if not anilist_descriptors:
            return targets

        medias = await self._anilist_client.batch_get_anime(
            [int(entry_id) for _, entry_id, _ in anilist_descriptors]
        )
        media_by_id = {media.id: media for media in medias}

        for provider, entry_id, scope in anilist_descriptors:
            media = media_by_id.get(int(entry_id))
            if media is None:
                continue
            media_key = await self._resolve_anilist_media_key(media)
            if media_key is None:
                continue
            targets.append(
                ListTarget(
                    descriptor=(provider, entry_id, scope),
                    media_key=media_key,
                )
            )

        return targets

    async def restore_list(self, backup: str) -> None:
        """Restore a backup created by backup_list()."""
        try:
            data = json.loads(backup)
        except JSONDecodeError:
            self.log.exception("Failed to decode HyakAnime backup JSON")
            raise

        if not isinstance(data, list):
            raise ValueError("HyakAnime backup payload must be a list")

        for item in data:
            anime_id = int(item["id"])
            progression = max(int(item.get("progression") or 0), 0)
            status = item.get("status")
            if status is None:
                status = 1 if progression > 0 else 2
            await self._client.write_progression(
                anime_id=anime_id,
                progression=progression,
                status=int(status),
            )

    async def search(self, query: str) -> Sequence[HyakAnimeListEntry]:
        """Search HyakAnime and return wrapped list entries."""
        results = await self._client.search_anime(query)
        entries: list[HyakAnimeListEntry] = []
        for anime in results:
            item = await self._client.get_progression(anime.id)
            progression = item.progression if item is not None else None
            entries.append(HyakAnimeListEntry(self, anime, progression))
        return entries

    async def update_entry(self, key: str, entry: ListEntry) -> ListEntry | None:
        """Persist status and progress to HyakAnime."""
        current_entry = await self.get_entry(key)
        if current_entry is None:
            return None

        progress = max(int(entry.progress or 0), 0)
        total_units = getattr(entry, "total_units", None)
        if (
            entry.status is ListStatus.COMPLETED
            and total_units
            and progress < total_units
        ):
            progress = total_units

        entry_status = entry.status
        status = (
            _LIST_STATUS_TO_HYAKANIME[entry_status]
            if entry_status is not None
            else None
        )
        if status is None:
            status = current_entry._progression.status
        if status is None:
            status = 1 if progress > 0 else 2

        await self._client.write_progression(
            anime_id=int(key),
            progression=progress,
            status=status,
        )
        self.log.debug(
            "Updated HyakAnime entry for anime id %s with status=%s progress=%s",
            key,
            status,
            progress,
        )
        return await self.get_entry(key)

    def user(self) -> ListUser | None:
        """Return the authenticated HyakAnime user."""
        return self._user

    async def clear_cache(self) -> None:
        """Clear both HyakAnime and AniList resolution caches."""
        self._client.clear_cache()
        self._resolved_anilist_keys.clear()
        self._anilist_client.offline_anilist_entries.clear()

    async def close(self) -> None:
        """Close underlying client sessions."""
        await self._client.close()
        await self._anilist_client.close()

    async def _resolve_anilist_media_key(self, media: Media) -> str | None:
        """Resolve an AniList media object into a HyakAnime media key."""
        cached = self._resolved_anilist_keys.get(media.id)
        if media.id in self._resolved_anilist_keys:
            return cached

        result = await self._client.resolve_anilist_media(media)
        if result is not None:
            resolved = str(result.id)
            self._resolved_anilist_keys[media.id] = resolved
            return resolved

        self._resolved_anilist_keys[media.id] = None
        return None
