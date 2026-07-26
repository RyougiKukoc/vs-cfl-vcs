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


def create_core(vs, *, autoload: bool):
    try:
        return vs.create_environment(flags=0 if autoload else vs.DISABLE_AUTO_LOADING).get_core()
    except AttributeError:
        return vs.core


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
    parser = argparse.ArgumentParser(description="Smoke-load a built vs-cfl artifact with VapourSynth.")
    parser.add_argument("--vapoursynth-root", help="Extracted VapourSynth wheel root.")
    parser.add_argument("--artifact-dir", required=True)
    parser.add_argument("--autoload", action="store_true", help="Load via manifest.vs autoload instead of std.LoadPlugin.")
    parser.add_argument("--exercise-filter", action="store_true")
    args = parser.parse_args(argv)

    artifact_root = Path(args.artifact_dir).resolve()
    package_dir = artifact_root / PLUGIN_NAME if not (artifact_root / f"{PLUGIN_NAME}.dll").exists() else artifact_root
    plugin = package_dir / f"{PLUGIN_NAME}.dll"
    manifest = package_dir / "manifest.vs"
    for path in [plugin, manifest]:
        if not path.exists():
            print(f"missing required path: {path}", file=sys.stderr)
            return 1

    vs_root = Path(args.vapoursynth_root).resolve() if args.vapoursynth_root else None
    if vs_root and (vs_root / "vapoursynth").exists():
        sys.path.insert(0, str(vs_root))
    add_dll_dirs([package_dir, Path(sys.executable).resolve().parent, Path(sysconfig.get_paths().get("platlib", "")), Path(sysconfig.get_paths().get("purelib", "")), *(Path(path) for path in site.getsitepackages()), *((vs_root / "vapoursynth",) if vs_root else ())])

    try:
        import vapoursynth as vs
    except ImportError as exc:
        print(f"failed to import VapourSynth Python module: {exc}", file=sys.stderr)
        return 1
    if args.autoload:
        os.environ["VAPOURSYNTH_EXTRA_PLUGIN_PATH"] = str(package_dir.parent)
    core = create_core(vs, autoload=args.autoload)
    if not args.autoload:
        core.std.LoadPlugin(str(plugin))
    if not hasattr(core, "cfl") or not hasattr(core.cfl, "KACFL"):
        print("core.cfl.KACFL missing after load", file=sys.stderr)
        return 1
    print(core.cfl.KACFL)
    if args.exercise_filter:
        exercise_filter(core, vs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
