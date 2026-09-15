#!/usr/bin/env python3
"""Explicitly load a packaged vs-cfl plugin with autoload disabled by default."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import site
import sys
import sysconfig
import tempfile
import zipfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "vs_cfl"


def plugin_suffix() -> str:
    if sys.platform == "win32":
        return ".dll"
    if sys.platform == "darwin":
        return ".dylib"
    return ".so"


def frame_hash(frame: Any) -> str:
    digest = hashlib.sha256()
    for plane in range(frame.format.num_planes):
        digest.update(bytes(frame[plane]))
    return digest.hexdigest()


class IsolatedEnvironmentPolicy:
    def __init__(self, flags: int) -> None:
        self.api: Any = None
        self.environment: Any = None
        self.flags = flags

    def on_policy_registered(self, api: Any) -> None:
        self.api = api
        self.environment = api.create_environment(self.flags)

    def on_policy_cleared(self) -> None:
        self.api = None
        self.environment = None

    def get_current_environment(self) -> Any:
        return self.environment

    def set_environment(self, environment: Any) -> Any:
        previous = self.environment
        if environment is not None:
            self.environment = environment
        return previous

    def is_alive(self, environment: Any) -> bool:
        return environment is self.environment

    def close(self) -> None:
        if self.api is not None and self.environment is not None:
            self.api.destroy_environment(self.environment)
            self.environment = None


def install_isolated_policy(vs: Any, *, autoload: bool) -> IsolatedEnvironmentPolicy | None:
    if not hasattr(vs, "register_policy") or vs.has_policy():
        return None
    policy = IsolatedEnvironmentPolicy(0 if autoload else int(vs.DISABLE_AUTO_LOADING))
    vs.register_policy(policy)
    return policy


def resolve_package(artifact_dir: str | None, artifact_zip: str | None) -> tuple[Path, Path | None]:
    if artifact_zip:
        archive_path = Path(artifact_zip).resolve()
        if not archive_path.is_file():
            raise FileNotFoundError(archive_path)
        temp_dir = Path(tempfile.mkdtemp(prefix="vs-cfl-package-"))
        with zipfile.ZipFile(archive_path) as archive:
            archive.extractall(temp_dir)
        directories = [path for path in temp_dir.iterdir() if path.is_dir()]
        if len(directories) != 1 or directories[0].name != PLUGIN_NAME:
            raise RuntimeError(f"expected one top-level {PLUGIN_NAME}/ directory in {archive_path}")
        return directories[0], temp_dir
    root = Path(artifact_dir or ROOT / "dist" / "msys2-ucrt64").resolve()
    return (root if (root / f"{PLUGIN_NAME}{plugin_suffix()}").is_file() else root / PLUGIN_NAME), None


def add_dll_directory(package_dir: Path) -> list[Any]:
    add_directory = getattr(os, "add_dll_directory", None)
    if add_directory is None:
        return []
    search = [package_dir, Path(sys.executable).resolve().parent, Path(sysconfig.get_paths().get("platlib", "")), Path(sysconfig.get_paths().get("purelib", "")), *(Path(path) for path in site.getsitepackages())]
    return [add_directory(str(path)) for path in search if path.is_dir()]


def exercise_filter(core: Any, vs: Any) -> dict[str, Any]:
    source = core.std.BlankClip(width=64, height=48, format=vs.YUV420P8, length=12, color=[96, 112, 144])
    output = core.cfl.KACFL(source)
    frames = {number: output.get_frame(number) for number in (0, 3, 11)}
    frame = frames[3]
    if frame.width != 64 or frame.height != 48 or frame.format.name != "YUV444P8":
        raise RuntimeError(f"unexpected CFL output: {frame.width}x{frame.height} {frame.format.name}")
    hashes = {number: frame_hash(value) for number, value in frames.items()}
    if len(set(hashes.values())) != 1:
        raise RuntimeError(f"static CFL input produced inconsistent hashes: {hashes}")
    stats = dict(core.std.PlaneStats(output).get_frame(3).props)
    invalid_error = ""
    try:
        core.cfl.KACFL(core.std.BlankClip(width=64, height=48, format=vs.RGB24, length=1))
    except vs.Error as exc:
        invalid_error = str(exc)
    if "input must be YUV color family" not in invalid_error:
        raise RuntimeError(f"unsupported RGB input did not return the documented error: {invalid_error!r}")
    return {
        "width": frame.width,
        "height": frame.height,
        "format": frame.format.name,
        "frames": output.num_frames,
        "frame_hashes": hashes,
        "plane_stats_average": float(stats["PlaneStatsAverage"]),
        "plane_stats_min": float(stats["PlaneStatsMin"]),
        "plane_stats_max": float(stats["PlaneStatsMax"]),
        "invalid_error": invalid_error,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Smoke test a packaged vs-cfl plugin.")
    parser.add_argument("--artifact-dir")
    parser.add_argument("--artifact-zip")
    parser.add_argument("--vapoursynth-root", help="Optional extracted VapourSynth wheel root.")
    parser.add_argument("--autoload", action="store_true", help="Exercise manifest autoload instead of explicit LoadPlugin.")
    parser.add_argument("--exercise-filter", action="store_true", help="Retained for compatibility; filter verification is always run.")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    package_dir, temporary_dir = resolve_package(args.artifact_dir, args.artifact_zip)
    plugin = package_dir / f"{PLUGIN_NAME}{plugin_suffix()}"
    manifest = package_dir / "manifest.vs"
    if not plugin.is_file() or not manifest.is_file():
        raise FileNotFoundError(f"missing plugin package files under {package_dir}")
    if args.vapoursynth_root:
        sys.path.insert(0, str(Path(args.vapoursynth_root).resolve()))
    handles = add_dll_directory(package_dir)
    try:
        import vapoursynth as vs

        if args.autoload:
            os.environ["VAPOURSYNTH_EXTRA_PLUGIN_PATH"] = str(package_dir.parent)
        policy = install_isolated_policy(vs, autoload=args.autoload)
        try:
            core = vs.core
            if not args.autoload:
                core.std.LoadPlugin(str(plugin))
            if not hasattr(core, "cfl") or not hasattr(core.cfl, "KACFL"):
                raise RuntimeError("core.cfl.KACFL missing after plugin load")
            result = {"plugin": str(plugin), "manifest": str(manifest), "autoload": args.autoload, **exercise_filter(core, vs)}
            print(json.dumps(result, indent=2, sort_keys=True) if args.json else result)
        finally:
            if policy is not None:
                policy.close()
    finally:
        for handle in handles:
            handle.close()
        if temporary_dir is not None:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
