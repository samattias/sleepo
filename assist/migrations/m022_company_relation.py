"""Companies (assist/companies.py, Sam, 23 Oct 2026): Sam's own calls on an organisation.
orgs.relation: what the company is to Acme when Sam says so (partner, customer, prospect, investor, vendor, other); it wins
over what SleePO works out from Salesforce deals and the records kept by hand.
orgs.merged_into: one company recorded twice (a Salesforce account and the mail domain of the same company, two records of
one partner) is shown once, under the record it was merged into. Idempotent."""


def up(con):
    have = {r[1] for r in con.execute("PRAGMA table_info(orgs)")}
    if "relation" not in have:
        con.execute("ALTER TABLE orgs ADD COLUMN relation TEXT")
    if "merged_into" not in have:
        con.execute("ALTER TABLE orgs ADD COLUMN merged_into INTEGER REFERENCES orgs(id) ON DELETE SET NULL")
