#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPOS_DIR="${REPOS_DIR:-$(cd "$ROOT/.." && pwd)}"
TEST_STACK="${TEST_STACK:-$REPOS_DIR/test-stack}"
TARGET="${TARGET:-linux-amd64}"
GOOS="${GOOS:-linux}"
CGO_ENABLED="${CGO_ENABLED:-1}"
ALL_OUTPUTS=(blockdag-node nodeworker mining-pool poolworker pool-payer pool-wallet-init pool-schema-init dashboard-api dashboard node-dashboard)
VERIFY_OUTPUTS=()

usage() {
  cat <<'EOF'
usage: scripts/rebuild-test-stack-artifacts.sh [all|node|pool|dashboard|BIN...]

Builds local upstream clones into test-stack so local release packaging can pick
up fresh artifacts after source changes.

Components:
  node        builds blockdag-node and nodeworker from ../blockdag-corechain Makefile
  pool        builds mining-pool, poolworker and dashboard-api from ../pool
  dashboard   builds dashboard from ../redis-dash and node-dashboard from ../node-dashboard
  node-dashboard builds only node-dashboard from ../node-dashboard
  all         runs node, pool, and dashboard

Useful overrides:
  REPOS_DIR=/home/ben/repos
  TEST_STACK=/home/ben/repos/test-stack
  GOARCH=amd64|arm64
  CC=gcc|aarch64-linux-gnu-gcc
EOF
}

case "$TARGET" in
  linux-amd64)
    GOARCH="${GOARCH:-amd64}"
    CC="${CC:-gcc}"
    ;;
  linux-arm64)
    GOARCH="${GOARCH:-arm64}"
    CC="${CC:-aarch64-linux-gnu-gcc}"
    ;;
  *)
    echo "unsupported TARGET=$TARGET" >&2
    exit 2
    ;;
esac

need_dir() {
  local dir="$1"
  [[ -d "$dir" ]] || { echo "missing directory: $dir" >&2; exit 1; }
}

need_file() {
  local file="$1"
  [[ -f "$file" ]] || { echo "missing file: $file" >&2; exit 1; }
}

go_common_env() {
  env \
    GOOS="$GOOS" \
    GOARCH="$GOARCH" \
    CGO_ENABLED="$CGO_ENABLED" \
    CC="$CC" \
    GOFLAGS=-buildvcs=false \
    "$@"
}

mark_output() {
  local output="$1"
  local existing
  for existing in "${VERIFY_OUTPUTS[@]}"; do
    [[ "$existing" == "$output" ]] && return
  done
  VERIFY_OUTPUTS+=("$output")
}

build_node() {
  local src="$REPOS_DIR/blockdag-corechain"
  need_file "$src/Makefile"
  need_file "$src/cmd/bdag/bdag.go"
  need_file "$src/cmd/nodeworker/main.go"
  mkdir -p "$TEST_STACK/bin"
  (
    cd "$src"
    env GOOS="$GOOS" GOARCH="$GOARCH" CGO_ENABLED="$CGO_ENABLED" CC="$CC" GOFLAGS=-buildvcs=false \
      make bdag nodeworker
    cp -f "$src/build/bin/bdag" "$TEST_STACK/bin/blockdag-node"
    cp -f "$src/build/bin/nodeworker" "$TEST_STACK/bin/nodeworker"
  )
}

