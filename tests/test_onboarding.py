"""First-run setup (assist/onboarding.py) and the demo copy (assist/demo.py), 16 Nov 2026."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from assist import db, demo, onboarding, scheduler


class Setup(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        (self.home / "memory" / "context").mkdir(parents=True)
        self.env = mock.patch.dict(os.environ, {"ASSIST_DB": str(Path(self.tmp.name) / "t.db")})
        self.env.start()
        self.assist = mock.patch.object(db, "ASSIST", self.home)
        self.assist.start()
        self.con = db.connect()
        db.migrate(self.con)

    def tearDown(self):
        self.con.close()
        self.assist.stop()
        self.env.stop()
        self.tmp.cleanup()

    def test_a_new_install_needs_setup_until_it_is_finished(self):
        from assist.routes import profile as routes
        with mock.patch.object(onboarding, "checks", lambda: []), mock.patch.object(routes, "suggest", lambda c: {"emails": ["ann@acme.com"]}):
            s = onboarding.state(self.con)
            self.assertTrue(s["needed"])
            self.assertFalse(s["done"])
            self.assertEqual(s["suggest"]["emails"], ["ann@acme.com"])
            onboarding.finish(self.con)
            first = db.get_setting(self.con, "onboarding_done")
            onboarding.finish(self.con)   # finishing twice keeps the first time
            self.assertEqual(db.get_setting(self.con, "onboarding_done"), first)
            self.assertTrue(onboarding.state(self.con)["done"])

    def test_bets_become_initiatives_through_the_seed(self):
        rows = onboarding.save_initiatives(self.con, [{"name": "Launch the platform", "weight": 9, "goal": "Three paying customers"},
                                                      {"name": "  "}, {"name": "Grow revenue", "weight": 0}])
        self.assertEqual([(r["name"], r["weight"]) for r in rows], [("Launch the platform", 5), ("Grow revenue", 1)])
        seed = json.loads((self.home / "memory" / "context" / "initiatives.json").read_text())
        self.assertEqual({x["slug"] for x in seed["initiatives"]}, {"launch-the-platform", "grow-revenue"})
        again = onboarding.save_initiatives(self.con, [{"name": "launch the platform", "weight": 4}])   # same bet, by name
        self.assertEqual(len(again), 2)
        self.assertEqual(self.con.execute("SELECT weight FROM initiatives WHERE slug='launch-the-platform'").fetchone()[0], 4)

    def test_an_org_pack_needs_a_name_and_domains(self):
        with self.assertRaises(ValueError):
            onboarding.save_org_pack(self.con, {"name": "Acme"})
        onboarding.save_org_pack(self.con, {"name": "Acme", "domains": ["acme.com"]})
        self.assertEqual(json.loads((self.home / "org" / "pack.json").read_text())["name"], "Acme")
        onboarding.save_org_pack(self.con, {"name": "Acme Two", "domains": ["acme.com"]})
        self.assertEqual(json.loads((self.home / "org" / "pack.json.bak").read_text())["name"], "Acme")   # the one before is kept

    def test_a_granola_key_that_is_not_one_is_refused_before_any_call(self):
        with mock.patch("urllib.request.urlopen") as call, mock.patch("subprocess.run") as run:
            for bad in ("", "short", "has spaces in it, not a key at all"):
                with self.assertRaises(ValueError):
                    onboarding.save_granola_key(bad)
            call.assert_not_called()
            run.assert_not_called()

    def test_only_fixed_settings_targets_open(self):
        with mock.patch("subprocess.run") as run:
            onboarding.open_settings("disk")
            self.assertEqual(run.call_args[0][0], ["open", onboarding.DISK_SETTINGS])
            with self.assertRaises(ValueError):
                onboarding.open_settings("file:///etc/passwd")


class RecommendedApps(unittest.TestCase):
    """Granola and FluidVoice on the Connect step (Sam, 25 Nov 2026): strongly recommended, with where to get them."""

    def rows(self, installed, key=False, trusted=False):
        from assist import applecal, applemail, dictation
        with mock.patch.object(onboarding, "_claude", lambda: ("/usr/local/bin/claude", True)), \
             mock.patch.object(onboarding, "_keychain", lambda service: key), \
             mock.patch.object(onboarding, "_installed", lambda app: installed), \
             mock.patch.object(dictation, "trusted", lambda: trusted), \
             mock.patch.object(applemail, "index_path", side_effect=OSError), \
             mock.patch.object(applecal, "connect", side_effect=OSError):
            return {c["id"]: c for c in onboarding.checks()}

    def test_missing_apps_say_where_to_get_them(self):
        r = self.rows(installed=False)
        for k, url in (("granola", "https://granola.ai"), ("fluidvoice", "https://github.com/altic-dev/FluidVoice")):
            self.assertEqual((r[k]["status"], r[k]["recommended"], r[k]["required"], r[k]["app"], r[k]["url"]), ("todo", True, False, False, url))
        self.assertIn("Install Granola", r["granola"]["detail"])
        self.assertIn("Install FluidVoice", r["fluidvoice"]["detail"])
        self.assertEqual(list(r)[:4], ["claude", "disk", "granola", "fluidvoice"])

    def test_installed_apps_need_the_key_and_accessibility(self):
        r = self.rows(installed=True)
        self.assertEqual((r["granola"]["status"], r["fluidvoice"]["status"]), ("todo", "todo"))
        self.assertIn("API key", r["granola"]["detail"])
        self.assertIn("Accessibility", r["fluidvoice"]["detail"])
        r = self.rows(installed=True, key=True, trusted=True)
        self.assertEqual((r["granola"]["status"], r["fluidvoice"]["status"]), ("ok", "ok"))


class Demo(unittest.TestCase):
    def test_the_demo_never_inherits_this_install_s_paths(self):
        with mock.patch.dict(os.environ, {"ASSIST_DB": "/real/assist.db", "ASSIST_HOME": "/real/home", "ASSIST_KEYCHAIN_ACCOUNT": "sam"}):
            e = demo.env()
        self.assertEqual((e["ASSIST_DB"], e["ASSIST_HOME"], e["ASSIST_KEYCHAIN_ACCOUNT"], e["ASSIST_PORT"], e["ASSIST_DEMO"]),
                         (str(demo.DB), str(demo.HOME), demo.ACCOUNT, "8766", "1"))
        self.assertNotEqual(demo.DB, db.DEFAULT_DB)
        self.assertNotEqual(demo.PORT, 8765)
        self.assertNotEqual(demo.TRIGGER, "reload.trigger")

    def test_reset_deletes_only_the_demo_folder(self):
        self.assertTrue(demo._safe(demo.ROOT))
        for other in (db.DEFAULT_DB.parent, db.APP, Path.home(), demo.ROOT.parent, demo.HOME):
            self.assertFalse(demo._safe(other), other)

    def test_the_demo_runs_nothing_by_itself(self):
        with mock.patch.object(db, "DEMO", True), mock.patch.object(scheduler, "_STARTED", False), mock.patch("threading.Thread") as t:
            scheduler.start(lambda: None, lambda: None, lambda: False)
            t.assert_not_called()
            self.assertFalse(scheduler._STARTED)


if __name__ == "__main__":
    unittest.main()
