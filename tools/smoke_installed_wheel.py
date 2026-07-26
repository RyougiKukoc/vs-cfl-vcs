from __future__ import annotations

import argparse
import os
import site
import sys
import sysconfig
from pathlib import Path


PLUGIN_NAME = "vs_cfl"


def add_dll_dirs(paths: list[Path]) -> None:
    add_dll_directory = getattr(os, "add_dll_directory", None)
    if add_dll_directory:
        for path in paths:
            if path.exists():
                add_dll_directory(str(path))


def exercise_filter(core, vs) -> None:
    source = core.std.BlankClip(width=64, height=32, format=vs.YUV420P8, length=1, color=[96, 112, 144])
    clip = core.cfl.KACFL(source)
    frame = clip.get_frame(0)
    if frame.width != 64 or frame.height != 32 or clip.format.id != vs.YUV444P8:
        raise RuntimeError(f"unexpected output: {frame.width}x{frame.height}, format={clip.format.name}")
    stats = core.std.PlaneStats(clip).get_frame(0).props
    print(f"filter exercise: {clip.width}x{clip.height} {clip.format.name}")
    print(f"PlaneStatsAverage={stats['PlaneStatsAverage']}")


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Smoke-test an installed vs-cfl wheel.")
    parser.add_argument("--exercise-filter", action="store_true")
    args = parser.parse_args(argv)

    try:
        import vapoursynth as vs
    except ImportError as exc:
        print(f"failed to import VapourSynth Python module: {exc}", file=sys.stderr)
        return 1
    vs_pkg = Path(vs.__file__).resolve().parent
    plugin_dir = vs_pkg / "plugins" / PLUGIN_NAME
    for path in [plugin_dir / f"{PLUGIN_NAME}.dll", plugin_dir / "manifest.vs"]:
        if not path.exists():
            print(f"missing installed file: {path}", file=sys.stderr)
            return 1
    add_dll_dirs([plugin_dir, vs_pkg, Path(sys.executable).resolve().parent, Path(sysconfig.get_paths().get("platlib", "")), Path(sysconfig.get_paths().get("purelib", "")), *(Path(path) for path in site.getsitepackages())])

    try:
        core = vs.create_environment().get_core()
    except AttributeError:
        core = vs.core
    if not hasattr(core, "cfl") or not hasattr(core.cfl, "KACFL"):
        print("core.cfl.KACFL missing after installed-wheel autoload", file=sys.stderr)
        return 1
    print(core.cfl.KACFL)
    if args.exercise_filter:
        exercise_filter(core, vs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
