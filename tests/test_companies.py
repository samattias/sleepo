"""People › Companies (assist/companies.py): what a company is to Acme, Sam's call winning; one company recorded twice
shown once after a merge; a company's own people by their address, never by sharing a thread; no bare addresses;
Salesforce account facts (Type, website, mail domain) stored without ever claiming a shared suffix; logos sniffed by their bytes.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

import struct

from assist import companies, db, entities, logos, sfsync


def ago(days):
    return (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Companies(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = c = db.connect(Path(self.tmp.name) / "t.db")
        db.migrate(c)
        entities.ensure_schema(c)
        c.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('outlook.inbox','outlook','i'), ('salesforce','salesforce','s')")
        c.executemany("INSERT INTO orgs(id, name, kind) VALUES (?,?,?)", [
            (1, "Acme", "internal"), (2, "Contoso", "partner"), (3, "CONTOSO", "account"),
            (4, "Company 845", "account"), (5, "Acme Prospect", "account"), (6, "Fabrikam", "external"), (7, "Quiet Ltd", "external")])
        c.executemany("INSERT INTO org_domains(domain, org_id) VALUES (?,?)", [("company086.org", 4), ("contoso.example", 2)])
        c.executemany("INSERT INTO people(id, name, is_me, org_id, affiliation) VALUES (?,?,?,?,?)", [
            (1, "Sam Doe", 1, 1, "employee"), (2, "Glen Yardley", 0, 1, "employee"), (3, "Reese Prescott", 0, None, "partner"),
            (4, "Pat Banker", 0, None, "external")])
        c.executemany("INSERT INTO people_aliases VALUES (?,?)", [
            ("glen.yardley@acme.example", 2), ("reese@contoso.example", 3), ("pat@company086.org", 4)])
        self.n = 0
        self.deal(3, "Upsell", "Closed Lost", False)
        self.deal(4, "Renewal", "01 - Validate", True, acv=35000)
        self.deal(5, "New Business", "02 - Discovery", True, acv=10000)

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def deal(self, org_id, sale_type, stage, is_open, acv=0):
        self.n += 1
        name = self.con.execute("SELECT name FROM orgs WHERE id=?", (org_id,)).fetchone()[0]
        payload = {"account": name, "name": f"{name} deal", "sale_type": sale_type, "stage": stage, "is_open": is_open, "acv": acv,
                   "currency": "USD", "close_date": "2026-12-01"}
        self.con.execute("INSERT INTO items(id, source_id, external_id, kind, ts, subject, text, pulled_at, payload) VALUES (?,?,?,?,?,?,?,?,?)",
                         (self.n, "salesforce", f"o{self.n}", "opportunity", ago(5), payload["name"], "", ago(0), json.dumps(payload)))

    def mail(self, org_ids, days=1, sender="Someone"):
        self.n += 1
        self.con.execute("INSERT INTO items(id, source_id, external_id, kind, ts, from_name, subject, text, pulled_at) VALUES (?,?,?,?,?,?,?,?,?)",
                         (self.n, "outlook.inbox", f"e{self.n}", "mail", ago(days), sender, f"mail {self.n}", "x", ago(0)))
        for o in org_ids:
            self.con.execute("INSERT INTO mentions(ref_type, ref_id, entity_type, entity_id, confidence) VALUES ('item',?,'org',?,0.9)", (self.n, o))
        return self.n

    def rel(self):
        return {c["name"]: c["relation"] for c in companies.listing(self.con)}

    def test_sections_from_the_records_and_deals(self):
        self.mail([6])
        r = self.rel()
        self.assertEqual(r["Acme"], "ours")
        self.assertEqual(r["Contoso"], "partner")
        self.assertEqual(r["Company 845"], "customer")       # a renewal makes a customer
        self.assertEqual(r["Acme Prospect"], "prospect")        # only new-logo deals
        self.assertEqual(r["Fabrikam"], "other")
        self.assertNotIn("Quiet Ltd", r)                        # nothing linked, no deals, no call: not listed

    def test_sams_call_wins_and_hidden_leaves_the_list(self):
        self.mail([6])
        companies.set_relation(self.con, 6, "partner")
        self.assertEqual(self.rel()["Fabrikam"], "partner")
        row = next(c for c in companies.listing(self.con) if c["name"] == "Fabrikam")
        self.assertEqual(row["relation_by"], "you")
        companies.set_relation(self.con, 6, None)
        self.assertEqual(self.rel()["Fabrikam"], "other")
        companies.set_relation(self.con, 6, "hidden")
        self.assertNotIn("Fabrikam", self.rel())
        with self.assertRaises(ValueError):
            companies.set_relation(self.con, 6, "friend")

    def test_merge_shows_one_company_with_both_records(self):
        self.mail([2]); self.mail([3])
        companies.merge(self.con, 3, 2)
        rows = [c for c in companies.listing(self.con) if "CTS" in c["name"]]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Contoso")
        self.assertEqual(rows[0]["merged"], ["CONTOSO"])
        self.assertEqual(rows[0]["links"], 2)
        p = companies.page(self.con, 3)                         # the merged record opens the company it belongs to
        self.assertEqual(p["id"], 2)
        self.assertEqual(len(p["deals"]), 1)                    # the Salesforce account's deal comes along
        with self.assertRaises(ValueError):
            companies.merge(self.con, 2, 3)                     # already the same company
        companies.merge(self.con, 3, None)
        self.assertEqual(len([c for c in companies.listing(self.con) if "CTS" in c["name"]]), 2)

    def test_people_by_address_not_by_shared_thread(self):
        self.mail([2, 4])                                       # a joint thread names both companies
        p = companies.page(self.con, 4)
        self.assertEqual([x["name"] for x in p["people"]], ["Pat Banker"])
        self.assertEqual([x["name"] for x in companies.page(self.con, 2)["people"]], ["Reese Prescott"])

    def test_no_bare_addresses_in_activity(self):
        self.mail([4], sender="glen.yardley@acme.example")
        self.mail([4], sender="stranger@example.com")
        self.assertEqual(sorted(x["from"] for x in companies.page(self.con, 4)["activity"]), ["", "Glen Yardley"])

    def test_salesforce_partner_type_files_a_partner(self):
        self.deal(7, "New Business", "02 - Discovery", True)   # an account with only new-logo deals: a prospect
        self.con.execute("UPDATE orgs SET kind='account', name='Quiet Ltd' WHERE id=7")
        self.assertEqual(self.rel()["Quiet Ltd"], "prospect")
        companies.store_accounts(self.con, [{"name": "Quiet Ltd", "type": "Partner", "website": "https://www.quiet.co.uk/", "email_domain": None}])
        self.assertEqual(self.rel()["Quiet Ltd"], "partner")

    def test_accounts_add_domains_merge_once_and_skip_shared_suffixes(self):
        self.con.execute("INSERT INTO orgs(id, name, kind, relation) VALUES (8, 'Nwt', 'external', 'customer')")
        self.con.execute("INSERT INTO org_domains(domain, org_id, source) VALUES ('company759.com', 8, 'domain')")
        self.con.execute("INSERT INTO orgs(id, name, kind) VALUES (9, 'Gov Agency', 'account')")
        self.deal(9, "Renewal", "01 - Validate", True)
        out = companies.store_accounts(self.con, [
            {"name": "Acme Prospect", "type": "Prospect", "website": "www.acme.com", "email_domain": "acme.com"},
            {"name": "Company 845", "type": "Customer", "website": "https://company759.com", "email_domain": None},   # the mail-domain record's domain
            {"name": "Gov Agency", "type": "Customer", "website": "https://www.agency.gov.za/", "email_domain": "gov.za"},
            {"name": "Not In SleePO", "type": "Customer", "website": "https://x.com"}])
        self.assertEqual(out["matched"], 3)
        held = dict(self.con.execute("SELECT domain, org_id FROM org_domains"))
        self.assertEqual(held["acme.com"], 5)
        self.assertEqual(held["agency.gov.za"], 9)
        self.assertNotIn("gov.za", held)                       # a suffix many organisations share is no one's domain
        self.assertEqual(self.con.execute("SELECT merged_into FROM orgs WHERE id=8").fetchone()[0], 4)
        self.assertEqual(self.con.execute("SELECT relation FROM orgs WHERE id=4").fetchone()[0], "customer")   # the pick carries over
        companies.merge(self.con, 8, None)                     # Sam separates them: a later load does not merge again
        companies.store_accounts(self.con, [{"name": "Company 845", "type": "Customer", "website": "https://company759.com"}])
        self.assertIsNone(self.con.execute("SELECT merged_into FROM orgs WHERE id=8").fetchone()[0])
        self.assertEqual(tuple(self.con.execute("SELECT website, sf_type FROM orgs WHERE id=5").fetchone()), ("www.acme.com", "Prospect"))

    def test_rename_only_what_sleepo_named(self):
        self.con.execute("INSERT INTO org_domains(domain, org_id, source) VALUES ('company223.com', 6, 'domain')")
        companies.rename(self.con, 6, "  Fabrikam ")
        self.assertEqual(self.con.execute("SELECT name FROM orgs WHERE id=6").fetchone()[0], "Fabrikam")
        # the full re-link re-derives 'domain' rows by name: the renamed company's domain is pinned and stays with it
        self.assertEqual(tuple(self.con.execute("SELECT org_id, source FROM org_domains WHERE domain='company223.com'").fetchone()), (6, "sam"))
        entities.link(self.con, full=True, log=lambda *_: None)
        self.assertEqual(self.con.execute("SELECT org_id FROM org_domains WHERE domain='company223.com'").fetchone()[0], 6)
        with self.assertRaises(ValueError):
            companies.rename(self.con, 4, "Adatum Group")   # Salesforce's name: deals are matched by it
        with self.assertRaises(ValueError):
            companies.rename(self.con, 6, " ")

    def test_suffixes_and_hosts(self):
        self.assertEqual(entities.registrable("www.ku.ac.ae"), "ku.ac.ae")
        self.assertEqual(entities.registrable("company638.com"), "company638.com")
        self.assertEqual(entities.registrable("company480.co.uk"), "company480.co.uk")
        self.assertTrue(entities.public_suffix("com.pl"))
        self.assertFalse(entities.public_suffix("company759.com"))
        self.assertEqual(logos.host_of("https://Company388.jp/en/"), "company388.jp")
        self.assertEqual(logos.host_of("contoso.example"), "contoso.example")
        self.assertIsNone(logos.host_of("not a website"))

    def test_logo_bytes_are_sniffed(self):
        png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + struct.pack(">II", 180, 180)
        self.assertEqual(logos.kind_and_size(png), ("png", 180))
        ico = b"\x00\x00\x01\x00" + struct.pack("<H", 2) + bytes([16, 16]) + b"\x00" * 14 + bytes([0, 0]) + b"\x00" * 14
        self.assertEqual(logos.kind_and_size(ico), ("ico", 256))   # 0 means 256 px
        self.assertEqual(logos.kind_and_size(b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"/>')[0], "svg")
        self.assertEqual(logos.kind_and_size(b"<!doctype html><html>not found</html>"), (None, 0))   # an error page is not a logo

    def test_account_bundle_keeps_company_fields_only(self):
        raw = Path(self.tmp.name) / "accounts.json"
        raw.write_text(json.dumps({"totalSize": 1, "accounts": [{"Id": "001", "Name": "Tailspin Ltd", "Type": "Customer", "Website": "https://company480.co.uk/",
            "eMail_Domain__c": "company480.co.uk", "Owner": {"Name": "An Owner"}, "Phone": "+44 1", "BillingAddress": {"city": "X"}, "Business_Goals__c": "free text"}]}))
        out, n, capped = sfsync.build_accounts([raw], out=Path(self.tmp.name) / "bundle.json")
        b = json.loads(out.read_text())
        self.assertEqual((n, capped), (1, []))
        self.assertEqual(b["accounts"], [{"name": "Tailspin Ltd", "type": "Customer", "website": "https://company480.co.uk/", "email_domain": "company480.co.uk"}])
        self.assertNotIn("An Owner", out.read_text())


if __name__ == "__main__":
    unittest.main()
