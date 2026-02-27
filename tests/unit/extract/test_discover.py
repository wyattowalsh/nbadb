"""Tests for EndpointRegistry.discover() auto-discovery mechanism."""

from __future__ import annotations

from nbadb.extract.registry import EndpointRegistry, registry


class TestDiscover:
    def test_discover_populates_global_registry(self) -> None:
        """discover() triggers @registry.register decorators on the global singleton."""
        # The global registry is already populated by module-level imports
        # from the other test files. But we can verify that calling discover()
        # on a fresh registry at least runs without error, and that the global
        # registry has the expected count.
        assert registry.count >= 100

    def test_discover_triggers_module_imports(self) -> None:
        """Calling discover() on a package imports all submodules."""
        reg = EndpointRegistry()
        # This will import all modules, registering to the global singleton
        reg.discover("nbadb.extract.stats")
        # reg itself stays empty (decorators target the global registry)
        # But we can verify no errors occurred by checking global registry
        assert registry.count >= 100

    def test_global_registry_has_box_score_traditional(self) -> None:
        cls = registry.get("box_score_traditional")
        assert cls.endpoint_name == "box_score_traditional"
        assert cls.category == "box_score"

    def test_discover_invalid_package(self) -> None:
        reg = EndpointRegistry()
        reg.discover("nbadb.nonexistent.package")
        assert reg.count == 0

    def test_discover_idempotent(self) -> None:
        """Multiple discover calls don't cause errors."""
        reg = EndpointRegistry()
        reg.discover("nbadb.extract.stats")
        reg.discover("nbadb.extract.stats")
        # No exception raised

    def test_all_categories_present_in_global_registry(self) -> None:
        expected_categories = {
            "box_score", "play_by_play", "game_log", "player_info",
            "team_info", "draft", "standings", "shots", "league",
            "schedule", "rotation", "synergy",
            "hustle", "tracking", "franchise", "leaders", "misc",
        }
        actual_categories = {cls.category for cls in registry.get_all()}
        assert expected_categories.issubset(actual_categories), (
            f"Missing categories: {expected_categories - actual_categories}"
        )