build_pool() {
  local src="$REPOS_DIR/pool"
  need_file "$src/cmd/pool/main.go"
  need_file "$src/cmd/poolworker/main.go"
  need_file "$src/cmd/pool-payer/main.go"
  need_file "$src/cmd/pool-wallet-init/main.go"
  need_file "$src/cmd/pool-schema-init/main.go"
  need_file "$src/cmd/dashboard-api/main.go"
  mkdir -p "$TEST_STACK/bin" "$src/build/bin"
  (
    cd "$src"
    go_common_env go build -buildvcs=false -trimpath -o "$src/build/bin/pool" ./cmd/pool
    go_common_env go build -buildvcs=false -trimpath -o "$src/build/bin/dashboard-api" ./cmd/dashboard-api
    for command in pool-payer pool-wallet-init pool-schema-init; do
      go_common_env go build -buildvcs=false -trimpath -o "$src/build/bin/$command" "./cmd/$command"
      cp -f "$src/build/bin/$command" "$TEST_STACK/bin/$command"
    done
    # poolworker is pure stdlib; build it without cgo so it stays static. Invoke
    # env directly rather than prefixing go_common_env — an assignment in front
    # of a function call leaks into the caller's scope in bash.
    env GOOS="$GOOS" GOARCH="$GOARCH" CGO_ENABLED=0 GOFLAGS=-buildvcs=false \
      go build -trimpath -o "$src/build/bin/poolworker" ./cmd/poolworker
    cp -f "$src/build/bin/pool" "$TEST_STACK/bin/mining-pool"
    cp -f "$src/build/bin/dashboard-api" "$TEST_STACK/bin/dashboard-api"
    cp -f "$src/build/bin/poolworker" "$TEST_STACK/bin/poolworker"
  )
}

build_dashboard() {
  local src="$REPOS_DIR/redis-dash"
  need_file "$src/main.go"
  mkdir -p "$TEST_STACK/bin"
  (
    cd "$src"
    env GOOS="$GOOS" GOARCH="$GOARCH" CGO_ENABLED=0 GOFLAGS=-buildvcs=false \
      go build -trimpath -o "$TEST_STACK/bin/dashboard" .
  )
}

build_node_dashboard() {
  local src="$REPOS_DIR/node-dashboard"
  need_file "$src/main.go"
  mkdir -p "$TEST_STACK/bin"
  (
    cd "$src"
    env GOOS="$GOOS" GOARCH="$GOARCH" CGO_ENABLED=0 GOFLAGS=-buildvcs=false \
      go build -trimpath -o "$TEST_STACK/bin/node-dashboard" .
  )
}

verify_outputs() {
  local output
  local paths=()
  local checksum_paths=()

  for output in "${VERIFY_OUTPUTS[@]}"; do
    need_file "$TEST_STACK/bin/$output"
    paths+=("$TEST_STACK/bin/$output")
  done

  chmod +x "${paths[@]}"
  if [[ -x "$ROOT/scripts/verify-release-architecture.py" ]]; then
    "$ROOT/scripts/verify-release-architecture.py" --target "$TARGET" "${paths[@]}"
  fi

  for output in "${ALL_OUTPUTS[@]}"; do
    [[ -f "$TEST_STACK/bin/$output" ]] && checksum_paths+=("$TEST_STACK/bin/$output")
  done
  sha256sum "${checksum_paths[@]}" > "$TEST_STACK/checksums.txt"
}

run_component() {
  case "$1" in
    node|blockdag-node|nodeworker)
      build_node
      mark_output blockdag-node
      mark_output nodeworker
      ;;
    pool|mining-pool|poolworker|pool-payer|pool-wallet-init|pool-schema-init|dashboard-api)
      build_pool
      mark_output mining-pool
      mark_output poolworker
      mark_output pool-payer
      mark_output pool-wallet-init
      mark_output pool-schema-init
      mark_output dashboard-api
      ;;
    dashboard)
      build_dashboard
      build_node_dashboard
      mark_output dashboard
      mark_output node-dashboard
      ;;
    node-dashboard)
      build_node_dashboard
      mark_output node-dashboard
      ;;
    all)
      build_node
      build_pool
      build_dashboard
      build_node_dashboard
      mark_output blockdag-node
      mark_output nodeworker
      mark_output mining-pool
      mark_output poolworker
      mark_output pool-payer
      mark_output pool-wallet-init
      mark_output pool-schema-init
      mark_output dashboard-api
      mark_output dashboard
      mark_output node-dashboard
      ;;
    -h|--help|help)
      usage
      exit 0
      ;;
    *)
      echo "unknown component: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
}

need_dir "$TEST_STACK"
mkdir -p "$TEST_STACK/bin"

if [[ $# -eq 0 ]]; then
  usage
  exit 2
fi

for component in "$@"; do
  run_component "$component"
done

verify_outputs
echo "updated test-stack artifacts in $TEST_STACK"
