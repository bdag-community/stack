#!/usr/bin/env python3
"""ASIC fleet operations: reboot miners that have stalled, and nothing else.

This is what remains of the watchdog once node and pool supervision moved
in-process (nodeworker and poolworker). Rebooting a miner is a LAN action over
HTTP, so this process needs no Docker socket, no host uid, and no bind mount of
the stack directory.

Safety
------
The watchdog refused to reboot a miner when the *pool* was unwell, on the
principle that you do not power-cycle an ASIC for a pool-wide fault. It read
that from `pool_health` keys such as `share_stall` and `duplicate_block_storm`,
which `collect_status()` derives by parsing `docker logs` of the pool container.

Without the Docker socket those keys are simply absent, which reads as False --
the guard would silently disarm and the fleet would be rebooted during a pool
outage. So the guard is rebuilt here on two footings that do not need Docker,
and both must hold before any miner is touched:

  1. The pool must say it is healthy, from its own /health/job-state endpoint.
     If the pool is unreachable or not `ok`, no miner is rebooted. Note this
     fails *safe*, where the log-derived guard failed *open*.

  2. A symptom shared by most of the fleet is a pool problem, not a miner
     problem. If more than `--max-affected-fraction` of managed ASICs are
     stalled at once, no miner is rebooted.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pool_ops  # noqa: E402
from incident_journal import append_incident  # noqa: E402

EFFICIENCY_EVENTS_FILE = pool_ops.LOG_DIR / "efficiency-events.jsonl"

ASIC_API_STALL_TEXT_FRAGMENTS = (
    "/mcb/cgminer",
    "/mcb/pools",
    "cgminer_devs",
    "cgminercmd=devs",
    "context deadline exceeded",
    "miner request failed",
    "timed out",
    "timeout",
    "http 500",
    "server error",
    "connection refused",
    "connection reset",
    "remote end closed",
)
ASIC_API_STALL_STATUSES = {
    "api-degraded",
    "api_degraded",
    "degraded",
    "down",
    "no-stratum",
    "no_stratum",
    "not-mining",
    "not_mining",
    "offline",
    "unknown",
}

DEFAULT_JOB_STATE_URL = os.environ.get("BDAG_POOL_JOB_STATE_URL", "http://127.0.0.1:9090/health/job-state")
DEFAULT_INTERVAL_SECONDS = int(os.environ.get("BDAG_MINEROPS_INTERVAL_SECONDS", "60"))
DEFAULT_RESTART_COOLDOWN = int(os.environ.get("BDAG_MINEROPS_RESTART_COOLDOWN_SECONDS", "600"))
DEFAULT_STALE_SECONDS = int(os.environ.get("BDAG_MINEROPS_STALL_SECONDS", "180"))
DEFAULT_MAX_AFFECTED_FRACTION = float(os.environ.get("BDAG_MINEROPS_MAX_AFFECTED_FRACTION", "0.5"))
DEFAULT_MIN_FLEET = int(os.environ.get("BDAG_MINEROPS_MIN_FLEET", "2"))
LOG_FILE = pool_ops.LOG_DIR / "minerops.log"


def log(message: str) -> None:
    print(f"[minerops] {message}", flush=True)
    pool_ops.append_log_line(LOG_FILE, message)


def int_or_none(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(float(value))
    except (TypeError, ValueError):
        return None


def miner_label(row: dict[str, Any]) -> str:
    name = str(row.get("display_name") or row.get("ip") or "miner")
    ip = str(row.get("ip") or "")
    return f"{name} {ip}" if ip and ip not in name else name


def ensure_efficiency_event_log() -> None:
    pool_ops.ensure_runtime()
    EFFICIENCY_EVENTS_FILE.touch(exist_ok=True)


def record_efficiency_event(event_type: str, severity: str, message: str, details: dict[str, Any] | None = None) -> None:
    try:
        ensure_efficiency_event_log()
        payload = {
            "generated_at": pool_ops.now_iso(),
            "event_type": event_type,
            "severity": severity,
            "message": message,
            "details": details or {},
        }
        with EFFICIENCY_EVENTS_FILE.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True, default=str) + "\n")
        append_incident(event_type, severity, "minerops", message, details or {})
    except Exception as exc:  # noqa: BLE001 - monitoring must never crash repair.
        try:
            log(f"failed to record efficiency event type={event_type}: {exc}")
        except Exception:
            pass


def is_primary_pool_identity(row: dict[str, Any], mining_address: str) -> bool:
    defaults = pool_ops.default_miner_pool_settings()
    expected_url = str(row.get("expected_pool_url") or row.get("configured_pool_url") or "")
    expected = str(
        row.get("expected_worker_user")
        or row.get("intended_wallet")
        or row.get("configured_pool_user")
        or row.get("active_pool_user")
        or ""
    ).lower()
    workers = [
        str(item).lower()
        for item in [
            *(row.get("workers", []) if isinstance(row.get("workers"), list) else []),
            row.get("intended_wallet"),
            row.get("configured_pool_user"),
            row.get("active_pool_user"),
        ]
        if item
    ]
    if expected_url == defaults["pool_url"] and (
        re.fullmatch(r"0x[a-f0-9]{40}", expected)
        or any(re.fullmatch(r"0x[a-f0-9]{40}", worker) for worker in workers)
    ):
        return True
    address = mining_address.lower()
    if address:
        return expected == address or address in workers
    return row.get("device_type") in {"asic", "stratum"} and row.get("display_name") != "Nestor"


def normalise_status_text(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "-")


def asic_api_stall_issue_text(row: dict[str, Any]) -> str:
    debug = row.get("debug") if isinstance(row.get("debug"), dict) else {}
    values: list[Any] = [
        row.get("issue"),
        row.get("debug_error"),
        row.get("api_error"),
        row.get("device_telemetry_errors"),
        row.get("telemetry_errors"),
        row.get("device_telemetry_status"),
        row.get("telemetry_status"),
        row.get("status"),
        row.get("health"),
        debug.get("error"),
        debug.get("debug_error"),
    ]
    return " ".join(str(value or "") for value in values).lower()


def asic_api_stall_evidence(row: dict[str, Any]) -> tuple[bool, str]:
    debug = row.get("debug") if isinstance(row.get("debug"), dict) else {}
    issue_text = asic_api_stall_issue_text(row)
    telemetry_status = normalise_status_text(
        row.get("device_telemetry_status") or row.get("telemetry_status") or ""
    )
    api_unavailable = debug.get("available") is False or bool(row.get("debug_error"))
    fragment_match = any(fragment in issue_text for fragment in ASIC_API_STALL_TEXT_FRAGMENTS)
    return bool(api_unavailable or telemetry_status == "degraded" or fragment_match), issue_text.strip()


def asic_has_recent_useful_work(row: dict[str, Any], max_age_seconds: int) -> bool:
    if row.get("ready") is True or row.get("pool_active") is True or row.get("work_pool_active") is True:
        return True
    status_text = normalise_status_text(row.get("status") or row.get("health") or row.get("lane_status") or "")
    if row.get("connected") is True and status_text in {"ok", "ready", "connected", "mining", "active"}:
        return True

    recent_age = None
    for key in ("last_share_age_seconds", "last_submit_age_seconds", "last_pool_seen_age_seconds"):
        value = int_or_none(row.get(key))
        if value is not None:
            recent_age = value if recent_age is None else min(recent_age, value)
    if recent_age is None or recent_age > max_age_seconds:
        return False

    for key in (
        "shares",
        "submits",
        "blocks_found",
        "device_accepted",
        "accepted",
        "accepted_shares",
    ):
        value = int_or_none(row.get(key))
        if value is not None and value > 0:
            return True
    return bool(row.get("connected")) and recent_age <= min(max_age_seconds, 60)


def fetch_pool_job_state(url: str, timeout: float = 5.0) -> dict[str, Any] | None:
    """Return the pool's own health snapshot, or None if it cannot be read."""
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - fixed localhost URL
            if response.status != 200:
                return None
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None


