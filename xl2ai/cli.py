"""Command router: `python -m xl2ai <stage> [args]`. Each stage is also runnable on its own.

Stages are registered lazily so that importing the CLI never loads Excel/COM code for stages that do not need it.
Only `extract` exists today; later stages register here (see ARCHITECTURE.md, roadmap).
"""
from __future__ import annotations

import importlib
import sys

# stage name -> (module, function, one-line description)
STAGES = {
    "extract": ("xl2ai.extract.pipeline", "main", "Excel workbooks -> SQLite via Excel COM, verified against Excel"),
}


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ("-h", "--help", "help"):
        print("usage: python -m xl2ai <stage> [args]\n\nstages:")
        for name, (_, _, desc) in STAGES.items():
            print(f"  {name:10} {desc}")
        print("\nrun `python -m xl2ai <stage> --help` for a stage's options")
        return 0
    stage = argv[0]
    if stage not in STAGES:
        print(f"unknown stage '{stage}'. Available: {', '.join(STAGES)}", file=sys.stderr)
        return 2
    module, func, _ = STAGES[stage]
    return getattr(importlib.import_module(module), func)(argv[1:])


if __name__ == "__main__":
    sys.exit(main())
