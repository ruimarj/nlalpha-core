"""Verify source contracts remain independent of optional data providers."""

import subprocess
import sys
import unittest


class MarketSourceIsolationTests(unittest.TestCase):
    def test_shared_contract_import_does_not_load_data_package(self):
        script = '''
import importlib.abc
import sys
class RejectData(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "nlalpha_data" or fullname.startswith("nlalpha_data."):
            raise AssertionError("optional data package imported")
sys.meta_path.insert(0, RejectData())
from nlalpha.core.contracts.market_source import BAR_CONTRACT, validate_request_description
assert BAR_CONTRACT.startswith(b"nlalpha.market.bar.v2")
assert validate_request_description({"price_adjustment": "unknown", "evidence": {"type": "unknown", "reference": "fixture"}})["price_adjustment"] == "unknown"
'''
        subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, text=True)
