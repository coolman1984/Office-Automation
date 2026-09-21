"""Read-only, capped query tools for AI and humans. Raw Excel is never touched here."""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time

from .core.config import load_config
from .core.errors import Xl2aiError
from .core.runs import current_run_id
from .core.sqliteutil import ro_connection


def q(name):
    return '"' + str(name).replace('"', '""') + '"'


def _run_paths(cfg, run_id=None):
    rid = run_id or current_run_id(cfg)
    if not rid:
        raise Xl2aiError("E_STAGE_INPUT", "no current run")
    run_dir = os.path.join(cfg.runs_dir, rid)
    cat = os.path.join(run_dir, "catalog.db")
    if not os.path.isfile(cat):
        raise Xl2aiError("E_STAGE_INPUT", "catalog not found")
    return rid, run_dir, cat


def _catalog(cat):
    return ro_connection(cat)


def _resolve_table(cat, selector):
    rows = cat.execute("""SELECT table_id,source_id,sheet_name,table_name,db_rel
                          FROM _tables WHERE table_id=? OR (source_id||'/'||table_name)=?
                             OR sheet_name=? OR table_name=? ORDER BY table_id""",
                       (selector,selector,selector,selector)).fetchall()
    if not rows:
        raise Xl2aiError("E_STAGE_INPUT", f"table not found: {selector}", "run xl2ai query schema")
    if len(rows) > 1:
        exact = [r for r in rows if r[0] == selector or f"{r[1]}/{r[3]}" == selector]
        if len(exact) == 1:
            return exact[0]
        raise Xl2aiError("E_STAGE_INPUT", f"ambiguous table selector: {selector}", "use table_id or source_id/table_name")
    return rows[0]


def _source_db(run_dir, db_rel):
    path=os.path.join(run_dir,db_rel.replace("/",os.sep))
    return ro_connection(path)


def _envelope(tool, columns, rows, started, cfg, evidence=None, total_rows=None, truncated=False, hint=""):
    out={"ok":True,"tool":tool,"columns":columns,"rows":rows,"row_count":len(rows),"total_rows":total_rows,
         "truncated":bool(truncated),"bytes":0,"elapsed_ms":round((time.perf_counter()-started)*1000,2),
         "hint":hint,"evidence":evidence or []}
    out["bytes"]=len(json.dumps(out["rows"],ensure_ascii=False,default=str).encode())
    return out


def _cap_rows(cur, cfg):
    rows=[]
    columns=[d[0] for d in cur.description or []]
    truncated=False
    for row in cur:
        candidate=rows+[list(row)]
        size=len(json.dumps(candidate,ensure_ascii=False,default=str).encode())
        if len(candidate)>cfg.ai["query_rows"] or size>cfg.ai["query_bytes"]:
            truncated=True
            break
        rows=candidate
    return columns,rows,truncated


def schema(cfg, run_id=None):
    started=time.perf_counter()
    rid,run_dir,catp=_run_paths(cfg,run_id)
    with _catalog(catp) as cat:
        rows=[]
        for tid,sid,sheet,table,nrows in cat.execute(
            "SELECT table_id,source_id,sheet_name,table_name,row_count FROM _tables ORDER BY table_id"):
            cols=[r[0] for r in cat.execute("SELECT name FROM _columns WHERE table_id=? ORDER BY position",(tid,))]
            rows.append([tid,sid,sheet,table,nrows,cols])
        rels=cat.execute("SELECT COUNT(*) FROM _relationships").fetchone()[0]
    return _envelope("schema",["table_id","source_id","sheet","table","rows","columns"],rows,started,cfg,
                     evidence=[{"run_id":rid}],hint=f"{rels} inferred relationship(s); use describe for one table")


