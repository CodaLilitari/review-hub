"""Local identity persistence and policy boundaries; no provider execution."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from coda_review_hub.identity import IdentityStore


class IdentityStoreTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix="review-hub-identity-test-")
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.store = IdentityStore(self.root / "state")

    def test_public_default_is_empty_and_requires_choice(self):
        profile = self.store.read()
        self.assertFalse(profile["configured"])
        self.assertEqual(profile["agent_name"], "")
        self.assertEqual(profile["user_name"], "")
        self.assertEqual(profile["collaborators"], {})
        self.assertFalse(self.store.path.exists())
        with self.assertRaisesRegex(ValueError, "Ask/check the user"):
            self.store.greeting()

    def test_named_profile_survives_reload_and_resolves_only_direct_alias(self):
        profile = self.store.configure(
            evidence="The fixture user explicitly chose these synthetic names.",
            agent_name="Guide", user_name="Researcher", collaborators={"chatgpt": "Editor"},
            aliases={"editor": "chatgpt"}, context_notes={"chatgpt": "Use the authorized project conversation."},
        )
        reloaded = IdentityStore(self.root / "state")
        self.assertEqual(reloaded.read(), profile)
        self.assertEqual(reloaded.resolve_provider("editor"), "chatgpt")
        self.assertEqual(reloaded.resolve_provider("claude"), "claude")
        self.assertIn("authorized project", reloaded.note("editor"))
        self.assertEqual(reloaded.note("grok"), "")
        self.assertTrue(reloaded.greeting().startswith("Guide: Hello, I'm Guide, collaborating with Researcher."))
        with self.assertRaisesRegex(ValueError, "Unknown provider"):
            reloaded.resolve_provider("unconfigured")

    def test_anonymous_choice_is_explicit_and_does_not_invent_names(self):
        self.store.configure(evidence="The user chose anonymous names for the local fixture.")
        self.assertTrue(self.store.read()["configured"])
        self.assertEqual(self.store.read()["agent_name"], "")
        self.assertEqual(self.store.read()["user_name"], "")
        self.assertTrue(self.store.greeting().startswith("Hello, I'm the coordinating assistant, collaborating with the user."))

    def test_invalid_profiles_do_not_replace_saved_choice(self):
        original = self.store.configure(evidence="The fixture user chose an anonymous profile.")
        invalid = (
            {"agent_name": 2}, {"user_name": "Two\nlines"}, {"collaborators": {"arbitrary": "Name"}},
            {"context_notes": {"chatgpt": 1}}, {"aliases": {"grok": "claude"}},
            {"aliases": {"editor": "not-a-provider"}}, {"aliases": {"Editor": "chatgpt"}},
            {"aliases": ["chatgpt"]}, {"evidence": "short"},
        )
        for fields in invalid:
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                self.store.configure(**dict({"evidence": "Synthetic user established these choices."}, **fields))
            self.assertEqual(self.store.read(), original)

    def test_seed_is_explicit_once_and_does_not_override_saved_choice(self):
        seed = self.root / "seed.json"
        seed.write_text(json.dumps({"agent_name": "Seed Guide", "evidence": "User established this synthetic seed."}), encoding="utf-8")
        seeded = IdentityStore(self.root / "state", seed_path=seed)
        self.assertEqual(seeded.read()["agent_name"], "Seed Guide")
        seeded.configure(agent_name="Chosen Guide", evidence="The user changed this synthetic name later.")
        seed.write_text("invalid later seed", encoding="utf-8")
        self.assertEqual(IdentityStore(self.root / "state", seed_path=seed).read()["agent_name"], "Chosen Guide")
        self.assertFalse(IdentityStore(self.root / "public-state").read()["configured"])

    def test_failed_atomic_replace_preserves_choice_and_cleans_temporary(self):
        original = self.store.configure(evidence="The fixture user chose an anonymous profile.")
        with patch("coda_review_hub.identity.os.replace", side_effect=OSError("synthetic replace failure")):
            with self.assertRaises(OSError):
                self.store.configure(agent_name="New Guide", evidence="This attempt is interrupted by the fixture.")
        self.assertEqual(self.store.read(), original)
        self.assertEqual(list(self.store.path.parent.glob("identity.*.tmp")), [])

    def test_corrupt_saved_profile_is_not_silently_reset(self):
        self.store.configure(evidence="The fixture user chose an anonymous profile.")
        self.store.path.write_text("{broken", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "valid UTF-8 JSON"):
            self.store.read()
        with self.assertRaises(ValueError):
            self.store.greeting()


if __name__ == "__main__":
    unittest.main()
