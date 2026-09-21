"""Project rule packs: deterministic SQL assertions and KPIs over verified source databases.

Pack format is TOML (stdlib, offline-friendly). Project knowledge lives in packs, never in xl2ai/.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import time
import tomllib

from .core.config import load_config
from .core.errors import Xl2aiError
from .core.runs import current_run_id
from .core.sqliteutil import install_readonly_authorizer

TABLE_TOKEN = re.compile(r"\{\{table:([^/{}]+)/([^{}]+)\}\}")


def q(name):
    return '"' + str(name).replace('"', '""') + '"'


def load_pack(path):
    file = os.path.join(path, "pack.toml") if os.path.isdir(path) else path
    try:
        with open(file, "rb") as f:
            raw = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise Xl2aiError("E_RULE", f"cannot load pack {file}: {e}") from None
    meta = raw.get("pack", {})
    name = str(meta.get("name", "")).strip()
    version = str(meta.get("version", "")).strip()
    if not name or not version:
        raise Xl2aiError("E_RULE", f"{file}: [pack] needs non-empty name and version")
    return {"file": file, "name": name, "version": version,
            "rules": list(raw.get("rule", [])), "kpis": list(raw.get("kpi", [])),
            "terms": list(raw.get("term", [])), "keys": list(raw.get("key", [])),
            "relations": list(raw.get("relation", []))}


def _maps(catalog, run_dir):
    rows = catalog.execute("SELECT source_id,table_name,db_rel,table_id FROM _tables ORDER BY source_id,table_name").fetchall()
    dbs, tables = {}, {}
    for source_id, table_name, db_rel, table_id in rows:
        if db_rel not in dbs:
            dbs[db_rel] = f"d{len(dbs)}"
        key = f"{source_id}/{table_name}"
        if key in tables:
            raise Xl2aiError("E_RULE", f"ambiguous table selector {key}", "use unique source aliases/table names")
        tables[key] = (dbs[db_rel], table_name, table_id)
    return dbs, tables


def _table_ref(tables, selector):
    selector = str(selector or "").strip()
    if selector not in tables:
        raise Xl2aiError("E_RULE", f"unknown table selector: {selector}")
    return tables[selector]


def _column_id(writer, table_id, name):
    row = writer.execute("SELECT column_id FROM _columns WHERE table_id=? AND name=?", (table_id, str(name))).fetchone()
    if not row:
        raise Xl2aiError("E_RULE", f"column '{name}' not found in table {table_id}")
    return row[0]


def _apply_confirmations(writer, tables, pack):
    for item in pack["keys"]:
        _, _, table_id = _table_ref(tables, item.get("table"))
        names = item.get("columns", [])
        if not isinstance(names, list) or not names:
            raise Xl2aiError("E_RULE", f"{pack['file']}: [[key]] needs a non-empty columns list")
        column_ids = [_column_id(writer, table_id, n) for n in names]
        kid = hashlib.sha1((table_id + "|" + "|".join(column_ids)).encode()).hexdigest()[:20]
        old = writer.execute("SELECT uniqueness,null_rate FROM _keys WHERE id=?", (kid,)).fetchone()
        uniqueness, null_rate = old if old else (None, None)
        writer.execute("INSERT OR REPLACE INTO _keys VALUES (?,?,?,?,?,?,?,?)",
                       (kid, table_id, json.dumps(column_ids, separators=(",", ":")), uniqueness, null_rate,
                        "confirmed", "pack", 1.0))

    for item in pack["relations"]:
        _, _, from_table_id = _table_ref(tables, item.get("from_table"))
        _, _, to_table_id = _table_ref(tables, item.get("to_table"))
        from_id = _column_id(writer, from_table_id, item.get("from_column"))
        to_id = _column_id(writer, to_table_id, item.get("to_column"))
        rid = hashlib.sha1(f"{from_id}|{to_id}".encode()).hexdigest()[:20]
        old = writer.execute("SELECT containment FROM _relationships WHERE id=?", (rid,)).fetchone()
        containment = old[0] if old else None
        evidence = json.dumps({"pack": pack["name"], "pack_version": pack["version"]}, separators=(",", ":"))
        writer.execute("INSERT OR REPLACE INTO _relationships VALUES (?,?,?,?,?,?,?,?,?)",
                       (rid, from_id, to_id, str(item.get("kind", "reference")), containment,
                        "confirmed", "pack", 1.0, evidence))


def _resolve_sql(sql, tables):
    if not isinstance(sql, str) or not sql.strip():
        raise Xl2aiError("E_RULE", "rule/KPI sql must be a non-empty string")
    def repl(m):
        key = f"{m.group(1)}/{m.group(2)}"
        if key not in tables:
            raise Xl2aiError("E_RULE", f"unknown table selector in SQL: {key}")
        alias, table_name, _ = tables[key]
        return f"{q(alias)}.{q(table_name)}"
    out = TABLE_TOKEN.sub(repl, sql).strip()
    low = out.lstrip().lower()
    if not (low.startswith("select") or low.startswith("with")):
        raise Xl2aiError("E_RULE", "pack SQL must be SELECT/WITH only")
    if ";" in out.rstrip(";"):
        raise Xl2aiError("E_RULE", "pack SQL must contain exactly one statement")
    return out.rstrip(";")


def _query_connection(run_dir, dbs, timeout_s):
    con = sqlite3.connect(":memory:", uri=True)
    for db_rel, alias in dbs.items():
        uri = f"file:{os.path.abspath(os.path.join(run_dir, db_rel.replace('/', os.sep)))}?mode=ro"
        con.execute(f"ATTACH DATABASE ? AS {q(alias)}", (uri,))
    con.execute("PRAGMA query_only=ON")
    install_readonly_authorizer(con)
    deadline = time.monotonic() + timeout_s
    con.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 2000)
    return con


def _scalar(con, sql):
    row = con.execute(sql).fetchone()
    return None if row is None else row[0]


def _expect(value, expect):
    if expect == "zero":
        return value == 0
    if expect == "nonzero":
        return value not in (None, 0, 0.0, "", False)
    if expect == "true":
        return bool(value)
    if expect == "not_null":
        return value is not None
    if expect.startswith("equals:"):
        target = expect.split(":", 1)[1]
        return str(value) == target
    raise Xl2aiError("E_RULE", f"unknown expectation '{expect}'")


def run_packs(cfg, run_id, catalog_path=None):
    run_dir = os.path.join(cfg.runs_dir, run_id)
    path = catalog_path or os.path.join(run_dir, "catalog.db")
    if not os.path.isfile(path):
        raise Xl2aiError("E_STAGE_INPUT", "catalog not found")
    writer = sqlite3.connect(path)
    try:
        writer.execute("DELETE FROM _rule_results")
        writer.execute("DELETE FROM _kpi_results")
        writer.execute("DELETE FROM _dictionary WHERE origin='pack'")
        dbs, tables = _maps(writer, run_dir)
        packs = [load_pack(p) for p in cfg.pack_paths()]
        for pack in packs:
            _apply_confirmations(writer, tables, pack)
            for item in pack["terms"]:
                term = str(item.get("term", "")).strip()
                meaning = str(item.get("meaning", "")).strip()
                if not term or not meaning:
                    raise Xl2aiError("E_RULE", f"{pack['file']}: [[term]] needs term and meaning")
                writer.execute("INSERT OR REPLACE INTO _dictionary VALUES (?,?,?,?,?,?,?,?,?)",
                               (term, meaning, json.dumps(item.get("aliases", []), ensure_ascii=False, separators=(",", ":")),
                                str(item.get("unit", "")), str(item.get("applies_to", "")),
                                str(item.get("status", "confirmed")), "pack", pack["name"], pack["version"]))
            qc = _query_connection(run_dir, dbs, cfg.ai["query_timeout"])
            try:
                for item in pack["rules"]:
                    rid = str(item.get("id", "")).strip()
                    if not rid:
                        raise Xl2aiError("E_RULE", f"{pack['file']}: rule missing id")
                    severity = str(item.get("severity", "warn"))
                    expected = str(item.get("expect", "zero"))
                    message = str(item.get("message", ""))
                    try:
                        sql = _resolve_sql(item.get("sql"), tables)
                        actual = _scalar(qc, sql)
                        ok = _expect(actual, expected)
                        status = "pass" if ok else "fail"
                        evidence = json.dumps({"sql": sql}, ensure_ascii=False, separators=(",", ":"))
                    except Exception as e:
                        if isinstance(e, Xl2aiError):
                            err = e.message
                        else:
                            err = f"{type(e).__name__}: {e}"
                        actual, status, evidence = err, "error", "{}"
                    writer.execute("INSERT OR REPLACE INTO _rule_results VALUES (?,?,?,?,?,?,?,?,?)",
                                   (rid, pack["name"], pack["version"], status, expected, str(actual),
                                    severity, message, evidence))
                for item in pack["kpis"]:
                    kid = str(item.get("id", "")).strip()
                    if not kid:
                        raise Xl2aiError("E_RULE", f"{pack['file']}: KPI missing id")
                    sql = _resolve_sql(item.get("sql"), tables)
                    value = _scalar(qc, sql)
                    writer.execute("INSERT OR REPLACE INTO _kpi_results VALUES (?,?,?,?,?,?,?,?)",
                                   (kid, pack["name"], pack["version"], None if value is None else str(value),
                                    str(item.get("unit", "")), json.dumps(item.get("dims", {}), separators=(",", ":")),
                                    os.path.basename(pack["file"]),
                                    json.dumps({"sql": sql}, ensure_ascii=False, separators=(",", ":"))))
            finally:
                qc.close()
        writer.commit()
    finally:
        writer.close()
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(prog="xl2ai rules", description="Run configured deterministic rule packs and KPIs.")
    ap.add_argument("--config")
    ap.add_argument("--run")
    args = ap.parse_args(argv)
    try:
        cfg = load_config(args.config)
        rid = args.run or current_run_id(cfg)
        if not rid:
            raise Xl2aiError("E_STAGE_INPUT", "no current run")
        run_packs(cfg, rid)
    except Xl2aiError as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
