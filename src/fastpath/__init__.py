"""FastPATH - Extensible pathology whole-slide image viewer."""

__version__ = "0.1.0"


# Suppress libvips module-loading warnings (jxl, magick, poppler) during import.
# These warnings come from optional modules that aren't needed for WSI processing.
# Must run before any pyvips import anywhere in the package.
def _setup_vips_quiet():
    """Configure VIPS DLL paths and suppress module warnings."""
    import logging
    import os
    import sys
    import ctypes

    from fastpath.config import VIPS_BASE_PATH, VIPS_REQUIRED_DLLS

    _logger = logging.getLogger(__name__)

    # Set warning level (doesn't help with module load warnings, but good to have)
    os.environ["VIPS_WARNING"] = "0"

    # Windows DLL setup
    if sys.platform == "win32":
        _setup_windows_vips(os, ctypes, VIPS_BASE_PATH, VIPS_REQUIRED_DLLS, _logger)

    # Import pyvips with C-level stderr suppressed to hide module warnings.
    # We use os.dup2 (not contextlib.redirect_stderr) because libvips writes
    # directly to the C-level file descriptor, bypassing Python's sys.stderr.
    _import_pyvips_quiet(os, sys, _logger)


def _setup_windows_vips(os, ctypes, vips_base_path, required_dlls, _logger):
    """Set up VIPS DLL directories and pre-load required DLLs on Windows."""
    if not vips_base_path.exists():
        return

    vips_dirs = sorted((d for d in vips_base_path.glob("vips-dev-*") if d.is_dir()), reverse=True)
    if not vips_dirs:
        return

    # Use the latest version if multiple are found
    vips_bin = vips_dirs[0] / "bin"
    if not vips_bin.exists():
        return

    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(vips_bin))
        vips_modules = vips_bin / "vips-modules-8.18"
        if vips_modules.exists():
            os.add_dll_directory(str(vips_modules))

    # Pre-load required DLLs
    for dll in required_dlls:
        dll_path = vips_bin / dll
        if dll_path.exists():
            try:
                ctypes.CDLL(str(dll_path))
            except OSError as e:
                _logger.debug("Failed to pre-load DLL %s: %s", dll, e)


def _import_pyvips_quiet(os, sys, _logger):
    """Import pyvips with C-level stderr suppressed to hide module warnings."""
    try:
        stderr_fd = sys.stderr.fileno()
    except (AttributeError, OSError):
        # fileno() unavailable (IDLE, embedded interpreters) — import without suppression
        try:
            import pyvips  # noqa: F401
        except ImportError:
            _logger.debug("pyvips not available")
        return

    try:
        old_stderr_fd = os.dup(stderr_fd)
        devnull = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(devnull, stderr_fd)
            import pyvips  # noqa: F401
        finally:
            os.dup2(old_stderr_fd, stderr_fd)
            os.close(old_stderr_fd)
            os.close(devnull)
    except (ImportError, OSError) as e:
        _logger.debug("pyvips import issue: %s", e)


_setup_vips_quiet()
del _setup_vips_quiet
del _setup_windows_vips
del _import_pyvips_quiet
