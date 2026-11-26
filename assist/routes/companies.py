"""Companies (assist/companies.py, Sam, 23 Oct 2026): People › Companies, the list, one company's page, its logo
(assist/logos.py), and Sam's calls on what a company is to Acme, its name and which records are one company."""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .. import companies, logos
from ..web import _nocache, con, json_only

router = APIRouter()


class Relation(BaseModel):
    relation: Optional[str] = None   # partner | customer | prospect | investor | vendor | other | hidden; None: SleePO decides


class Name(BaseModel):
    name: str


class Merge(BaseModel):
    into: Optional[int] = None       # the company it is the same as; None undoes a merge


@router.get("/api/companies")
def api_companies():
    c = con()
    try:
        return _nocache({"companies": companies.listing(c), "labels": companies.LABEL})
    finally:
        c.close()


@router.get("/api/companies/search")   # before /{oid}: "search" is not a company id
def api_companies_search(q: str = ""):
    c = con()
    try:
        return _nocache(companies.search(c, q[:80]))
    finally:
        c.close()


@router.get("/api/companies/{oid}")
def api_company(oid: int):
    c = con()
    try:
        p = companies.page(c, oid)
        if not p:
            raise HTTPException(404, "No such company.")
        return _nocache(p)
    finally:
        c.close()


@router.post("/api/companies/{oid}/relation", dependencies=[Depends(json_only)])
def api_company_relation(oid: int, body: Relation):
    c = con()
    try:
        companies.set_relation(c, oid, body.relation or None)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@router.post("/api/companies/{oid}/merge", dependencies=[Depends(json_only)])
def api_company_merge(oid: int, body: Merge):
    c = con()
    try:
        companies.merge(c, oid, body.into)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()


@router.get("/api/companies/{oid}/logo")
def api_company_logo(oid: int):
    """The company's cached logo (a file under Application Support/Assist/logos). The address carries a version, so the
    browser may keep it; an SVG may not run anything."""
    c = con()
    try:
        orgs = companies._orgs(c)
        if oid not in orgs:
            raise HTTPException(404, "No such company.")
        rid = companies.root(orgs, oid)
        d = logos.domains(c, orgs, {rid: [m for m in orgs if companies.root(orgs, m) == rid]}).get(rid)
        f = logos.cached(c).get(d[0]) if d else None
    finally:
        c.close()
    path = (logos.LOGO_DIR / f[0]).resolve() if f else None
    if not path or path.parent != logos.LOGO_DIR.resolve() or not path.is_file():
        raise HTTPException(404, "No logo for this company.")
    return FileResponse(path, media_type=logos.TYPES.get(path.suffix[1:], "application/octet-stream"),
                        headers={"Cache-Control": "private, max-age=604800", "X-Content-Type-Options": "nosniff",
                                 "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox"})


@router.post("/api/companies/{oid}/name", dependencies=[Depends(json_only)])
def api_company_name(oid: int, body: Name):
    c = con()
    try:
        companies.rename(c, oid, body.name)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(400, str(e))
    finally:
        c.close()
