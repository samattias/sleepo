"""Extract profile photos from the BambooHR org chart PDF and attach them to people.

Each photo sits directly above the name in its box, so a photo is matched to the text block whose top is just below
the image and whose x-range overlaps the image centre. BambooHR's grey placeholder appears many times with identical
pixels and is skipped. Photos are stored outside OneDrive, 96x96 JPEG:
  ~/Library/Application Support/Assist/avatars/<person_id>.jpg

  assist import-avatars [pdf]
"""
import hashlib
from collections import Counter
from pathlib import Path

from . import db

AVATARS = db.db_path().parent / "avatars"


def import_avatars(con, pdf):
    import fitz
    AVATARS.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(str(pdf))
    pg = doc[0]
    infos = pg.get_image_info(xrefs=True)
    blocks = [b for b in pg.get_text("blocks") if b[4].strip()]
    def signature(pm):
        """8x8 greyscale fingerprint, quantised: identical for re-encoded copies of the same placeholder."""
        g = fitz.Pixmap(fitz.csGRAY, pm) if pm.n - pm.alpha != 1 else pm
        if g.alpha:
            g = fitz.Pixmap(g, 0)
        small = fitz.Pixmap(g, 16, 16, None)
        return list(small.samples)
    pix_hash = {}
    for i in infos:
        pm = fitz.Pixmap(doc, i["xref"])
        pix_hash[i["xref"]] = signature(pm)
    def dist(a, b):
        return sum(abs(x - y) for x, y in zip(a, b)) / len(a)
    keys = list(pix_hash)
    uses = Counter(i["xref"] for i in infos)  # the placeholder is one shared image drawn in many boxes
    placeholder = {k for k in keys if uses[k] > 2 or sum(1 for o in keys if o != k and dist(pix_hash[k], pix_hash[o]) < 6) >= 2}
    matched, skipped = 0, 0
    for i in infos:
        x0, y0, x1, y1 = i["bbox"]
        cx = (x0 + x1) / 2
        below = [b for b in blocks if b[1] >= y1 - 2 and b[1] - y1 < 25 and b[0] - 5 <= cx <= b[2] + 5]
        if not below:
            continue
        name = sorted(below, key=lambda b: b[1])[0][4].strip().splitlines()[0]
        name = {"Jory Quayle": "Jory Quayle"}.get(name, name)
        pid = db.resolve_person(con, name)
        if not pid:
            continue
        if i["xref"] in placeholder:
            skipped += 1
            con.execute("UPDATE people SET avatar=NULL WHERE id=?", (pid,))
            continue
        pm = fitz.Pixmap(doc, i["xref"])
        if pm.n - pm.alpha >= 4:
            pm = fitz.Pixmap(fitz.csRGB, pm)
        if pm.alpha:
            pm = fitz.Pixmap(pm, 0)
        out = AVATARS / f"{pid}.jpg"
        img = fitz.Pixmap(pm, 96, 96, None) if pm.width > 96 else pm
        img.save(str(out), jpg_quality=82) if hasattr(img, "save") else None
        con.execute("UPDATE people SET avatar=? WHERE id=?", (out.name, pid))
        matched += 1
    con.commit()
    return matched, skipped
