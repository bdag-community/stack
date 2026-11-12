#!/usr/bin/env python3

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
import unittest.mock


OPS_DIR = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(OPS_DIR))

import automation_control  # noqa: E402


class AutomationControlTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.state_path = self.root / "automation-control.json"
        self.lock_path = self.root / "automation-control.lock"
        self.event_path = self.root / "automation-control-events.jsonl"
        self.now = datetime(2026, 5, 31, 21, 0, tzinfo=timezone.utc)

    def control_state(
        self,
        state: str,
        *,
        expires_at: datetime | None = None,
        allowed_mutations: list[str] | None = None,
    ) -> dict[str, object]:
        return {
            "schema_version": 1,
            "state": state,
            "owner": "operator",
            "owner_unit": "test",
            "pid": 123,
            "reason": "unit test",
            "correlation_id": "test",
            "created_at": self.now.isoformat(),
            "updated_at": self.now.isoformat(),
            "expires_at": expires_at.isoformat() if expires_at else None,
            "allowed_mutations": allowed_mutations or [],
            "suppressed_count": 0,
            "last_transition": {"from": "normal", "to": state, "at": self.now.isoformat(), "by": "test"},
        }

    def write_state(self, state: dict[str, object]) -> None:
        automation_control.write_control_state(
            state,
            state_path=self.state_path,
            lock_path=self.lock_path,
            now=self.now,
        )

    def check(
        self,
        action: str = automation_control.ACTION_ASIC_POOL_START,
        target: str = "asic-pool",
        actor: str = "watchdog",
    ):
        return automation_control.check_mutation_allowed(
            action,
            actor=actor,
            target=target,
            reason="test mutation",
            state_path=self.state_path,
            event_path=self.event_path,
            lock_path=self.lock_path,
            now=self.now,
        )

    def event_lines(self) -> list[dict[str, object]]:
        if not self.event_path.exists():
            return []
        return [json.loads(line) for line in self.event_path.read_text(encoding="utf-8").splitlines()]

    def test_missing_control_denies_high_risk_mutation_and_logs(self) -> None:
        decision = self.check()

        self.assertFalse(decision.allowed)
        self.assertEqual("missing", decision.control_status)
        events = self.event_lines()
        self.assertEqual(1, len(events))
        self.assertEqual("automation_control_denied", events[0]["event_type"])

    def test_corrupt_control_denies_high_risk_mutation_and_logs(self) -> None:
        self.state_path.write_text("{not-json", encoding="utf-8")

        decision = self.check()

        self.assertFalse(decision.allowed)
        self.assertEqual("corrupt", decision.control_status)
        self.assertEqual(1, len(self.event_lines()))

    def test_schema_invalid_control_denies_high_risk_mutation_and_logs(self) -> None:
        self.state_path.write_text(json.dumps({"schema_version": 1, "state": "normal"}), encoding="utf-8")

        decision = self.check()

        self.assertFalse(decision.allowed)
        self.assertEqual("schema_invalid", decision.control_status)
        self.assertEqual(1, len(self.event_lines()))

    def test_expired_control_denies_high_risk_mutation_and_logs(self) -> None:
        expired = self.control_state("normal", expires_at=self.now - timedelta(seconds=1))
        self.state_path.write_text(json.dumps(expired), encoding="utf-8")

        decision = self.check()

        self.assertFalse(decision.allowed)
        self.assertEqual("expired", decision.control_status)
        self.assertEqual(1, len(self.event_lines()))

    def test_repair_hold_controlled_stop_and_chain_incident_deny_high_risk_mutations(self) -> None:
        for state in ("repair_hold", "controlled_stop", "chain_incident"):
            with self.subTest(state=state):
                self.write_state(self.control_state(state))
                self.event_path.unlink(missing_ok=True)

                decision = self.check()

                self.assertFalse(decision.allowed)
                self.assertEqual(state, decision.control_state)
                self.assertIn("denies high-risk", decision.reason)
                self.assertEqual(1, len(self.event_lines()))

    def test_normal_control_allows_high_risk_mutation(self) -> None:
        self.write_state(self.control_state("normal"))

        decision = self.check()

        self.assertTrue(decision.allowed)
        self.assertEqual([], self.event_lines())

    def test_normal_control_denies_high_risk_mutation_from_non_controller_actor(self) -> None:
        self.write_state(self.control_state("normal"))

        sentinel = self.check(actor="sentinel")
        sampler = self.check(actor="status-sampler")
        watchdog_decision = self.check(actor="watchdog")

        self.assertFalse(sentinel.allowed)
        self.assertIn("high-risk mutation controller is watchdog", sentinel.reason)
        self.assertFalse(sampler.allowed)
        self.assertTrue(watchdog_decision.allowed)
        self.assertEqual(2, len(self.event_lines()))

    def test_normal_control_can_explicitly_delegate_high_risk_controller(self) -> None:
        state = self.control_state("normal")
        state["high_risk_controller"] = "watchdog,status-sampler"
        self.write_state(state)

        sampler = self.check(actor="status-sampler")
        sentinel = self.check(actor="sentinel")

        self.assertTrue(sampler.allowed)
        self.assertFalse(sentinel.allowed)

    def test_ensure_normal_control_state_creates_missing_control(self) -> None:
        created, previous_status, path = automation_control.ensure_normal_control_state(
            state_path=self.state_path,
            lock_path=self.lock_path,
            owner="unit-test",
            owner_unit="test_automation_control",
            reason="create missing default",
            correlation_id="test-create",
            now=self.now,
        )

        self.assertTrue(created)
        self.assertEqual("missing", previous_status)
        self.assertEqual(str(self.state_path), path)
        control, status, _reason = automation_control.read_control_state(
            state_path=self.state_path,
            now=self.now,
        )
        self.assertEqual("ok", status)
        self.assertIsNotNone(control)
        self.assertEqual("normal", control["state"])
        self.assertEqual("watchdog", control["high_risk_controller"])

    def test_check_cli_exits_zero_when_allowed_and_one_when_denied(self) -> None:
        self.write_state(self.control_state("normal"))

        allowed = subprocess.run(
            [
                sys.executable,
                str(OPS_DIR / "automation_control.py"),
                "check",
                "--state-path",
                str(self.state_path),
                "--event-path",
                str(self.event_path),
                "--lock-path",
                str(self.lock_path),
                "--action",
                automation_control.ACTION_ASIC_POOL_START,
                "--actor",
                "watchdog",
                "--target",
                "pool",
                "--reason",
                "unit test",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        denied = subprocess.run(
            [
                sys.executable,
                str(OPS_DIR / "automation_control.py"),
                "check",
                "--state-path",
                str(self.state_path),
                "--event-path",
                str(self.event_path),
                "--lock-path",
                str(self.lock_path),
                "--action",
                automation_control.ACTION_ASIC_POOL_START,
                "--actor",
                "sentinel",
                "--target",
                "pool",
                "--reason",
                "unit test",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(0, allowed.returncode, allowed.stderr)
        self.assertTrue(json.loads(allowed.stdout)["allowed"])
        self.assertEqual(1, denied.returncode, denied.stderr)
        denied_payload = json.loads(denied.stdout)
        self.assertFalse(denied_payload["allowed"])
        self.assertIn("observer-only", denied_payload["reason"])

    def test_set_state_cli_writes_chain_incident_hold(self) -> None:
        self.write_state(self.control_state("normal"))

        result = subprocess.run(
            [
                sys.executable,
                str(OPS_DIR / "automation_control.py"),
                "set-state",
                "--state",
                "chain_incident",
                "--state-path",
                str(self.state_path),
                "--event-path",
                str(self.event_path),
                "--lock-path",
                str(self.lock_path),
                "--owner",
                "unit-test",
                "--owner-unit",
                "test_automation_control",
                "--reason",
                "hold node until chain data provenance is repaired",
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual("chain_incident", payload["state"])
        decision = self.check(actor="watchdog")
        self.assertFalse(decision.allowed)
        self.assertEqual("chain_incident", decision.control_state)
        control, status, _reason = automation_control.read_control_state(
            state_path=self.state_path,
            now=self.now,
        )
        self.assertEqual("ok", status)
        self.assertEqual("watchdog", control["high_risk_controller"])
        events = self.event_lines()
        self.assertEqual("automation_control_state_changed", events[0]["event_type"])

    def test_ensure_normal_control_state_preserves_existing_hold(self) -> None:
        self.write_state(self.control_state("repair_hold"))

        created, previous_status, _path = automation_control.ensure_normal_control_state(
            state_path=self.state_path,
            lock_path=self.lock_path,
            owner="unit-test",
            owner_unit="test_automation_control",
            reason="must not overwrite hold",
            now=self.now,
        )

        self.assertFalse(created)
        self.assertEqual("ok", previous_status)
        control, status, _reason = automation_control.read_control_state(
            state_path=self.state_path,
            now=self.now,
        )
        self.assertEqual("ok", status)
        self.assertEqual("repair_hold", control["state"])

    def test_ensure_normal_control_state_leaves_corrupt_file_without_repair_flag(self) -> None:
        self.state_path.write_text("{not-json", encoding="utf-8")

        created, previous_status, _path = automation_control.ensure_normal_control_state(
            state_path=self.state_path,
            lock_path=self.lock_path,
            owner="unit-test",
            owner_unit="test_automation_control",
            reason="must not overwrite corrupt file by default",
            now=self.now,
        )

        self.assertFalse(created)
        self.assertEqual("corrupt", previous_status)
        self.assertEqual("{not-json", self.state_path.read_text(encoding="utf-8"))

    def test_transition_hold_requires_exact_allowlist_match(self) -> None:
        self.write_state(self.control_state("transition_hold"))

        denied = self.check()

        self.assertFalse(denied.allowed)
        self.write_state(self.control_state("transition_hold", allowed_mutations=["asic-pool"]))

        target_only = self.check()

        self.assertFalse(target_only.allowed)
        self.write_state(
            self.control_state(
                "transition_hold",
                allowed_mutations=[automation_control.ACTION_ASIC_POOL_START],
            )
        )

        action_only_with_target = self.check()

        self.assertFalse(action_only_with_target.allowed)
        self.write_state(
            self.control_state(
                "transition_hold",
                allowed_mutations=[f"{automation_control.ACTION_ASIC_POOL_START}:asic-pool"],
            )
        )

        allowed = self.check()

        self.assertTrue(allowed.allowed)

    def test_transition_hold_allows_target_wildcard_for_specific_action_only(self) -> None:
        self.write_state(
            self.control_state(
                "transition_hold",
                allowed_mutations=[f"{automation_control.ACTION_ASIC_MINER_OPEN_RESTART}:*"],
            )
        )

        allowed = self.check(
            automation_control.ACTION_ASIC_MINER_OPEN_RESTART,
            target="192.168.1.16",
        )
        broader_restart = self.check(
            automation_control.ACTION_ASIC_MINER_RESTART,
            target="192.168.1.16",
        )

        self.assertTrue(allowed.allowed)
        self.assertFalse(broader_restart.allowed)

    def patch_default_control_paths(self):
        return unittest.mock.patch.multiple(
            automation_control,
            DEFAULT_STATE_PATH=self.state_path,
            DEFAULT_LOCK_PATH=self.lock_path,
            DEFAULT_EVENT_PATH=self.event_path,
        )


if __name__ == "__main__":
    unittest.main()
