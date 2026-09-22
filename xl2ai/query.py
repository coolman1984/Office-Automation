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
from .core.sqliteutil import install_readonly_authorizer, ro_connection


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


def _cap_values(rows, cfg, row_limit=None):
    limit=cfg.ai["query_rows"] if row_limit is None else row_limit
    kept=[]
    truncated=False
    for row in rows:
        candidate=kept+[list(row)]
        size=len(json.dumps(candidate,ensure_ascii=False,default=str).encode())
        if len(candidate)>limit or size>cfg.ai["query_bytes"]:
            truncated=True
            break
        kept=candidate
    return kept,truncated


def _cap_rows(cur, cfg, row_limit=None):
    columns=[d[0] for d in cur.description or []]
    rows,truncated=_cap_values(cur,cfg,row_limit)
    return columns,rows,truncated


def _run_capped(src, sql_text, params, cfg, row_limit=None):
    """Execute a query built by this module and cap it, turning any SQLite failure into a normal Xl2aiError
    envelope instead of an uncaught traceback (the tools are meant to fail cleanly for an AI/CLI caller)."""
    try:
        cur=src.execute(sql_text,params)
        return _cap_rows(cur,cfg,row_limit)
    except sqlite3.DatabaseError as e:
        raise Xl2aiError("E_STAGE_INPUT",f"query failed: {e}") from None


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
    rows,truncated=_cap_values(rows,cfg)
    return _envelope("schema",["table_id","source_id","sheet","table","rows","columns"],rows,started,cfg,
                     evidence=[{"run_id":rid}],truncated=truncated,
                     hint=f"{rels} relationship(s); use describe for one table")


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
        findings=cat.execute("SELECT COUNT(*) FROM _dq_findings WHERE table_id=?",(tid,)).fetchone()[0]
        keys=cat.execute("SELECT COUNT(*) FROM _keys WHERE table_id=?",(tid,)).fetchone()[0]
    outrows=[list(r[:-2])+[json.loads(r[-2] or "[]"),json.loads(r[-1] or "[]")] for r in rows]
    outrows,truncated=_cap_values(outrows,cfg)
    return _envelope("describe",
        ["position","name","original_header","sql_type","kind","n","nulls","distinct","min","max","mean","top_k","sample"],
        outrows,started,cfg,evidence=[{"run_id":rid,"table_id":tid}],truncated=truncated,
        hint=f"quality_findings={findings}; candidate_or_confirmed_keys={keys}; use query meta quality/keys for details")


def sample(cfg, selector, limit=None, run_id=None):
    started=time.perf_counter()
    rid,run_dir,catp=_run_paths(cfg,run_id)
    with _catalog(catp) as cat:
        tid,sid,sheet,table,db_rel=_resolve_table(cat,selector)
    lim=max(1,min(int(limit or cfg.ai["query_rows"]),cfg.ai["query_rows"]))
    with _source_db(run_dir,db_rel) as src:
        columns,rows,truncated=_run_capped(src,f"SELECT * FROM {q(table)} LIMIT ?",(lim+1,),cfg,row_limit=lim)
    return _envelope("sample",columns,rows,started,cfg,evidence=[{"run_id":rid,"source_id":sid,"sheet":sheet,"table_id":tid}],
                     truncated=truncated)


def repaired(cfg, selector, limit=None, run_id=None):
    """Same rows as `sample`, but with any `_repairs` suggestions applied in the response only.

    The extracted database is never touched: this reads raw rows and rewrites cells in the returned envelope,
    strictly by (xl_row, column) match against `_repairs`. Empty when [repair].enabled is false, since no
    suggestions were ever generated.
    """
    started = time.perf_counter()
    rid, run_dir, catp = _run_paths(cfg, run_id)
    with _catalog(catp) as cat:
        tid, sid, sheet, table, db_rel = _resolve_table(cat, selector)
        col_names = {r[0]: r[1] for r in cat.execute(
            "SELECT column_id,name FROM _columns WHERE table_id=?", (tid,)).fetchall()}
        repair_rows = cat.execute(
            "SELECT column_id,xl_row,repaired_value FROM _repairs WHERE table_id=?", (tid,)).fetchall()
    lim = max(1, min(int(limit or cfg.ai["query_rows"]), cfg.ai["query_rows"]))
    with _source_db(run_dir, db_rel) as src:
        columns, rows, truncated = _run_capped(src, f"SELECT * FROM {q(table)} LIMIT ?", (lim + 1,), cfg, row_limit=lim)
    repair_map = {}
    for column_id, xl_row, repaired_value in repair_rows:
        name = col_names.get(column_id)
        if name in columns:
            repair_map[(xl_row, name)] = repaired_value
    xl_idx = columns.index("_xl_row") if "_xl_row" in columns else None
    out_rows = []
    applied = 0
    for row in rows:
        row = list(row)
        if xl_idx is not None:
            xlr = row[xl_idx]
            for i, name in enumerate(columns):
                if (xlr, name) in repair_map:
                    row[i] = repair_map[(xlr, name)]
                    applied += 1
        out_rows.append(row)
    return _envelope("repaired", columns, out_rows, started, cfg,
                     evidence=[{"run_id": rid, "source_id": sid, "sheet": sheet, "table_id": tid}],
                     truncated=truncated, hint=f"{applied} cell(s) shown with a repair applied; raw values unchanged")


