"""Installed strategy-family identity, contract publication, and failure diagnostics."""

from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from nlalpha.core.capabilities import CapabilityEntry, CapabilityRegistry, FamilyContract
from nlalpha.core.errors import InvalidRequestError, NlAlphaError
from nlalpha.core.strategy.plugin import registry
from nlalpha.core.strategy.plugin.protocol import BaseStrategyFamilyPlugin
from nlalpha.core.strategy.plugin.registry import StrategyFamilyRegistry


def family_type(family="test", helper_name="mean"):
    """Create a concrete installed family with observable contract calls."""
    contract = FamilyContract(family, "Base", "module.Base", ["on_bar(self, bar)"], helpers=[
        CapabilityEntry(helper_name, "function", f"self.{helper_name}(values)", "Compute a mean.", "test"),
    ])
    return type("TestFamily", (BaseStrategyFamilyPlugin,), {
        "family": family, "plugin_name": f"{family}-plugin",
        "family_contract": Mock(return_value=contract), "confess": Mock(return_value="## Notes\nSource notes."),
    })


def point(name, plugin_type):
    """Create an installed entry point with distribution metadata."""
    return SimpleNamespace(name=name, value=f"{name}:Plugin", load=Mock(return_value=plugin_type),
                           dist=SimpleNamespace(metadata={"Name": f"dist-{name}"}, version="1.2.3"))


