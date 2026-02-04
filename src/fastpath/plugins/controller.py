"""PluginController — QML facade for the plugin system.

Composes ``PluginRegistry`` + ``PluginExecutor``.
"""

from __future__ import annotations

import logging

import threading

from PySide6.QtCore import QObject, Signal, Slot, Property

from fastpath.core.annotations import AnnotationManager

from .base import ModelPlugin, Plugin
from .executor import PluginExecutor
from .registry import PluginRegistry
from .types import PluginOutput, RegionOfInterest

logger = logging.getLogger(__name__)


class PluginController(QObject):
    """Thin QML-facing facade over PluginRegistry + PluginExecutor."""

    pluginsChanged = Signal()
    processingStarted = Signal(str)
    processingFinished = Signal(dict)
    processingError = Signal(str)
    processingProgress = Signal(int)
    cudaStatusChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._registry = PluginRegistry()
        self._executor = PluginExecutor()
        self._loaded_models: set[str] = set()
        self._last_output: PluginOutput | None = None
        self._cleaned_up = False
        self._annotation_manager: AnnotationManager | None = None
        self._current_plugin_name: str | None = None
        self._cuda_status = "Checking"
        self._cuda_check_in_progress = False

    def __del__(self) -> None:
        try:
            if not self._cleaned_up:
                self._executor.cleanup_worker()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @Property(int, notify=pluginsChanged)
    def pluginCount(self) -> int:
        return self._registry.count

    @Property(bool, notify=cudaStatusChanged)
    def cudaAvailable(self) -> bool:
        return self._cuda_status == "Available"

    @Property(str, notify=cudaStatusChanged)
    def cudaStatus(self) -> str:
        return self._cuda_status

    @property
    def last_output(self) -> PluginOutput | None:
        """Most recent PluginOutput (for overlay rendering / numpy access)."""
        return self._last_output

    # ------------------------------------------------------------------
    # Slide lifecycle (called by AppController)
    # ------------------------------------------------------------------

    def set_slide(self, path: str) -> None:
        """Create a SlideContext for the given path."""
        try:
            self._executor.set_slide(path)
        except Exception as e:
            logger.warning("Failed to create SlideContext for %s: %s", path, e)

    def clear_slide(self) -> None:
        """Discard the current SlideContext."""
        self._executor.clear_slide()

    # ------------------------------------------------------------------
    # Plugin registration (Python API)
    # ------------------------------------------------------------------

    def register_plugin(self, plugin: Plugin) -> None:
        self._registry.register(plugin)
        self.pluginsChanged.emit()

    def set_annotation_manager(self, manager: AnnotationManager | None) -> None:
        self._annotation_manager = manager

    def unregister_plugin(self, name: str) -> None:
        removed = self._registry.unregister(name)
        if removed is not None:
            if name in self._loaded_models:
                if isinstance(removed, ModelPlugin):
                    removed.unload_model()
                self._loaded_models.discard(name)
            self.pluginsChanged.emit()

    # ------------------------------------------------------------------
    # QML Slots
    # ------------------------------------------------------------------

    @Slot(result="QVariantList")
    def getPluginList(self) -> list[dict]:
        result = []
        for name, plugin in self._registry.plugins.items():
            meta = plugin.metadata
            result.append({
                "name": meta.name,
                "description": meta.description,
                "version": meta.version,
                "author": meta.author,
                "inputType": meta.input_type.value,
                "outputTypes": [ot.value for ot in meta.output_types],
                "labels": meta.labels,
                "isLoaded": name in self._loaded_models,
                "hasModel": isinstance(plugin, ModelPlugin),
                "workingMpp": meta.resolution.working_mpp,
            })
        return result

    @Slot(str, result="QVariant")
    def getPluginInfo(self, name: str) -> dict | None:
        plugin = self._registry.get(name)
        if plugin is None:
            return None

        meta = plugin.metadata
        return {
            "name": meta.name,
            "description": meta.description,
            "version": meta.version,
            "author": meta.author,
            "inputType": meta.input_type.value,
            "outputTypes": [ot.value for ot in meta.output_types],
            "inputSize": list(meta.input_size) if meta.input_size else None,
            "labels": meta.labels,
            "isLoaded": name in self._loaded_models,
            "hasModel": isinstance(plugin, ModelPlugin),
            "workingMpp": meta.resolution.working_mpp,
        }

    @Slot()
    def discoverPlugins(self) -> None:
        self._registry.discover()
        self.pluginsChanged.emit()

    @Slot(str)
    def addPluginPath(self, path: str) -> None:
        self._registry.add_search_path(path)

    @Slot(str)
    def loadModel(self, plugin_name: str) -> None:
        plugin = self._registry.get(plugin_name)
        if plugin is None:
            return
        if isinstance(plugin, ModelPlugin) and plugin_name not in self._loaded_models:
            try:
                plugin.load_model()
                self._loaded_models.add(plugin_name)
                self.pluginsChanged.emit()
            except Exception as e:
                self.processingError.emit(f"Failed to load model: {e}")

    @Slot(str)
    def unloadModel(self, plugin_name: str) -> None:
        plugin = self._registry.get(plugin_name)
        if plugin is not None and isinstance(plugin, ModelPlugin):
            if plugin_name in self._loaded_models:
                plugin.unload_model()
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
        """Process a region using a plugin."""
        plugin = self._registry.get(plugin_name)
        if plugin is None:
            self.processingError.emit(f"Plugin not found: {plugin_name}")
            return

        if self._executor.is_running:
            self.processingError.emit("Another process is already running")
            return

        # Ensure slide context matches the requested path
        ctx = self._executor.context
        if ctx is None or str(ctx.slide_path) != slide_path:
            try:
                self._executor.set_slide(slide_path)
            except Exception as e:
                self.processingError.emit(f"Failed to load slide: {e}")
                return

        roi = RegionOfInterest(x=x, y=y, w=width, h=height)
        self._current_plugin_name = plugin_name

        try:
            worker = self._executor.execute(plugin, region=roi, parent=self)
        except Exception as e:
            self.processingError.emit(str(e))
            return

        worker.finished.connect(self._on_finished)
        worker.error.connect(self._on_error)
        worker.progress.connect(self.processingProgress.emit)

        self.processingStarted.emit(plugin_name)

    # ------------------------------------------------------------------
    # Internal handlers
    # ------------------------------------------------------------------

    def _on_finished(self, output: PluginOutput) -> None:
        self._last_output = output
        if (
            output.success
            and output.annotations
            and self._annotation_manager is not None
            and self._is_flat_annotation_list(output.annotations)
        ):
            group = self._current_plugin_name or "plugin"
            try:
                self._annotation_manager.addAnnotationsBatch(output.annotations, group)
                result = output.to_dict()
                result["annotations"] = None
                result["annotationsRouted"] = True
                result["annotationGroup"] = group

                breakdown = self._build_annotation_breakdown(output)
                result["annotationBreakdown"] = breakdown
                if breakdown:
                    result["annotationCount"] = sum(breakdown.values())
                else:
                    result["annotationCount"] = len(output.annotations)

                self.processingFinished.emit(result)
                return
            except Exception as e:
                logger.warning("Failed to route annotations: %s", e)

        self.processingFinished.emit(output.to_dict())

    def _build_annotation_breakdown(self, output: PluginOutput) -> dict[str, int]:
        if output.measurements:
            for key in ("counts_by_type", "type_counts", "counts"):
                counts = output.measurements.get(key)
                if isinstance(counts, dict):
                    return {str(k): int(v) for k, v in counts.items()}

        breakdown: dict[str, int] = {}
        for ann in output.annotations or []:
            label = ann.get("label") or "Unknown"
            breakdown[label] = breakdown.get(label, 0) + 1
        return breakdown

    @staticmethod
    def _is_flat_annotation_list(annotations: list[dict]) -> bool:
        for ann in annotations:
            if not isinstance(ann, dict):
                continue
            if "geometry" in ann:
                return False
            if "coordinates" in ann:
                return True
        return False

    @Slot()
    def refreshCudaAvailability(self) -> None:
        if self._cuda_check_in_progress:
            return
        self._cuda_check_in_progress = True

        def _check() -> None:
            status = "Not available"
            try:
                import torch  # Heavy import; run in background
                status = "Available" if torch.cuda.is_available() else "Not available"
            except Exception:
                status = "Not available"

            self._cuda_check_in_progress = False
            if status != self._cuda_status:
                self._cuda_status = status
                self.cudaStatusChanged.emit()

        threading.Thread(target=_check, daemon=True).start()

    def _on_error(self, error: str) -> None:
        self.processingError.emit(error)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def cleanup(self) -> None:
        """Explicitly clean up resources."""
        if self._cleaned_up:
            return
        self._executor.cleanup()
        # Unload all models
        for name in list(self._loaded_models):
            plugin = self._registry.get(name)
            if plugin is not None and isinstance(plugin, ModelPlugin):
                try:
                    plugin.unload_model()
                except Exception as e:
                    logger.debug("Failed to unload model %s during cleanup: %s", name, e)
        self._loaded_models.clear()
        self._cleaned_up = True
