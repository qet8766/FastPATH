"""AI plugin discovery and management."""

from __future__ import annotations

import importlib.util
import logging
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal, Slot, Property

logger = logging.getLogger(__name__)

from .base import AIPlugin, PluginMetadata, PluginResult, OutputType

# Import backends for pyvips access
from fastpath.preprocess.backends import VIPSBackend, is_vips_available

try:
    import pyvips
except (ImportError, OSError):
    pyvips = None


class PluginWorker(QThread):
    """Worker thread for running AI plugins."""

    finished = Signal(dict)  # Result dict
    progress = Signal(int)  # Progress percentage
    error = Signal(str)  # Error message

    def __init__(
        self,
        plugin: AIPlugin,
        image: np.ndarray,
        context: dict,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.plugin = plugin
        self.image = image
        self.context = context

    def run(self) -> None:
        result_dict: dict = {}
        try:
            start_time = time.time()

            # Validate input
            valid, error = self.plugin.validate_input(self.image)
            if not valid:
                self.error.emit(f"Invalid input: {error}")
                return

            # Run inference
            result = self.plugin.process(self.image, self.context)
            result.processing_time = time.time() - start_time
            result_dict = result.to_dict()

        except Exception as e:
            logger.exception("Plugin processing error")
            self.error.emit(str(e))
        finally:
            # Always emit finished to signal thread completion
            self.finished.emit(result_dict)


class AIPluginManager(QObject):
    """Manages AI plugin discovery, loading, and execution.

    Discovers plugins from:
    1. Built-in plugins in fastpath.ai.plugins
    2. External plugins in user-specified directories

    Important: Call cleanup() explicitly before discarding this object to ensure
    proper resource cleanup. Do not rely solely on garbage collection.
    """

    pluginsChanged = Signal()
    processingStarted = Signal(str)  # plugin name
    processingFinished = Signal(dict)  # result
    processingError = Signal(str)  # error message
    processingProgress = Signal(int)  # progress percentage

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._plugins: dict[str, AIPlugin] = {}
        self._plugin_paths: list[Path] = []
        self._worker: PluginWorker | None = None
        self._loaded_models: set[str] = set()
        self._cleaned_up = False

    def __del__(self) -> None:
        """Clean up worker thread on destruction (fallback, prefer explicit cleanup())."""
        if not self._cleaned_up:
            self._cleanup_worker()

    def cleanup(self) -> None:
        """Explicitly clean up resources. Call this before discarding the manager.

        This method should be called explicitly rather than relying on __del__,
        which is not guaranteed to run immediately or at all during garbage collection.
        """
        if self._cleaned_up:
            return
        self._cleanup_worker()
        # Unload all models
        for name in list(self._loaded_models):
            try:
                self._plugins[name].unload_model()
            except Exception:
                pass
        self._loaded_models.clear()
        self._cleaned_up = True

    def _cleanup_worker(self) -> None:
        """Clean up the current worker thread, disconnecting signals and waiting for completion."""
        if self._worker is not None:
            try:
                # Disconnect all signals to prevent callbacks to stale objects
                self._worker.finished.disconnect()
                self._worker.error.disconnect()
                self._worker.progress.disconnect()
            except RuntimeError:
                # Signals may already be disconnected
                pass
            # Wait for thread to finish (timeout 5 seconds)
            if self._worker.isRunning():
                self._worker.wait(5000)
            self._worker = None

    @Property(int, notify=pluginsChanged)
    def pluginCount(self) -> int:
        """Number of registered plugins."""
        return len(self._plugins)

    @Slot(result="QVariantList")
    def getPluginList(self) -> list[dict]:
        """Get list of all registered plugins with metadata."""
        result = []
        for name, plugin in self._plugins.items():
            meta = plugin.metadata
            result.append({
                "name": meta.name,
                "description": meta.description,
                "version": meta.version,
                "author": meta.author,
                "inputType": meta.input_type.value,
                "outputType": meta.output_type.value,
                "labels": meta.labels,
                "isLoaded": name in self._loaded_models,
            })
        return result

    @Slot(str, result="QVariant")
    def getPluginInfo(self, name: str) -> dict | None:
        """Get detailed info about a specific plugin."""
        if name not in self._plugins:
            return None

        plugin = self._plugins[name]
        meta = plugin.metadata
        return {
            "name": meta.name,
            "description": meta.description,
            "version": meta.version,
            "author": meta.author,
            "inputType": meta.input_type.value,
            "outputType": meta.output_type.value,
            "inputSize": list(meta.input_size) if meta.input_size else None,
            "labels": meta.labels,
            "isLoaded": name in self._loaded_models,
        }

    def register_plugin(self, plugin: AIPlugin) -> None:
        """Register a plugin instance."""
        name = plugin.metadata.name
        self._plugins[name] = plugin
        self.pluginsChanged.emit()

    def unregister_plugin(self, name: str) -> None:
        """Unregister a plugin by name."""
        if name in self._plugins:
            if name in self._loaded_models:
                self._plugins[name].unload_model()
                self._loaded_models.discard(name)
            del self._plugins[name]
            self.pluginsChanged.emit()

    @Slot(str)
    def addPluginPath(self, path: str) -> None:
        """Add a directory to search for plugins."""
        path = Path(path)
        if path.is_dir() and path not in self._plugin_paths:
            self._plugin_paths.append(path)

    @Slot()
    def discoverPlugins(self) -> None:
        """Discover and load plugins from registered paths."""
        # Load built-in plugins
        self._load_builtin_plugins()

        # Load external plugins
        for plugin_dir in self._plugin_paths:
            self._load_plugins_from_directory(plugin_dir)

        self.pluginsChanged.emit()

    def _load_builtin_plugins(self) -> None:
        """Load built-in plugins from fastpath.ai.plugins."""
        try:
            from . import plugins

            plugins_dir = Path(plugins.__file__).parent
            self._load_plugins_from_directory(plugins_dir)
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

        # Also check for plugin.py in subdirectories
        for subdir in directory.iterdir():
            if subdir.is_dir():
                plugin_file = subdir / "plugin.py"
                if plugin_file.exists():
                    self._load_plugin_from_file(plugin_file)

    def _load_plugin_from_file(self, filepath: Path) -> None:
        """Load a plugin from a Python file."""
        try:
            # Create module spec
            module_name = f"fastpath_plugin_{filepath.stem}"
            spec = importlib.util.spec_from_file_location(module_name, filepath)
            if spec is None or spec.loader is None:
                return

            # Load module
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            # Find AIPlugin subclasses
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                try:
                    if issubclass(attr, AIPlugin) and attr is not AIPlugin:
                        plugin = attr()
                        self.register_plugin(plugin)
                except TypeError:
                    pass  # attr is not a class
                except Exception as e:
                    logger.warning(
                        "Failed to instantiate plugin %s from %s: %s",
                        attr_name, filepath, e
                    )

        except Exception as e:
            logger.warning("Failed to load plugin from %s: %s", filepath, e)

    @Slot(str)
    def loadModel(self, plugin_name: str) -> None:
        """Load a plugin's model into memory."""
        if plugin_name not in self._plugins:
            return

        if plugin_name not in self._loaded_models:
            try:
                self._plugins[plugin_name].load_model()
                self._loaded_models.add(plugin_name)
                self.pluginsChanged.emit()
            except Exception as e:
                self.processingError.emit(f"Failed to load model: {e}")

    @Slot(str)
    def unloadModel(self, plugin_name: str) -> None:
        """Unload a plugin's model from memory."""
        if plugin_name in self._plugins and plugin_name in self._loaded_models:
            self._plugins[plugin_name].unload_model()
            self._loaded_models.discard(plugin_name)
            self.pluginsChanged.emit()

    @Slot(str, str, float, float, float, float, float)
    def processRegion(
        self,
        plugin_name: str,
        slide_path: str,
        x: float,
        y: float,
        width: float,
        height: float,
        mpp: float,
    ) -> None:
        """Process a region using a plugin.

        Args:
            plugin_name: Name of the plugin to use
            slide_path: Path to the .fastpath directory
            x, y: Top-left corner in slide coordinates
            width, height: Region size in slide coordinates
            mpp: Microns per pixel
        """
        if plugin_name not in self._plugins:
            self.processingError.emit(f"Plugin not found: {plugin_name}")
            return

        if self._worker is not None and self._worker.isRunning():
            self.processingError.emit("Another process is already running")
            return

        # Clean up any previous worker (even if finished) to prevent memory leaks
        self._cleanup_worker()

        plugin = self._plugins[plugin_name]

        # Ensure model is loaded
        if plugin_name not in self._loaded_models:
            self.loadModel(plugin_name)

        # Load region image
        try:
            image = self._load_region(slide_path, x, y, width, height)
        except Exception as e:
            self.processingError.emit(f"Failed to load region: {e}")
            return

        context = {
            "mpp": mpp,
            "region": (x, y, width, height),
            "slide_path": slide_path,
        }

        # Start worker thread
        self._worker = PluginWorker(plugin, image, context, self)
        self._worker.finished.connect(self._on_processing_finished)
        self._worker.error.connect(self._on_processing_error)
        self._worker.progress.connect(self.processingProgress.emit)

        self.processingStarted.emit(plugin_name)
        self._worker.start()

    def _load_region(
        self, slide_path: str, x: float, y: float, width: float, height: float
    ) -> np.ndarray:
        """Load a region from the tile pyramid."""
        from fastpath.core.slide import SlideManager

        manager = SlideManager()
        try:
            if not manager.load(slide_path):
                raise ValueError(f"Failed to load slide: {slide_path}")

            # Determine best level for the region
            # For simplicity, use level 0 tiles and composite
            tile_size = manager.tileSize

            # Calculate tile range
            col_start = int(x / tile_size)
            col_end = int((x + width) / tile_size) + 1
            row_start = int(y / tile_size)
            row_end = int((y + height) / tile_size) + 1

            # Create composite using pyvips or numpy
            composite_width = (col_end - col_start) * tile_size
            composite_height = (row_end - row_start) * tile_size

            if is_vips_available() and pyvips is not None:
                # Use pyvips for compositing
                bg_color = (255, 255, 255)
                composite = VIPSBackend.new_rgb(composite_width, composite_height, bg_color)

                for row in range(row_start, row_end):
                    for col in range(col_start, col_end):
                        tile_path = manager.getTilePath(0, col, row)
                        if tile_path:
                            tile = pyvips.Image.new_from_file(tile_path, access="sequential")
                            # Ensure RGB
                            if tile.bands == 4:
                                tile = tile.extract_band(0, n=3)
                            paste_x = (col - col_start) * tile_size
                            paste_y = (row - row_start) * tile_size
                            composite = composite.insert(tile, paste_x, paste_y)

                # Crop to exact region
                crop_x = int(x - col_start * tile_size)
                crop_y = int(y - row_start * tile_size)
                composite = composite.crop(crop_x, crop_y, int(width), int(height))

                # Convert to numpy
                return VIPSBackend.to_numpy(composite)
            else:
                # Fallback: use numpy directly
                composite = np.full((composite_height, composite_width, 3), 255, dtype=np.uint8)

                for row in range(row_start, row_end):
                    for col in range(col_start, col_end):
                        tile = manager.getTile(0, col, row)
                        if tile is not None:
                            # Convert QImage to numpy
                            tile = tile.convertToFormat(tile.Format.Format_RGB888)
                            # Make explicit copy - tile buffer is temporary and will be freed
                            # when tile goes out of scope, causing use-after-free if not copied
                            arr = np.array(tile.bits()).reshape(tile.height(), tile.width(), 3).copy()
                            paste_x = (col - col_start) * tile_size
                            paste_y = (row - row_start) * tile_size
                            composite[paste_y:paste_y + tile_size, paste_x:paste_x + tile_size] = arr

                # Crop to exact region
                crop_x = int(x - col_start * tile_size)
                crop_y = int(y - row_start * tile_size)
                return composite[crop_y:crop_y + int(height), crop_x:crop_x + int(width)]
        finally:
            # Always close the manager to prevent resource leaks
            manager.close()

    def _on_processing_finished(self, result: dict) -> None:
        """Handle processing completion."""
        self.processingFinished.emit(result)

    def _on_processing_error(self, error: str) -> None:
        """Handle processing error."""
        self.processingError.emit(error)
