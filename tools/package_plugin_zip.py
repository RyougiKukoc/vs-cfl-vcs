from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path


PLUGIN_NAME = "vs_cfl"


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Create a release zip for a packaged vs-cfl plugin directory.")
    parser.add_argument("--input-dir", required=True, help="Directory containing the top-level vs_cfl package directory.")
    parser.add_argument("--output", required=True, help="Output zip path.")
    args = parser.parse_args(argv)

    input_dir = Path(args.input_dir).resolve()
    output = Path(args.output).resolve()
    package_dir = input_dir / PLUGIN_NAME
    for required in [package_dir / "manifest.vs", package_dir / f"{PLUGIN_NAME}.dll"]:
        if not required.exists():
            print(f"missing required package file: {required}", file=sys.stderr)
            return 1

    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(package_dir.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(input_dir).as_posix())
    print(f"release_asset={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
