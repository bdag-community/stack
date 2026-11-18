import importlib.util
import tempfile
import unittest
from pathlib import Path


spec = importlib.util.spec_from_file_location("stack_defaults", Path(__file__).with_name("validate-stack-defaults.py"))
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


class WalletTemplateTest(unittest.TestCase):
    def check(self, text):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".env.example").write_text(text)
            errors = []
            validator.assert_wallet_template_empty(errors, root)
            return errors

    def test_blank_wallet_fields_are_allowed(self):
        self.assertEqual(self.check("MINING_POOL_ADDRESS=\nPOOL_COINBASE_ADDRESS=\n"), [])

    def test_embedded_wallets_or_private_key_are_rejected_without_echo(self):
        for key in ("MINING_POOL_ADDRESS", "POOL_COINBASE_ADDRESS", "MINING_ADDRESS", "POOL_PRIVATE_KEY"):
            with self.subTest(key=key):
                values = {"MINING_POOL_ADDRESS": "", "POOL_COINBASE_ADDRESS": "", key: "sensitive-example"}
                errors = self.check("".join(f"{name}={value}\n" for name, value in values.items()))
                self.assertTrue(errors)
                self.assertNotIn("sensitive-example", " ".join(errors))

    def test_missing_or_duplicate_required_fields_are_rejected(self):
        self.assertTrue(self.check("MINING_POOL_ADDRESS=\n"))
        self.assertTrue(self.check("MINING_POOL_ADDRESS=\nMINING_POOL_ADDRESS=\nPOOL_COINBASE_ADDRESS=\n"))


if __name__ == "__main__":
    unittest.main()
