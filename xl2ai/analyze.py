"""Profile verified tables, surface generic data-quality findings, infer candidate keys, and fingerprint rows."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import sys

from .core.config import load_config
from .core.errors import Xl2aiError
from .core.runs import current_run_id


NULL_TOKENS = ("n/a", "na", "null", "none", "-", "--", "nil", "(blank)", "blank")


def q(name):
    return '"' + str(name).replace('"', '""') + '"'


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)


def _finding_id(code, subject):
    return hashlib.sha1(f"{code}|{subject}".encode()).hexdigest()[:20]


def _ro(path):
    return sqlite3.connect(f"file:{os.path.abspath(path)}?mode=ro", uri=True)


def _value(v):
    if v is None:
        return None
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return str(v)
    return v


def _row_fingerprint(src, table_name, row_count, max_rows):
    if max_rows <= 0 or row_count > max_rows:
        return None, "omitted"
    h = hashlib.sha256()
    cur = src.execute(f"SELECT * FROM {q(table_name)} ORDER BY _xl_row")
    for row in cur:
        h.update(_json([_value(v) for v in row]).encode("utf-8", "surrogatepass"))
        h.update(b"\n")
    return h.hexdigest(), "ordered_sha256"


def _column_profile(src, table_name, name, sql_type, kind, row_count, top_k, sample_values):
    col = q(name)
    n, distinct_count = src.execute(
        f"SELECT COUNT({col}), COUNT(DISTINCT {col}) FROM {q(table_name)}"
    ).fetchone()
    nulls = max(0, int(row_count) - int(n or 0))
    mn = mx = mean = None
    if n:
        mn, mx = src.execute(f"SELECT MIN({col}), MAX({col}) FROM {q(table_name)} WHERE {col} IS NOT NULL").fetchone()
        if str(sql_type).upper() in ("INTEGER", "REAL") and kind not in ("date", "datetime", "time"):
            mean = src.execute(f"SELECT AVG({col}) FROM {q(table_name)} WHERE {col} IS NOT NULL").fetchone()[0]
    top = src.execute(
        f"SELECT {col}, COUNT(*) c FROM {q(table_name)} WHERE {col} IS NOT NULL "
        f"GROUP BY {col} ORDER BY c DESC, {col} LIMIT ?", (top_k,)
    ).fetchall()
    sample = src.execute(
        f"SELECT DISTINCT {col} FROM {q(table_name)} WHERE {col} IS NOT NULL LIMIT ?", (sample_values,)
    ).fetchall()
    return {
        "n": int(n or 0), "nulls": nulls, "distinct": int(distinct_count or 0),
        "min": _value(mn), "max": _value(mx), "mean": _value(mean),
        "top": [[_value(v), int(c)] for v, c in top], "sample": [_value(x[0]) for x in sample],
    }


def _add_finding(con, code, severity, table_id, column_id, count, examples, message):
    subject = column_id or table_id
    con.execute("INSERT OR REPLACE INTO _dq_findings VALUES (?,?,?,?,?,?,?,?)",
                (_finding_id(code, subject), code, severity, table_id, column_id, int(count or 0),
                 _json(examples or []), message))


def analyze_catalog(cfg, run_id, catalog_path=None):
    run_dir = os.path.join(cfg.runs_dir, run_id)
    path = catalog_path or os.path.join(run_dir, "catalog.db")
    if not os.path.isfile(path):
        raise Xl2aiError("E_STAGE_INPUT", f"catalog not found: {path}", "run catalog first")

    con = sqlite3.connect(path)
    try:
        con.execute("DELETE FROM _profile_columns")
        con.execute("DELETE FROM _table_profiles")
        con.execute("DELETE FROM _dq_findings")
        con.execute("DELETE FROM _keys")
        tables = con.execute("""SELECT table_id,table_name,db_rel,row_count FROM _tables ORDER BY table_id""").fetchall()
        for table_id, table_name, db_rel, row_count in tables:
            src_path = os.path.join(run_dir, db_rel.replace("/", os.sep))
            with _ro(src_path) as src:
                row_fp, row_mode = _row_fingerprint(src, table_name, int(row_count), cfg.analysis["row_hash_max_rows"])
                con.execute("INSERT INTO _table_profiles VALUES (?,?,?,?)",
                            (table_id, int(row_count), row_fp, row_mode))
                cols = con.execute("""SELECT column_id,name,sql_type,kind,non_null,error_cells,original_header
                                      FROM _columns WHERE table_id=? ORDER BY position""", (table_id,)).fetchall()
                candidate_cols = []
                for column_id, name, sql_type, kind, non_null, error_cells, original_header in cols:
                    p = _column_profile(src, table_name, name, sql_type, kind, int(row_count),
                                        cfg.analysis["top_k"], cfg.analysis["sample_values"])
                    con.execute("INSERT INTO _profile_columns VALUES (?,?,?,?,?,?,?,?,?)",
                                (column_id, p["n"], p["nulls"], p["distinct"],
                                 None if p["min"] is None else str(p["min"]),
                                 None if p["max"] is None else str(p["max"]),
                                 p["mean"], _json(p["top"]), _json(p["sample"])))

                    if row_count and p["nulls"] / row_count >= 0.5:
                        sev = "error" if p["nulls"] / row_count >= 0.9 else "warn"
                        _add_finding(con, "DQ_HIGH_NULL", sev, table_id, column_id, p["nulls"], p["sample"],
                                     f"{p['nulls']} of {row_count} rows are null")
                    if p["n"] > 1 and p["distinct"] == 1:
                        _add_finding(con, "DQ_CONSTANT", "info", table_id, column_id, p["n"], p["sample"],
                                     "column has one non-null value")
                    if int(error_cells or 0):
                        _add_finding(con, "DQ_EXCEL_ERRORS", "warn", table_id, column_id, int(error_cells), [],
                                     "Excel error cells were stored as NULL; inspect source _cell_errors")
                    if kind == "mixed":
                        _add_finding(con, "DQ_MIXED_TYPE", "warn", table_id, column_id, p["n"], p["sample"],
                                     "column contains mixed value types")
                    if original_header is None:
                        _add_finding(con, "DQ_GENERATED_HEADER", "info", table_id, column_id, 1, [name],
                                     "column name was generated because no header text was available")
                    if str(sql_type).upper() in ("TEXT", "BLOB") and p["n"]:
                        marks = ",".join("?" * len(NULL_TOKENS))
                        cnt = src.execute(
                            f"SELECT COUNT(*) FROM {q(table_name)} WHERE LOWER(TRIM(CAST({q(name)} AS TEXT))) "
                            f"IN ({marks})", NULL_TOKENS).fetchone()[0]
                        if cnt:
                            ex = src.execute(
                                f"SELECT DISTINCT {q(name)} FROM {q(table_name)} WHERE "
                                f"LOWER(TRIM(CAST({q(name)} AS TEXT))) IN ({marks}) LIMIT 3", NULL_TOKENS
                            ).fetchall()
                            _add_finding(con, "DQ_NULL_TOKEN", "warn", table_id, column_id, cnt,
                                         [x[0] for x in ex], "text values look like null markers; no coercion was applied")

                    if row_count > 1 and p["n"]:
                        uniq = p["distinct"] / max(1, row_count)
                        null_rate = p["nulls"] / max(1, row_count)
                        if uniq >= 0.98 and null_rate <= 0.02:
                            kid = hashlib.sha1(f"{table_id}|{column_id}".encode()).hexdigest()[:20]
                            con.execute("INSERT INTO _keys VALUES (?,?,?,?,?,?,?,?)",
                                        (kid, table_id, _json([column_id]), uniq, null_rate,
                                         "inferred", "single_column_uniqueness", min(1.0, uniq)))
                        if uniq >= 0.10 and null_rate <= 0.10:
                            candidate_cols.append((column_id, name, uniq, null_rate))

                # Try a small number of composite candidates only when there is no near-perfect single key.
                have_single = con.execute(
                    "SELECT 1 FROM _keys WHERE table_id=? AND method='single_column_uniqueness' LIMIT 1",
                    (table_id,)).fetchone()
                if not have_single and 1 < len(candidate_cols) <= 12 and row_count <= max(200_000, cfg.analysis["row_hash_max_rows"]):
                    for i in range(min(6, len(candidate_cols))):
                        for j in range(i + 1, min(6, len(candidate_cols))):
                            c1, n1, _, _ = candidate_cols[i]
                            c2, n2, _, _ = candidate_cols[j]
                            distinct_pair = src.execute(
                                f"SELECT COUNT(*) FROM (SELECT {q(n1)},{q(n2)} FROM {q(table_name)} "
                                f"WHERE {q(n1)} IS NOT NULL AND {q(n2)} IS NOT NULL GROUP BY {q(n1)},{q(n2)})"
                            ).fetchone()[0]
                            uniq = distinct_pair / max(1, row_count)
                            if uniq >= 0.98:
                                null_pair = src.execute(
                                    f"SELECT COUNT(*) FROM {q(table_name)} WHERE {q(n1)} IS NULL OR {q(n2)} IS NULL"
                                ).fetchone()[0] / max(1, row_count)
                                kid = hashlib.sha1(f"{table_id}|{c1}|{c2}".encode()).hexdigest()[:20]
                                con.execute("INSERT INTO _keys VALUES (?,?,?,?,?,?,?,?)",
                                            (kid, table_id, _json([c1, c2]), uniq, null_pair,
                                             "inferred", "composite_uniqueness", min(1.0, uniq)))
                                break
                        else:
                            continue
                        break
        con.commit()
    finally:
        con.close()
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(prog="xl2ai analyze", description="Profile columns, detect generic quality issues, infer keys.")
    ap.add_argument("--config")
    ap.add_argument("--run")
    args = ap.parse_args(argv)
    try:
        cfg = load_config(args.config)
        rid = args.run or current_run_id(cfg)
        if not rid:
            raise Xl2aiError("E_STAGE_INPUT", "no current run")
        analyze_catalog(cfg, rid)
    except Xl2aiError as e:
        print(str(e), file=sys.stderr)
        return 1
    print(os.path.join(cfg.runs_dir, rid, "catalog.db"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
