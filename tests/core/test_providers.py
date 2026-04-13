"""Tests for provider loader helpers."""

from logging import Logger
from types import SimpleNamespace
from typing import cast

import pytest

import anibridge.app.core.providers as providers_module
from anibridge.app.exceptions import ProfileConfigError


class DummyConfig(SimpleNamespace):
    """Minimal config object exposing provider class overrides."""

    def __init__(self, provider_classes):
        super().__init__(provider_classes=provider_classes)


def test_collect_class_overrides_returns_empty_for_none() -> None:
    """No provider_classes should yield an empty override set."""
    config = DummyConfig(provider_classes=None)

    assert (
        providers_module._collect_class_overrides(
            cast("providers_module.AnibridgeConfig", config)
        )
        == set()
    )


def test_collect_class_overrides_returns_set_for_values() -> None:
    """Provider class overrides should be returned as a set."""
    config = DummyConfig(provider_classes=["pkg.a.A", "pkg.b.B"])

    assert providers_module._collect_class_overrides(
        cast("providers_module.AnibridgeConfig", config)
    ) == {"pkg.a.A", "pkg.b.B"}


def test_register_classes_skips_duplicates_and_blanks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only new, non-empty classes should be imported once."""
    calls: list[str] = []

    class FakeLibraryProvider:
        NAMESPACE = "fake"

    def fake_import(module: str) -> SimpleNamespace:
        calls.append(module)
        return SimpleNamespace(Provider=FakeLibraryProvider)

    monkeypatch.setattr(providers_module, "import_module", fake_import)
    monkeypatch.setattr(providers_module, "_LOADED_CLASSES", set())
    monkeypatch.setattr(providers_module, "LibraryProvider", object)
    monkeypatch.setattr(providers_module, "ListProvider", type("ListBase", (), {}))

    register_calls: list[type] = []

    class DummyRegistry:
        def register(self, provider_cls: type) -> None:
            register_calls.append(provider_cls)

    monkeypatch.setattr(providers_module, "library_registry", DummyRegistry())
    monkeypatch.setattr(providers_module, "list_registry", DummyRegistry())

    providers_module._register_classes(
        ["mod.a.Provider", "", "mod.a.Provider", "mod.b.Provider"]
    )

    assert calls == ["mod.a", "mod.b"]
    assert len(register_calls) == 2


def test_build_library_provider_raises_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing library providers should raise ProfileConfigError."""
    profile = SimpleNamespace(
        library_provider="missing",
        library_provider_config={},
        parent=DummyConfig(provider_classes=[]),
    )

    def fake_create(_namespace: str, logger: Logger, config=None):
        raise LookupError("missing")

    monkeypatch.setattr(providers_module.library_registry, "create", fake_create)

    with pytest.raises(ProfileConfigError):
        providers_module.build_library_provider(
            cast("providers_module.AnibridgeProfileConfig", profile)
        )


def test_build_list_provider_raises_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing list providers should raise ProfileConfigError."""
    profile = SimpleNamespace(
        list_provider="missing",
        list_provider_config={},
        parent=DummyConfig(provider_classes=[]),
    )

    def fake_create(_namespace: str, logger: Logger, config=None):
        raise LookupError("missing")

    monkeypatch.setattr(providers_module.list_registry, "create", fake_create)

    with pytest.raises(ProfileConfigError):
        providers_module.build_list_provider(
            cast("providers_module.AnibridgeProfileConfig", profile)
        )


@pytest.mark.parametrize(
    "class_path",
    ["missing-separator", "package.only."],
)
def test_register_classes_rejects_invalid_class_paths(class_path: str) -> None:
    """Malformed class paths should fail fast before import resolution."""
    with pytest.raises(ProfileConfigError, match="Invalid provider class path"):
        providers_module._register_classes([class_path])


def test_register_classes_wraps_import_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    """Import failures should be translated into ProfileConfigError."""
    monkeypatch.setattr(providers_module, "_LOADED_CLASSES", set())
    monkeypatch.setattr(
        providers_module,
        "import_module",
        lambda _module: (_ for _ in ()).throw(RuntimeError("boom")),
    )

    with pytest.raises(ProfileConfigError, match="Failed to import provider class"):
        providers_module._register_classes(["pkg.module.Provider"])


def test_register_classes_rejects_non_class_and_unknown_bases(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Resolved objects must be classes inheriting from a supported provider base."""
    monkeypatch.setattr(providers_module, "_LOADED_CLASSES", set())
    monkeypatch.setattr(
        providers_module,
        "import_module",
        lambda _module: SimpleNamespace(Provider="not-a-class"),
    )

    with pytest.raises(ProfileConfigError, match="does not resolve to a class"):
        providers_module._register_classes(["pkg.module.Provider"])

    class Other:
        pass

    monkeypatch.setattr(
        providers_module,
        "import_module",
        lambda _module: SimpleNamespace(Provider=Other),
    )
    monkeypatch.setattr(
        providers_module, "LibraryProvider", type("LibraryBase", (), {})
    )
    monkeypatch.setattr(providers_module, "ListProvider", type("ListBase", (), {}))

    with pytest.raises(ProfileConfigError, match="must inherit from"):
        providers_module._register_classes(["pkg.module.Provider"])


def test_ensure_default_provider_registers_hyakanime_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The HyakAnime namespace should map to the built-in provider class."""
    captured: list[str] = []

    monkeypatch.setattr(providers_module, "_LOADED_CLASSES", set())
    monkeypatch.setattr(
        providers_module,
        "_register_classes",
        lambda class_paths: captured.extend(class_paths),
    )

    providers_module._ensure_default_provider("hyakanime")

    assert captured == ["anibridge.providers.list.hyakanime.HyakAnimeListProvider"]
