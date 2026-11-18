#!/usr/bin/env bash
set -euo pipefail
umask 077
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
wallet_dir=${POOL_WALLET_DIR:-$root/pool-wallet}
runtime_dir=${POOL_REWARD_RUNTIME_DIR:-$root/pool-runtime}
env_path=${POOL_STACK_ENV:-$root/.env}
for path in "$wallet_dir" "$runtime_dir"; do
  [[ $path == /* && $path != *$'\n'* && $path != *' '* ]] || { echo 'Pool directories must be absolute and contain no spaces.' >&2; exit 1; }
  [[ ! -L $path ]] || { echo 'Pool directory must not be a symlink.' >&2; exit 1; }
  if [[ ! -e $path ]]; then mkdir -m 700 -- "$path"; fi
  [[ -d $path && $(stat -c '%u:%a' "$path") == "$(id -u):700" ]] || { echo 'Pool directories must be private and owned by the current user.' >&2; exit 1; }
done
[[ -x $root/bin/pool-wallet-init ]] || { echo 'Build or install bin/pool-wallet-init first.' >&2; exit 1; }
if [[ ! -e $wallet_dir/.env ]]; then "$root/bin/pool-wallet-init" --env "$wallet_dir/.env"; fi
[[ -f $wallet_dir/.env && ! -L $wallet_dir/.env && $(stat -c '%u:%a' "$wallet_dir/.env") == "$(id -u):600" ]] || { echo 'Pool wallet file must be private and owned by the current user.' >&2; exit 1; }
python3 - "$wallet_dir" "$runtime_dir" "$env_path" "$root/.env.example" <<'PY'
import os,pathlib,re,stat,sys,tempfile
wallet,runtime,env,example=map(pathlib.Path,sys.argv[1:])
lines=(wallet/'.env').read_text().splitlines()
entries={}
for line in lines:
 if not line or line.startswith('#'): continue
 key,sep,value=line.partition('=')
 if not sep or key in entries: raise SystemExit('Pool wallet file has invalid fields.')
 entries[key]=value
address=entries.get('POOL_COINBASE_ADDRESS','')
if not re.fullmatch(r'0x[0-9a-fA-F]{40}',address) or entries.get('MINING_POOL_ADDRESS','').lower()!=address.lower() or not re.fullmatch(r'(?:0x)?[0-9a-fA-F]{64}',entries.get('POOL_PRIVATE_KEY','')):
 raise SystemExit('Pool wallet file is incomplete.')
if env.is_symlink(): raise SystemExit('Stack environment must not be a symlink.')
source=env.read_text() if env.exists() else example.read_text()
updates={'POOL_COINBASE_ADDRESS':address,'MINING_POOL_ADDRESS':address,'POOL_WALLET_DIR':str(wallet),'POOL_REWARD_RUNTIME_DIR':str(runtime),'BDAG_POOL_REWARD_IPC_PATH':'/var/lib/bdagStack/pool-reward/reward.sock','PUID':str(os.getuid()),'PGID':str(os.getgid())}
out=[]; seen=set()
for line in source.splitlines():
 key,sep,value=line.partition('=')
 if sep and key in updates:
  if key in seen: raise SystemExit('Duplicate stack setting: '+key)
  seen.add(key)
  if key in ('POOL_COINBASE_ADDRESS','MINING_POOL_ADDRESS') and value.strip() and value.strip().lower()!=updates[key].lower():
   raise SystemExit('Existing pool address differs; preserve it until an authorized cutover.')
  out.append(key+'='+updates[key])
 else: out.append(line)
for key,value in updates.items():
 if key not in seen: out.append(key+'='+value)
fd,tmp=tempfile.mkstemp(prefix='.pool-env-',dir=env.parent)
try:
 os.fchmod(fd,0o600)
 with os.fdopen(fd,'w') as f:
  f.write('\n'.join(out)+'\n'); f.flush(); os.fsync(f.fileno())
 os.replace(tmp,env)
finally:
 if os.path.exists(tmp): os.unlink(tmp)
print('Pool wallet configured:',address)
PY
