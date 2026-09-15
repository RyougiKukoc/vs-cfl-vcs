#!/usr/bin/env python3
"""Smoke test an installed vs-cfl wheel through VapourSynth plugin autoload."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from smoke_load_artifact import exercise_filter, plugin_suffix


PLUGIN_NAME = "vs_cfl"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Smoke test an installed vs-cfl wheel.")
    parser.add_argument("--site-dir", help="Optional site-packages path to prepend.")
    parser.add_argument("--exercise-filter", action="store_true", help="Retained for compatibility; filter verification is always run.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.site_dir:
        sys.path.insert(0, args.site_dir)
    import vapoursynth as vs

    package_dir = Path(vs.__file__).resolve().parent / "plugins" / PLUGIN_NAME
    for required in (package_dir / f"{PLUGIN_NAME}{plugin_suffix()}", package_dir / "manifest.vs"):
        if not required.is_file():
            raise FileNotFoundError(f"missing installed file: {required}")
    core = vs.core
    if not hasattr(core, "cfl") or not hasattr(core.cfl, "KACFL"):
        raise RuntimeError("core.cfl.KACFL was not autoloaded from the installed wheel")
    result = {"plugin_dir": str(package_dir), "namespace_loaded": True, **exercise_filter(core, vs)}
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
