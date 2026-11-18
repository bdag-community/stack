#!/usr/bin/env bash
# Import only a validated public address, never the private wallet file.
load_pool_wallet_address() {
  local file=${POOL_WALLET_PUBLIC_FILE:-} address configured requested
  [[ -z $file || ! -L $file ]] || { echo 'Pool public wallet address is symlinked' >&2; return 1; }
  if [[ -z $file || ! -e $file ]]; then
    [[ ${POOL_WALLET_PUBLIC_REQUIRED:-0} != 1 ]] || { echo 'Pool public wallet address is unavailable' >&2; return 1; }
    return 0
  fi
  [[ -f $file && ! -L $file ]] || { echo 'Pool public wallet address is invalid' >&2; return 1; }
  address=$(cat -- "$file")
  [[ $address =~ ^0x[[:xdigit:]]{40}$ && ${address,,} != 0x0000000000000000000000000000000000000000 ]] || { echo 'Pool public wallet address is invalid' >&2; return 1; }
  for configured in "${POOL_COINBASE_ADDRESS:-}" "${MINING_POOL_ADDRESS:-}" "${MINING_ADDRESS:-}"; do
    [[ -z $configured || ${configured,,} == ${address,,} ]] || { echo 'Configured address differs from the pool wallet' >&2; return 1; }
  done
  for configured in ${BDAG_NODE_MINING_ARGS:-}; do
    case "$configured" in
      --miningaddr=*) requested=${configured#*=}; [[ ${requested,,} == ${address,,} ]] || { echo 'Node mining argument differs from the pool wallet' >&2; return 1; } ;;
    esac
  done
  export POOL_COINBASE_ADDRESS="$address" MINING_POOL_ADDRESS="$address"
  export BDAG_POOL_REWARD_IPC_PATH="${BDAG_POOL_REWARD_IPC_PATH:-/var/lib/bdagStack/pool-reward/reward.sock}"
}
