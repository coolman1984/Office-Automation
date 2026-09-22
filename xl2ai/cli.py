"""Command router: `python -m xl2ai <stage> [args]`. Each stage is also runnable on its own.

Stages are registered lazily so that importing the CLI never loads Excel/COM code for commands that do not need it.
Later stages (quality, profile, relations, ...) register here as they are built (see ARCHITECTURE.md, roadmap).
"""
from __future__ import annotations

import importlib
import sys

# command -> (module, function, one-line description)
STAGES = {
    "init": ("xl2ai.init_project", "main", "create a reusable project config and optional rule-pack skeleton"),
    "doctor": ("xl2ai.doctor", "main", "check environment, sources, storage and current dataset"),
    "audit": ("xl2ai.audit", "main", "verify run artifacts and cross-database consistency"),
    "refresh": ("xl2ai.refresh", "main", "run every stage into a new run; promote it only if valid"),
    "watch": ("xl2ai.console.app", "main", "refresh with a live step-by-step view (--demo to see it without Excel)"),
    "diagnose": ("xl2ai.console.app", "diagnose_main", "explain what a run did and where it failed (--ai for AI help)"),
    "status": ("xl2ai.status", "main", "show the current dataset, its freshness and the last attempt"),
    "brief": ("xl2ai.brief", "main", "one-call orientation for a cold agent: readiness, gaps, next commands"),
    "sources": ("xl2ai.sources.inventory", "main", "list and fingerprint the configured source files"),
    "extract": ("xl2ai.extract.pipeline", "main", "Excel workbooks -> SQLite via Excel COM, verified against Excel (stand-alone)"),
    "catalog": ("xl2ai.catalog", "main", "build stable source/table/column identities for a run"),
    "analyze": ("xl2ai.analyze", "main", "profile data, flag generic quality issues and infer candidate keys"),
    "relations": ("xl2ai.relations", "main", "infer conservative relationships between tables"),
    "rules": ("xl2ai.rules", "main", "run configured deterministic business rules and KPIs"),
    "changes": ("xl2ai.changes", "main", "compare a run with the previous trusted run"),
    "pack": ("xl2ai.contextpack", "main", "build a compact deterministic context pack for AI"),
    "query": ("xl2ai.query", "main", "read-only capped schema/describe/sample/aggregate/trace/sql tools"),
    "report": ("xl2ai.report", "main", "show one-screen health, rules, KPI and change summary"),
}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print("usage: python -m xl2ai <command> [args]\n\ncommands:")
        for name, (_, _, desc) in STAGES.items():
            print(f"  {name:10} {desc}")
        print("\nrun `python -m xl2ai <command> --help` for a command's options")
        return 0
    stage = argv[0]
    if stage not in STAGES:
        print(f"unknown command '{stage}'. Available: {', '.join(STAGES)}", file=sys.stderr)
        return 2
    module, func, _ = STAGES[stage]
    return getattr(importlib.import_module(module), func)(argv[1:])


if __name__ == "__main__":
    sys.exit(main())
