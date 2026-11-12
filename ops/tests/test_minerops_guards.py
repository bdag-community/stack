"""The guards that stop minerops power-cycling a fleet for a pool-wide fault.

The watchdog read `pool_health["share_stall"]` and friends, which collect_status()
derives from `docker logs` of the pool container. minerops has no Docker socket,
so those keys would simply be absent -- reading as False, silently disarming the
guard. These tests pin the replacement, which fails safe instead of open.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import minerops  # noqa: E402


class PoolHealthGate(unittest.TestCase):
    def test_unreachable_pool_blocks_reboots(self) -> None:
        healthy, why = minerops.pool_is_healthy(None)
        self.assertFalse(healthy, "an unreadable pool must never permit reboots")
        self.assertIn("unreachable", why)

    def test_unhealthy_pool_blocks_reboots(self) -> None:
        healthy, why = minerops.pool_is_healthy({"status": "degraded", "reason_code": "submit_stall"})
        self.assertFalse(healthy)
        self.assertIn("submit_stall", why)

    def test_healthy_pool_permits_reboots(self) -> None:
        healthy, _why = minerops.pool_is_healthy({"status": "ok", "reason_code": "ok"})
        self.assertTrue(healthy)

    def test_missing_status_is_not_healthy(self) -> None:
        # A payload shape we do not recognise must not read as healthy.
        healthy, _why = minerops.pool_is_healthy({})
        self.assertFalse(healthy)


class FleetWideGate(unittest.TestCase):
    def test_single_stalled_miner_in_a_healthy_fleet_is_actionable(self) -> None:
        self.assertFalse(minerops.fleet_wide(stalled=1, managed=4, max_fraction=0.5, min_fleet=2))

    def test_majority_stalled_is_treated_as_a_pool_fault(self) -> None:
        self.assertTrue(minerops.fleet_wide(stalled=3, managed=4, max_fraction=0.5, min_fleet=2))

    def test_exactly_half_stalled_is_actionable(self) -> None:
        # Strictly greater than the fraction, so half of a four-miner fleet still acts.
        self.assertFalse(minerops.fleet_wide(stalled=2, managed=4, max_fraction=0.5, min_fleet=2))

    def test_whole_fleet_stalled_never_acts(self) -> None:
        self.assertTrue(minerops.fleet_wide(stalled=4, managed=4, max_fraction=0.5, min_fleet=2))

    def test_fleet_too_small_to_correlate_never_acts(self) -> None:
        # With one miner there is no fleet to compare against: a stalled miner and
        # a pool-wide fault are indistinguishable, so a human should look.
        self.assertTrue(minerops.fleet_wide(stalled=1, managed=1, max_fraction=0.5, min_fleet=2))

    def test_no_managed_miners_never_acts(self) -> None:
        self.assertTrue(minerops.fleet_wide(stalled=0, managed=0, max_fraction=0.5, min_fleet=2))


class NoDockerDependency(unittest.TestCase):
    def test_minerops_never_shells_out_to_docker(self) -> None:
        source = Path(minerops.__file__).read_text(encoding="utf-8")
        # Only the module docstring may mention Docker, explaining why it is absent.
        body = source.split('"""', 2)[-1]
        self.assertNotIn('"docker"', body)
        self.assertNotIn("docker_logs", body)
        self.assertNotIn("docker_compose", body)


if __name__ == "__main__":
    unittest.main()