class StrategyFamilyRegistryTest(unittest.TestCase):
    def setUp(self):
        self.previous_records = StrategyFamilyRegistry._records
        self.previous_published = StrategyFamilyRegistry._published
        self.previous_helpers = CapabilityRegistry._FAMILY_HELPERS
        StrategyFamilyRegistry._records = None
        StrategyFamilyRegistry._published = {}
        CapabilityRegistry._FAMILY_HELPERS = {}

    def tearDown(self):
        StrategyFamilyRegistry.clear()
        StrategyFamilyRegistry._records = self.previous_records
        StrategyFamilyRegistry._published = self.previous_published
        CapabilityRegistry._FAMILY_HELPERS = self.previous_helpers

    def inventory(self, points):
        """Scope the installed family inventory to one test."""
        return patch.object(registry, "entry_points", return_value=SimpleNamespace(select=Mock(return_value=points)))

    def test_discovery_is_cached_once_across_threads_and_contract_is_the_publication_source(self):
        plugin = family_type()
        entry = point("test", plugin)
        with self.inventory([entry]) as inventory:
            with ThreadPoolExecutor(max_workers=8) as workers:
                records = list(workers.map(lambda _: StrategyFamilyRegistry.get_record("test"), range(24)))
            self.assertTrue(all(record is records[0] for record in records))
            record = records[0]
            self.assertIs(record.contract, plugin.family_contract.return_value)
            self.assertEqual((record.package, record.version), ("dist-test", "1.2.3"))
            self.assertEqual(CapabilityRegistry.family_names("test"), {"mean"})
            self.assertIs(CapabilityRegistry.get_family("test").helpers[0], record.contract.helpers[0])
            inventory.assert_called_once()
            entry.load.assert_called_once()
            plugin.family_contract.assert_called_once()
            plugin.confess.assert_called_once()

    def test_duplicate_family_invalidates_both_without_leaking_helpers(self):
        first, second = family_type("duplicate", "first"), family_type("duplicate", "second")
        with self.inventory([point("first", first), point("second", second), point("healthy", family_type("healthy"))]):
            self.assertEqual(StrategyFamilyRegistry.list_families(), ["healthy"])
            diagnostics = StrategyFamilyRegistry.diagnostics()
            self.assertEqual(len(diagnostics), 2)
            self.assertTrue(all(item["reason"] == "duplicate strategy family: duplicate" for item in diagnostics))
            self.assertIsNone(CapabilityRegistry.get_family("duplicate"))
            with self.assertRaises(NlAlphaError) as raised:
                StrategyFamilyRegistry.get_record("duplicate")
            self.assertNotIsInstance(raised.exception, InvalidRequestError)

    def test_optional_absence_is_normal_and_system_metadata_errors_remain_visible(self):
        with self.inventory([]), patch.object(registry.logger, "warning") as warning:
            self.assertEqual(StrategyFamilyRegistry.list_records(), [])
            self.assertEqual(StrategyFamilyRegistry.diagnostics(), [])
            warning.assert_not_called()
            with self.assertRaises(InvalidRequestError):
                StrategyFamilyRegistry.get_record("absent")
        StrategyFamilyRegistry.clear()
        with patch.object(registry, "entry_points", side_effect=OSError("system metadata unavailable")):
            with self.assertRaisesRegex(OSError, "system metadata unavailable"):
                StrategyFamilyRegistry.list_records()
            self.assertIsNone(StrategyFamilyRegistry._records)
        for metadata in ({}, {"Name": ""}, {"Name": " padded "}):
            entry = point("bad-dist", family_type())
            entry.dist.metadata = metadata
            with self.subTest(metadata=metadata), self.inventory([entry]):
                with self.assertRaises((KeyError, ValueError)):
                    StrategyFamilyRegistry.list_records()
                entry.load.assert_not_called()
                self.assertIsNone(StrategyFamilyRegistry._records)

    def test_installed_failures_retain_load_contract_confess_phase_and_internal_keyerror(self):
        for phase in ("load", "family_contract", "confess"):
            StrategyFamilyRegistry.clear()
            plugin = family_type("broken")
            entry = point("broken", plugin)
            target = entry.load if phase == "load" else getattr(plugin, phase)
            target.side_effect = KeyError("implementation bug")
            with self.subTest(phase=phase), self.inventory([entry]):
                self.assertEqual(StrategyFamilyRegistry.list_families(), [])
                diagnostic = StrategyFamilyRegistry.diagnostics()[0]
                self.assertIn(f"{phase}: KeyError", diagnostic["reason"])
                self.assertIsNone(CapabilityRegistry.get_family("broken"))
                with self.assertRaises(NlAlphaError) as raised:
                    StrategyFamilyRegistry.get_record("broken")
                self.assertNotIsInstance(raised.exception, InvalidRequestError)
                self.assertIn("implementation bug", str(raised.exception.details))

    def test_clear_only_removes_owned_publications_and_conflicts_are_diagnosed(self):
        foreign = CapabilityRegistry.register_family("foreign", [])
        with self.inventory([point("test", family_type())]):
            StrategyFamilyRegistry.get_record("test")
            replacement = CapabilityRegistry.register_family("test", [])
            StrategyFamilyRegistry.clear()
            self.assertIs(CapabilityRegistry.get_family("foreign"), foreign)
            self.assertIs(CapabilityRegistry.get_family("test"), replacement)
            self.assertEqual(StrategyFamilyRegistry.list_families(), [])
            self.assertIn("another publisher", StrategyFamilyRegistry.diagnostics()[0]["reason"])
            self.assertIs(CapabilityRegistry.get_family("test"), replacement)

    def test_publication_failure_rolls_back_only_this_discovery_attempt(self):
        original = CapabilityRegistry.register_family
        def publish(family, helpers):
            if family == "second":
                raise RuntimeError("publication failed")
            return original(family, helpers)
        foreign = original("foreign", [])
        with self.inventory([point("first", family_type("first")), point("second", family_type("second"))]):
            with patch.object(CapabilityRegistry, "register_family", side_effect=publish):
                with self.assertRaisesRegex(RuntimeError, "publication failed"):
                    StrategyFamilyRegistry.list_records()
        self.assertIsNone(CapabilityRegistry.get_family("first"))
        self.assertIsNone(CapabilityRegistry.get_family("second"))
        self.assertIs(CapabilityRegistry.get_family("foreign"), foreign)
        self.assertIsNone(StrategyFamilyRegistry._records)

    def test_inflight_family_lookup_survives_explicit_clear(self):
        with self.inventory([point("test", family_type())]):
            original = StrategyFamilyRegistry._discover

            def discover_then_clear():
                snapshot = original()
                StrategyFamilyRegistry.clear()
                return snapshot

            with patch.object(StrategyFamilyRegistry, "_discover", side_effect=discover_then_clear):
                self.assertEqual(StrategyFamilyRegistry.get_record("test").family, "test")
                self.assertEqual(StrategyFamilyRegistry.list_families(), ["test"])
                self.assertEqual(StrategyFamilyRegistry.list_records()[0]["family"], "test")
