"""
Unit tests for the agentbox support library.

Runnable without a database or network (FileBackend + in-process crypto):

    python -m unittest railway.tests.test_agentbox -v

Covers the credential store (encryption round-trip, isolation, revoke),
usage tracking (attribution + secret scrubbing), and the per-user env builder
(billing-key guardrail).
"""

import os
import tempfile
import unittest

from railway.agentbox.backends import FileBackend
from railway.agentbox.credstore import CredentialStore, generate_enc_key
from railway.agentbox.tokens import BILLING_KEYS, build_user_env, strip_billing_keys
from railway.agentbox.tracking import UsageTracker


class CredentialStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.backend = FileBackend(self.tmp.name)
        self.key = generate_enc_key()
        self.store = CredentialStore(enc_key=self.key, backend=self.backend)

    def tearDown(self):
        self.tmp.cleanup()

    def test_set_get_roundtrip(self):
        self.store.set_token("alice", "sk-ant-oat-ALICE")
        self.assertEqual(self.store.get_token("alice"), "sk-ant-oat-ALICE")

    def test_token_encrypted_at_rest(self):
        self.store.set_token("alice", "supersecret-token")
        raw = self.backend.kv_get("user_credentials", "alice")["token"]
        self.assertNotIn("supersecret-token", raw)  # ciphertext, not plaintext

    def test_user_isolation(self):
        self.store.set_token("alice", "tok-A")
        self.store.set_token("bob", "tok-B")
        self.assertEqual(self.store.get_token("alice"), "tok-A")
        self.assertEqual(self.store.get_token("bob"), "tok-B")
        self.assertCountEqual(self.store.list_users(), ["alice", "bob"])

    def test_revoke(self):
        self.store.set_token("alice", "tok-A")
        self.assertTrue(self.store.revoke("alice"))
        self.assertIsNone(self.store.get_token("alice"))
        self.assertFalse(self.store.revoke("alice"))  # already gone

    def test_wrong_key_cannot_decrypt(self):
        self.store.set_token("alice", "tok-A")
        other = CredentialStore(enc_key=generate_enc_key(), backend=self.backend)
        self.assertIsNone(other.get_token("alice"))  # returns None, doesn't raise

    def test_missing_key_rejected(self):
        with self.assertRaises(ValueError):
            CredentialStore(enc_key="", backend=self.backend)

    def test_invalid_key_rejected(self):
        with self.assertRaises(ValueError):
            CredentialStore(enc_key="not-a-fernet-key", backend=self.backend)

    def test_empty_inputs_rejected(self):
        with self.assertRaises(ValueError):
            self.store.set_token("", "tok")
        with self.assertRaises(ValueError):
            self.store.set_token("alice", "   ")

    def test_updated_at_changes_created_at_stable(self):
        self.store.set_token("alice", "tok-A")
        first = self.backend.kv_get("user_credentials", "alice")
        self.store.set_token("alice", "tok-B")
        second = self.backend.kv_get("user_credentials", "alice")
        self.assertEqual(first["created_at"], second["created_at"])
        self.assertGreaterEqual(second["updated_at"], first["updated_at"])


class TokenEnvTests(unittest.TestCase):
    def test_strip_billing_keys(self):
        env = {"ANTHROPIC_API_KEY": "x", "OPENAI_API_KEY": "y", "PATH": "/bin"}
        stripped = strip_billing_keys(env)
        for k in BILLING_KEYS:
            self.assertNotIn(k, stripped)
        self.assertEqual(stripped["PATH"], "/bin")

    def test_build_user_env_injects_token_and_strips_billing(self):
        base = {"ANTHROPIC_API_KEY": "should-be-gone", "PATH": "/bin"}
        env = build_user_env("user-tok", base_env=base)
        self.assertEqual(env["CLAUDE_CODE_OAUTH_TOKEN"], "user-tok")
        self.assertNotIn("ANTHROPIC_API_KEY", env)
        self.assertEqual(env["PATH"], "/bin")

    def test_build_user_env_requires_token(self):
        with self.assertRaises(ValueError):
            build_user_env("   ")


class UsageTrackingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tracker = UsageTracker(backend=FileBackend(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_login_recorded(self):
        self.tracker.record_login("alice", ip="1.2.3.4", location="SF")
        logins = self.tracker.recent_logins()
        self.assertEqual(len(logins), 1)
        self.assertEqual(logins[0]["user_id"], "alice")
        self.assertEqual(logins[0]["ip"], "1.2.3.4")

    def test_task_attribution_and_filter(self):
        self.tracker.record_task("alice", "build feature X")
        self.tracker.record_task("bob", "review PR")
        self.assertEqual(len(self.tracker.recent_tasks()), 2)
        alice = self.tracker.for_user("alice")
        self.assertEqual(len(alice), 1)
        self.assertEqual(alice[0]["summary"], "build feature X")

    def test_secrets_scrubbed_from_detail(self):
        self.tracker.record_task(
            "alice", "task", detail={"token": "leak", "repo": "myrepo"}
        )
        rec = self.tracker.recent_tasks()[0]
        self.assertNotIn("token", rec["detail"])
        self.assertEqual(rec["detail"]["repo"], "myrepo")


class PersistenceTests(unittest.TestCase):
    def test_survives_new_instance(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        key = generate_enc_key()
        CredentialStore(enc_key=key, backend=FileBackend(tmp.name)).set_token("a", "t")
        # New store instance, same backend dir = same volume after redeploy.
        reopened = CredentialStore(enc_key=key, backend=FileBackend(tmp.name))
        self.assertEqual(reopened.get_token("a"), "t")
        # File is restrictive (0600).
        path = os.path.join(tmp.name, "agentbox", "user_credentials.json")
        self.assertEqual(oct(os.stat(path).st_mode & 0o777), "0o600")


if __name__ == "__main__":
    unittest.main()