def pool_is_healthy(job_state: dict[str, Any] | None) -> tuple[bool, str]:
    """Whether the pool is well enough that a stalled miner is the miner's fault."""
    if job_state is None:
        return False, "pool health endpoint unreachable"
    status = str(job_state.get("status") or "")
    if status != "ok":
        return False, f"pool status={status or 'unknown'} reason={job_state.get('reason_code') or 'unknown'}"
    return True, "pool ok"


def managed_asic_rows(miner_health: dict[str, Any], mining_address: str) -> list[dict[str, Any]]:
    rows = []
    for row in miner_health.get("miners") or []:
        if not isinstance(row, dict) or not row.get("managed"):
            continue
        if row.get("device_type") != "asic":
            continue
        if not pool_ops.is_lan_ipv4(str(row.get("ip", ""))):
            continue
        if not is_primary_pool_identity(row, mining_address):
            continue
        rows.append(row)
    return rows


def stalled_rows(rows: list[dict[str, Any]], stale_seconds: int) -> list[dict[str, Any]]:
    """Rows whose own evidence says the miner has stopped doing useful work."""
    stalled = []
    for row in rows:
        if asic_has_recent_useful_work(row, stale_seconds):
            continue
        api_stall, _issue = asic_api_stall_evidence(row)
        status_text = normalise_status_text(row.get("status") or row.get("health") or "")
        if api_stall or status_text in ASIC_API_STALL_STATUSES:
            stalled.append(row)
    return stalled


