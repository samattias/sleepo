"""Import the Acme knowledge base (the Obsidian vault published at kb.svc.staging.acmecloud.com).

Source id 'acme-kb'. One item per note (kind 'doc', full text kept: the KB is org-public), external_id = vault path.
The vault copy lives in Documents/acme-kb; the staging site itself sits behind Entra ID login, so the local copy is
the readable version until the "Acme Development Mind Knowledgebase" MCP connector is authenticated.

  assist import-kb [path]
"""
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import db
from . import org

_KB = org.section("kb", {})   # the org pack: the company knowledge base
DEFAULT_VAULT = db.ASSIST.parent / (_KB.get("folder") or "kb")
FM = re.compile(r"^---\n(.*?)\n---\n", re.S)


def import_kb(con, vault=None):
    vault = Path(vault) if vault else DEFAULT_VAULT
    if not vault.exists():
        raise SystemExit(f"vault not found: {vault}")
    db.upsert_source(con, {"id": "acme-kb", "system": "acme-kb", "name": _KB.get("name") or "Knowledge base", "vendor": _KB.get("vendor") or org.name(),
                           "kind": "Org knowledge base: people, roadmap, products, tech stack, processes",
                           "how": f"Local copy of the Obsidian vault behind {_KB.get('site')} (Entra ID login). Imported file by file; the "
                                  f"'{_KB.get('connector')}' MCP connector can refresh it from the live site once authenticated.",
                           "auth": "Entra ID on the site; MCP connector OAuth", "connect": "Local vault imported; live refresh via MCP pending authentication",
                           "color": "#1f3a5f", "mono": "KB", "logo": "acme", "health": "stale", "sort": 55})
    files = sorted(p for p in vault.rglob("*.md") if ".obsidian" not in p.parts and p.name != "CLAUDE.md")
    pull = db.start_pull(con, "acme-kb", "assist import-kb", note=f"vault {vault.name}: {len(files)} notes")
    newest = None
    n_new = 0
    for p in files:
        raw = p.read_text(errors="replace")
        meta, body = {}, raw
        m = FM.match(raw)
        if m:
            for line in m.group(1).splitlines():
                if ":" in line and not line.startswith((" ", "-")):
                    k, v = line.split(":", 1)
                    meta[k.strip()] = v.strip().strip('"')
            body = raw[m.end():]
        title = next((l[2:].strip() for l in body.splitlines() if l.startswith("# ")), p.stem)
        rel = str(p.relative_to(vault))
        folder = rel.split("/")[0] if "/" in rel else "(root)"
        date = meta.get("date") if re.match(r"\d{4}-\d{2}-\d{2}$", meta.get("date", "")) else None
        mtime = datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)
        ts = (date + "T00:00:00Z") if date else mtime.strftime("%Y-%m-%dT%H:%M:%SZ")
        newest = max(newest or ts, ts)
        _, created = db.upsert_item(con, "acme-kb", rel, "doc", ts, pull_id=pull, from_name=folder, subject=title,
                                    text=(meta.get("description") or "") + ("\n\n" + body.strip() if body.strip() else ""),
                                    thread=rel, url=f"https://{_KB.get('site')}/" + rel.replace(" ", "%20").replace(".md", ""),
                                    payload={"frontmatter": meta, "bytes": len(raw)}, retention="general")
        n_new += created
        db.upsert_document(con, "kb/" + rel, "Knowledge base", title, body, "acme-kb/" + rel, meta)
    db.finish_pull(con, pull, available=len(files), pulled=len(files))
    con.execute(f"UPDATE sources SET window_from='{_KB.get('since') or ''}', window_to=?, note=? WHERE id='acme-kb'",
                (newest[:10] if newest else None, f"{len(files)} notes imported from the local vault; newest dated {newest[:10] if newest else '—'}. "
                                                   "The site may be more current; refresh through the MCP connector when authenticated."))
    con.execute("INSERT INTO docs_fts(docs_fts) VALUES ('rebuild')")
    con.commit()
    return len(files), n_new
