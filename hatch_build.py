from __future__ import annotations

import importlib.util
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
import urllib.request
import zipfile
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface
from packaging import tags


ROOT = Path(__file__).resolve().parent
PLUGIN_NAME = "vs_cfl"
DEFAULT_REPOSITORY = "RyougiKukoc/vs-cfl-vcs"
WINDOWS_PREBUILT_ASSET = "vs-cfl-msys2-ucrt64.zip"
LINUX_PREBUILT_ASSET = "vs-cfl-linux-x86_64.zip"


def _truthy(value: str | None) -> bool:
    return bool(value and value.strip().lower() not in {"", "0", "false", "no", "off"})


def _project_version() -> str:
    override = os.environ.get("VS_CFL_PREBUILT_VERSION")
    if override:
        return override
    with (ROOT / "pyproject.toml").open("rb") as handle:
        version = tomllib.load(handle).get("project", {}).get("version")
    if not isinstance(version, str) or not version.strip():
        raise RuntimeError("project.version is missing from pyproject.toml")
    return version


def _plugin_suffix() -> str:
    if sys.platform == "win32":
        return ".dll"
    if sys.platform == "darwin":
        return ".dylib"
    return ".so"


def _supports_prebuilt() -> bool:
    return sys.platform in {"win32", "linux"} and platform.machine().lower() in {"amd64", "x86_64"}


def _default_prebuilt_asset() -> str:
    if sys.platform == "linux" and platform.machine().lower() in {"amd64", "x86_64"}:
        return LINUX_PREBUILT_ASSET
    return WINDOWS_PREBUILT_ASSET


def _default_prebuilt_url(version: str) -> str:
    repository = os.environ.get("VS_CFL_PREBUILT_REPOSITORY") or os.environ.get("GITHUB_REPOSITORY") or DEFAULT_REPOSITORY
    tag = os.environ.get("VS_CFL_PREBUILT_TAG") or f"v{version}"
    asset = os.environ.get("VS_CFL_PREBUILT_ASSET_NAME") or _default_prebuilt_asset()
    return f"https://github.com/{repository}/releases/download/{tag}/{asset}"


def _prebuilt_source(version: str) -> tuple[str, bool]:
    explicit = os.environ.get("VS_CFL_PREBUILT_URL")
    if explicit:
        return explicit, True
    return _default_prebuilt_url(version), False


def _fetch_prebuilt_archive(source: str, destination: Path) -> None:
    candidate = Path(source)
    if candidate.exists():
        shutil.copy2(candidate, destination)
        return
    request = urllib.request.Request(source, headers={"User-Agent": "vs-cfl-build-hook"})
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as handle:
        shutil.copyfileobj(response, handle)


def _write_manifest(target_dir: Path) -> None:
    (target_dir / "manifest.vs").write_text(
        "[VapourSynth Manifest V1]\n"
        f"{PLUGIN_NAME}\n",
        encoding="ascii",
        newline="\n",
    )


def _stage_package_from_zip(archive_path: Path, target_dir: Path) -> None:
    package_prefix = f"{PLUGIN_NAME}/"
    with zipfile.ZipFile(archive_path) as archive:
        members = [name for name in archive.namelist() if name.replace("\\", "/").startswith(package_prefix) and not name.endswith("/")]
        if not members:
            raise FileNotFoundError(f"prebuilt archive does not contain a {PLUGIN_NAME}/ package directory")
        for member in members:
            normalized = member.replace("\\", "/")
            relative = Path(normalized[len(package_prefix):])
            if relative.is_absolute() or ".." in relative.parts:
                raise RuntimeError(f"unsafe prebuilt archive member: {member}")
            destination = target_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, destination.open("wb") as handle:
                shutil.copyfileobj(source, handle)

    plugin = target_dir / f"{PLUGIN_NAME}{_plugin_suffix()}"
    if not plugin.is_file():
        raise FileNotFoundError(f"prebuilt archive did not provide {plugin.name}")
    if not (target_dir / "manifest.vs").is_file():
        _write_manifest(target_dir)


def _stage_prebuilt_plugin(version: str, target_dir: Path) -> bool:
    if _truthy(os.environ.get("VS_CFL_FORCE_BUILD")):
        print("vs-cfl wheel build: skipping prebuilt asset because VS_CFL_FORCE_BUILD is set")
        return False
    if not _supports_prebuilt():
        print("vs-cfl wheel build: no matching release asset for this platform; falling back to a native build")
        return False

    source, explicit = _prebuilt_source(version)
    try:
        with tempfile.TemporaryDirectory(prefix="vs-cfl-prebuilt-") as temp_dir_text:
            archive_path = Path(temp_dir_text) / (Path(source).name or _default_prebuilt_asset())
            _fetch_prebuilt_archive(source, archive_path)
            _stage_package_from_zip(archive_path, target_dir)
    except Exception as exc:
        if explicit:
            raise RuntimeError(f"failed to use explicit vs-cfl prebuilt asset {source!r}") from exc
        print(f"vs-cfl wheel build: prebuilt asset unavailable at {source}; falling back to local build ({exc})")
        return False

    print(f"vs-cfl wheel build: using prebuilt release asset {source}")
    return True


