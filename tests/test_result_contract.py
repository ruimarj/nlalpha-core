"""Tests for the canonical error builder and deterministic budget enforcer."""

from __future__ import annotations

import json
import os
import sysconfig
import tempfile
import types
import unittest
from nlalpha.core.data_artifacts import DataArtifactBackendError, DataArtifactNotFoundError

from nlalpha.core.errors import (
    DATA_ERROR,
    INFRASTRUCTURE_ERROR,
    INTERNAL_ERROR,
    STRATEGY_ERROR,
    AssumptionViolationError,
    DataError,
    NlAlphaError,
    StrategyRuntimeError,
)
from nlalpha.core.result_contract import (
    ERROR_BUDGET_BYTES,
    ERROR_DETAILS_BUDGET_BYTES,
    ERROR_MESSAGE_BUDGET_BYTES,
    ERROR_SUGGESTION_BUDGET_BYTES,
    ERROR_TRACEBACK_BUDGET_BYTES,
    ERROR_FIELD_ORDER,
    RESPONSE_BUDGET_BYTES,
    TRACEBACK_MAX_FRAMES,
    build_error,
    enforce_budget,
    failure_response,
    format_traceback_tail,
)


def _bytes(value: object) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _exception_with_frame(module_name: str, filename: str) -> BaseException:
    source = "import sys\ndef grab():\n    return sys._getframe(0)\n"
    namespace: dict[str, object] = {"__name__": module_name}
    exec(compile(source, filename, "exec"), namespace)
    frame = namespace["grab"]()  # type: ignore[operator]
    exc = RuntimeError("x")
    exc.__traceback__ = types.TracebackType(None, frame, frame.f_lasti, frame.f_lineno)
    return exc


class ErrorTypeMappingTests(unittest.TestCase):
    def test_core_exception_classes_map_to_canonical_codes(self):
        self.assertEqual(DataError("x").error_type, DATA_ERROR)
        self.assertEqual(DataArtifactNotFoundError("x").error_type, DATA_ERROR)
        self.assertEqual(DataArtifactBackendError("x").error_type, INFRASTRUCTURE_ERROR)
        self.assertEqual(StrategyRuntimeError("x").error_type, STRATEGY_ERROR)
        self.assertEqual(AssumptionViolationError("x").error_type, STRATEGY_ERROR)
        self.assertEqual(NlAlphaError("x").error_type, INTERNAL_ERROR)

    def test_builder_reads_code_via_getattr_and_falls_back(self):
        self.assertEqual(build_error(DataError("x"))["type"], DATA_ERROR)
        self.assertEqual(build_error(ValueError("x"))["type"], INTERNAL_ERROR)

        class Bogus(NlAlphaError):
            error_type = "not_a_canonical_code"

        self.assertEqual(build_error(Bogus("x"))["type"], INTERNAL_ERROR)


class ErrorBuilderTests(unittest.TestCase):
    def test_retryable_defaults_follow_error_type(self):
        self.assertFalse(build_error(DataError("x"))["retryable"])
        self.assertFalse(build_error(StrategyRuntimeError("x"))["retryable"])
        self.assertTrue(build_error(DataArtifactBackendError("x"))["retryable"])

    def test_exception_attribute_overrides_default_retryable(self):
        self.assertTrue(build_error(DataError("x", retryable=True))["retryable"])
        self.assertFalse(build_error(DataArtifactBackendError("x", retryable=False))["retryable"])

    def test_stage_from_argument_and_attribute(self):
        self.assertEqual(build_error(DataError("x"), stage="validate")["stage"], "validate")
        self.assertEqual(build_error(DataError("x", stage="load"))["stage"], "load")

    def test_unknown_stage_is_omitted(self):
        self.assertNotIn("stage", build_error(DataError("x"), stage="nonsense"))
        self.assertNotIn("stage", build_error(DataError("x")))

    def test_optional_attributes_are_extracted(self):
        exc = DataError("boom", suggestion="fix it", details={"line": 42})
        error = build_error(exc)
        self.assertEqual(error["suggestion"], "fix it")
        self.assertEqual(error["details"], {"line": 42})

    def test_message_uses_str_for_plain_exceptions(self):
        error = build_error(ValueError("plain message"))
        self.assertEqual(error["message"], "plain message")

    def test_field_order_matches_contract(self):
        try:
            raise DataError(
                "boom", suggestion="fix", details={"a": 1}, stage="run", retryable=False
            )
        except DataError as exc:
            error = build_error(exc)
        self.assertEqual(tuple(error), ERROR_FIELD_ORDER)

    def test_failure_response_envelope(self):
        response = failure_response(DataError("boom"), stage="request")
        self.assertEqual(response["status"], "failed")
        self.assertEqual(response["error"]["type"], DATA_ERROR)
        self.assertEqual(response["error"]["stage"], "request")