def describe(cfg, selector, run_id=None):
    started=time.perf_counter()
    rid,run_dir,catp=_run_paths(cfg,run_id)
    with _catalog(catp) as cat:
        t=_resolve_table(cat,selector)
        tid=t[0]
        rows=cat.execute("""SELECT c.position,c.name,c.original_header,c.sql_type,c.kind,
                                  p.n,p.nulls,p.distinct_count,p.min_value,p.max_value,p.mean,p.top_k,p.sample
                           FROM _columns c LEFT JOIN _profile_columns p ON p.column_id=c.column_id
                           WHERE c.table_id=? ORDER BY c.position""",(tid,)).fetchall()
        findings=cat.execute("SELECT code,severity,message FROM _dq_findings WHERE table_id=? ORDER BY severity,code",(tid,)).fetchall()
        keys=cat.execute("SELECT columns_json,uniqueness,status FROM _keys WHERE table_id=? ORDER BY uniqueness DESC",(tid,)).fetchall()
    outrows=[list(r[:-2])+[json.loads(r[-2] or "[]"),json.loads(r[-1] or "[]")] for r in rows]
    return _envelope("describe",
        ["position","name","original_header","sql_type","kind","n","nulls","distinct","min","max","mean","top_k","sample"],
        outrows,started,cfg,evidence=[{"run_id":rid,"table_id":tid}],
        hint=f"findings={findings}; keys={keys}")


def sample(cfg, selector, limit=None, run_id=None):
    started=time.perf_counter()
    rid,run_dir,catp=_run_paths(cfg,run_id)
    with _catalog(catp) as cat:
        tid,sid,sheet,table,db_rel=_resolve_table(cat,selector)
    lim=min(int(limit or cfg.ai["query_rows"]),cfg.ai["query_rows"])
    with _source_db(run_dir,db_rel) as src:
        cur=src.execute(f"SELECT * FROM {q(table)} LIMIT ?",(lim+1,))
        columns,rows,truncated=_cap_rows(cur,cfg)
    return _envelope("sample",columns,rows,started,cfg,evidence=[{"run_id":rid,"source_id":sid,"sheet":sheet,"table_id":tid}],
                     truncated=truncated)


def aggregate(cfg, selector, column, op="count", group_by=None, run_id=None):
    started=time.perf_counter()
    rid,run_dir,catp=_run_paths(cfg,run_id)
    op=op.lower()
    if op not in {"count","sum","avg","min","max"}:
        raise Xl2aiError("E_NOT_ALLOWED",f"aggregate not allowed: {op}")
    with _catalog(catp) as cat:
        tid,sid,sheet,table,db_rel=_resolve_table(cat,selector)
        names={r[0] for r in cat.execute("SELECT name FROM _columns WHERE table_id=?",(tid,))}
    if column!="*" and column not in names:
        raise Xl2aiError("E_STAGE_INPUT",f"column not found: {column}")
    if group_by and group_by not in names:
        raise Xl2aiError("E_STAGE_INPUT",f"group-by column not found: {group_by}")
    target="*" if column=="*" else q(column)
    expr=f"{op.upper()}({target})"
    sql_text=(f"SELECT {q(group_by)}, {expr} AS value FROM {q(table)} GROUP BY {q(group_by)} "
              f"ORDER BY value DESC LIMIT {cfg.ai['query_rows']+1}") if group_by else f"SELECT {expr} AS value FROM {q(table)}"
    with _source_db(run_dir,db_rel) as src:
        cur=src.execute(sql_text)
        columns,rows,truncated=_cap_rows(cur,cfg)
    return _envelope("aggregate",columns,rows,started,cfg,evidence=[{"run_id":rid,"source_id":sid,"table_id":tid}],
                     truncated=truncated)


def compare(cfg, kind=None, run_id=None):
    """Return the bounded run-to-run differences already computed by the deterministic change stage."""
    started=time.perf_counter()
    rid,run_dir,catp=_run_paths(cfg,run_id)
    with _catalog(catp) as cat:
        if kind:
            cur=cat.execute("""SELECT kind,severity,subject,before_value,after_value,evidence
                               FROM _changes WHERE kind=? ORDER BY severity,subject""",(kind,))
        else:
            cur=cat.execute("""SELECT kind,severity,subject,before_value,after_value,evidence
                               FROM _changes ORDER BY kind,severity,subject""")
        columns,rows,truncated=_cap_rows(cur,cfg)
    decoded=[]
    for row in rows:
        decoded.append(row[:3]+[json.loads(x) if x else None for x in row[3:]])
    return _envelope("compare",columns,decoded,started,cfg,evidence=[{"run_id":rid}],truncated=truncated)