def _prepend_path(env: dict[str, str], key: str, entries: list[Path]) -> None:
    values = [str(entry) for entry in entries if entry.is_dir()]
    if values:
        env[key] = os.pathsep.join(values + ([env[key]] if env.get(key) else []))


def _configure_build_env(env: dict[str, str]) -> dict[str, str]:
    if sys.platform != "win32":
        module_spec = importlib.util.find_spec("vapoursynth")
        if module_spec is None or module_spec.origin is None:
            raise RuntimeError("native builds require VapourSynth headers and pkg-config metadata")
        pkgconfig_dir = Path(module_spec.origin).resolve().parent / "pkgconfig"
        if not pkgconfig_dir.is_dir():
            raise FileNotFoundError(f"VapourSynth pkg-config directory is missing: {pkgconfig_dir}")
        # Preserve caller-provided search paths, which may contain unrelated build metadata.
        _prepend_path(env, "PKG_CONFIG_PATH", [pkgconfig_dir])
        return env

    msystem_prefix = env.get("MSYSTEM_PREFIX")
    if msystem_prefix:
        prefix = Path(msystem_prefix)
        _prepend_path(env, "PATH", [prefix / "bin", prefix.parent / "usr" / "bin"])
    else:
        _prepend_path(env, "PATH", [Path(r"C:\msys64\ucrt64\bin"), Path(r"C:\msys64\usr\bin")])
    env.setdefault("CC", "gcc")
    env.setdefault("CXX", "g++")
    return env


def _meson_command() -> list[str]:
    meson = shutil.which("meson")
    if meson:
        return [meson]
    command = [sys.executable, "-m", "mesonbuild.mesonmain"]
    if subprocess.run(command + ["--version"], cwd=ROOT, capture_output=True).returncode == 0:
        return command
    raise FileNotFoundError("Meson is not available as an executable or Python module")


def _run(command: list[str], *, env: dict[str, str]) -> None:
    print("+ " + subprocess.list2cmdline(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True, env=env)


def _find_built_plugin(build_dir: Path) -> Path:
    for stem in (PLUGIN_NAME, f"lib{PLUGIN_NAME}"):
        candidate = build_dir / f"{stem}{_plugin_suffix()}"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"missing built plugin under {build_dir}")


def _stage_linux_runtime(plugin: Path, target_dir: Path) -> None:
    if sys.platform != "linux":
        return
    completed = subprocess.run(["ldd", str(plugin)], check=True, capture_output=True, text=True)
    for line in completed.stdout.splitlines():
        match = re.match(r"\s*(libgomp\.so[^\s]*)\s+=>\s+(\S+)", line)
        if match and Path(match.group(2)).is_file():
            shutil.copy2(match.group(2), target_dir / match.group(1))
            return
    if "libgomp.so" in completed.stdout:
        raise RuntimeError(f"could not resolve libgomp required by {plugin}: {completed.stdout}")


def _stage_local_build(target_dir: Path) -> None:
    env = _configure_build_env(os.environ.copy())
    build_dir = ROOT / "build-wheel"
    if sys.platform == "win32":
        _run([sys.executable, "tools/ci_prepare_msys2.py"], env=env)
        _run([sys.executable, "tools/ci_build_msys2.py", "--clean", "--build-dir", str(build_dir), "--dist-dir", str(target_dir.parent)], env=env)
        plugin = target_dir / f"{PLUGIN_NAME}.dll"
        if not plugin.is_file():
            raise FileNotFoundError(plugin)
        return

    meson = _meson_command()
    setup_args = ["setup", str(build_dir), "--wipe"]
    if sys.platform == "linux":
        # The OpenMP build is unstable in the conservative Linux runtime.
        setup_args.append("-Dopenmp=disabled")
    _run(meson + setup_args, env=env)
    _run(meson + ["compile", "-C", str(build_dir)], env=env)
    plugin = _find_built_plugin(build_dir)
    staged_plugin = target_dir / f"{PLUGIN_NAME}{plugin.suffix}"
    shutil.copy2(plugin, staged_plugin)
    _stage_linux_runtime(staged_plugin, target_dir)
    _write_manifest(target_dir)


class CustomHook(BuildHookInterface[Any]):
    build_dir = ROOT / "build-wheel"
    dist_dir = ROOT / "vapoursynth" / "plugins" / PLUGIN_NAME

    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        del version
        build_data["pure_python"] = False
        platform_tag = os.environ.get("VS_CFL_PLATFORM_TAG") or str(next(tags.platform_tags()))
        build_data["tag"] = f"py3-none-{platform_tag}"

        shutil.rmtree(self.build_dir, ignore_errors=True)
        shutil.rmtree(self.dist_dir.parent.parent, ignore_errors=True)
        self.dist_dir.mkdir(parents=True, exist_ok=True)
        if not _stage_prebuilt_plugin(_project_version(), self.dist_dir):
            _stage_local_build(self.dist_dir)

    def finalize(self, version: str, build_data: dict[str, Any], artifact_path: str) -> None:
        del version, build_data, artifact_path
        shutil.rmtree(self.build_dir, ignore_errors=True)
        shutil.rmtree(self.dist_dir.parent.parent, ignore_errors=True)
