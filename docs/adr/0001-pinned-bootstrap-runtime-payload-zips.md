# ADR 0001: Pinned Bootstrap Scripts And Runtime Payload Zips

Date: 2026-06-02

## Status

Accepted

## Context

The old normal pool release attached one primary `pool-stack-docker-<tag>.zip`
that behaved like a universal package while bundling Linux AMD64 service
binaries. ARM hosts had to rely on Docker `linux/amd64` emulation even when the
runtime should have been able to run native Linux ARM64 containers.

The release should have one supported distribution path: public release
payload zips consumed by the `bdagrig` CLI. Appliance-specific image/archive
builders are outside the repo's active release path.

## Decision

Normal pool releases publish runtime-architecture payload zips only:

- `pool-stack-docker-<tag>-linux-amd64.zip`.
- `pool-stack-docker-<tag>-linux-arm64.zip`.

Linux host CPU architecture decides the payload: AMD64 uses `linux-amd64`;
ARM64 uses `linux-arm64`. Non-Linux hosts are rejected by the CLI.

Each payload includes `release-payload.env`, and `bdagrig` writes
`DOCKER_PLATFORM` from that payload metadata when it applies the release.

## Consequences

CI must build and package both Linux runtime architectures and run
`scripts/verify-release-architecture.py --target linux-<arch>` before zipping
each payload.

Operators start with the public `bdagrig` CLI and still receive a pinned,
reproducible payload for the release tag.

ARM64 Docker hosts get native `linux/arm64` service binaries in the normal pool
release path without a separate appliance builder.
