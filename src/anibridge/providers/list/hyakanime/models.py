"""HyakAnime API models."""

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

__all__ = [
    "HyakAnimeAnime",
    "HyakAnimeDate",
    "HyakAnimeProgression",
    "HyakAnimeProgressionItem",
    "HyakAnimeRefreshResponse",
]


class HyakAnimeBaseModel(BaseModel):
    """Base model for HyakAnime API payloads."""

    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class HyakAnimeDate(HyakAnimeBaseModel):
    """Date payload returned by HyakAnime."""

    day: int | None = None
    month: int | None = None
    year: int | None = None

    def to_datetime(self) -> datetime | None:
        """Convert the date payload to a timezone-aware datetime."""
        if self.year is None or self.month is None or self.day is None:
            return None
        try:
            return datetime(self.year, self.month, self.day, tzinfo=UTC)
        except ValueError:
            return None


class HyakAnimeAnime(HyakAnimeBaseModel):
    """Anime payload returned by HyakAnime."""

    id: int
    title: str | None = None
    alt: list[str] = Field(default_factory=list)
    image: str | None = None
    banner_url: str | None = Field(default=None, alias="bannerURL")
    type: str | None = None
    status: int | None = None
    title_en: str | None = Field(default=None, alias="titleEN")
    title_jp: str | None = Field(default=None, alias="titleJP")
    romaji: str | None = Field(default=None, alias="romanji")
    id_mal: int | None = Field(default=None, alias="idMAL")
    id_anilist: int | None = Field(default=None, alias="idAnilist")
    total_episodes: int | None = Field(default=None, alias="NbEpisodes")
    season: str | None = None
    start: HyakAnimeDate | None = None
    end: HyakAnimeDate | None = None

    @field_validator("alt", mode="before")
    @classmethod
    def _normalize_alt_titles(cls, value: object) -> list[str]:
        """Drop null or empty alternate titles from partial progression payloads."""
        if value is None:
            return []
        if not isinstance(value, list):
            return []
        return [
            item.strip() for item in value if isinstance(item, str) and item.strip()
        ]

    def best_title(self) -> str:
        """Return the preferred display title for the anime."""
        return self.title or self.title_en or self.romaji or self.title_jp or ""

    def titles(self) -> list[str]:
        """Return distinct candidate titles for search and display."""
        titles: list[str] = []
        for value in (
            self.title,
            self.title_en,
            self.romaji,
            self.title_jp,
            *self.alt,
        ):
            if not value:
                continue
            cleaned = value.strip()
            if cleaned and cleaned not in titles:
                titles.append(cleaned)
        return titles


class HyakAnimeProgression(HyakAnimeBaseModel):
    """User progression payload returned by HyakAnime."""

    anime_id: int | None = Field(default=None, alias="animeID")
    progression: int | None = None
    status: int | None = None
    score: float | None = None
    comment: str | None = None
    last_change: int | None = Field(default=None, alias="lastChange")
    start_date: datetime | str | None = Field(default=None, alias="startDate")
    end_date: datetime | str | None = Field(default=None, alias="endDate")

    def backup_payload(self) -> dict[str, int | None]:
        """Return the minimal payload needed to restore this progression."""
        return {
            "id": self.anime_id,
            "progression": self.progression,
            "status": self.status,
        }


class HyakAnimeProgressionItem(HyakAnimeBaseModel):
    """Joined progression and media payload returned by HyakAnime."""

    media: HyakAnimeAnime
    progression: HyakAnimeProgression


class HyakAnimeRefreshResponse(HyakAnimeBaseModel):
    """Authentication refresh payload returned by HyakAnime."""

    is_valid: bool = Field(default=False, alias="isValid")
    uid: str | None = None
    username: str | None = None
    token: str | None = None
    email: str | None = None
    is_premium: bool | None = Field(default=None, alias="isPremium")
    is_staff: bool | None = Field(default=None, alias="isStaff")
