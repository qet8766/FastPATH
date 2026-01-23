"""FastPATH - Extensible pathology whole-slide image viewer."""

__version__ = "0.1.0"

# Suppress libvips module-loading warnings (jxl, magick, poppler) during import.
# These warnings come from optional modules that aren't needed for WSI processing.
# Must run before any pyvips import anywhere in the package.
def _setup_vips_quiet():
    """Configure VIPS DLL paths and suppress module warnings."""
    import os
    import sys
    import ctypes

    from fastpath.config import VIPS_BASE_PATH, VIPS_REQUIRED_DLLS

    # Set warning level (doesn't help with module load warnings, but good to have)
    os.environ["VIPS_WARNING"] = "0"

    # Windows DLL setup
    if sys.platform == "win32":
        if VIPS_BASE_PATH.exists():
            vips_dirs = list(VIPS_BASE_PATH.glob("vips-dev-*"))
            if vips_dirs:
                vips_bin = vips_dirs[0] / "bin"
                if vips_bin.exists():
                    if hasattr(os, "add_dll_directory"):
                        os.add_dll_directory(str(vips_bin))
                        vips_modules = vips_bin / "vips-modules-8.18"
                        if vips_modules.exists():
                            os.add_dll_directory(str(vips_modules))
                    # Pre-load required DLLs
                    for dll in VIPS_REQUIRED_DLLS:
                        dll_path = vips_bin / dll
                        if dll_path.exists():
                            try:
                                ctypes.CDLL(str(dll_path))
                            except OSError:
                                pass

    # Import pyvips with C-level stderr suppressed to hide module warnings
    try:
        stderr_fd = sys.stderr.fileno()
        old_stderr_fd = os.dup(stderr_fd)
        devnull = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(devnull, stderr_fd)
            import pyvips  # noqa: F401
        finally:
            os.dup2(old_stderr_fd, stderr_fd)
            os.close(old_stderr_fd)
            os.close(devnull)
    except (ImportError, OSError):
        pass  # pyvips not available, will be handled by backends.py

_setup_vips_quiet()
del _setup_vips_quiet