def aggregate(cfg, selector, column, op="count", group_by=None, run_id=None):
    started=time.perf_counter()
    rid,run_dir,catp=_run_paths(cfg,run_id)
    op=op.lower()
    if op not in {"count","sum","avg","min","max"}:
        raise Xl2aiError("E_NOT_ALLOWED",f"aggregate not allowed: {op}")
    if column=="*" and op!="count":
        raise Xl2aiError("E_STAGE_INPUT",f"op '{op}' needs a real column, not '*'","use --op count, or name a column")
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
        columns,rows,truncated=_run_capped(src,sql_text,(),cfg)
    return _envelope("aggregate",columns,rows,started,cfg,evidence=[{"run_id":rid,"source_id":sid,"table_id":tid}],
                     truncated=truncated)


META_SECTIONS = {"relationships", "definitions", "kpis", "rules", "quality", "keys", "unsupported",
                 "table_kind", "row_flags", "column_roles", "grain", "time_coverage", "duplicates", "repairs",
                 "regions", "header_groups", "lineage"}
NEWER_SECTIONS = {"regions": "_regions", "header_groups": "_header_groups", "lineage": "_lineage"}


def meta(cfg, section, run_id=None):
    """Return bounded catalog metadata that may be omitted from the context pack."""
    started=time.perf_counter()
    rid,run_dir,catp=_run_paths(cfg,run_id)
    section=str(section).lower()
    if section not in META_SECTIONS:
        raise Xl2aiError("E_STAGE_INPUT",f"unknown metadata section: {section}",
                         "use one of: " + ", ".join(sorted(META_SECTIONS)))
    with _catalog(catp) as cat:
        needed=NEWER_SECTIONS.get(section)
        if needed and not cat.execute("SELECT 1 FROM sqlite_master WHERE name=?",(needed,)).fetchone():
            return _envelope("meta",[],[],started,cfg,evidence=[{"run_id":rid,"section":section}],
                             hint=f"this run predates the {section} section; run xl2ai refresh to compute it")
        if section=="relationships":
            cur=cat.execute("""SELECT r.status,r.kind,ft.source_id,ft.table_name,fc.name,
                                      tt.source_id,tt.table_name,tc.name,r.containment,r.method,r.score
                               FROM _relationships r
                               JOIN _columns fc ON fc.column_id=r.from_column
                               JOIN _tables ft ON ft.table_id=fc.table_id
                               JOIN _columns tc ON tc.column_id=r.to_column
                               JOIN _tables tt ON tt.table_id=tc.table_id
                               ORDER BY r.status DESC,r.score DESC,r.id""")
        elif section=="definitions":
            cur=cat.execute("""SELECT term,meaning,aliases,unit,applies_to,status,origin,pack,pack_version
                               FROM _dictionary ORDER BY term,pack""")
        elif section=="kpis":
            cur=cat.execute("""SELECT kpi_id,pack,pack_version,value,unit,dims,definition_ref
                               FROM _kpi_results ORDER BY pack,kpi_id""")
        elif section=="rules":
            cur=cat.execute("""SELECT rule_id,pack,pack_version,status,expected,actual,severity,message
                               FROM _rule_results ORDER BY pack,rule_id""")
        elif section=="quality":
            cur=cat.execute("""SELECT code,severity,table_id,column_id,count,examples,message
                               FROM _dq_findings
                               ORDER BY CASE severity WHEN 'error' THEN 0 WHEN 'warn' THEN 1 ELSE 2 END,code,id""")
        elif section=="unsupported":
            cur=cat.execute("""SELECT scope,source_id,table_id,kind,count,detail
                               FROM _unsupported ORDER BY scope,kind""")
        elif section=="table_kind":
            cur=cat.execute("""SELECT table_id,kind,confidence,method,reasons
                               FROM _table_kind ORDER BY table_id""")
        elif section=="row_flags":
            cur=cat.execute("""SELECT table_id,xl_row,flag,detail
                               FROM _row_flags ORDER BY table_id,xl_row""")
        elif section=="column_roles":
            cur=cat.execute("""SELECT column_id,table_id,role,confidence,method,reasons,unit,currency
                               FROM _column_roles ORDER BY table_id,column_id""")
        elif section=="grain":
            cur=cat.execute("""SELECT table_id,columns_json,description,status,confidence,method
                               FROM _table_grain ORDER BY table_id""")
        elif section=="time_coverage":
            cur=cat.execute("""SELECT table_id,column_id,min_value,max_value
                               FROM _time_coverage ORDER BY table_id,column_id""")
        elif section=="duplicates":
            cur=cat.execute("""SELECT table_id_a,table_id_b,method,score,evidence
                               FROM _duplicate_candidates ORDER BY score DESC""")
        elif section=="regions":
            cur=cat.execute("""SELECT r.table_id,t.sheet_name,r.region_no,r.kind,r.first_row,r.first_col,r.last_row,
                                      r.last_col,r.header_row,r.cells,r.complete
                               FROM _regions r JOIN _tables t ON t.table_id=r.table_id
                               ORDER BY r.table_id,r.region_no""")
        elif section=="header_groups":
            cur=cat.execute("""SELECT g.table_id,c.name,g.path,g.method
                               FROM _header_groups g JOIN _columns c ON c.column_id=g.column_id
                               ORDER BY g.table_id,c.position""")
        elif section=="lineage":
            cur=cat.execute("""SELECT l.table_id,c.name,l.ref_kind,l.ref_workbook,l.ref_sheet,l.target_table_id,
                                      l.status,l.cells,l.method,l.sample
                               FROM _lineage l LEFT JOIN _columns c ON c.column_id=l.column_id
                               ORDER BY l.table_id,c.position,l.ref_sheet""")
        elif section=="repairs":
            cur=cat.execute("""SELECT table_id,column_id,xl_row,original_value,repaired_value,rule
                               FROM _repairs ORDER BY table_id,xl_row""")
        else:
            cur=cat.execute("""SELECT table_id,columns_json,uniqueness,null_rate,status,method,score
                               FROM _keys ORDER BY status DESC,score DESC,id""")
        columns,rows,truncated=_cap_rows(cur,cfg)

    json_cols={
        "definitions":{"aliases"},
        "kpis":{"dims"},
        "quality":{"examples"},
        "keys":{"columns_json"},
        "table_kind":{"reasons"},
        "column_roles":{"reasons"},
        "grain":{"columns_json"},
        "duplicates":{"evidence"},
        "header_groups":{"path"},
    }.get(section,set())
    if json_cols:
        indexes={name:i for i,name in enumerate(columns)}
        decoded=[]
        for row in rows:
            row=list(row)
            for name in json_cols:
                i=indexes[name]
                try:
                    row[i]=json.loads(row[i] or ("{}" if name=="dims" else "[]"))
                except (json.JSONDecodeError,TypeError):
                    pass
            decoded.append(row)
        rows=decoded
    return _envelope("meta",columns,rows,started,cfg,
                     evidence=[{"run_id":rid,"section":section}],
                     truncated=truncated,hint=f"catalog metadata section: {section}")


