#!/usr/bin/env python3
"""Verify Linux release binaries match the target architecture.

This uses ELF headers directly instead of the host `file` command and runs from
Linux build hosts.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import struct
import sys


TARGETS = {
    "linux-arm64": ("elf", 183),
    "linux-amd64": ("elf", 62),
}

ELF_MACHINES = {
    62: "amd64",
    183: "arm64",
}


def identify(path: Path) -> tuple[str, int, str]:
    with path.open("rb") as handle:
        data = handle.read(4096)
    if data.startswith(b"\x7fELF"):
        if len(data) < 20:
            raise ValueError("truncated ELF header")
        if data[4] != 2:
            raise ValueError("expected 64-bit ELF")
        endian = "<" if data[5] == 1 else ">" if data[5] == 2 else None
        if endian is None:
            raise ValueError("unknown ELF byte order")
        machine = struct.unpack(endian + "H", data[18:20])[0]
        return "elf", machine, ELF_MACHINES.get(machine, f"elf-machine-{machine}")

    raise ValueError("expected 64-bit Linux ELF executable")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", required=True, choices=sorted(TARGETS))
    parser.add_argument("binaries", nargs="+", type=Path)
    args = parser.parse_args()

    expected_format, expected_machine = TARGETS[args.target]
    ok = True
    for path in args.binaries:
        try:
            actual_format, actual_machine, actual_arch = identify(path)
        except Exception as exc:
            print(f"{path}: invalid executable: {exc}", file=sys.stderr)
            ok = False
            continue
        if actual_format != expected_format or actual_machine != expected_machine:
            print(
                f"{path}: expected {args.target}, got {actual_format}/{actual_arch}",
                file=sys.stderr,
            )
            ok = False
            continue
        print(f"{path}: ok {args.target}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