class ExplicitTracebackTailTests(unittest.TestCase):
    def test_explicit_attribute_is_used_and_round_trips(self):
        exc = NlAlphaError("boom", traceback_tail='  File "<strategy>", line 1\n')
        self.assertEqual(
            build_error(exc)["traceback_tail"], '  File "<strategy>", line 1\n'
        )

    def test_explicit_attribute_overrides_walker(self):
        try:
            raise DataError("boom", traceback_tail="explicit tail")
        except DataError as exc:
            error = build_error(exc)
        self.assertEqual(error["traceback_tail"], "explicit tail")

    def test_empty_explicit_attribute_falls_back_to_walker(self):
        try:
            raise DataError("boom", traceback_tail="")
        except DataError as exc:
            error = build_error(exc)
        self.assertIn("test_result_contract.py", error["traceback_tail"])

    def test_missing_attribute_uses_walker(self):
        try:
            raise DataError("boom")
        except DataError as exc:
            error = build_error(exc)
        self.assertIn("test_result_contract.py", error["traceback_tail"])

    def test_explicit_attribute_is_clipped_to_budget(self):
        exc = NlAlphaError(
            "boom", traceback_tail="T" * (ERROR_TRACEBACK_BUDGET_BYTES + 5000)
        )
        tail = build_error(exc)["traceback_tail"]
        self.assertLessEqual(len(tail.encode("utf-8")), ERROR_TRACEBACK_BUDGET_BYTES)


