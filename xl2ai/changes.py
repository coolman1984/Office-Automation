"""Compare a run with the previous trusted run: sources, schema, volume, content fingerprints, categories and KPIs."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys

from .core.config import load_config
from .core.errors import Xl2aiError
from .core.fsutil import read_json
from .core.runs import current_run_id


def _id(kind, subject):
    return hashlib.sha1(f"{kind}|{subject}".encode()).hexdigest()[:20]


def _previous(cfg, run_id):
    cur = current_run_id(cfg)
    if cur and cur != run_id:
        return cur
    try:
        ptr = read_json(cfg.current_file)
        return ptr.get("previous") if ptr.get("run_id") == run_id else cur
    except (OSError, ValueError):
        return cur


def _insert(con, kind, severity, subject, before, after, evidence=None):
    con.execute("INSERT OR REPLACE INTO _changes VALUES (?,?,?,?,?,?,?)",
                (_id(kind, subject), kind, severity, subject,
                 json.dumps(before, ensure_ascii=False, separators=(",", ":"), default=str),
                 json.dumps(after, ensure_ascii=False, separators=(",", ":"), default=str),
                 json.dumps(evidence or {}, ensure_ascii=False, separators=(",", ":"), default=str)))


def detect_changes(cfg, run_id, previous_run_id=None, catalog_path=None):
    run_dir = os.path.join(cfg.runs_dir, run_id)
    path = catalog_path or os.path.join(run_dir, "catalog.db")
    if not os.path.isfile(path):
        raise Xl2aiError("E_STAGE_INPUT", "current catalog not found")
    prev_id = previous_run_id if previous_run_id is not None else _previous(cfg, run_id)
    con = sqlite3.connect(path)
    try:
        con.execute("DELETE FROM _changes")
        if not prev_id:
            _insert(con, "baseline", "info", "run", None, run_id)
            con.commit()
            return path
        prev_path = os.path.join(cfg.runs_dir, prev_id, "catalog.db")
        if not os.path.isfile(prev_path):
            _insert(con, "baseline", "info", "run", prev_id, run_id, {"reason": "previous catalog unavailable"})
            con.commit()
            return path
        prev = sqlite3.connect(f"file:{os.path.abspath(prev_path)}?mode=ro", uri=True)
        try:
            old_sources = {r[0]: r[1] for r in prev.execute("SELECT source_id,sha256 FROM _sources")}
            new_sources = {r[0]: r[1] for r in con.execute("SELECT source_id,sha256 FROM _sources")}
            for sid in sorted(set(old_sources) | set(new_sources)):
                if sid not in old_sources:
                    _insert(con, "source", "info", sid, None, new_sources[sid])
                elif sid not in new_sources:
                    _insert(con, "source", "warn", sid, old_sources[sid], None)
                elif old_sources[sid] != new_sources[sid]:
                    _insert(con, "source", "info", sid, old_sources[sid], new_sources[sid])

            def tmap(db):
                rows = db.execute("""SELECT table_id,source_id,sheet_name,row_count,schema_fingerprint
                                     FROM _tables""").fetchall()
                return {(r[1], r[2]): r for r in rows}
            old_t, new_t = tmap(prev), tmap(con)
            for key in sorted(set(old_t) | set(new_t)):
                subject = f"{key[0]}/{key[1]}"
                if key not in old_t:
                    _insert(con, "schema", "info", subject, None, {"table_id": new_t[key][0]})
                    continue
                if key not in new_t:
                    _insert(con, "schema", "warn", subject, {"table_id": old_t[key][0]}, None)
                    continue
                o, n = old_t[key], new_t[key]
                if o[4] != n[4]:
                    _insert(con, "schema", "warn", subject, o[4], n[4])
                if int(o[3]) != int(n[3]):
                    base = max(1, int(o[3]))
                    ratio = abs(int(n[3]) - int(o[3])) / base
                    _insert(con, "volume", "warn" if ratio >= 0.2 else "info", subject, int(o[3]), int(n[3]),
                            {"change_ratio": round(ratio, 6)})
                old_fp = prev.execute("SELECT row_fingerprint,row_hash_mode FROM _table_profiles WHERE table_id=?", (o[0],)).fetchone()
                new_fp = con.execute("SELECT row_fingerprint,row_hash_mode FROM _table_profiles WHERE table_id=?", (n[0],)).fetchone()
                if old_fp and new_fp and old_fp[0] and new_fp[0] and old_fp[0] != new_fp[0]:
                    _insert(con, "value", "info", subject, old_fp[0], new_fp[0],
                            {"mode_before": old_fp[1], "mode_after": new_fp[1]})

                old_cols = {r[0]: r[1] for r in prev.execute(
                    """SELECT c.name,p.top_k FROM _columns c JOIN _profile_columns p ON p.column_id=c.column_id
                       WHERE c.table_id=?""", (o[0],))}
                new_cols = {r[0]: r[1] for r in con.execute(
                    """SELECT c.name,p.top_k FROM _columns c JOIN _profile_columns p ON p.column_id=c.column_id
                       WHERE c.table_id=?""", (n[0],))}
                for col in sorted(set(old_cols) & set(new_cols)):
                    if old_cols[col] != new_cols[col]:
                        _insert(con, "category", "info", f"{subject}.{col}",
                                json.loads(old_cols[col] or "[]"), json.loads(new_cols[col] or "[]"))

            old_k = {(r[0],r[1]): r[2] for r in prev.execute("SELECT kpi_id,pack,value FROM _kpi_results")}
            new_k = {(r[0],r[1]): r[2] for r in con.execute("SELECT kpi_id,pack,value FROM _kpi_results")}
            for key in sorted(set(old_k) | set(new_k)):
                subject = f"{key[1]}/{key[0]}"
                if old_k.get(key) != new_k.get(key):
                    _insert(con, "kpi", "info", subject, old_k.get(key), new_k.get(key))
        finally:
            prev.close()
        con.commit()
    finally:
        con.close()
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(prog="xl2ai changes", description="Compare a run with its previous trusted run.")
    ap.add_argument("--config")
    ap.add_argument("--run")
    ap.add_argument("--previous")
    args = ap.parse_args(argv)
    try:
        cfg = load_config(args.config)
        rid = args.run or current_run_id(cfg)
        if not rid:
            raise Xl2aiError("E_STAGE_INPUT", "no current run")
        detect_changes(cfg, rid, args.previous)
    except Xl2aiError as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