def trace(cfg, selector, xl_row, run_id=None):
    started=time.perf_counter()
    rid,run_dir,catp=_run_paths(cfg,run_id)
    with _catalog(catp) as cat:
        tid,sid,sheet,table,db_rel=_resolve_table(cat,selector)
    with _source_db(run_dir,db_rel) as src:
        cur=src.execute(f"SELECT * FROM {q(table)} WHERE _xl_row=? LIMIT 2",(int(xl_row),))
        columns,rows,truncated=_cap_rows(cur,cfg)
    return _envelope("trace",columns,rows,started,cfg,
                     evidence=[{"run_id":rid,"source_id":sid,"sheet":sheet,"table_id":tid,"xl_row":int(xl_row)}],
                     truncated=truncated)


def sql(cfg, source_id, statement, run_id=None):
    started=time.perf_counter()
    rid,run_dir,catp=_run_paths(cfg,run_id)
    s=statement.strip()
    low=s.lower()
    if not (low.startswith("select") or low.startswith("with")) or ";" in s.rstrip(";"):
        raise Xl2aiError("E_NOT_ALLOWED","SQL must be exactly one SELECT/WITH statement")
    with _catalog(catp) as cat:
        rows=cat.execute("SELECT db_rel FROM _sources WHERE source_id=?",(source_id,)).fetchall()
    if len(rows)!=1:
        raise Xl2aiError("E_STAGE_INPUT",f"source not found: {source_id}")
    with _source_db(run_dir,rows[0][0]) as src:
        src.execute("PRAGMA query_only=ON")
        deadline=time.monotonic()+cfg.ai["query_timeout"]
        src.set_progress_handler(lambda:1 if time.monotonic()>deadline else 0,2000)
        try:
            cur=src.execute(s.rstrip(";"))
            columns,data,truncated=_cap_rows(cur,cfg)
        except sqlite3.DatabaseError as e:
            raise Xl2aiError("E_NOT_ALLOWED",f"query rejected: {e}") from None
    return _envelope("sql",columns,data,started,cfg,evidence=[{"run_id":rid,"source_id":source_id}],truncated=truncated)


def _print(obj):
    print(json.dumps(obj,ensure_ascii=False,indent=1,default=str))


def main(argv=None):
    ap=argparse.ArgumentParser(prog="xl2ai query",description="Read-only capped query tools.")
    ap.add_argument("--config")
    sub=ap.add_subparsers(dest="cmd",required=True)
    sub.add_parser("schema")
    d=sub.add_parser("describe")
    d.add_argument("table")
    s=sub.add_parser("sample")
    s.add_argument("table")
    s.add_argument("--limit",type=int)
    a=sub.add_parser("aggregate")
    a.add_argument("table")
    a.add_argument("column")
    a.add_argument("--op",default="count")
    a.add_argument("--group-by")
    c=sub.add_parser("compare")
    c.add_argument("--kind")
    t=sub.add_parser("trace")
    t.add_argument("table")
    t.add_argument("xl_row",type=int)
    x=sub.add_parser("sql")
    x.add_argument("source_id")
    x.add_argument("statement")
    args=ap.parse_args(argv)
    try:
        cfg=load_config(args.config)
        if args.cmd=="schema":
            out=schema(cfg)
        elif args.cmd=="describe":
            out=describe(cfg,args.table)
        elif args.cmd=="sample":
            out=sample(cfg,args.table,args.limit)
        elif args.cmd=="aggregate":
            out=aggregate(cfg,args.table,args.column,args.op,args.group_by)
        elif args.cmd=="compare":
            out=compare(cfg,args.kind)
        elif args.cmd=="trace":
            out=trace(cfg,args.table,args.xl_row)
        else:
            out=sql(cfg,args.source_id,args.statement)
    except Xl2aiError as e:
        _print({"ok":False,"error":e.as_dict()})
        return 1
    _print(out)
    return 0


if __name__=="__main__":
    sys.exit(main())
