"""The onboarding agent (assist/onboard_agent.py), 16 Nov 2026: the evidence pack built in code, what the run may return,
and what the user's confirmation saves. Everything here runs on a temporary database and data folder."""
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from assist import db, onboard_agent as oa, profile
from assist.routes import profile as profile_routes

ME = "ann.lee@acme.com"


def iso(days=0, hour=None, minute=0):
    t = datetime.now(timezone.utc) + timedelta(days=days)
    if hour is not None:
        t = t.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / "home"
        (self.home / "memory" / "context").mkdir(parents=True)
        self.env = mock.patch.dict(os.environ, {"ASSIST_DB": str(Path(self.tmp.name) / "t.db")})
        self.env.start()
        self.assist = mock.patch.object(db, "ASSIST", self.home)
        self.assist.start()
        self.suggest = mock.patch.object(profile_routes, "suggest", lambda c: {"emails": [ME], "full_name": "Ann Noel", "timezone": "Europe/London"})
        self.suggest.start()
        self.con = db.connect()
        db.migrate(self.con)
        profile.use({**profile.DEFAULTS, "full_name": "Ann Noel", "emails": [ME], "timezone": "Europe/London"})
        self.con.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('outlook.inbox','outlook','i'), ('outlook.sent','outlook','s'), "
                         "('calendar','calendar','c'), ('granola','granola','g'), ('local','local','l')")
        self.n = 0

    def tearDown(self):
        profile.use(None)
        self.con.close()
        self.suggest.stop()
        self.assist.stop()
        self.env.stop()
        self.tmp.cleanup()

    def item(self, source, kind, ts, subject="", text="", payload=None, retention="general"):
        self.n += 1
        self.con.execute("INSERT INTO items(id, source_id, external_id, kind, ts, subject, text, payload, retention, pulled_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (self.n, source, f"x{self.n}", kind, ts, subject, text, json.dumps(payload) if payload else None, retention, ts))
        return self.n

    def mail(self, folder, frm, to, subject, body, days=-2, cc=()):
        i = self.item("outlook.sent" if folder == "sentitems" else "outlook.inbox", "sent" if folder == "sentitems" else "mail", iso(days), subject)
        self.con.execute("INSERT INTO mail_messages(item_id, graph_id, folder, from_name, from_address, to_json, cc_json, subject, sent_at, received_at, body_text, synced_at) "
                         "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                         (i, f"g{i}", folder, frm.split("@")[0], frm, json.dumps([{"name": "", "address": a} for a in to]),
                          json.dumps([{"name": "", "address": a} for a in cc]), subject, iso(days), iso(days), body, iso(days)))

    def event(self, title, days, hour, attendees, organizer=ME, minutes=30):
        st = iso(days, hour)
        en = (datetime.strptime(st, "%Y-%m-%dT%H:%M:%SZ") + timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S")
        self.item("calendar", "event", st, title, payload={"subject": title, "start": st[:-1], "end": en, "attendees": [ME, *attendees],
                                                          "organizer": organizer, "isOrganizer": organizer == ME})

    def fixture(self):
        sig = "Thanks,\n-Ann\nAnn Noel | Head of Customer Success\n+44 20 7946 0958\nhttps://acme.com"
        for k in range(4):
            self.mail("sentitems", ME, ["bo.chen@acme.com"], f"Re: Renewal plan Q{k}", f"Looks good, please organise the review.\n\n{sig}\n\nFrom: Bo\nold text")
        self.mail("sentitems", ME, ["cara@example.org"], "Pricing", f"Colour me impressed.\n\n{sig}", cc=["bo.chen@acme.com"])
        self.mail("sentitems", ME, ["dee@acme.com"], "FYI", "FYI\n[__tpx__]")
        self.mail("inbox", "bo.chen@acme.com", [ME], "Renewal plan", "Can you look?")
        self.mail("inbox", "no-reply@vendor.com", [ME], "Your invoice", "noise")
        for w in range(4):   # a weekly 1:1 Ann runs with Bo, and a staff meeting someone else runs
            self.event("Ann / Bo", -7 * w - 1, 14, ["bo.chen@acme.com"])
            self.event("CS leadership", -7 * w - 2, 15, ["eve.ross@acme.com", "bo.chen@acme.com"], organizer="eve.ross@acme.com", minutes=60)
        self.event("Lisbon partner call", -3, 2, ["kenji@example.org"])   # a trip: the small hours do not set the working window
        self.event("Gym", -5, 12, ["coach@example.org"])
        self.event("Gym", -12, 12, ["coach@example.org"])
        self.item("granola", "note", iso(-2), "Renewal review with Bo", "# Renewals\n- Q4 renewals at risk")
        self.item("granola", "note", iso(-3), "Performance chat", "private", retention="hr_legal")
        self.item("local", "doc", iso(-1), "Renewal plan.xlsx")
        self.con.commit()


class Pack(Base):
    def test_the_pack_reads_who_she_is_who_she_works_with_and_when_she_meets(self):
        self.fixture()
        pk = oa.build_pack(self.con)
        t = pk["text"]
        self.assertIn("Calendar.app's own address on this Mac: ann.lee@acme.com", t)
        self.assertIn('Last line "-Ann"', t)
        self.assertNotIn("__tpx__", t)                                 # markup is not a sign-off
        self.assertIn("Head of Customer Success", t)                    # the signature block, repeated
        self.assertNotIn("7946", t)                                     # with the phone number masked
        self.assertNotIn("https://acme.com", t)
        self.assertNotIn("old text", t)                                 # quoted mail is not hers
        self.assertRegex(t, r"Bo Chen <bo.chen@acme.com> · 4.5 emails · same company")
        self.assertIn("cara@example.org", t)
        self.assertNotIn("no-reply@vendor.com", t)
        self.assertIn('"CS leadership" · 4 times', t)
        self.assertIn("organised by Eve Ross", t)
        self.assertIn("With Bo Chen <bo.chen@acme.com> · 4 times · organised by the user", t)
        self.assertIn("Renewal review with Bo", t)
        self.assertNotIn("Performance chat", t)                         # HR notes are left out
        self.assertIn("Renewal plan.xlsx", t)
        self.assertIn("British forms", t)
        self.assertEqual(pk["spelling"], "British")
        self.assertIn("Gym", pk["recurring"])
        self.assertNotIn("gmail.com", pk["domains"])
        self.assertIn("acme.com", pk["domains"])
        c = pk["computed"]
        self.assertTrue(c["meeting_hours"].startswith(("12:", "13:", "14:")), c)   # not 02:00 from the Lisbon call
        self.assertTrue(pk["has_data"])
        self.assertTrue(any("You write most to Bo Chen" in n for n in pk["notes"]))
        for r in pk["refs"]:
            self.assertIn(f"[{r}]", t)

    def test_an_empty_install_has_nothing_to_read(self):
        self.assertFalse(oa.build_pack(self.con)["has_data"])


class Validate(Base):
    def pk(self):
        return {"refs": {"K1": "the 1:1", "E1": "a thread", "M1": "notes", "I1": "calendar"}, "names": {"Bo Chen", "Eve Ross"},
                "emails": {ME}, "domains": {"acme.com"}, "recurring": ["Gym", "Ann / Bo"], "computed": {"timezone": "Europe/London", "meeting_days": "mon,tue"},
                "spelling": "British"}

    def test_only_what_the_pack_supports_is_kept(self):
        raw = {"summary": "You run customer success.",
               "identity": {"full_name": "Ann Noel", "emails": [ME, "made.up@acme.com"], "title": "Head of CS", "confidence": "sure", "refs": ["I1", "Z9"], "pronouns": "she/her"},
               "company": {"name": "Acme", "domains": ["acme.com", "evil.com"], "refs": ["I1"]},
               "manager": {"name": "eve ross", "confidence": "likely", "refs": ["K1"]},
               "team": [{"name": "Bo Chen", "refs": ["K1"]}, {"name": "Someone Invented", "refs": ["K1"]}],
               "key_people": [{"name": "Eve Ross"}],
               "bets": [{"name": "Cut churn", "weight": 9, "refs": ["E1", "M1"]}, {"name": "Uncited", "refs": ["Q1"]}],
               "voice": {"signoff": "-Ann", "spelling": "Klingon", "notes": ["Short"]},
               "personal_meetings": [{"title": "gym"}, {"title": "Ann / Bo x"}],
               "questions": [{"id": "q1", "field": "top_bet", "header": "Top bet", "question": "Which matters most?", "options": [{"label": "Churn", "value": "Cut churn"}, {"label": "X", "value": "Not a bet"}]},
                             {"id": "q2", "field": "team", "header": "Team", "question": "Who else?", "multi": True, "options": [{"label": "Bo", "value": "Bo Chen"}, {"label": "Eve", "value": "Eve Ross"}]},
                             {"id": "q3", "field": "salary", "question": "?", "options": [{"label": "a", "value": "a"}, {"label": "b", "value": "b"}]}]}
        r = oa.validate(raw, self.pk())
        self.assertEqual(r["identity"]["emails"], [ME])
        self.assertEqual(r["identity"]["refs"], ["I1"])
        self.assertEqual(r["identity"]["confidence"], "unverified")
        self.assertNotIn("pronouns", r["identity"])
        self.assertEqual(r["company"]["domains"], ["acme.com"])
        self.assertEqual(r["manager"]["name"], "Eve Ross")            # the pack's spelling
        self.assertEqual([t["name"] for t in r["team"]], ["Bo Chen"])
        self.assertEqual(r["key_people"], [])                         # the manager is not also a key person
        self.assertEqual([(b["name"], b["weight"]) for b in r["bets"]], [("Cut churn", 5)])
        self.assertEqual(r["voice"]["spelling"], "British")           # from the mail when the run says something else
        self.assertEqual([p["title"] for p in r["personal_meetings"]], ["Gym"])
        self.assertEqual([q["field"] for q in r["questions"]], ["team"])   # one option left is not a question; unknown fields go
        self.assertTrue(r["questions"][0]["multi"])
        self.assertEqual(r["calendar"], {"meeting_days": "mon,tue"})
        self.assertEqual(set(r["ref_labels"]), {"I1", "K1", "E1", "M1"})


class Apply(Base):
    def draft(self, **over):
        d = {"summary": "You run customer success at Acme.", "identity": {"full_name": "Ann Noel", "first_name": "Ann", "emails": [ME], "title": "Head of Customer Success", "role_short": "HCS"},
             "company": {"name": "Acme", "domains": ["acme.com"]}, "timezone": "Europe/Paris", "manager": {"name": "Eve Ross", "title": "COO"},
             "team": [{"name": "Bo Chen"}], "key_people": [{"name": "Cara Diaz", "why": "biggest customer"}],
             "bets": [{"name": "Cut churn", "goal": "Under 5% by June", "weight": 5}], "voice": {"signoff": "-Ann", "spelling": "British", "notes": ["Short and direct"]},
             "calendar": {"meeting_days": "tue,mon,xyz", "meeting_hours": "13:00-17:30", "meeting_minutes": 30}, "personal_meetings": ["Gym (Tue)"]}
        d.update(over)
        return d

    def test_what_she_confirms_is_saved_where_sleepo_reads_it(self):
        tpl = Path(__file__).resolve().parents[1] / "templates" / "data" / "memory" / "context"
        for f in ("me.md", "preferences.md"):
            (self.home / "memory" / "context" / f).write_text((tpl / f).read_text())
        oa.apply(self.con, self.draft())
        p = json.loads(db.get_setting(self.con, "profile"))
        self.assertEqual(p["role"], "Head of Customer Success")
        self.assertEqual(p["manager"], "Eve Ross")
        self.assertEqual(p["meeting_days"], "mon,tue")
        self.assertEqual(p["timezone"], "Europe/Paris")
        self.assertEqual(p["personal_meetings"], r"Gym\ \(Tue\)")
        self.assertNotIn("pronouns", p)
        self.assertEqual(json.loads(db.get_setting(self.con, "org"))["name"], "Acme")
        self.assertEqual(self.con.execute("SELECT name, weight FROM initiatives").fetchall()[0][:], ("Cut churn", 5))
        me = (self.home / "memory" / "context" / "me.md").read_text()
        self.assertIn("Head of Customer Success at Acme.", me)
        self.assertIn("Reports to Eve Ross (COO).", me)
        self.assertIn("**Cut churn**: Under 5% by June", me)
        voice = (self.home / "memory" / "context" / "preferences.md").read_text()
        self.assertIn("Short and direct.", voice)
        self.assertIn('Sign off with "-Ann". British spelling.', voice)
        self.assertEqual(self.con.execute("SELECT name FROM people WHERE is_me=1").fetchone()[0], "Ann Noel")

    def test_pages_she_already_wrote_are_left_alone_and_empty_fields_keep_what_is_there(self):
        (self.home / "memory" / "context" / "me.md").write_text("# About me\nMy own words.\n")
        profile.save(self.con, signoff="Best, Ann")
        oa.apply(self.con, self.draft(voice={"signoff": "", "spelling": "", "notes": []}))
        self.assertEqual((self.home / "memory" / "context" / "me.md").read_text(), "# About me\nMy own words.\n")
        self.assertEqual(json.loads(db.get_setting(self.con, "profile"))["signoff"], "Best, Ann")

    def test_a_name_and_an_address_are_needed(self):
        with self.assertRaises(ValueError):
            oa.apply(self.con, self.draft(identity={"full_name": "", "emails": [ME]}))
        with self.assertRaises(ValueError):
            oa.apply(self.con, self.draft(timezone="Mars/Olympus"))


class Run(Base):
    def test_a_run_imports_reads_thinks_and_waits_for_review(self):
        self.fixture()
        answer = json.dumps({"summary": "You run customer success.", "identity": {"full_name": "Ann Noel", "emails": [ME], "refs": ["I1"]},
                             "bets": [{"name": "Cut churn", "refs": ["E1", "K1"]}]})
        with mock.patch.object(oa, "_import") as imp, mock.patch.object(oa.llm, "run", return_value=answer) as run:
            d = oa.run(chat=False, log=lambda x: None)
        imp.assert_called_once()
        self.assertEqual(run.call_args.kwargs["purpose"], "onboarding")
        self.assertEqual(d["stage"], "review")
        self.assertFalse(d["running"])
        self.assertEqual(d["result"]["bets"][0]["name"], "Cut churn")
        self.assertTrue(d["notes"])
        self.assertEqual(oa.status()["stage"], "review")
        self.assertEqual(oa._path().parent, Path(self.tmp.name) / "jobs")   # never the live jobs folder

    def test_nothing_to_read_stops_with_a_reason(self):
        with mock.patch.object(oa, "_import"), mock.patch.object(oa.llm, "run") as run:
            d = oa.run(log=lambda x: None)
        run.assert_not_called()
        self.assertEqual((d["stage"], d["failed_at"]), ("failed", "read"))
        self.assertIn("could not read any mail", d["error"])

    def test_a_run_whose_process_died_shows_as_stopped(self):
        oa._write({"running": True, "stage": "think", "pid": 999999, "started": iso(-1)})
        self.assertEqual(oa.status()["stage"], "failed")

    def test_setup_opens_again_until_the_review_is_confirmed(self):
        from assist import api
        profile.save(self.con, full_name="Ann Noel", emails=[ME])
        profile.reload()
        with mock.patch.object(profile, "get", lambda *a, **k: profile.complete(profile.from_db(self.con))):
            self.assertFalse(api._meta_setup()["needed"])             # nothing started: the profile is enough
            oa._write({"running": False, "stage": "review", "started": iso(-1)})
            self.assertTrue(api._meta_setup()["needed"])              # read, not confirmed: the Welcome page opens again
            oa._write({"running": False, "stage": "review", "started": iso(-1), "applied": iso()})
            self.assertFalse(api._meta_setup()["needed"])

    def test_the_address_calendar_knows_is_kept_before_the_import(self):
        profile.use(None)
        self.assertEqual(oa.provisional_identity(self.con), ME)
        self.assertEqual(json.loads(db.get_setting(self.con, "profile"))["emails"], [ME])
        self.assertIsNone(oa.provisional_identity(self.con))   # once known, left alone


class FreshInstall(Base):
    def test_the_calendar_import_makes_its_folder_on_a_new_install(self):
        from assist import importer
        path = Path(self.tmp.name) / "new" / "inbox" / "calendar" / "events.json"   # no inbox/calendar yet
        ev = {"id": "e1", "subject": "Ann / Bo", "start": "2026-11-17T14:00:00", "end": "2026-11-17T14:30:00", "attendees": [ME]}
        importer.merge_calendar({"window": {"from": "2026-11-16", "to": "2026-11-18"}, "events": [ev]}, path, record_window=False)
        self.assertEqual(json.loads(path.read_text())["events"][0]["subject"], "Ann / Bo")


if __name__ == "__main__":
    unittest.main()
