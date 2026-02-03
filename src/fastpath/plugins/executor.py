"""Plugin execution engine — worker thread and executor."""

from __future__ import annotations

import logging
import time
import warnings
from pathlib import Path

import numpy as np
from PySide6.QtCore import QObject, QThread, Signal

from .base import ModelPlugin, Plugin
from .context import SlideContext
from .types import PluginInput, PluginOutput, RegionOfInterest

logger = logging.getLogger(__name__)


class PluginWorker(QThread):
    """Worker thread for running a plugin."""

    finished = Signal(object)  # PluginOutput
    error = Signal(str)
    progress = Signal(int)

    def __init__(
        self,
        plugin: Plugin,
        plugin_input: PluginInput,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._plugin = plugin
        self._input = plugin_input

    def run(self) -> None:
        output: PluginOutput | None = None
        try:
            # Auto-load ModelPlugin if needed
            if isinstance(self._plugin, ModelPlugin) and not self._plugin.is_loaded:
                self._plugin.load_model()

            # Validate input
            valid, err = self._plugin.validate_input(self._input)
            if not valid:
                self.error.emit(f"Invalid input: {err}")
                return

            start = time.time()
            output = self._plugin.process(self._input, self.progress.emit)
            output.processing_time = time.time() - start

        except Exception as e:
            logger.exception("Plugin processing error")
            self.error.emit(str(e))
        finally:
            if output is None:
                output = PluginOutput(success=False, message="Plugin produced no output")
            self.finished.emit(output)


class PluginExecutor:
    """Manages SlideContext lifecycle and plugin execution.

    Owns a ``SlideContext`` and spawns ``PluginWorker`` threads.
    """

    def __init__(self) -> None:
        self._context: SlideContext | None = None
        self._worker: PluginWorker | None = None

    # ------------------------------------------------------------------
    # Slide lifecycle
    # ------------------------------------------------------------------

    def set_slide(self, path: str | Path) -> None:
        """Create a new SlideContext for the given .fastpath directory."""
        self.clear_slide()
        self._context = SlideContext(path)

    def clear_slide(self) -> None:
        """Discard the current SlideContext."""
        if self._context is not None:
            self._context.close()
        self._context = None

    @property
    def context(self) -> SlideContext | None:
        return self._context

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(
        self,
        plugin: Plugin,
        region: RegionOfInterest | None = None,
        annotations: list[dict] | None = None,
        parent: QObject | None = None,
    ) -> PluginWorker:
        """Build a PluginInput, start a worker, and return it.

        The caller should connect to the worker's ``finished``, ``error``,
        and ``progress`` signals.
        """
        if self._context is None:
            raise RuntimeError("No slide loaded — call set_slide() first")

        self.cleanup_worker()

        # Build PluginInput
        image: np.ndarray | None = None
        image_level: int | None = None

        if plugin.metadata.wants_image and region is not None:
            # Assemble image from tiles at working resolution
            mpp = plugin.metadata.resolution.working_mpp
            level = self._context.level_for_mpp(mpp)
            lx, ly = self._context.to_level(level, region.x, region.y)
            lw = region.w / self._context.level_downsample(level)
            lh = region.h / self._context.level_downsample(level)
            image = self._context.get_region(
                level, int(lx), int(ly), int(lw), int(lh)
            )
            image_level = level

        plugin_input = PluginInput(
            slide=self._context,
            region=region,
            image=image,
            image_level=image_level,
            annotations=annotations,
        )

        self._worker = PluginWorker(plugin, plugin_input, parent)
        self._worker.start()
        return self._worker

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def cleanup_worker(self) -> None:
        """Disconnect and wait for any existing worker."""
        if self._worker is not None:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", RuntimeWarning)
                for sig in (self._worker.finished, self._worker.error, self._worker.progress):
                    try:
                        sig.disconnect()
                    except RuntimeError:
                        pass
            if self._worker.isRunning():
                if not self._worker.wait(5000):
                    logger.warning("Plugin worker did not finish within 5s timeout")
            self._worker = None

    def cleanup(self) -> None:
        """Full cleanup — worker + context."""
        self.cleanup_worker()
        self.clear_slide()
