from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DEPS = ROOT / "_deps"
VAPOURSYNTH_VERSION = "77"


def run(cmd: list[str], cwd: Path | None = None) -> None:
    print("+ " + subprocess.list2cmdline(cmd), flush=True)
    subprocess.run(cmd, cwd=cwd, check=True)


def download_wheel(deps: Path) -> Path:
    wheel_dir = deps / "downloads" / "vapoursynth-r77-wheel"
    wheel_dir.mkdir(parents=True, exist_ok=True)
    wheels = sorted(wheel_dir.glob(f"vapoursynth-{VAPOURSYNTH_VERSION}-*.whl"))
    if wheels:
        return wheels[0]
    run(
        [
            sys.executable,
            "-m",
            "pip",
            "download",
            f"VapourSynth=={VAPOURSYNTH_VERSION}",
            "--only-binary=:all:",
            "--platform",
            "win_amd64",
            "--python-version",
            "312",
            "--abi",
            "abi3",
            "--dest",
            str(wheel_dir),
            "--no-deps",
        ]
    )
    wheels = sorted(wheel_dir.glob(f"vapoursynth-{VAPOURSYNTH_VERSION}-*.whl"))
    if not wheels:
        raise FileNotFoundError(wheel_dir / f"vapoursynth-{VAPOURSYNTH_VERSION}-*.whl")
    return wheels[0]


def write_pkg_config(vs_pkg: Path) -> None:
    pc_dir = vs_pkg / "lib" / "pkgconfig"
    pc_dir.mkdir(parents=True, exist_ok=True)
    prefix = vs_pkg.resolve().as_posix()
    (pc_dir / "vapoursynth.pc").write_text(
        "\n".join(
            [
                f"prefix={prefix}",
                "includedir=${prefix}/include",
                "",
                "Name: vapoursynth",
                "Description: VapourSynth R77 wheel headers for vs-cfl CI builds",
                f"Version: {VAPOURSYNTH_VERSION}",
                "Libs:",
                "Cflags: -I${includedir}",
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )


def prepare_vapoursynth(deps: Path) -> Path:
    out = deps / f"vapoursynth-wheel-R{VAPOURSYNTH_VERSION}"
    marker = out / "vapoursynth" / "include" / "VapourSynth4.h"
    if not marker.exists():
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(download_wheel(deps)) as zf:
            zf.extractall(out)
    required = [
        out / "vapoursynth" / "include" / "VapourSynth4.h",
        out / "vapoursynth" / "include" / "VSHelper4.h",
        out / "vapoursynth" / "libvapoursynth.dll",
    ]
    for path in required:
        if not path.exists():
            raise FileNotFoundError(path)
    write_pkg_config(out / "vapoursynth")
    return out


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Prepare VapourSynth R77 wheel files for the MSYS2 build.")
    parser.add_argument("--deps-dir", default=str(DEFAULT_DEPS), help="Dependency cache/work directory.")
    args = parser.parse_args(argv)

    deps = Path(args.deps_dir).resolve()
    deps.mkdir(parents=True, exist_ok=True)
    vs_root = prepare_vapoursynth(deps)
    print("Prepared dependencies:")
    print(f"VAPOURSYNTH_WHEEL_ROOT={vs_root}")
    print(f"PKG_CONFIG_PATH={vs_root / 'vapoursynth' / 'lib' / 'pkgconfig'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
