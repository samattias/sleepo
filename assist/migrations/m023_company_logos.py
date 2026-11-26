"""Company logos and Salesforce account facts (assist/companies.py, assist/logos.py; Sam, 23 Oct 2026).
orgs.sf_type: the Salesforce account Type (Customer, Partner, Former Customer, Prospect…); a Partner account is listed as a partner.
orgs.website: the account's website host from Salesforce, the address its logo is looked up by.
org_logos: one logo per web domain, cached as a file under Application Support/Assist/logos (file NULL: none found; tried again
after 30 days). Idempotent."""


def up(con):
    have = {r[1] for r in con.execute("PRAGMA table_info(orgs)")}
    if "sf_type" not in have:
        con.execute("ALTER TABLE orgs ADD COLUMN sf_type TEXT")
    if "website" not in have:
        con.execute("ALTER TABLE orgs ADD COLUMN website TEXT")
    con.execute("CREATE TABLE IF NOT EXISTS org_logos (domain TEXT PRIMARY KEY, file TEXT, width INTEGER, source TEXT, fetched_at TEXT NOT NULL)")