def fleet_wide(stalled: int, managed: int, max_fraction: float, min_fleet: int) -> bool:
    """A symptom most of the fleet shares is not a per-miner fault.

    Below min_fleet there is no fleet to correlate against, so a single stalled
    miner out of one cannot be distinguished from a pool-wide fault. Treat that
    as fleet-wide and decline to act: a human should look.
    """
    if managed < min_fleet:
        return True
    return stalled > managed * max_fraction


def reboot(ip: str) -> tuple[bool, str]:
    """Reboot one miner, unauthenticated first, then with the admin password."""
    try:
        pool_ops.restart_miner_open(ip)
        return True, "open restart"
    except Exception as exc:  # noqa: BLE001 - a failed reboot must not stop the loop
        open_error = str(exc)

    password = pool_ops.read_miner_admin_password()
    if not password:
        return False, f"open restart failed ({open_error}); no admin password stored"
    try:
        pool_ops.restart_miner(ip, password)
        return True, "authenticated restart"
    except Exception as exc:  # noqa: BLE001
        return False, f"open restart failed ({open_error}); authenticated restart failed ({exc})"


def tick(args: argparse.Namespace, last_restart: dict[str, float]) -> None:
    job_state = fetch_pool_job_state(args.job_state_url)
    healthy, why = pool_is_healthy(job_state)

    miner_health = pool_ops.collect_miner_health()
    mining_address = str(os.environ.get("MINING_ADDRESS") or "")
    managed = managed_asic_rows(miner_health, mining_address)
    stalled = stalled_rows(managed, args.stall_seconds)

    if not stalled:
        log(f"{len(managed)} managed ASICs, none stalled ({why})")
        return

    labels = ", ".join(miner_label(row) for row in stalled)

    if not healthy:
        log(f"{len(stalled)}/{len(managed)} ASICs stalled but NOT rebooting: {why} ({labels})")
        return

    if fleet_wide(len(stalled), len(managed), args.max_affected_fraction, args.min_fleet):
        log(
            f"{len(stalled)}/{len(managed)} ASICs stalled at once: treating as a pool-wide "
            f"fault, not rebooting ({labels})"
        )
        record_efficiency_event(
            "minerops_fleet_wide_stall",
            "warning",
            f"{len(stalled)} of {len(managed)} ASICs stalled simultaneously; no reboot issued",
            {"miners": labels},
        )
        return

    now = time.time()
    for row in stalled:
        ip = str(row.get("ip", ""))
        since = now - last_restart.get(ip, 0.0)
        if since < args.restart_cooldown:
            log(f"{miner_label(row)} stalled, in cooldown ({int(args.restart_cooldown - since)}s left)")
            continue

        ok, detail = reboot(ip)
        last_restart[ip] = now
        if ok:
            log(f"rebooted {miner_label(row)}: {detail}")
            record_efficiency_event(
                "minerops_miner_restart", "warning", f"rebooted stalled ASIC {ip}", {"detail": detail}
            )
        else:
            log(f"failed to reboot {miner_label(row)}: {detail}")
            record_efficiency_event(
                "minerops_miner_restart_failed", "critical", f"could not reboot stalled ASIC {ip}", {"detail": detail}
            )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="BlockDAG ASIC fleet operations")
    parser.add_argument("--loop", action="store_true", help="run continuously")
    parser.add_argument("--once", action="store_true", help="run a single pass")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument("--job-state-url", default=DEFAULT_JOB_STATE_URL)
    parser.add_argument("--stall-seconds", type=int, default=DEFAULT_STALE_SECONDS)
    parser.add_argument("--restart-cooldown", type=int, default=DEFAULT_RESTART_COOLDOWN)
    parser.add_argument("--max-affected-fraction", type=float, default=DEFAULT_MAX_AFFECTED_FRACTION)
    parser.add_argument("--min-fleet", type=int, default=DEFAULT_MIN_FLEET)
    parser.add_argument("--dry-run", action="store_true", help="report decisions without rebooting")
    args = parser.parse_args(argv)

    if args.dry_run:
        global reboot  # noqa: PLW0603 - deliberate test/inspection hook

        def reboot(ip: str) -> tuple[bool, str]:  # type: ignore[misc]
            return True, f"dry-run: would reboot {ip}"

    last_restart: dict[str, float] = {}
    if not args.loop:
        tick(args, last_restart)
        return 0

    while True:
        try:
            tick(args, last_restart)
        except Exception as exc:  # noqa: BLE001 - monitoring must never crash the loop
            log(f"tick failed: {exc}")
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
