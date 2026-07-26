from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEPS = ROOT / "_deps"
DEFAULT_BUILD = ROOT / "build-ci-msys2"
DEFAULT_DIST = ROOT / "dist" / "msys2-ucrt64"
PLUGIN_NAME = "vs_cfl"

SYSTEM_DLLS = {
    "advapi32.dll", "bcrypt.dll", "cfgmgr32.dll", "comdlg32.dll", "gdi32.dll",
    "kernel32.dll", "msvcrt.dll", "ntdll.dll", "ole32.dll", "oleaut32.dll",
    "shell32.dll", "user32.dll", "version.dll", "winspool.drv", "ws2_32.dll",
}


def run(cmd: list[str], cwd: Path | None = None, env: dict[str, str] | None = None) -> None:
    print("+ " + subprocess.list2cmdline(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def find_tool(name: str, env: dict[str, str]) -> str:
    found = shutil.which(name, path=env.get("PATH"))
    if found:
        return found
    candidate = Path(sys.executable).resolve().parent / "Scripts" / f"{name}.exe"
    if candidate.exists():
        return str(candidate)
    raise RuntimeError(f"{name} is not on PATH")


def prepend_path_entries(env: dict[str, str], entries: list[Path]) -> None:
    parts = [str(entry) for entry in entries if entry.exists()]
    if parts:
        env["PATH"] = os.pathsep.join(parts + ([env["PATH"]] if env.get("PATH") else []))


def candidate_msys2_prefixes(env: dict[str, str]) -> list[Path]:
    candidates: list[Path] = []
    if env.get("MSYSTEM_PREFIX"):
        candidates.append(Path(env["MSYSTEM_PREFIX"]))
    candidates.extend([ROOT.parents[2] / "msys2" / "ucrt64", Path(r"C:\msys64\ucrt64")])
    unique: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate).lower()
        if key not in seen:
            seen.add(key)
            unique.append(candidate)
    return unique


def dll_dependencies(objdump: str, dll: Path) -> list[str]:
    completed = subprocess.run(
        [objdump, "-p", str(dll)], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace", check=True,
    )
    return [line.strip().removeprefix("DLL Name: ") for line in completed.stdout.splitlines() if line.strip().startswith("DLL Name: ")]


def collect_runtime_dlls(pkg_dir: Path, search_dirs: list[Path], env: dict[str, str]) -> None:
    queue = sorted(pkg_dir.glob("*.dll"))
    seen: set[str] = set()
    objdump = find_tool("objdump", env)
    while queue:
        dll = queue.pop(0)
        key = dll.name.lower()
        if key in seen:
            continue
        seen.add(key)
        for dependency in dll_dependencies(objdump, dll):
            dep_key = dependency.lower()
            if dep_key in SYSTEM_DLLS or dep_key.startswith("api-ms-win-"):
                continue
            destination = pkg_dir / dependency
            if destination.exists():
                if dep_key not in seen:
                    queue.append(destination)
                continue
            for search_dir in search_dirs:
                source = search_dir / dependency
                if source.exists():
                    shutil.copy2(source, destination)
                    queue.append(destination)
                    break


def configure_env(vs_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    prefixes = candidate_msys2_prefixes(env)
    prepend_path_entries(env, [*(prefix / "bin" for prefix in prefixes), *(prefix.parent / "usr" / "bin" for prefix in prefixes)])
    pc_dir = vs_root / "vapoursynth" / "lib" / "pkgconfig"
    env["PKG_CONFIG_PATH"] = os.pathsep.join([str(pc_dir), env["PKG_CONFIG_PATH"]]) if env.get("PKG_CONFIG_PATH") else str(pc_dir)
    for prefix in prefixes:
        gcc = prefix / "bin" / "gcc.exe"
        gxx = prefix / "bin" / "g++.exe"
        if gcc.exists() and gxx.exists():
            env.setdefault("CC", str(gcc))
            env.setdefault("CXX", str(gxx))
            break
    return env


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Build and package vs-cfl with MSYS2 UCRT64.")
    parser.add_argument("--deps-dir", default=str(DEFAULT_DEPS))
    parser.add_argument("--build-dir", default=str(DEFAULT_BUILD))
    parser.add_argument("--dist-dir", default=str(DEFAULT_DIST))
    parser.add_argument("--vapoursynth-wheel-root")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args(argv)

    deps = Path(args.deps_dir).resolve()
    build_dir = Path(args.build_dir).resolve()
    dist_dir = Path(args.dist_dir).resolve()
    pkg_dir = dist_dir / PLUGIN_NAME
    vs_root = Path(args.vapoursynth_wheel_root).resolve() if args.vapoursynth_wheel_root else deps / "vapoursynth-wheel-R77"
    for path in [
        vs_root / "vapoursynth" / "include" / "VapourSynth4.h",
        vs_root / "vapoursynth" / "lib" / "pkgconfig" / "vapoursynth.pc",
    ]:
        if not path.exists():
            raise FileNotFoundError(path)

    if args.clean and build_dir.exists():
        shutil.rmtree(build_dir)
    if args.clean and dist_dir.exists():
        shutil.rmtree(dist_dir)

    env = configure_env(vs_root)
    meson = find_tool("meson", env)
    ninja = find_tool("ninja", env)
    setup_cmd = [meson, "setup", str(build_dir), str(ROOT), "--backend", "ninja", "--buildtype", "release"]
    if build_dir.exists():
        setup_cmd.insert(2, "--reconfigure")
    run(setup_cmd, cwd=ROOT, env=env)
    run([ninja, "-C", str(build_dir), "-v"], cwd=ROOT, env=env)

    built_dll = build_dir / f"{PLUGIN_NAME}.dll"
    if not built_dll.exists():
        raise FileNotFoundError(built_dll)
    pkg_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(built_dll, pkg_dir / built_dll.name)
    (pkg_dir / "manifest.vs").write_text(f"[VapourSynth Manifest V1]\n{PLUGIN_NAME}\n", encoding="ascii", newline="\n")
    search_dirs = [Path(item) for item in env.get("PATH", "").split(os.pathsep) if item]
    collect_runtime_dlls(pkg_dir, search_dirs, env)

    print(f"artifact_dir={dist_dir}")
    for path in sorted(pkg_dir.iterdir()):
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
