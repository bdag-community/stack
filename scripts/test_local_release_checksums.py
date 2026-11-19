import hashlib
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
BINARIES = ("blockdag-node", "nodeworker", "mining-pool", "poolworker", "pool-payer",
            "pool-wallet-init", "pool-schema-init", "dashboard-api", "dashboard", "node-dashboard")


class LocalReleaseChecksumsTest(unittest.TestCase):
    def test_checksums_work_after_relocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source" / "bin"
            source.mkdir(parents=True)
            for name in BINARIES:
                (source / name).write_text("fixture " + name, encoding="utf-8")
            output = base / "output"
            env = {**os.environ, "PAYLOAD_SOURCE": str(source.parent),
                   "OUT_DIR": os.path.relpath(output, ROOT)}
            subprocess.run(["bash", "scripts/local-test-release.sh", "local-fixture"], cwd=ROOT,
                           env=env, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            archive = next(output.glob("*.zip"))
            digest, archive_name = (output / (archive.name + ".sha256")).read_text().split()
            self.assertEqual(archive_name, archive.name)
            self.assertEqual(digest, hashlib.sha256(archive.read_bytes()).hexdigest())
            with zipfile.ZipFile(archive) as z:
                root = archive.stem + "/"
                lines = z.read(root + "checksums.txt").decode().splitlines()
                self.assertEqual(len(lines), len(BINARIES))
                for line in lines:
                    expected, path = line.split(maxsplit=1)
                    self.assertTrue(path.startswith("bin/"), path)
                    self.assertEqual(expected, hashlib.sha256(z.read(root + path)).hexdigest())


if __name__ == "__main__":
    unittest.main()
