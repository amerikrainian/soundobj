from pathlib import Path

from setuptools import setup
from setuptools.command.egg_info import egg_info as _egg_info


class egg_info(_egg_info):
    def run(self):
        # Drop stale file lists that can retain absolute paths from older CFFI builds.
        sources = Path(self.egg_info) / "SOURCES.txt"
        if sources.exists():
            sources.unlink()
        super().run()


setup(
    cffi_modules=["src/soundobj/_build_ffi.py:ffibuilder"],
    cmdclass={"egg_info": egg_info},
)
