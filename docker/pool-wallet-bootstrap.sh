#!/usr/bin/env bash
# Prepare the wallet once, validate it on every start, and expose only its address.
set -euo pipefail
umask 077
wallet_dir=${POOL_WALLET_DIR_IN_CONTAINER:-/var/lib/bdagStack/pool-wallet}
runtime_dir=${POOL_REWARD_RUNTIME_DIR_IN_CONTAINER:-/var/lib/bdagStack/pool-reward}
wallet_init=${POOL_WALLET_INIT_BINARY:-/usr/local/bin/pool-wallet-init}
payer=${POOL_PAYER_BINARY:-/usr/local/bin/pool-payer}
uid=${PUID:-1000}; gid=${PGID:-1000}
[[ $uid =~ ^[0-9]+$ && $gid =~ ^[0-9]+$ ]] || { echo 'Invalid pool wallet UID or GID' >&2; exit 1; }
if [[ ${1:-} != --as-user ]]; then
  for dir in "$wallet_dir" "$runtime_dir"; do
    [[ -d $dir && ! -L $dir ]] || { echo 'Pool wallet directory is unavailable or symlinked' >&2; exit 1; }
    owner=$(stat -c '%u' "$dir")
    if [[ $owner == 0 && ( $owner != "$uid" || $(stat -c '%a' "$dir") != 700 ) ]]; then
      [[ -z $(find "$dir" -mindepth 1 -maxdepth 1 -print -quit) ]] || { echo 'Refusing to change a nonempty root-owned directory' >&2; exit 1; }
      chown "$uid:$gid" "$dir"; chmod 700 "$dir"
    fi
    [[ $(stat -c '%u:%a' "$dir") == "$uid:700" ]] || { echo 'Pool wallet directory must be private and owned by the configured user' >&2; exit 1; }
  done
  if [[ $(id -u) == 0 ]]; then
    exec setpriv --reuid "$uid" --regid "$gid" --clear-groups -- "$0" --as-user
  fi
  [[ $(id -u) == "$uid" ]] || { echo 'Pool wallet owner differs from configured user' >&2; exit 1; }
fi
wallet_file="$wallet_dir/.env"; public_file="$runtime_dir/wallet-address"
if [[ ! -e $wallet_file && ! -L $wallet_file ]]; then
  [[ -z ${POOL_COINBASE_ADDRESS:-}${MINING_POOL_ADDRESS:-}${MINING_ADDRESS:-} ]] || { echo 'Existing pool address requires its matching private wallet' >&2; exit 1; }
  "$wallet_init" --env "$wallet_file" >/dev/null
fi
address=$(POOL_WALLET_ENV_FILE="$wallet_file" "$payer" --wallet-address)
[[ $address =~ ^0x[[:xdigit:]]{40}$ && ${address,,} != 0x0000000000000000000000000000000000000000 ]] || { echo 'Invalid generated pool wallet address' >&2; exit 1; }
for configured in "${POOL_COINBASE_ADDRESS:-}" "${MINING_POOL_ADDRESS:-}" "${MINING_ADDRESS:-}"; do
  [[ -z $configured || ${configured,,} == ${address,,} ]] || { echo 'Configured pool address differs from the private wallet' >&2; exit 1; }
done
if [[ -e $public_file || -L $public_file ]]; then
  [[ -f $public_file && ! -L $public_file && $(cat "$public_file") == "$address" ]] || { echo 'Existing public wallet address differs; refusing replacement' >&2; exit 1; }
else
  tmp=$(mktemp "$runtime_dir/.wallet-address.XXXXXXXX")
  trap 'rm -f -- "$tmp"' EXIT
  printf '%s\n' "$address" > "$tmp"
  chmod 600 "$tmp"
  ln "$tmp" "$public_file"
  rm -f -- "$tmp"
  trap - EXIT
fi
printf 'Pool wallet ready: %s\n' "$address"
