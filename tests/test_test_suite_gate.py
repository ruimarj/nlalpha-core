"""Verify the shared pytest gate rejects incomplete test execution."""

from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class TestSuiteGateTests(unittest.TestCase):
    def test_passes_run_and_skipped_xfailed_xpassed_runs_fail_the_gate(self):
        plugin = Path(__file__).resolve().parents[2] / "scripts/nlalpha_pytest_gate.py"
        cases = {
            "passed": "def test_probe(): pass\n",
            "skipped": "import pytest\n@pytest.mark.skip(reason='unexpected skip')\ndef test_probe(): pass\n",
            "xfailed": "import pytest\n@pytest.mark.xfail(reason='unexpected xfail')\ndef test_probe(): assert False\n",
            "xpassed": "import pytest\n@pytest.mark.xfail(reason='unexpected xpass')\ndef test_probe(): pass\n",
        }
        for outcome, source in cases.items():
            with self.subTest(outcome=outcome), tempfile.TemporaryDirectory(prefix="nlalpha-pytest-gate-") as temporary:
                directory = Path(temporary)
                scripts = directory / "scripts"
                scripts.mkdir()
                (scripts / "nlalpha_pytest_gate.py").write_text(plugin.read_text())
                (directory / "test_probe.py").write_text(source)
                result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "scripts.nlalpha_pytest_gate"],
                                        cwd=directory, capture_output=True, text=True, timeout=30)
                self.assertEqual(result.returncode, 0 if outcome == "passed" else 1, result.stdout + result.stderr)
                if outcome != "passed":
                    self.assertIn("NLAlpha suite rejects", result.stdout)
