"""Revenue retention from Salesforce renewals (assist/renewals.py): prior ARR from ACV and net forecast, gross and net
renewal rates, logos, likely re-papers, the company bridge and next year's outlook weighted by segment share.
Run: ~/.assist/venv/bin/python -m unittest discover -s tests"""
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from assist import db, renewals

TODAY = date(2026, 10, 16)


class Renewals(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.con = c = db.connect(Path(self.tmp.name) / "t.db")
        db.migrate(c)
        c.execute("INSERT OR IGNORE INTO sources(id, system, name) VALUES ('salesforce','salesforce','s')")
        self.n = 0

    def tearDown(self):
        self.con.close()
        self.tmp.cleanup()

    def opp(self, account, sale_type, stage, close, acv, net, region="NAM", prob=None, name=None, noise=0):
        self.n += 1
        p = {"id": f"o{self.n}", "name": name or f"{account} -  | {sale_type} | {close} | $1K", "account": account, "target_region": region,
             "stage": stage, "probability": prob if prob is not None else (100 if stage == "Closed Won" else 0 if stage == "Closed Lost" else 50),
             "sale_type": sale_type, "currency": "USD", "acv": acv, "net_forecast": net, "net_forecast_usd": net, "close_date": close,
             "is_open": not stage.startswith("Closed"), "seen": "2026-10-16"}
        self.con.execute("INSERT INTO items(id, source_id, external_id, kind, ts, subject, payload, noise, pulled_at) VALUES (?,?,?,?,?,?,?,?,?)",
                         (self.n, "salesforce", f"sf:o{self.n}", "opportunity", close, p["name"], json.dumps(p), noise, "2026-10-16T00:00:00Z"))

    def test_rates_on_the_renewal_book(self):
        self.opp("A", "Renewal", "Closed Won", "2026-02-01", 110_000, 10_000)   # prior 100K, uplift 10K
        self.opp("B", "Renewal", "Closed Won", "2026-03-01", 40_000, -10_000)   # prior 50K, downsell 10K
        self.opp("C", "Renewal", "Closed Lost", "2026-05-01", 0, -50_000)       # churn 50K
        self.opp("D", "Renewal", "Closed Won", "2026-04-01", 0, 0)              # $0 placeholder: ignored
        self.opp("E", "Renewal", "Closed Won", "2025-12-01", 90_000, 0)         # before the window
        self.opp("F", "Renewal", "Closed Won", "2026-06-01", 30_000, 0, noise=1)  # marked noise
        a = renewals.summary(self.con, TODAY)["bases"]["recorded"]["actual"]
        self.assertEqual((a["n"], a["won"], a["lost"]), (3, 2, 1))
        self.assertEqual((a["prior"], a["churn"], a["downsell"], a["uplift"]), (200_000, 50_000, 10_000, 10_000))
        self.assertAlmostEqual(a["grr"], 0.70)          # (200 - 50 - 10) / 200
        self.assertAlmostEqual(a["nrr"], 0.75)          # (110 + 40) / 200
        self.assertEqual(a["logos_lost"], 1)
        self.assertEqual(a["lost_logo_accounts"], ["C"])

    def test_a_customer_with_another_contract_is_not_a_lost_logo(self):
        self.opp("C", "Renewal", "Closed Lost", "2026-05-01", 0, -20_000)
        self.opp("C", "Renewal", "02 - Create Quote", "2027-03-01", 60_000, 0)   # still under contract
        a = renewals.summary(self.con, TODAY)["bases"]["recorded"]["actual"]
        self.assertEqual(a["logos_lost"], 0)
        self.assertEqual(a["churn"], 20_000)

    def test_repaper_counts_as_kept_and_is_not_counted_twice(self):
        self.opp("G", "Renewal", "Closed Lost", "2026-09-28", 0, -60_000, region="EMEA")
        self.opp("G", "Upsell", "Closed Won", "2026-09-30", 150_000, 150_000, region="EMEA")   # replaces it
        self.opp("H", "Renewal", "Closed Won", "2026-02-11", 150_000, 0, region="EMEA")
        self.opp("H", "Renewal", "Closed Lost", "2026-04-09", 0, -150_000, region="EMEA")      # duplicate of the won one
        self.opp("G", "Renewal", "01 - Validate", "2027-09-30", 210_000, 0, region="EMEA")
        self.opp("H", "Renewal", "01 - Validate", "2027-02-11", 150_000, 0, region="EMEA")
        s = renewals.summary(self.con, TODAY)
        rec, adj = s["bases"]["recorded"], s["bases"]["adjusted"]
        self.assertEqual(rec["actual"]["churn"], 210_000)
        self.assertEqual(adj["actual"]["churn"], 0)
        self.assertEqual(adj["actual"]["n"], 2)                     # the duplicate is dropped
        self.assertEqual(adj["company"]["expansion"], 90_000)       # the upsell's 150K less the 60K it replaced
        self.assertAlmostEqual(adj["company"]["grr"], 1.0)
        # the re-paper moves churn into kept ARR without changing net growth
        rec_growth = rec["company"]["nrr"] * rec["company"]["base_start"] - rec["company"]["base_start"]
        adj_growth = adj["company"]["nrr"] * adj["company"]["base_start"] - adj["company"]["base_start"]
        self.assertAlmostEqual(rec_growth, 150_000 - 210_000, delta=100)   # rates are rounded to 4 places
        self.assertAlmostEqual(adj_growth, 90_000, delta=100)
        self.assertEqual({c["account"] for c in s["closed"] if c["replaced_by"]}, {"G", "H"})

    def test_company_base_bridges_back_to_january(self):
        self.opp("A", "Renewal", "Closed Won", "2026-02-01", 110_000, 10_000)
        self.opp("C", "Renewal", "Closed Lost", "2026-05-01", 0, -50_000)
        self.opp("N", "New Logo", "Closed Won", "2026-06-01", 40_000, 40_000)
        self.opp("A", "Renewal", "01 - Validate", "2027-02-01", 110_000, 0)
        self.opp("N", "Renewal", "01 - Validate", "2027-06-01", 40_000, 0)
        s = renewals.summary(self.con, TODAY)
        c = s["bases"]["recorded"]["company"]
        self.assertEqual(s["base_now"]["arr"], 150_000)
        self.assertEqual(c["base_start"], 150_000 - 40_000 - 10_000 + 50_000)    # 150K: A's 100K and C's 50K on 1 January
        self.assertAlmostEqual(c["grr"], 1 - 50_000 / 150_000, places=4)

    def test_outlook_weights_segments_by_their_share_of_next_years_book(self):
        for i in range(8):                                                        # NAM small: 7 of 8 kept
            self.opp(f"s{i}", "Renewal", "Closed Lost" if i == 0 else "Closed Won", "2026-03-01", 0 if i == 0 else 5_000, -5_000 if i == 0 else 0)
        for i in range(8):                                                        # EMEA mid-size: all kept
            self.opp(f"m{i}", "Renewal", "Closed Won", "2026-04-01", 20_000, 0, region="EMEA")
        self.opp("x", "Renewal", "01 - Validate", "2027-03-01", 30_000, 0)                    # NAM mid-size
        self.opp("y", "Renewal", "01 - Validate", "2027-05-01", 5_000, 0)                     # NAM small
        self.opp("z", "Renewal", "03 - Awaiting Order", "2027-07-01", 20_000, 0, region="EMEA", prob=90)
        n = renewals.summary(self.con, TODAY)["bases"]["recorded"]["next_year"]
        self.assertEqual((n["n"], n["prior"]), (3, 55_000))
        seg = {(x["region"], x["band"]): x for x in n["segments"]}
        self.assertEqual(seg[("NAM", "Under $10K")]["source"], "segment")
        self.assertAlmostEqual(seg[("NAM", "Under $10K")]["grr"], 35_000 / 40_000)
        self.assertEqual(seg[("NAM", "$10K–50K")]["source"], "region")             # no closed NAM mid-size renewals
        self.assertEqual(seg[("EMEA", "$10K–50K")]["grr"], 1.0)
        self.assertAlmostEqual(sum(x["share"] for x in n["segments"]), 1.0, places=3)
        expected = (30_000 * (35_000 / 40_000) + 5_000 * (35_000 / 40_000) + 20_000 * 1.0) / 55_000
        self.assertAlmostEqual(n["grr"], expected, places=3)
        self.assertAlmostEqual(n["stage"]["grr"], (0.5 * 35_000 + 0.9 * 20_000) / 55_000, places=3)
        self.assertEqual(n["as_quoted"]["grr"], 1.0)

    def test_prior_from_the_name_when_acv_is_missing(self):
        self.opp("J", "Renewal", "Negotiation", "2027-05-01", None, 2_000, name="J -  | Renewal | 2027-05-01 | $23.3K")
        b = renewals.summary(self.con, TODAY)["bases"]["recorded"]["next_year"]
        self.assertEqual(b["prior"], 23_300)


if __name__ == "__main__":
    unittest.main()
