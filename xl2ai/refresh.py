"""`xl2ai refresh`: run every stage into a new run folder, and promote it only if it earned it.

Exit codes: 0 promoted | 1 run failed | 2 partial (not promoted) | 4 another refresh holds the lock | 5 config/source error.
Stages today: sources, extract. Later stages register in STAGES (each is `fn(run, stage_rec, cfg, ctx)`).
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys

from .core.config import load_config
from .core.errors import Xl2aiError
from .core.fsutil import atomic_write_json
from .core.log import log
from .core.runs import CONTRACT_VERSION, Lock, Run, current_run_id, load_manifest, now_iso, reap_orphans
from .sources.inventory import build_inventory


def stage_sources(run, st, cfg, ctx):
    sources, warnings = build_inventory(cfg)
    for w in warnings:
        st.warn(w)
    path = run.path("sources.json")
    atomic_write_json(path, {"contract_version": CONTRACT_VERSION, "generated": now_iso(),
                             "sources": sources, "warnings": warnings})
    st.artifact(path)
    run.m["inputs"] = [{k: s[k] for k in ("source_id", "path", "sha256", "size", "mtime", "hash_mode")} for s in sources]
    st.detail("count", len(sources))
    ctx["sources"] = sources


def _same_source_path(a, b):
    try:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))
    except (TypeError, OSError):
        return False


def find_reusable_extraction(cfg, source):
    """Return a trusted prior extraction for an exactly unchanged source, otherwise None.

    Reuse is intentionally conservative: the previous run must be the promoted, fully-passed run; extraction-affecting
    settings must match; and path, hash, size and mtime must all be identical. Old manifests that predate this feature
    have no extract_fingerprint and therefore fall back to a normal extraction once.
    """
    prev_id = current_run_id(cfg)
    if not prev_id:
        return None
    try:
        prev = load_manifest(cfg, prev_id)
    except (OSError, ValueError):
        return None
    if prev.get("status") != "passed" or not prev.get("promoted"):
        return None
    if prev.get("extract_fingerprint") != cfg.extract_fingerprint():
        return None

    old = next((x for x in prev.get("inputs", []) if x.get("source_id") == source.get("source_id")), None)
    if not old or not _same_source_path(old.get("path"), source.get("path")):
        return None
    if any(old.get(k) != source.get(k) for k in ("sha256", "size", "mtime")):
        return None

    stage = next((x for x in prev.get("stages", []) if x.get("name") == "extract"), None)
    if not stage or stage.get("status") != "passed":
        return None
    rec = next((x for x in stage.get("details", {}).get("sources", [])
                if x.get("source_id") == source.get("source_id")), None)
    if not rec or rec.get("exit_code") != 0 or int(rec.get("verify_mismatches", 0) or 0):
        return None
    rel = rec.get("db")
    if not rel:
        return None

    root = os.path.abspath(os.path.join(cfg.runs_dir, prev_id))
    candidate = os.path.abspath(os.path.join(root, rel.replace("/", os.sep)))
    try:
        if os.path.commonpath([root, candidate]) != root:
            return None
    except ValueError:
        return None
    if not os.path.isfile(candidate):
        return None
    return {"run_id": prev_id, "db": candidate, "record": rec}


def materialize_reuse(src, dst):
    """Make the new run self-contained. Prefer an instant NTFS hard link; fall back to a normal copy."""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        os.link(src, dst)
        return "hardlink"
    except OSError:
        shutil.copy2(src, dst)
        return "copy"


def stage_catalog(run, st, cfg, ctx):
    from .catalog import build_catalog
    path = build_catalog(cfg, run.id, run.m)
    st.artifact(path)
    st.detail("tables", sqlite3.connect(path).execute("SELECT COUNT(*) FROM _tables").fetchone()[0])
    ctx["catalog"] = path


def stage_extract(run, st, cfg, ctx):
    opts = cfg.extract_options()
    per, codes = [], set()
    process_file = None                              # COM is imported only when at least one workbook really changed
    for s in ctx["sources"]:
        db = run.path("extract", s["source_id"] + ".db")
        reusable = None if ctx.get("force_extract") else find_reusable_extraction(cfg, s)
        if reusable:
            mode = materialize_reuse(reusable["db"], db)
            old = reusable["record"]
            info = {"source_id": s["source_id"], "exit_code": 0, "db": run.rel(db),
                    "message": "unchanged source; reused previous trusted extraction",
                    "sheets": dict(old.get("sheets", {})),
                    "verify_checks": int(old.get("verify_checks", 0) or 0),
                    "verify_mismatches": 0, "reused": True,
                    "reused_from_run": reusable["run_id"], "reuse_mode": mode}
            st.artifact(db)
            per.append(info)
            codes.add(0)
            log("INFO", f"Reused unchanged source '{s['source_id']}' from run {reusable['run_id']} ({mode}); Excel not opened")
            continue

        if process_file is None:
            from .extract.pipeline import process_file as _process_file
            process_file = _process_file
        print(f"\n{'=' * 100}\n{s['path']}\n{'=' * 100}")
        code, results, message = process_file(s["path"], db, opts)
        codes.add(code)
        info = {"source_id": s["source_id"], "exit_code": code, "db": None, "message": message, "reused": False,
                "sheets": {k: sum(r.status == k for r in results) for k in ("extracted", "skipped", "error")}}
        if os.path.isfile(db):
            info["db"] = run.rel(db)
            st.artifact(db)
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            meta = dict(con.execute("SELECT key, value FROM _meta").fetchall())
            con.close()
            info["verify_checks"] = int(meta.get("verify_checks", 0))
            info["verify_mismatches"] = int(meta.get("verify_mismatches", 0))
        per.append(info)
    st.detail("sources", per)
    if 3 in codes:
        bad = [p["source_id"] for p in per if p["exit_code"] == 3]
        st.fail("E_VERIFY_MISMATCH", "stored data differs from Excel for: " + ", ".join(bad),
                "see the _verification table in that database")
    elif 1 in codes:
        bad = [f"{p['source_id']} ({p['message']})" for p in per if p["exit_code"] == 1]
        st.fail("E_EXTRACT", "could not extract: " + "; ".join(bad))
    elif 2 in codes:
        st.partial("some sheets failed to extract; the run is not promoted unless allow_partial is set")


STAGES = (("sources", stage_sources), ("extract", stage_extract), ("catalog", stage_catalog))


def run_refresh(cfg, force=False):
    """Returns (exit_code, run). Raises Xl2aiError for lock/config problems before any run exists."""
    with Lock(cfg):
        reap_orphans(cfg)
        run = Run.create(cfg)
        log("INFO", f"Run {run.id} started (project '{cfg.project}')")
        ctx = {"force_extract": bool(force)}
        try:
            for name, fn in STAGES:
                with run.stage(name) as st:
                    fn(run, st, cfg, ctx)
                if run.stage_status(name) != "passed":
                    break                                   # later stages need this stage's output
        finally:
            promoted = run.finish()
        code = 0 if promoted else (2 if run.m["status"] == "partial" else 1)
        return code, run


def print_summary(run, promoted):
    m = run.m
    print(f"\nRun {m['run_id']}: {m['status'].upper()}  |  promoted: {'yes' if promoted else 'NO (current dataset unchanged)'}")
    for s in m["stages"]:
        err = f"  -> {s['error']['code']}: {s['error']['message']}" if s.get("error") else ""
        print(f"  {s['name']:<10} {s['status']:<11} {s['seconds'] if s['seconds'] is not None else '-':>7}s{err}")
        for w in s["warnings"]:
            print(f"      warn: {w}")
    print(f"Folder: {run.dir}")


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    ap = argparse.ArgumentParser(prog="xl2ai refresh", description="Refresh everything into a new run; promote only if valid.")
    ap.add_argument("paths", nargs="*", help="override the configured sources")
    ap.add_argument("--config", help="path to xl2ai.toml (default: discovered upward from the current folder)")
    ap.add_argument("--json", action="store_true", help="print the run manifest as JSON at the end")
    ap.add_argument("--force", action="store_true", help="re-extract every source even when it is unchanged")
    args = ap.parse_args(argv)
    try:
        cfg = load_config(args.config, required=not args.paths)
        if args.paths:
            cfg = cfg.with_sources(args.paths)
        code, run = run_refresh(cfg, force=args.force)
    except Xl2aiError as e:
        print(f"{e}" + (f"\n  hint: {e.hint}" if e.hint else ""), file=sys.stderr)
        return 4 if e.code == "E_LOCKED" else 5
    print_summary(run, run.m["promoted"])
    if args.json:
        print(json.dumps(run.m, indent=1, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
