import os
from pathlib import Path
import stat
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[2] / 'scripts' / 'init-pool-postgres.sh'

class InitPoolPostgresSecretsTest(unittest.TestCase):
    def test_placeholder_rotation_does_not_leave_readable_backup(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            envfile = root / 'pool.env'
            envfile.write_text('POSTGRES_PASSWORD=change_me_to_a_strong_secret\nNODE_RPC_PASS=test-secret-sentinel\n')
            envfile.chmod(0o644)
            schema = root / 'schema.sql'
            schema.write_text('SELECT 1;\n')
            docker = root / 'docker'
            docker.write_text('#!/bin/sh\nif [ "$2" = ps ]; then echo postgres; else cat >/dev/null; fi\n')
            docker.chmod(0o700)
            env = dict(os.environ, ENV_FILE=str(envfile), SCHEMA_FILE=str(schema), PATH=str(root) + ':' + os.environ['PATH'])
            result = subprocess.run(['bash', str(SCRIPT)], env=env, text=True, capture_output=True, check=True)
            self.assertEqual(stat.S_IMODE(envfile.stat().st_mode), 0o600)
            self.assertFalse((root / 'pool.env.bak').exists())
            self.assertNotIn('test-secret-sentinel', result.stdout + result.stderr)
            self.assertNotIn('change_me_to_a_strong_secret', envfile.read_text())

    def test_existing_secret_is_restricted_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            envfile = root / 'pool.env'
            envfile.write_text('POSTGRES_PASSWORD=already-configured-secret\n')
            envfile.chmod(0o644)
            schema = root / 'schema.sql'
            schema.write_text('SELECT 1;\n')
            docker = root / 'docker'
            docker.write_text('#!/bin/sh\nif [ "$2" = ps ]; then echo postgres; else cat >/dev/null; fi\n')
            docker.chmod(0o700)
            env = dict(os.environ, ENV_FILE=str(envfile), SCHEMA_FILE=str(schema), PATH=str(root) + ':' + os.environ['PATH'])
            subprocess.run(['bash', str(SCRIPT)], env=env, text=True, capture_output=True, check=True)
            self.assertEqual(stat.S_IMODE(envfile.stat().st_mode), 0o600)

if __name__ == '__main__':
    unittest.main()
