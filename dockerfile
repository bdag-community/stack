# syntax=docker/dockerfile:1.7
# Pool release build (GITHUB `pool-v*` tarball, build context is repo root).
#
# Expects unpacked layout:
#
#   ./
#   ├── bin/blockdag-node, bin/nodeworker, bin/mining-pool, bin/dashboard-api, bin/dashboard
#   ├── docker/             (e.g. no-snapshot.marker; see SNAPSHOT_PATH)
#   ├── .env.example, docker-compose.yml, …
#
# Snapshot import is runtime-only via a read-only bind mount handled by
# docker/entrypoint-nodeworker.sh. Do not copy .bdsnap files into the image.

# ----------------------------------------------------------------------------
# Common base
# ----------------------------------------------------------------------------
FROM golang:1.26-bookworm AS base
RUN apt-get update && apt-get install -y --no-install-recommends \
    make git gcc g++ libc6-dev jq ca-certificates wget \
 && rm -rf /var/lib/apt/lists/*

# ----------------------------------------------------------------------------
# Node Build Stage (blockdag-corechain)
# ----------------------------------------------------------------------------
FROM base AS node-build
WORKDIR /src
COPY bin ./bin
RUN set -eu; mkdir -p /out; \
    test -f ./bin/blockdag-node || { echo 'ERROR: ./bin/blockdag-node missing'; exit 1; }; \
    test -f ./bin/nodeworker     || { echo 'ERROR: ./bin/nodeworker missing'; exit 1; }; \
    cp -f ./bin/blockdag-node /out/blockdag-node && \
    cp -f ./bin/nodeworker    /out/nodeworker && \
    chmod +x /out/blockdag-node /out/nodeworker

# ----------------------------------------------------------------------------
# Pool Build Stage (asic-pool) — binaries from tarball bin/
# ----------------------------------------------------------------------------
FROM base AS pool-build
WORKDIR /src
COPY bin ./bin
RUN set -eu; mkdir -p /out; \
    test -f ./bin/mining-pool    || { echo 'ERROR: ./bin/mining-pool missing'; exit 1; }; \
    test -f ./bin/poolworker     || { echo 'ERROR: ./bin/poolworker missing'; exit 1; }; \
    cp -f ./bin/mining-pool    /out/mining-pool && \
    cp -f ./bin/poolworker     /out/poolworker && \
    chmod +x /out/mining-pool /out/poolworker

# ----------------------------------------------------------------------------
# Dashboard Build Stage
# ----------------------------------------------------------------------------
FROM base AS dashboard-build
WORKDIR /src
COPY bin ./bin
ARG DASHBOARD_BINARY=dashboard
RUN set -eu; \
    case "$DASHBOARD_BINARY" in dashboard|node-dashboard) ;; *) echo "ERROR: unsupported DASHBOARD_BINARY=$DASHBOARD_BINARY"; exit 1 ;; esac; \
    mkdir -p /out; \
    test -f "./bin/$DASHBOARD_BINARY" || { echo "ERROR: ./bin/$DASHBOARD_BINARY missing"; exit 1; }; \
    cp -f "./bin/$DASHBOARD_BINARY" /out/dashboard && \
    chmod +x /out/dashboard

# ----------------------------------------------------------------------------
# Node Runtime Stage (with optional snapshot import)
# ----------------------------------------------------------------------------
FROM ubuntu:24.04 AS node

RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    ca-certificates tzdata curl zstd \
 && rm -rf /var/lib/apt/lists/*

RUN groupadd -r bdagStack && useradd -r -g bdagStack -d /var/lib/bdagStack -m bdagStack
RUN mkdir -p /etc/bdagStack /var/lib/bdagStack/node/mainnet /var/lib/bdagStack/nodeworker /var/log/bdagStack \
 && chown -R bdagStack:bdagStack /var/lib/bdagStack /var/log/bdagStack /etc/bdagStack

COPY --from=node-build /out/blockdag-node  /usr/local/bin/blockdag-node
COPY --from=node-build /out/nodeworker     /usr/local/bin/nodeworker
RUN chmod +x /usr/local/bin/blockdag-node /usr/local/bin/nodeworker

COPY docker/entrypoint-nodeworker.sh /usr/local/bin/docker-entrypoint-nodeworker.sh
RUN chmod +x /usr/local/bin/docker-entrypoint-nodeworker.sh

# Snapshot path is relative to build context (Compose sets this in .env for dev vs release).
ARG SNAPSHOT_PATH=docker/no-snapshot.marker
COPY ${SNAPSHOT_PATH} /tmp/snapshot-candidate.bdsnap

RUN set -eu; \
    if [ "$(stat -c%s /tmp/snapshot-candidate.bdsnap)" -ge 1024 ]; then \
      echo "Importing local snapshot ($(stat -c%s /tmp/snapshot-candidate.bdsnap) bytes)"; \
      /usr/local/bin/blockdag-node snap import \
        --datadir /var/lib/bdagStack/node/mainnet \
        --path /tmp/snapshot-candidate.bdsnap; \
      cp -f /tmp/snapshot-candidate.bdsnap /var/lib/bdagStack/node/mainnet/snapshot.bdsnap; \
      chown -R bdagStack:bdagStack /var/lib/bdagStack/node /var/log/bdagStack; \
      echo "Snapshot import finished"; \
    else \
      echo "No snapshot file (marker or tiny file); node will sync normally"; \
    fi; \
    rm -f /tmp/snapshot-candidate.bdsnap

WORKDIR /var/lib/bdagStack/node
EXPOSE 8150 38131 38132 18545 18546 6060
# Start as root so entrypoint can chown Docker volumes (often created as uid 0);
# nodeworker and blockdag-node run as bdagStack after that.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint-nodeworker.sh", \
    "/usr/local/bin/nodeworker", \
    "--node-binary=/usr/local/bin/blockdag-node", \
    "--node-args=--configfile /etc/bdagStack/node.conf", \
    "--rpc-url=ws://127.0.0.1:18546", \
    "--dag-rpc-url=http://127.0.0.1:38131", \
    "--persist-root=/var/lib/bdagStack/nodeworker", \
    "--health-min-peers=2", \
    "--rollout-window=30m"]

# ----------------------------------------------------------------------------
# Pool Runtime Stage
# ----------------------------------------------------------------------------
FROM ubuntu:24.04 AS pool
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    ca-certificates tzdata \
 && rm -rf /var/lib/apt/lists/*

RUN groupadd -r bdagStack && useradd -r -g bdagStack -d /var/lib/bdagStack -m bdagStack \
 && mkdir -p /etc/bdagStack /var/lib/bdagStack/pool /var/log/bdagStack \
 && chown -R bdagStack:bdagStack /var/lib/bdagStack /var/log/bdagStack /etc/bdagStack

COPY --from=pool-build /out/mining-pool    /usr/local/bin/mining-pool
COPY --from=pool-build /out/poolworker     /usr/local/bin/poolworker
RUN chmod +x /usr/local/bin/mining-pool /usr/local/bin/poolworker

# godotenv loads this path at runtime; tarball uses committed .env.example. Copy a
# local `.env` on the host only if you want non-default keys in-file.
COPY .env.example /var/lib/bdagStack/pool/.env
RUN chown bdagStack:bdagStack /var/lib/bdagStack/pool/.env

USER bdagStack
WORKDIR /var/lib/bdagStack/pool
EXPOSE 3334 8080
ENTRYPOINT ["/usr/local/bin/poolworker", "--pool-binary=/usr/local/bin/mining-pool"]

# ----------------------------------------------------------------------------
# Shared Ops Runtime Stage (Docker repair helpers)
# ----------------------------------------------------------------------------
# minerops reboots stalled ASICs over the LAN. It supervises nothing, so it needs
# no Docker CLI, no host uid and no bind mount of the stack directory: the image
# carries its own code and runs as its own unprivileged user.
FROM alpine:3.20 AS minerops

RUN apk add --no-cache \
    ca-certificates \
    python3 \
    tzdata \
 && adduser -S -D -H -u 10001 bdagops

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BDAG_PROJECT_ROOT=/opt/bdag \
    BDAG_RUNTIME_DIR=/var/lib/bdagStack/runtime

COPY ops /opt/bdag/ops
RUN mkdir -p /var/lib/bdagStack/runtime && chown -R bdagops /var/lib/bdagStack/runtime

USER bdagops
WORKDIR /opt/bdag
LABEL org.opencontainers.image.title="BlockDAG ASIC Fleet Operations"
ENTRYPOINT ["python3", "ops/minerops.py", "--loop"]

# ----------------------------------------------------------------------------
# Dashboard Runtime Stage (Go UI with private Redis live state)
# ----------------------------------------------------------------------------
FROM ubuntu:24.04 AS dashboard
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    ca-certificates tzdata curl redis-server redis-tools \
 && rm -rf /var/lib/apt/lists/*

COPY --from=dashboard-build /out/dashboard /usr/local/bin/dashboard
COPY docker/dashboard-redis.conf /etc/redis/redis.conf
RUN chmod +x /usr/local/bin/dashboard \
 && mkdir -p /run/dashboard-redis /var/lib/dashboard-redis /app/redis/functions \
 && chmod 700 /run/dashboard-redis /var/lib/dashboard-redis

ENV ADDR=0.0.0.0:8088 \
    BDAG_DASHBOARD_REDIS_ENABLED=1 \
    BDAG_DASHBOARD_REDIS_MANAGED=1 \
    BDAG_REDIS_SOCKET=/run/dashboard-redis/redis.sock \
    BDAG_REDIS_CONFIG=/etc/redis/redis.conf \
    BDAG_EVM_HTTP_URL=http://node:18545 \
    BDAG_EVM_WS_URL=ws://node:18546 \
    BDAG_POOL_METRICS_URL=http://pool:9090/metrics

EXPOSE 8088
ENTRYPOINT ["/usr/local/bin/dashboard"]
