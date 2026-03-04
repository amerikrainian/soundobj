"""CFFI build script for soundobj._c_miniaudio."""
import os
import subprocess
import sys
from pathlib import Path

from cffi import FFI

_PKG_DIR = Path(__file__).resolve().parent
_LIB_DIR = _PKG_DIR / "lib"
_DECLARATIONS_H = _PKG_DIR / "declarations.h"

ffibuilder = FFI()


def _try_pkg_config():
    """Try to get compiler/linker flags via pkg-config. Returns (include_dirs, library_dirs, libraries) or None."""
    try:
        cflags = subprocess.check_output(
            ["pkg-config", "--cflags", "opus", "opusfile", "ogg", "vorbis", "vorbisfile"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
        libs = subprocess.check_output(
            ["pkg-config", "--libs", "opus", "opusfile", "ogg", "vorbis", "vorbisfile"],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return None

    include_dirs = []
    library_dirs = []
    libraries = []
    for token in cflags.split():
        if token.startswith("-I"):
            include_dirs.append(token[2:])
    for token in libs.split():
        if token.startswith("-L"):
            library_dirs.append(token[2:])
        elif token.startswith("-l"):
            libraries.append(token[2:])
    if not libraries:
        return None
    return include_dirs, library_dirs, libraries


def _get_vcpkg_flags():
    """Get compiler/linker flags from vcpkg (auto-download if needed)."""
    # Import _vcpkg as a sibling file — can't use `from soundobj._vcpkg` because
    # this script is execfile()'d by cffi before the package is installed.
    import importlib.util
    spec = importlib.util.spec_from_file_location("_vcpkg", _PKG_DIR / "_vcpkg.py")
    _vcpkg = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(_vcpkg)
    install_path = _vcpkg.ensure_installed()
    return (
        [str(install_path / "include")],
        [str(install_path / "lib")],
        ["opus", "opusfile", "ogg", "vorbis", "vorbisfile"],
    )


def _get_flags():
    """Get compiler/linker flags: try VCPKG_INSTALL_PATH env, then pkg-config, then auto-download vcpkg."""
    env_path = os.environ.get("VCPKG_INSTALL_PATH")
    if env_path:
        p = Path(env_path)
        return (
            [str(p / "include")],
            [str(p / "lib")],
            ["opus", "opusfile", "ogg", "vorbis", "vorbisfile"],
        )

    result = _try_pkg_config()
    if result is not None:
        return result

    print("pkg-config not available or missing codec libs, falling back to vcpkg...")
    return _get_vcpkg_flags()


include_dirs, library_dirs, libraries = _get_flags()
# Always include our bundled lib/ dir for miniaudio.h and codec wrappers
include_dirs.insert(0, str(_LIB_DIR))

# When linking static .a archives into a shared library, the linker only pulls
# in symbols that are directly referenced.  The codec backends use vtable
# pointers, so the linker misses them.  Force all symbols to be included.
extra_link_args = []
if sys.platform == "linux":
    for lib_dir in library_dirs:
        static_libs = [os.path.join(lib_dir, f"lib{l}.a") for l in libraries]
        if all(os.path.exists(a) for a in static_libs):
            extra_link_args = ["-Wl,--whole-archive"] + static_libs + ["-Wl,--no-whole-archive"]
            libraries = []  # linked via extra_link_args now
            library_dirs = []
            break
elif sys.platform == "darwin":
    for lib_dir in library_dirs:
        static_libs = [os.path.join(lib_dir, f"lib{l}.a") for l in libraries]
        if all(os.path.exists(a) for a in static_libs):
            extra_link_args = ["-Wl,-force_load," + a for a in static_libs]
            libraries = []
            library_dirs = []
            break

with open(_DECLARATIONS_H, "r") as f:
    cdefs = f.read()
ffibuilder.cdef(cdefs)

ffibuilder.set_source("soundobj._c_miniaudio", """
	#include <stdint.h>
	#include <stdlib.h>
	#define MINIAUDIO_IMPLEMENTATION
	#include "miniaudio.h"
	#include "miniaudio_libopus.h"
	#include "miniaudio_libvorbis.h"
	#include "miniaudio_libopus.c"
	#include "miniaudio_libvorbis.c"
	ma_decoding_backend_vtable** soundobj_get_custom_decoders(ma_uint32* count) {
		static ma_decoding_backend_vtable* custom_decoders[2];
		custom_decoders[0] = ma_decoding_backend_libvorbis;
		custom_decoders[1] = ma_decoding_backend_libopus;
		if (count) *count = sizeof(custom_decoders) / sizeof(custom_decoders[0]);
		return custom_decoders;
	}
""",
    include_dirs=include_dirs,
    library_dirs=library_dirs,
    libraries=libraries,
    extra_link_args=extra_link_args,
)


if __name__ == "__main__":
    ffibuilder.compile(verbose=True)
