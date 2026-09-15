#!/usr/bin/env python3
"""Create a release zip and copy platform-specific wheels from a tested package."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_NAME = "vs_cfl"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Create release-ready vs-cfl assets.")
    parser.add_argument("--package-dir", required=True, help="Top-level vs_cfl plugin directory.")
    parser.add_argument("--wheel-dir", required=True, help="Directory containing built wheels.")
    parser.add_argument("--out-dir", required=True, help="Directory for the release zip and wheels.")
    parser.add_argument("--zip-name", required=True, help="Release zip filename.")
    parser.add_argument("--clean", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    package_dir = (ROOT / args.package_dir).resolve()
    wheel_dir = (ROOT / args.wheel_dir).resolve()
    out_dir = (ROOT / args.out_dir).resolve()
    native = [path for path in package_dir.glob(f"{PLUGIN_NAME}.*") if path.suffix in {".dll", ".so", ".dylib"}]
    if not (package_dir / "manifest.vs").is_file() or len(native) != 1:
        raise FileNotFoundError(f"invalid plugin package directory: {package_dir}")
    wheels = sorted(wheel_dir.glob("*.whl"))
    if not wheels:
        raise FileNotFoundError(f"no wheels under {wheel_dir}")

    if args.clean:
        shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / args.zip_name
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for file_path in sorted(package_dir.rglob("*")):
            if file_path.is_file():
                archive.write(file_path, f"{PLUGIN_NAME}/{file_path.relative_to(package_dir).as_posix()}")
    copied_wheels = []
    for wheel in wheels:
        destination = out_dir / wheel.name
        shutil.copy2(wheel, destination)
        copied_wheels.append(destination)

    result = {
        "package_dir": str(package_dir),
        "native": str(native[0]),
        "zip": str(zip_path),
        "wheels": [str(path) for path in copied_wheels],
    }
    print(json.dumps(result, indent=2, sort_keys=True) if args.json else result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
