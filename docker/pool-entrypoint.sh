#!/usr/bin/env bash
set -euo pipefail
export POOL_WALLET_PUBLIC_REQUIRED=1
source "$(dirname -- "$0")/pool-wallet-address.sh"
load_pool_wallet_address
exec /usr/local/bin/poolworker --pool-binary=/usr/local/bin/mining-pool "$@"
