"""Plugin discovery and registration.

Plain Python — no Qt dependencies.
"""

from __future__ import annotations

import importlib.util
import inspect
import logging
import sys
from pathlib import Path

from .base import Plugin

logger = logging.getLogger(__name__)


class PluginRegistry:
    """Discovers, registers, and retrieves plugins."""

    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}
        self._search_paths: list[Path] = []

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, plugin: Plugin) -> None:
        """Register a plugin instance."""
        name = plugin.metadata.name
        self._plugins[name] = plugin

    def unregister(self, name: str) -> Plugin | None:
        """Remove a plugin by name. Returns the removed plugin or None."""
        return self._plugins.pop(name, None)

    def get(self, name: str) -> Plugin | None:
        """Retrieve a plugin by name."""
        return self._plugins.get(name)

    @property
    def plugins(self) -> dict[str, Plugin]:
        """All registered plugins (read-only view)."""
        return dict(self._plugins)

    @property
    def count(self) -> int:
        return len(self._plugins)

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def add_search_path(self, path: str | Path) -> None:
        """Add a directory to search for external plugins."""
        p = Path(path)
        if p.is_dir() and p not in self._search_paths:
            self._search_paths.append(p)

    def discover(self) -> None:
        """Scan built-in examples and external search paths for plugins."""
        # Built-in examples
        self._load_builtin_plugins()

        # External directories
        for search_dir in self._search_paths:
            self._load_plugins_from_directory(search_dir)

    def _load_builtin_plugins(self) -> None:
        """Load built-in plugins from fastpath.plugins.examples."""
        try:
            from fastpath.plugins import examples

            examples_dir = Path(examples.__file__).parent
            self._load_plugins_from_directory(examples_dir)
        except ImportError:
            pass

    def _load_plugins_from_directory(self, directory: Path) -> None:
        """Load all plugins from a directory."""
        if not directory.is_dir():
            return

        for py_file in directory.glob("*.py"):
            if py_file.name.startswith("_"):
                continue
            self._load_plugin_from_file(py_file)

    def _load_plugin_from_file(self, filepath: Path) -> None:
        """Load concrete Plugin subclasses from a Python file."""
        try:
            module_name = f"fastpath_plugin_{filepath.stem}"
            spec = importlib.util.spec_from_file_location(module_name, filepath)
            if spec is None or spec.loader is None:
                return

            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                try:
                    if (
                        inspect.isclass(attr)
                        and issubclass(attr, Plugin)
                        and attr is not Plugin
                        and not getattr(attr, "__abstractmethods__", None)
                    ):
                        plugin = attr()
                        self.register(plugin)
                except TypeError:
                    pass
                except Exception as e:
                    logger.warning(
                        "Failed to instantiate plugin %s from %s: %s",
                        attr_name,
                        filepath,
                        e,
                    )

        except Exception as e:
            logger.warning("Failed to load plugin from %s: %s", filepath, e)
