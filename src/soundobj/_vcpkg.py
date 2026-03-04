"""Auto-download and build vcpkg dependencies for soundobj."""
import os
import platform
import subprocess
import sys
from pathlib import Path


def _get_cache_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    return base / "soundobj-vcpkg"


def _get_triplet() -> str:
    machine = platform.machine().lower()
    is_arm = machine in ("arm64", "aarch64")
    if sys.platform == "win32":
        return "arm64-windows-static-md" if is_arm else "x64-windows-static-md"
    elif sys.platform == "darwin":
        return "arm64-osx" if is_arm else "x64-osx"
    elif sys.platform == "linux":
        return "arm64-linux" if is_arm else "x64-linux"
    else:
        sys.exit(f"Unable to determine vcpkg triplet for platform: {sys.platform}")


def _bootstrap_vcpkg(vcpkg_root: Path) -> Path:
    """Clone vcpkg (shallow) and bootstrap it. Returns path to vcpkg executable."""
    exe_name = "vcpkg.exe" if sys.platform == "win32" else "vcpkg"
    vcpkg_exe = vcpkg_root / exe_name
    if vcpkg_exe.exists():
        return vcpkg_exe
    if not vcpkg_root.exists():
        print("Cloning vcpkg (shallow)...")
        subprocess.check_call([
            "git", "clone", "--depth", "1",
            "https://github.com/microsoft/vcpkg.git",
            str(vcpkg_root),
        ])
    print("Bootstrapping vcpkg...")
    if sys.platform == "win32":
        subprocess.check_call([str(vcpkg_root / "bootstrap-vcpkg.bat"), "-disableMetrics"])
    else:
        subprocess.check_call([str(vcpkg_root / "bootstrap-vcpkg.sh"), "-disableMetrics"])
    return vcpkg_exe


def _is_valid_install_prefix(path: Path) -> bool:
    return (path / "include").exists() and (path / "lib").exists()


def _find_manifest() -> Path:
    """Find vcpkg.json walking up from this file's directory to the repo root."""
    d = Path(__file__).resolve().parent
    for _ in range(10):
        candidate = d / "vcpkg.json"
        if candidate.exists():
            return candidate
        parent = d.parent
        if parent == d:
            break
        d = parent
    raise FileNotFoundError("Cannot find vcpkg.json manifest")


def _iter_candidate_prefixes(manifest_dir: Path, triplet: str, cache_dir: Path):
    yield manifest_dir / "vcpkg_installed" / "current"
    # Project-local install root.
    yield manifest_dir / "vcpkg_installed" / triplet
    # Global cache install root used by local builds and build isolation.
    yield cache_dir / "installed" / triplet


def ensure_installed() -> Path:
    """Ensure vcpkg dependencies are installed. Returns the install prefix path.

    Checks VCPKG_INSTALL_PATH env var first (for CI pre-installed deps).
    Otherwise auto-downloads vcpkg and runs install.
    """
    env_path = os.environ.get("VCPKG_INSTALL_PATH")
    if env_path:
        p = Path(env_path)
        if _is_valid_install_prefix(p):
            return p
        raise FileNotFoundError(
            f"VCPKG_INSTALL_PATH={env_path} is missing include/ and lib/ directories"
        )

    triplet = _get_triplet()
    cache_dir = _get_cache_dir()
    vcpkg_root = cache_dir / "vcpkg"
    manifest = _find_manifest()
    manifest_dir = manifest.parent

    for candidate in _iter_candidate_prefixes(manifest_dir, triplet, cache_dir):
        if _is_valid_install_prefix(candidate):
            return candidate

    auto_install = os.environ.get("SOUNDOBJ_AUTO_INSTALL_VCPKG", "1").lower()
    if auto_install in {"0", "false", "no"}:
        raise RuntimeError(
            "Missing codec dependencies. Set VCPKG_INSTALL_PATH or enable "
            "automatic installation by setting SOUNDOBJ_AUTO_INSTALL_VCPKG=1."
        )

    install_root = Path(os.environ.get("SOUNDOBJ_VCPKG_INSTALL_ROOT", str(cache_dir / "installed")))
    install_dir = install_root / triplet

    vcpkg_exe = _bootstrap_vcpkg(vcpkg_root)
    print(f"Installing vcpkg packages for {triplet}...")
    env = os.environ.copy()
    env.setdefault("VCPKG_DOWNLOADS", str(cache_dir / "downloads"))
    try:
        subprocess.check_call([
            str(vcpkg_exe), "install",
            "--triplet", triplet,
            "--x-manifest-root", str(manifest_dir),
            "--x-install-root", str(install_root),
        ], env=env)
    except subprocess.CalledProcessError as e:
        sys.exit(f"vcpkg install failed for {triplet} with code {e.returncode}")

    if not _is_valid_install_prefix(install_dir):
        raise RuntimeError(f"vcpkg install completed but prefix is missing: {install_dir}")

    return install_dir


if __name__ == "__main__":
    path = ensure_installed()
    print(f"vcpkg install path: {path}")
