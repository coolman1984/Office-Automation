"""Command router: `python -m xl2ai <stage> [args]`. Each stage is also runnable on its own.

Stages are registered lazily so that importing the CLI never loads Excel/COM code for commands that do not need it.
Later stages (quality, profile, relations, ...) register here as they are built (see ARCHITECTURE.md, roadmap).
"""
from __future__ import annotations

import importlib
import sys

# command -> (module, function, one-line description)
STAGES = {
    "refresh": ("xl2ai.refresh", "main", "run every stage into a new run; promote it only if valid"),
    "status": ("xl2ai.status", "main", "show the current dataset, its freshness and the last attempt"),
    "sources": ("xl2ai.sources.inventory", "main", "list and fingerprint the configured source files"),
    "extract": ("xl2ai.extract.pipeline", "main", "Excel workbooks -> SQLite via Excel COM, verified against Excel (stand-alone)"),
    "catalog": ("xl2ai.catalog", "main", "build stable source/table/column identities for a run"),
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
