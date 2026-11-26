"""Search by meaning (Sam, 28 Oct 2026; option A of the mem0 review): a small embedding model on this Mac turns text into
vectors, so search, the context packs and what SleePO remembers (assist/remember.py) find things said in other words
("price list" for "SKU", a French or Japanese line for an English question).

Local only: fastembed runs an ONNX model on the CPU. The model is downloaded once from Hugging Face by `embed-sync` (only
the model files travel; no text leaves the Mac) into Application Support/Assist/models; the server never downloads (a
search loads the model only when it is already there). Vectors live in their own file, vectors.db next to assist.db: a
derived index, rebuilt from search_fts and the memories at any time, and outside the database so writing it does not make
every open tab reload (/api/events watches assist.db). It follows the index: a row purged from search_fts is dropped here
on the next sync. Without fastembed installed (`~/.assist/venv/bin/pip install fastembed`) everything here returns nothing
and search stays keyword-only.

  assist embed-sync      embed what is new or changed in the search index and the memories, drop what is gone
"""
import hashlib
import os
import sqlite3
import threading

from . import db

MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"   # 384 dimensions; English, French, Japanese and more
DIR = db.db_path().parent
PATH = DIR / "vectors.db"
MODELS = DIR / "models"
BODY = 1000          # characters of a body embedded after the title
MIN_SIM = 0.45       # below this a match by meaning is noise for this model

_lock = threading.Lock()
_model = {"m": None, "tried": 0}
_cache = {"mtime": None, "keys": [], "kinds": [], "ts": [], "mat": None}


def available():
    """fastembed and numpy are installed."""
    try:
        import fastembed  # noqa: F401
        import numpy  # noqa: F401
        return True
    except Exception:
        return False


def _load(download=False):
    """The model, or None. Without download it loads only from the local copy (never fetches from inside a request); a
    failed try is retried after five minutes, so the server picks up a model `embed-sync` fetched meanwhile."""
    import time
    with _lock:
        if _model["m"] is not None or (not download and time.time() - (_model["tried"] or 0) < 300):
            return _model["m"]
        _model["tried"] = time.time()
        if not available():
            return None
        from fastembed import TextEmbedding
        try:
            _model["m"] = TextEmbedding(model_name=MODEL, cache_dir=str(MODELS), **({} if download else {"local_files_only": True}))
        except TypeError:   # an older fastembed without local_files_only: only load a copy that is already here
            _model["m"] = TextEmbedding(model_name=MODEL, cache_dir=str(MODELS)) if download or any(MODELS.glob("*")) else None
        except Exception:
            _model["m"] = None
        return _model["m"]


def vectors(texts, download=False):
    """Unit-length float32 vectors, one row per text, or None when no model."""
    m = _load(download)
    if m is None:
        return None
    import numpy as np
    v = np.array(list(m.embed([t or " " for t in texts], batch_size=64)), dtype=np.float32)
    n = np.linalg.norm(v, axis=1, keepdims=True)
    n[n == 0] = 1
    return v / n


def _vcon():
    c = sqlite3.connect(PATH)
    c.execute("CREATE TABLE IF NOT EXISTS vec (key TEXT PRIMARY KEY, kind TEXT, ts TEXT, hash TEXT, model TEXT, v BLOB)")
    return c


def _key(kind, ref):
    return f"{kind}\t{ref}"


def _wanted(con):
    """{key: (kind, ts, text)}: every search_fts row and every active memory."""
    from . import search
    search.ensure_fresh(con)
    out = {}
    for r in con.execute("SELECT kind, ref, title, substr(body, 1, ?) AS body, ts FROM search_fts", (BODY,)):
        out[_key(r["kind"], r["ref"])] = (r["kind"], r["ts"] or "", f"{r['title'] or ''}\n{r['body'] or ''}".strip())
    if db.has_table(con, "memories"):
        for r in con.execute("SELECT id, text, created_at FROM memories WHERE status='active'"):
            out[_key("memory", r["id"])] = ("memory", r["created_at"] or "", r["text"] or "")
    return out


def sync(con, log=print, limit=None):
    """Embed new and changed rows, drop rows that are gone. Downloads the model the first time."""
    if not available():
        log("embed: fastembed is not installed (~/.assist/venv/bin/pip install fastembed); search stays keyword-only")
        return {"available": False}
    want = _wanted(con)
    vc = _vcon()
    have = {k: (h, m) for k, h, m in vc.execute("SELECT key, hash, model FROM vec")}
    gone = [k for k in have if k not in want]
    todo = []
    for k, (kind, ts, text) in want.items():
        h = hashlib.sha1(text.encode()).hexdigest()[:16]
        if have.get(k) != (h, MODEL):
            todo.append((k, kind, ts, h, text))
    if limit:
        todo = todo[:limit]
    if todo and _load(download=True) is None:
        log("embed: the model could not be loaded")
        return {"available": True, "error": "model not loaded"}
    for i in range(0, len(todo), 256):
        chunk = todo[i:i + 256]
        v = vectors([t[4] for t in chunk])
        vc.executemany("INSERT OR REPLACE INTO vec (key, kind, ts, hash, model, v) VALUES (?,?,?,?,?,?)",
                       [(k, kind, ts, h, MODEL, v[j].tobytes()) for j, (k, kind, ts, h, _) in enumerate(chunk)])
        vc.commit()
    if gone:
        vc.executemany("DELETE FROM vec WHERE key=?", [(k,) for k in gone])
        vc.commit()
    vc.close()
    if todo or gone:
        log(f"embed: {len(todo)} embedded, {len(gone)} dropped, {len(want)} in the index")
    return {"available": True, "embedded": len(todo), "dropped": len(gone), "total": len(want)}


def _matrix():
    """The vectors in memory, reloaded when vectors.db changes."""
    try:
        mtime = os.path.getmtime(PATH)
    except OSError:
        return None
    if _cache["mtime"] != mtime:
        import numpy as np
        c = _vcon()
        rows = c.execute("SELECT key, kind, ts, v FROM vec WHERE model=?", (MODEL,)).fetchall()
        c.close()
        _cache.update(mtime=mtime, keys=[r[0] for r in rows], kinds=[r[1] for r in rows], ts=[r[2] for r in rows],
                      mat=np.vstack([np.frombuffer(r[3], dtype=np.float32) for r in rows]) if rows else None)
    return _cache["mat"]


def query(text, k=40, kinds=None, after=None, before=None, min_sim=MIN_SIM):
    """[(kind, ref, similarity)], best first, or [] when search by meaning is off. Reads only; never downloads."""
    if not (text or "").strip() or not available() or not PATH.exists():
        return []
    try:
        mat = _matrix()
        if mat is None:
            return []
        q = vectors([text])
        if q is None:
            return []
        import numpy as np
        sims = mat @ q[0]
        out = []
        for i in np.argsort(-sims):
            s = float(sims[i])
            if s < min_sim or len(out) >= k:
                break
            kind = _cache["kinds"][i]
            if (kinds and kind not in kinds) or (after and _cache["ts"][i] < after) or (before and _cache["ts"][i] > before):
                continue
            out.append((kind, _cache["keys"][i].split("\t", 1)[1], round(s, 3)))
        return out
    except Exception:
        return []
