"""Load an org chart into people: titles, departments, locations, reporting lines.

Source: BambooHR org chart export (PDF, 6 Oct 2026). Text gives name/title/department/location per box; reporting
lines were read from the chart layout and are encoded below (manager -> reports). Re-run after a new export. People who have left since
the export (affiliations.KNOWN, former employee) are taken off it by affiliations.classify at the end.

  assist import-orgchart [pdf]
"""
import re
from pathlib import Path

from . import db
from . import org

_CHART = org.section("org_chart", {})   # the org pack: the HR export's reporting lines, titles and name fixes
TREE = _CHART.get("tree", {})
FULL_TITLES = _CHART.get("titles", {})   # titles truncated in the export, completed by hand
ALIASES = _CHART.get("name_fixes", {})


def parse_pdf(path):
    from pypdf import PdfReader
    lines = [l.strip() for l in PdfReader(str(path)).pages[0].extract_text().splitlines() if l.strip()]
    people, i = [], 0
    while i + 3 < len(lines):
        name, title, dept, loc = lines[i:i + 4]
        i += 4
        if i < len(lines) and re.fullmatch(r"\d+", lines[i]):
            i += 1
        name = ALIASES.get(name, name)
        title = re.sub(r"[^\x20-\x7E\u00C0-\u017F&’'(),.\-]", "", title).rstrip("…").strip()
        people.append({"name": name, "title": FULL_TITLES.get(name, title), "department": dept, "location": loc})
    return people


def import_orgchart(con, pdf):
    rows = parse_pdf(pdf)
    ids = {}
    for r in rows:
        pid = db.resolve_person(con, r["name"]) or db.get_or_create_person(con, r["name"], aliases=[r["name"].split()[0]])
        con.execute("UPDATE people SET title=?, department=?, location=?, org_source=?, active=1, role=COALESCE(role, ?) WHERE id=?",
                    (r["title"], r["department"], r["location"], _CHART.get("source") or "org chart", r["title"], pid))
        ids[r["name"]] = pid
    links = 0
    for mgr, reports in TREE.items():
        for rep in reports:
            if mgr in ids and rep in ids:
                con.execute("UPDATE people SET manager_id=? WHERE id=?", (ids[mgr], ids[rep]))
                links += 1
    # KB page link where a profile exists
    for r in con.execute("SELECT external_id, url FROM items WHERE source_id='acme-kb' AND external_id LIKE '%/people/%'").fetchall():
        nm = Path(r["external_id"]).stem
        pid = db.resolve_person(con, nm) or db.resolve_person(con, nm.replace("-", " "))
        if pid:
            con.execute("UPDATE people SET kb_url=? WHERE id=?", (r["url"], pid))
    # people not on the chart are kept but marked
    con.execute("UPDATE people SET active=0 WHERE org_source IS NULL AND is_me=0")
    from . import affiliations
    affiliations.classify(con)
    con.commit()
    return len(rows), links