class TracebackTailTests(unittest.TestCase):
    def test_user_frames_kept_and_framework_frames_excluded(self):
        try:
            raise DataError("boom")
        except DataError as exc:
            tail = format_traceback_tail(exc)
        self.assertIsNotNone(tail)
        self.assertIn("test_result_contract.py", tail)
        self.assertNotIn("core/result_contract.py", tail)

    def test_framework_only_traceback_is_omitted(self):
        for module_name, filename in (
            ("nlalpha.core.fake", "/tmp/fake.py"),
            ("user_module", "/opt/venv/site-packages/thing.py"),
            ("another", os.path.join(sysconfig.get_paths()["stdlib"], "fake_stdlib.py")),
        ):
            with self.subTest(module=module_name):
                exc = _exception_with_frame(module_name, filename)
                self.assertIsNone(format_traceback_tail(exc))
                self.assertNotIn("traceback_tail", build_error(exc))

    def test_user_frame_survives_stdlib_callback(self):
        def _default_raises(obj: object) -> object:
            raise DataError("inner")

        try:
            json.dumps(object(), default=_default_raises)
        except DataError as exc:
            tail = format_traceback_tail(exc)
        self.assertIsNotNone(tail)
        self.assertIn("_default_raises", tail)
        self.assertNotIn("encoder.py", tail)

    def test_traceback_frame_count_is_capped(self):
        def _recurse(depth: int) -> int:
            if depth == 0:
                raise DataError("deep")
            return _recurse(depth - 1)

        try:
            _recurse(40)
        except DataError as exc:
            tail = format_traceback_tail(exc)
        self.assertIsNotNone(tail)
        self.assertLessEqual(tail.count('File "'), TRACEBACK_MAX_FRAMES)

    def test_traceback_bytes_are_capped(self):
        line = "raise DataError('x')  # " + "A" * 200_000
        source = f"from nlalpha.core.errors import DataError\ndef boom():\n    {line}\n"
        handle, path = tempfile.mkstemp(suffix=".py", text=False)
        try:
            os.write(handle, source.encode("utf-8"))
            os.close(handle)
            namespace: dict[str, object] = {"__name__": "user_long_source"}
            exec(compile(source, path, "exec"), namespace)
            namespace["boom"]()
        except DataError as exc:
            tail = format_traceback_tail(exc)
        finally:
            os.unlink(path)
        self.assertIsNotNone(tail)
        self.assertLessEqual(len(tail.encode("utf-8")), ERROR_TRACEBACK_BUDGET_BYTES)
        self.assertLess(len(tail), 100_000)

    def test_user_frame_only_in_cause_chain_is_kept(self):
        framework = _exception_with_frame("nlalpha.core.fake", "/tmp/fake_framework.py")
        cause = _exception_with_frame("user_module", "/tmp/user_cause.py")
        wrapper = StrategyRuntimeError("wrapped")
        wrapper.__traceback__ = framework.__traceback__
        wrapper.__cause__ = cause
        tail = format_traceback_tail(wrapper)
        self.assertIsNotNone(tail)
        self.assertIn("user_cause.py", tail)
        self.assertNotIn("fake_framework.py", tail)

    def test_framework_only_cause_chain_is_omitted(self):
        cause = _exception_with_frame("nlalpha.core.fake", "/tmp/fake_a.py")
        wrapper = _exception_with_frame("nlalpha.core.other", "/tmp/fake_b.py")
        wrapper.__cause__ = cause
        self.assertIsNone(format_traceback_tail(wrapper))
        self.assertNotIn("traceback_tail", build_error(wrapper))

    def test_cause_cycle_is_guarded(self):
        first = _exception_with_frame("user_module", "/tmp/cycle_first.py")
        second = _exception_with_frame("user_module", "/tmp/cycle_second.py")
        first.__cause__ = second
        second.__cause__ = first
        tail = format_traceback_tail(first)
        self.assertIsNotNone(tail)
        self.assertIn("cycle_first.py", tail)


class ErrorCapTests(unittest.TestCase):
    def test_message_capped_to_two_kib(self):
        error = build_error(DataError("M" * (ERROR_MESSAGE_BUDGET_BYTES + 5000)))
        self.assertLessEqual(len(error["message"].encode("utf-8")), ERROR_MESSAGE_BUDGET_BYTES)

    def test_suggestion_capped_to_one_kib(self):
        error = build_error(DataError("x", suggestion="S" * (ERROR_SUGGESTION_BUDGET_BYTES + 5000)))
        self.assertLessEqual(
            len(error["suggestion"].encode("utf-8")), ERROR_SUGGESTION_BUDGET_BYTES
        )

    def test_details_list_trimmed_with_count_marker(self):
        error = build_error(DataError("x", details={"items": list(range(25))}))
        self.assertEqual(len(error["details"]["items"]), 10)
        self.assertEqual(error["details"]["items_count"], 25)
        self.assertTrue(error["details"]["items_truncated"])

    def test_errors_list_uses_errors_total_marker(self):
        error = build_error(DataError("x", details={"errors": [{"msg": "x" * 1000}] * 20}))
        self.assertEqual(len(error["details"]["errors"]), 10)
        self.assertEqual(error["details"]["errors_total"], 20)
        self.assertTrue(error["details"]["errors_truncated"])
        for item in error["details"]["errors"]:
            self.assertLessEqual(_bytes(item), 512)

    def test_details_capped_to_eight_kib(self):
        details = {f"key_{index}": "V" * 400 for index in range(60)}
        error = build_error(DataError("x", details=details))
        self.assertLessEqual(_bytes(error["details"]), ERROR_DETAILS_BUDGET_BYTES)
        self.assertTrue(error["details"]["details_truncated"])

    def test_error_total_capped_to_sixteen_kib(self):
        details = {f"key_{index}": "V" * 400 for index in range(60)}
        error = build_error(DataError("M" * 6000, suggestion="S" * 5000, details=details))
        self.assertLessEqual(_bytes(error), ERROR_BUDGET_BYTES)


