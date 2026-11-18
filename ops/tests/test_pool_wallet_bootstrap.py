from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BOOTSTRAP = ROOT / "docker" / "pool-wallet-bootstrap.sh"
ADDRESS = "0x1111111111111111111111111111111111111111"


class PoolWalletBootstrapTest(unittest.TestCase):
    def test_first_start_reuse_and_address_conflict(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            wallet, runtime = root / "wallet", root / "runtime"
            wallet.mkdir(mode=0o700)
            runtime.mkdir(mode=0o700)
            initializer, payer = root / "initializer", root / "payer"
            initializer.write_text(
                "#!/usr/bin/env bash\nset -eu\nprintf 'POOL_COINBASE_ADDRESS=%s\\nMINING_POOL_ADDRESS=%s\\nPOOL_PRIVATE_KEY=private-test-key\\n' "
                f"'{ADDRESS}' '{ADDRESS}' > \"$2\"\nchmod 600 \"$2\"\n",
                encoding="utf-8",
            )
            payer.write_text(f"#!/usr/bin/env bash\ntest \"$1\" = --wallet-address\nprintf '%s\\n' '{ADDRESS}'\n", encoding="utf-8")
            initializer.chmod(0o700)
            payer.chmod(0o700)
            env = {
                "PATH": os.environ.get("PATH", ""),
                "PUID": str(os.getuid()),
                "PGID": str(os.getgid()),
                "POOL_WALLET_DIR_IN_CONTAINER": str(wallet),
                "POOL_REWARD_RUNTIME_DIR_IN_CONTAINER": str(runtime),
                "POOL_WALLET_INIT_BINARY": str(initializer),
                "POOL_PAYER_BINARY": str(payer),
            }
            def start(**extra: str) -> subprocess.CompletedProcess[str]:
                return subprocess.run(["bash", str(BOOTSTRAP)], env={**env, **extra}, capture_output=True, text=True, check=False)

            first = start()
            self.assertEqual(first.returncode, 0, first.stderr)
            private = wallet / ".env"
            original = private.read_bytes()
            self.assertEqual(private.stat().st_mode & 0o777, 0o600)
            self.assertEqual((runtime / "wallet-address").read_text(), ADDRESS + "\n")
            self.assertNotIn("private-test-key", first.stdout + first.stderr)
            self.assertEqual(start().returncode, 0)
            self.assertEqual(private.read_bytes(), original)
            conflict = start(POOL_COINBASE_ADDRESS="0x2222222222222222222222222222222222222222")
            self.assertNotEqual(conflict.returncode, 0)
            self.assertEqual(private.read_bytes(), original)
            self.assertEqual((runtime / "wallet-address").read_text(), ADDRESS + "\n")


if __name__ == "__main__":
    unittest.main()
