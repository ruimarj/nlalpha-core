"""Exercise runtime symbol configuration and detached actual position snapshots."""

from __future__ import annotations

import unittest
from dataclasses import FrozenInstanceError, replace
from types import SimpleNamespace

from nlalpha.core.contracts.market import CancelOrder, Order, Position
from nlalpha.core.strategy.runtime.base import BaseEventDrivenStrategy


class StrategySnapshotTest(unittest.TestCase):
    def test_symbols_and_position_snapshots_cannot_change_engine_state(self) -> None:
        configured = ["A", "B"]
        strategy = BaseEventDrivenStrategy(configured)
        configured.append("C")
        self.assertEqual(strategy.symbols, ("A", "B"))
        with self.assertRaises(AttributeError):
            strategy.symbols = ("C",)

        source = Position(symbol="A", long_volume=3.0, long_avg_price=10.0)
        strategy._update_positions_snapshot({"A": source})
        source.long_volume = 99.0
        detached = strategy.position_for("A")
        detached.long_volume = 88.0
        snapshots = strategy.positions
        snapshots["A"].long_volume = 77.0
        with self.assertRaises(TypeError):
            snapshots["C"] = Position(symbol="C")
        self.assertEqual(strategy.position_for("A").net_volume, 3.0)
        self.assertEqual(strategy.position_for("B").net_volume, 0.0)

        strategy.buy(10.0, 5.0, "A")
        self.assertEqual(strategy.position_for("A").net_volume, 3.0)
        strategy._update_positions_snapshot({})
        self.assertEqual(strategy.position_for("A").net_volume, 0.0)
        self.assertEqual(snapshots["A"].long_volume, 77.0)

    def test_unknown_and_mismatched_position_symbols_are_rejected(self) -> None:
        strategy = BaseEventDrivenStrategy(["A"])
        with self.assertRaisesRegex(ValueError, "Unknown strategy symbol"):
            strategy.position_for("B")
        with self.assertRaisesRegex(ValueError, "Unknown strategy symbols"):
            strategy._update_positions_snapshot({"B": Position(symbol="B")})
        with self.assertRaisesRegex(ValueError, "must match"):
            strategy._update_positions_snapshot({"A": Position(symbol="B")})
        with self.assertRaisesRegex(ValueError, "unique"):
            strategy._set_symbols(("A", "A"))
        self.assertEqual(strategy.symbols, ("A",))

    def test_fifo_cancellation_waits_for_native_state_and_snapshots_are_immutable(self) -> None:
        strategy = BaseEventDrivenStrategy(["A"])
        order_id = strategy.buy(None, 5.0)
        queued = strategy.order_for(order_id)
        self.assertEqual((queued.symbol, queued.status, queued.filled_volume, queued.remaining_volume),
                         ("A", "queued", 0.0, 5.0))
        with self.assertRaises(FrozenInstanceError):
            queued.status = "filled"
        with self.assertRaises(TypeError):
            strategy.orders[order_id] = queued
        strategy.cancel_order(order_id)
        self.assertEqual(strategy.order_for(order_id).status, "queued")
        with self.assertRaisesRegex(ValueError, "already requested"):
            strategy.cancel_order(order_id)
        commands = strategy.collect_commands()
        self.assertIsInstance(commands[0], Order)
        self.assertEqual(commands[1], CancelOrder(order_id=order_id))
        self.assertEqual(strategy.collect_commands(), [])

        partial = replace(queued, status="partially_filled", filled_volume=2.0, remaining_volume=3.0,
                          avg_price=10.0, timestamp_ns=1_000_000_007)
        strategy._update_order_snapshot(partial)
        self.assertEqual(strategy.pending_orders[order_id], partial)
        self.assertEqual(queued.status, "queued")
        self.assertEqual(strategy.position_for("A").net_volume, 0.0)
        strategy._clear_cancel_request(order_id)
        strategy.cancel_order(order_id)
        self.assertEqual(strategy.collect_commands(), [CancelOrder(order_id=order_id)])
        canceled = replace(partial, status="canceled", timestamp_ns=1_000_000_011)
        strategy._update_order_snapshot(canceled)
        self.assertEqual(strategy.pending_orders, {})
        self.assertTrue(strategy.order_for(order_id).is_closed)
        with self.assertRaisesRegex(ValueError, "closed order"):
            strategy.cancel_order(order_id)
        with self.assertRaisesRegex(ValueError, "Unknown strategy order"):
            strategy._update_order_snapshot(replace(canceled, order_id="foreign"))
        with self.assertRaisesRegex(ValueError, "changed submission fields"):
            strategy._update_order_snapshot(replace(canceled, volume=6.0))
        with self.assertRaisesRegex(TypeError, "core OrderSnapshot"):
            strategy._update_order_snapshot(SimpleNamespace(order_id=order_id))

    def test_invalid_submissions_leave_no_commands_or_queued_state(self) -> None:
        strategy = BaseEventDrivenStrategy(["A", "B"])
        request = {"symbol": "A", "direction": "long", "offset": "open", "volume": 2.0}
        invalid_fields = [
            {"symbol": ""}, {"direction": "buy"}, {"offset": "entry"},
            {"volume": True}, {"volume": float("nan")}, {"price": float("inf")},
            {"order_type": "limit"}, {"order_type": "stop"},
            {"order_type": "stop_limit", "stop_price": 10.0},
            {"limit_price": 10.0}, {"stop_price": 10.0},
            {"order_type": "limit", "limit_price": False}, {"time_in_force": "unknown"},
        ]
        for changes in invalid_fields:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                strategy.submit_order(**(request | changes))
        self.assertEqual(strategy.orders, {})
        self.assertEqual(strategy.collect_commands(), [])
        order_id = strategy.submit_order(**(request | {"order_type": "stop_limit", "limit_price": 11.0,
                                                      "stop_price": 10.0, "time_in_force": "gtc"}))
        self.assertEqual(order_id, "o_1")
        self.assertEqual(strategy.order_for(order_id).stop_price, 10.0)


if __name__ == "__main__":
    unittest.main()