def region(cfg, selector, region_no, limit=None, run_id=None):
    """Rows of one detected table region, named by that region's own header row (see `meta regions`).

    A sheet holding several tables is stored as one wide table; this reads one of them back out on the fly --
    only the region's columns and rows, headers taken from the region's header row. The database is untouched.
    """
    started=time.perf_counter()
    rid,run_dir,catp=_run_paths(cfg,run_id)
    with _catalog(catp) as cat:
        tid,sid,sheet,table,db_rel=_resolve_table(cat,selector)
        if not cat.execute("SELECT 1 FROM sqlite_master WHERE name='_regions'").fetchone():
            raise Xl2aiError("E_STAGE_INPUT","this run predates region detection","run xl2ai refresh")
        reg=cat.execute("""SELECT first_row,first_col,last_row,last_col,header_row,kind FROM _regions
                           WHERE table_id=? AND region_no=?""",(tid,int(region_no))).fetchone()
        if not reg:
            n=cat.execute("SELECT COUNT(*) FROM _regions WHERE table_id=?",(tid,)).fetchone()[0]
            raise Xl2aiError("E_STAGE_INPUT",f"no region {region_no} in {tid}",
                             f"this table has {n} detected region(s); see query meta regions")
        table_hdr=cat.execute("SELECT header_row FROM _tables WHERE table_id=?",(tid,)).fetchone()[0]
        cols=cat.execute("""SELECT name,xl_col FROM _columns WHERE table_id=? AND xl_col BETWEEN ? AND ?
                            ORDER BY position""",(tid,reg[1],reg[3])).fetchall()
    r0,_,r1,_,hdr,kind=reg
    if not cols:
        return _envelope("region",[],[],started,cfg,evidence=[{"run_id":rid,"table_id":tid,"region":region_no}],
                         hint="the region's columns hold no stored data columns")
    lim=max(1,min(int(limit or cfg.ai["query_rows"]),cfg.ai["query_rows"]))
    names=[c[0] for c in cols]
    with _source_db(run_dir,db_rel) as src:
        if hdr is not None and hdr!=table_hdr:
            row=src.execute(f"SELECT {','.join(q(n) for n in names)} FROM {q(table)} WHERE _xl_row=?",(hdr,)).fetchone()
            if row:
                names_out=[str(v) if v is not None else n for v,n in zip(row,names)]
            else:
                names_out=names
            start=hdr+1
        else:
            names_out=names
            start=r0 if hdr is None else hdr+1
        columns,rows,truncated=_run_capped(src,
            f"SELECT _xl_row,{','.join(q(n) for n in names)} FROM {q(table)} WHERE _xl_row BETWEEN ? AND ? "
            f"ORDER BY _xl_row LIMIT ?",(start,r1,lim+1),cfg,row_limit=lim)
        total=src.execute(f"SELECT COUNT(*) FROM {q(table)} WHERE _xl_row BETWEEN ? AND ?",(start,r1)).fetchone()[0]
    return _envelope("region",["_xl_row"]+names_out,rows,started,cfg,
                     evidence=[{"run_id":rid,"source_id":sid,"sheet":sheet,"table_id":tid,"region":int(region_no),
                                "xl_rows":[start,r1]}],
                     total_rows=total,truncated=truncated,
                     hint=f"region {region_no} ({kind}) of {sheet}; column names come from its own header row")


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
        columns,rows,truncated=_run_capped(src,f"SELECT * FROM {q(table)} WHERE _xl_row=? LIMIT 2",(int(xl_row),),cfg)
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
        install_readonly_authorizer(src)
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
    ap.add_argument("--run",help="inspect a specific run id instead of the current trusted run")
    sub=ap.add_subparsers(dest="cmd",required=True)
    sub.add_parser("schema")
    d=sub.add_parser("describe")
    d.add_argument("table")
    s=sub.add_parser("sample")
    s.add_argument("table")
    s.add_argument("--limit",type=int)
    rp=sub.add_parser("repaired")
    rp.add_argument("table")
    rp.add_argument("--limit",type=int)
    a=sub.add_parser("aggregate")
    a.add_argument("table")
    a.add_argument("column")
    a.add_argument("--op",default="count")
    a.add_argument("--group-by")
    m=sub.add_parser("meta")
    m.add_argument("section",choices=sorted(META_SECTIONS))
    rg=sub.add_parser("region")
    rg.add_argument("table")
    rg.add_argument("region_no",type=int)
    rg.add_argument("--limit",type=int)
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
            out=schema(cfg,args.run)
        elif args.cmd=="describe":
            out=describe(cfg,args.table,args.run)
        elif args.cmd=="sample":
            out=sample(cfg,args.table,args.limit,args.run)
        elif args.cmd=="repaired":
            out=repaired(cfg,args.table,args.limit,args.run)
        elif args.cmd=="aggregate":
            out=aggregate(cfg,args.table,args.column,args.op,args.group_by,args.run)
        elif args.cmd=="meta":
            out=meta(cfg,args.section,args.run)
        elif args.cmd=="region":
            out=region(cfg,args.table,args.region_no,args.limit,args.run)
        elif args.cmd=="compare":
            out=compare(cfg,args.kind,args.run)
        elif args.cmd=="trace":
            out=trace(cfg,args.table,args.xl_row,args.run)
        else:
            out=sql(cfg,args.source_id,args.statement,args.run)
    except Xl2aiError as e:
        _print({"ok":False,"error":e.as_dict()})
        return 1
    except sqlite3.DatabaseError as e:
        _print({"ok":False,"error":Xl2aiError("E_STAGE_INPUT",f"query failed: {e}").as_dict()})
        return 1
    _print(out)
    return 0


if __name__=="__main__":
    sys.exit(main())
