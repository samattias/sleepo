"""Numbered schema/data migrations, applied in order by db.migrate().

Each module is named mNNN_<what>.py and defines up(con). The applied version is recorded in schema_version, so each
migration runs once. Never edit an applied migration; add a new one. Keep them idempotent all the same.
"""
import importlib
import pkgutil
import re


def available():
    out = []
    for m in pkgutil.iter_modules(__path__):
        g = re.match(r"^m(\d{3})_", m.name)
        if g:
            out.append((int(g.group(1)), m.name))
    return sorted(out)


def apply(con, current, now, log=print):
    done = []
    for num, name in available():
        if num <= current:
            continue
        mod = importlib.import_module(f"{__name__}.{name}")
        mod.up(con)
        con.execute("INSERT INTO schema_version(version, applied_at) VALUES (?, ?)", (num, now()))
        con.commit()
        log(f"migration {num} applied: {name}")
        done.append(num)
    return done