class BudgetEnforcerTests(unittest.TestCase):
    def test_payload_within_budget_is_unchanged(self):
        payload = {"error": {"type": INTERNAL_ERROR}, "metrics": {"a": 1}}
        self.assertEqual(enforce_budget(payload, priority=["metrics"], max_bytes=10_000), payload)

    def test_input_payload_is_not_mutated(self):
        payload = {"error": {}, "blob": "B" * 10_000}
        before = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        enforce_budget(payload, priority=["blob"], max_bytes=1000)
        self.assertEqual(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), before)

    def test_sections_drop_in_priority_order(self):
        payload = {
            "error": {"type": INTERNAL_ERROR, "message": "boom", "retryable": False},
            "a": "A" * 4000,
            "b": "B" * 4000,
        }
        result = enforce_budget(payload, priority=["a", "b"], max_bytes=5000)
        self.assertNotIn("a", result)
        self.assertIn("b", result)
        self.assertIn("error", result)

    def test_list_prefix_is_halved_with_markers(self):
        payload = {"error": {"type": INTERNAL_ERROR, "message": "b", "retryable": False}, "equity_curve": list(range(500))}
        result = enforce_budget(payload, priority=["equity_curve"], max_bytes=600)
        self.assertLess(len(result["equity_curve"]), 500)
        self.assertEqual(result["equity_curve_count"], 500)
        self.assertTrue(result["equity_curve_truncated"])
        self.assertLessEqual(_bytes(result), 600)

    def test_last_section_is_byte_cut_with_result_truncated(self):
        payload = {"error": {"type": INTERNAL_ERROR, "message": "b", "retryable": False}, "blob": "C" * 50_000}
        result = enforce_budget(payload, priority=[], max_bytes=4096)
        self.assertTrue(result["result_truncated"])
        self.assertIn("blob", result)
        self.assertLessEqual(_bytes(result), 4096)

    def test_error_is_never_shed(self):
        error = build_error(NlAlphaError("E" * 3000))
        payload = {"error": error, "blob": "D" * 20_000}
        result = enforce_budget(payload, priority=["error", "blob"], max_bytes=1024)
        self.assertEqual(result["error"], error)
        self.assertNotIn("blob", result)

    def test_shedding_is_deterministic(self):
        payload = {
            "error": {"type": INTERNAL_ERROR, "message": "b", "retryable": False},
            "a": "A" * 4000,
            "b": [1] * 400,
        }
        first = enforce_budget(payload, priority=["a", "b"], max_bytes=3000)
        second = enforce_budget(payload, priority=["a", "b"], max_bytes=3000)
        self.assertEqual(first, second)
        self.assertEqual(_bytes(first), _bytes(second))

    def test_default_budget_constant_is_256_kib(self):
        self.assertEqual(RESPONSE_BUDGET_BYTES, 256 * 1024)

    def test_existing_count_marker_is_not_overwritten(self):
        payload = {
            "error": {"type": INTERNAL_ERROR, "message": "b", "retryable": False},
            "equity_curve": list(range(500)),
            "equity_curve_count": 999,
        }
        result = enforce_budget(payload, priority=["equity_curve"], max_bytes=600)
        self.assertEqual(result["equity_curve_count"], 999)
        self.assertTrue(result["equity_curve_truncated"])
        self.assertLessEqual(_bytes(result), 600)


if __name__ == "__main__":
    unittest.main()
