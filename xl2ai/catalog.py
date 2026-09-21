"""Build the run-level catalog: a small registry that gives every extracted table/column a stable identity.

The catalog never copies business rows. It stores metadata and points query/analysis stages at the verified per-source
SQLite databases created by extraction.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys

from .core.config import load_config
from .core.errors import Xl2aiError
from .core.runs import current_run_id, load_manifest

DDL = """
CREATE TABLE _catalog_meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE _sources (
  source_id TEXT PRIMARY KEY, path TEXT, sha256 TEXT, size INTEGER, mtime TEXT, hash_mode TEXT,
  db_rel TEXT NOT NULL, reused INTEGER NOT NULL DEFAULT 0, reused_from_run TEXT
);
CREATE TABLE _tables (
  table_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, sheet_name TEXT NOT NULL, table_name TEXT NOT NULL,
  db_rel TEXT NOT NULL, row_count INTEGER NOT NULL, column_count INTEGER NOT NULL, header_row INTEGER,
  visibility TEXT, schema_fingerprint TEXT NOT NULL
);
CREATE TABLE _columns (
  column_id TEXT PRIMARY KEY, table_id TEXT NOT NULL, position INTEGER NOT NULL, name TEXT NOT NULL,
  original_header TEXT, xl_col INTEGER, xl_col_letter TEXT, sql_type TEXT, kind TEXT,
  non_null INTEGER, error_cells INTEGER
);
CREATE TABLE _table_profiles (
  table_id TEXT PRIMARY KEY, row_count INTEGER NOT NULL, row_fingerprint TEXT, row_hash_mode TEXT
);
CREATE TABLE _profile_columns (
  column_id TEXT PRIMARY KEY, n INTEGER, nulls INTEGER, distinct_count INTEGER, min_value TEXT, max_value TEXT,
  mean REAL, top_k TEXT, sample TEXT
);
CREATE TABLE _dq_findings (
  id TEXT PRIMARY KEY, code TEXT, severity TEXT, table_id TEXT, column_id TEXT, count INTEGER,
  examples TEXT, message TEXT
);
CREATE TABLE _keys (
  id TEXT PRIMARY KEY, table_id TEXT, columns_json TEXT, uniqueness REAL, null_rate REAL,
  status TEXT, method TEXT, score REAL
);
CREATE TABLE _relationships (
  id TEXT PRIMARY KEY, from_column TEXT, to_column TEXT, kind TEXT, containment REAL,
  status TEXT, method TEXT, score REAL, evidence TEXT
);
CREATE TABLE _dictionary (
  term TEXT, meaning TEXT, aliases TEXT, unit TEXT, applies_to TEXT, status TEXT, origin TEXT,
  pack TEXT, pack_version TEXT, PRIMARY KEY(term, pack)
);
CREATE TABLE _rule_results (
  rule_id TEXT, pack TEXT, pack_version TEXT, status TEXT, expected TEXT, actual TEXT,
  severity TEXT, message TEXT, evidence TEXT, PRIMARY KEY(rule_id, pack)
);
CREATE TABLE _kpi_results (
  kpi_id TEXT, pack TEXT, pack_version TEXT, value TEXT, unit TEXT, dims TEXT,
  definition_ref TEXT, evidence TEXT, PRIMARY KEY(kpi_id, pack)
);
CREATE TABLE _changes (
  id TEXT PRIMARY KEY, kind TEXT, severity TEXT, subject TEXT, before_value TEXT, after_value TEXT, evidence TEXT
);
CREATE INDEX idx_columns_table ON _columns(table_id);
CREATE INDEX idx_tables_source ON _tables(source_id);
CREATE INDEX idx_dq_table ON _dq_findings(table_id);
CREATE INDEX idx_rel_from ON _relationships(from_column);
"""


def q(name):
    return '"' + str(name).replace('"', '""') + '"'


def _ro(path):
    return sqlite3.connect(f"file:{os.path.abspath(path)}?mode=ro", uri=True)


def _schema_fingerprint(columns):
    body = [(int(c["position"]), c["sql_name"], c["sql_type"], c["kind"], int(c["xl_col"])) for c in columns]
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _extract_stage(manifest):
    return next((s for s in manifest.get("stages", []) if s.get("name") == "extract"), None)


def build_catalog(cfg, run_id, manifest=None):
    manifest = manifest or load_manifest(cfg, run_id)
    stage = _extract_stage(manifest)
    if not stage or stage.get("status") != "passed":
        raise Xl2aiError("E_STAGE_INPUT", "catalog needs a passed extract stage")
    run_dir = os.path.join(cfg.runs_dir, run_id)
    out = os.path.join(run_dir, "catalog.db")
    partial = out + ".partial"
    for p in (partial, partial + "-journal"):
        try:
            os.remove(p)
        except FileNotFoundError:
            pass

    inputs = {x["source_id"]: x for x in manifest.get("inputs", [])}
    con = sqlite3.connect(partial)
    try:
        con.executescript(DDL)
        con.execute("INSERT INTO _catalog_meta VALUES (?,?)", ("run_id", run_id))
        con.execute("INSERT INTO _catalog_meta VALUES (?,?)", ("contract_version", str(manifest.get("contract_version", ""))))
        for rec in stage.get("details", {}).get("sources", []):
            if rec.get("exit_code") != 0 or not rec.get("db"):
                continue
            sid = rec["source_id"]
            inp = inputs.get(sid, {})
            con.execute("INSERT INTO _sources VALUES (?,?,?,?,?,?,?,?,?)",
                        (sid, inp.get("path"), inp.get("sha256"), inp.get("size"), inp.get("mtime"), inp.get("hash_mode"),
                         rec["db"], int(bool(rec.get("reused"))), rec.get("reused_from_run")))
            srcdb = os.path.join(run_dir, rec["db"].replace("/", os.sep))
            with _ro(srcdb) as src:
                logs = src.execute("""SELECT sheet_name, table_name, data_rows, columns, header_row, visibility
                                      FROM _extraction_log
                                      WHERE status='extracted' AND table_name IS NOT NULL
                                      ORDER BY sheet_index""").fetchall()
                seen = {}
                for sheet_name, table_name, rows, ncols, header_row, visibility in logs:
                    col_rows = src.execute("""SELECT position, sql_name, original_header, xl_col, xl_col_letter,
                                                     sql_type, kind, non_null, error_cells
                                              FROM _columns WHERE table_name=? ORDER BY position""", (table_name,)).fetchall()
                    cols = [{"position": r[0], "sql_name": r[1], "original_header": r[2], "xl_col": r[3],
                             "xl_col_letter": r[4], "sql_type": r[5], "kind": r[6], "non_null": r[7],
                             "error_cells": r[8]} for r in col_rows]
                    fp = _schema_fingerprint(cols)
                    seen[fp] = seen.get(fp, 0) + 1
                    suffix = "" if seen[fp] == 1 else f"-{seen[fp]}"
                    table_id = f"{sid}/{fp[:12]}{suffix}"
                    con.execute("INSERT INTO _tables VALUES (?,?,?,?,?,?,?,?,?,?)",
                                (table_id, sid, sheet_name, table_name, rec["db"], int(rows or 0), int(ncols or len(cols)),
                                 header_row, visibility, fp))
                    for c in cols:
                        column_id = f"{table_id}.c{int(c['position'])}"
                        con.execute("INSERT INTO _columns VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                                    (column_id, table_id, int(c["position"]), c["sql_name"], c["original_header"],
                                     c["xl_col"], c["xl_col_letter"], c["sql_type"], c["kind"],
                                     c["non_null"], c["error_cells"]))
        con.commit()
        con.execute("PRAGMA optimize")
    finally:
        con.close()
    os.replace(partial, out)
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(prog="xl2ai catalog", description="Build/rebuild catalog.db for a completed extraction run.")
    ap.add_argument("--config")
    ap.add_argument("--run", help="run id; default is current promoted run")
    args = ap.parse_args(argv)
    try:
        cfg = load_config(args.config)
        rid = args.run or current_run_id(cfg)
        if not rid:
            raise Xl2aiError("E_STAGE_INPUT", "no current run; run refresh first")
        path = build_catalog(cfg, rid)
    except Xl2aiError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
