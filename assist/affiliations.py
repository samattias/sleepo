"""Classify every person: employee, former employee, partner, customer, investor/board, advisor, vendor.

Employees come from the org chart (the BambooHR extract is the list of current staff); an Acme person not on it has left,
unless Sam says otherwise (Sam, 12 Oct 2026). Someone Sam says has left is a former employee even while the last export
still lists them: they come off the org chart (not active, no org source, no manager), so they leave his team counts. Everyone else is set from what the meetings, mail and knowledge base say;
unknowns default to 'unclassified' so they are visible rather than guessed.

  assist classify-people
"""
from . import db, profile
from . import org as orgpack   # classify() has its own variable named org

KNOWN = {k: tuple(v) for k, v in orgpack.section("known_people", {}).items()}   # former staff and outside contacts (the org pack)


def classify(con):
    n = 0
    for r in con.execute("SELECT id, name, org_source, is_me FROM people").fetchall():
        if r["is_me"]:
            aff, org, note = "employee", orgpack.name() or None, profile.get(con)["role"] or None
        elif r["name"] in KNOWN:
            aff, org, note = KNOWN[r["name"]]
        elif r["org_source"]:
            aff, org, note = "employee", orgpack.name() or None, None
        else:
            aff, org, note = "unclassified", None, None
        org_id = None
        if org:
            row = con.execute("SELECT id FROM orgs WHERE name=?", (org,)).fetchone()
            kind = "internal" if org == orgpack.name() else orgpack.section("company_kinds", {}).get(org, aff)
            org_id = row["id"] if row else con.execute("INSERT INTO orgs (name, kind) VALUES (?, ?)", (org, kind)).lastrowid
        con.execute("UPDATE people SET affiliation=?, affiliation_note=COALESCE(?, affiliation_note), org_id=? WHERE id=?",
                    (aff, note, org_id, r["id"]))
        if aff == "former employee":
            con.execute("UPDATE people SET active=0, org_source=NULL, manager_id=NULL WHERE id=?", (r["id"],))
        n += 1
    con.commit()
    return n
