"""The personal layer (DESIGN-PERSONALISATION.md, 16 Nov 2026): identity from a profile, the org pack, and the
Personalisation page's save on a new install. Every test uses its own database and pack; nothing reads Sam's."""
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from assist import db, org, profile
from assist.promptkit import USER

ALEX = {"full_name": "Milo Rivera", "emails": ["milo.rivera@acme.com", "milo@example.org"], "aliases": ["milo r"], "role": "VP of Sales",
        "role_short": "VP Sales", "pronouns": "she/her", "timezone": "America/New_York", "locale": "en-US",
        "meeting_days": "mon,tue,wed", "meeting_hours": "13:00-17:00", "personal_meetings": "school run", "forwarded_mailboxes": ["pat.former"]}


class Identity(unittest.TestCase):
    def setUp(self):
        profile.use(ALEX)

    def tearDown(self):
        profile.use(None)

    def test_the_user_is_recognised_by_name_and_address_only(self):
        self.assertTrue(profile.is_me("Milo Rivera"))
        self.assertTrue(profile.is_me("milo"))
        self.assertTrue(profile.is_me("Milo.Rivera@acme.com"))
        self.assertTrue(db.ME_STRICT.search("milo@example.org"))
        self.assertFalse(profile.is_me("Alexandra Smith"))
        self.assertFalse(profile.is_me("sam.doe@acme.example"))
        self.assertTrue(profile.mentions_me("From: Milo Rivera <x@y.z>"))
        self.assertFalse(profile.mentions_me("Alexander Rivers"))

    def test_greetings_and_one_to_one_titles_use_the_first_name(self):
        self.assertTrue(profile.GREETING.search("Hi Milo,"))
        self.assertFalse(profile.GREETING.search("milo.rivera@acme.com"))
        self.assertTrue(profile.ADDRESSED.search("Thanks. Milo, can you send it?"))
        self.assertEqual(profile.ONE_TO_ONE.sub(" ", "Milo <> Jordan 1:1").strip(), "Jordan")
        self.assertEqual(profile.strip_address("@Milo Rivera, can you look"), "can you look")

    def test_sql_finds_the_user_as_author(self):
        c = sqlite3.connect(":memory:")
        c.execute("CREATE TABLE m (author TEXT)")
        c.executemany("INSERT INTO m VALUES (?)", [("Milo Rivera",), ("milo",), ("ALEX.RIVERA@ACME.COM",), ("Jordan",), ("O'Brien",)])
        self.assertEqual(c.execute(f"SELECT COUNT(*) FROM m WHERE {profile.sql_author('author')}").fetchone()[0], 3)
        self.assertEqual(c.execute(f"SELECT COUNT(*) FROM m WHERE {profile.sql_mentions('author')}").fetchone()[0], 2)

    def test_rules_and_prompt_text_come_from_the_profile(self):
        self.assertTrue(profile.PERSONAL.search("School run with the kids"))
        self.assertFalse(profile.PERSONAL.search("Pipeline review"))
        self.assertTrue(profile.forwarded_only(["pat.former@acme.com"]))
        self.assertFalse(profile.forwarded_only(["pat.former@acme.com", "milo.rivera@acme.com"]))
        self.assertEqual((USER.first, USER.his, USER.himself, USER.signoff, USER.spelling, USER.city), ("Milo", "her", "herself", "-Milo", "American", "New York"))
        self.assertEqual(USER.not_free, "mornings, Thursdays or Fridays")
        self.assertEqual(profile.meeting_window()[0], [0, 1, 2])

    def test_no_profile_names_no_one(self):
        profile.use({})
        self.assertFalse(profile.is_me("Sam Doe"))
        self.assertFalse(db.ME_LOOSE.search("sam"))
        self.assertEqual(profile.sql_author("author"), "0")
        self.assertEqual(USER.first, "the user")


class OrgPack(unittest.TestCase):
    def test_pack_then_overrides(self):
        with tempfile.TemporaryDirectory() as d:
            pack = Path(d) / "pack.json"
            pack.write_text(json.dumps({"name": "Acme", "domains": ["acme.com", "acme.de"], "address_pattern": "{first}.{last}@acme.com",
                                        "noise_senders": ["vendorbot"], "company_names": ["acme"]}))
            with mock.patch.dict(os.environ, {"ASSIST_DB": str(Path(d) / "t.db"), "ASSIST_ORG_PACK": str(pack)}):
                c = db.connect(); db.migrate(c)
                org._cache.clear()
                self.assertEqual(org.name(), "Acme")
                self.assertEqual(org.address_for("Jordan Noel"), "jordan.lee@acme.com")
                self.assertTrue(org.is_primary_address("x@acme.com"))
                self.assertTrue(org.is_own_company("Acme Inc"))
                self.assertEqual(org.alt("noise_senders"), "|vendorbot")
                org.save(c, name="Acme Corp")
                self.assertEqual(org.get(c)["name"], "Acme Corp")
                c.close()
                org._cache.clear()

    def test_no_pack_is_empty(self):
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.dict(os.environ, {"ASSIST_DB": str(Path(d) / "t.db"), "ASSIST_ORG_PACK": str(Path(d) / "none.json")}):
                org._cache.clear()
                self.assertEqual((org.name(), org.domains(), org.alt("noise_senders"), org.primary_domain()), ("", [], "", ""))
                self.assertFalse(org.site_home().search("https://example.com/"))
                org._cache.clear()


class FirstRun(unittest.TestCase):
    def test_saving_the_profile_creates_me_and_reads_back(self):
        from assist.routes import profile as R
        with tempfile.TemporaryDirectory() as d:
            with mock.patch.dict(os.environ, {"ASSIST_DB": str(Path(d) / "t.db"), "ASSIST_ORG_PACK": str(Path(d) / "none.json")}), \
                    mock.patch.object(R, "suggest", lambda c: {}):
                c = db.connect(); db.migrate(c)
                profile.reload(); org._cache.clear()
                self.assertTrue(R.payload(c)["needs_setup"])
                R.save(c, R.ProfileIn(fields={"full_name": "Milo Rivera", "emails": ["milo.rivera@acme.com"], "pronouns": "she/her"},
                                      followed_channels=["#sales"], task_areas=[{"key": "admin", "name": "Admin", "hint": ""}]))
                d2 = R.payload(c)
                self.assertFalse(d2["needs_setup"])
                self.assertEqual(d2["me_person"]["name"], "Milo Rivera")
                self.assertEqual(d2["followed_channels"], ["#sales"])
                self.assertEqual([a["key"] for a in d2["task_areas"]], ["admin"])
                self.assertTrue(profile.is_me("milo.rivera@acme.com"))
                before = os.path.getmtime(Path(d) / "t.db")
                R.payload(c)   # reading writes nothing
                self.assertEqual(os.path.getmtime(Path(d) / "t.db"), before)
                c.close()
                profile.reload(); org._cache.clear()


if __name__ == "__main__":
    unittest.main()
