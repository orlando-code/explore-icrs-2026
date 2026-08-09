"""Shared pytest fixtures for pipeline unit tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _clear_pipeline_caches():
    """Reset module-level caches between tests so fixtures stay isolated."""
    yield

    try:
        import src.sources.delegates as delegates_module

        delegates_module._ORGANISATION_OVERRIDE_CACHE = None
        delegates_module._COUNTRY_SUFFIXES = None
    except Exception:
        pass

    try:
        from src.registry.key_resolution import clear_registry_key_resolver_cache

        clear_registry_key_resolver_cache()
    except Exception:
        pass

    try:
        import src.geocoding.geocode as geocode_module

        geocode_module._DISPLAY_ALIASES_CACHE = None
    except Exception:
        pass

    try:
        import src.geocoding.affiliation_geocodes as affiliation_geocodes_module

        affiliation_geocodes_module._GEOCODE_OVERRIDES_CACHE = None
    except Exception:
        pass

    try:
        from src.geography.country_neighbors import load_country_neighbors
        from src.geography.country_continents import load_country_continents

        load_country_neighbors.cache_clear()
        load_country_continents.cache_clear()
    except Exception:
        pass


@pytest.fixture
def assert_eq():
    """Return a verbose equality checker used across pipeline unit tests."""

    def _assert_eq(actual, expected, *, context: str = ""):
        if actual == expected:
            return
        prefix = f"{context}: " if context else ""
        raise AssertionError(
            f"{prefix}expected {expected!r} ({type(expected).__name__}), "
            f"got {actual!r} ({type(actual).__name__})"
        )

    return _assert_eq


@pytest.fixture(scope="module")
def built_person_registry():
    """Built registry shared across tests in a module (expensive to rebuild)."""
    from src.registry.person_registry import build_person_registry

    return build_person_registry()
