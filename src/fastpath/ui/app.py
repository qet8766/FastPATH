"""QML application setup for FastPATH viewer."""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Slot, Signal, Property, QThread
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from fastpath.config import TILE_CACHE_SIZE_MB, PREFETCH_DISTANCE

# Threshold for cache miss ratio - if more than this fraction of tiles are uncached,
# show all tiles immediately rather than waiting for cache (avoids gray screen)
CACHE_MISS_THRESHOLD = 0.3


def _normalize_file_url(path: str) -> str:
    """Convert file:// URL to local filesystem path.

    Handles both file:/// (Windows) and file:// (Unix) prefixes.
    """
    if path.startswith("file:///"):
        return path[8:]
    elif path.startswith("file://"):
        return path[7:]
    return path
from fastpath.core.slide import SlideManager
from fastpath.core.annotations import AnnotationManager
from fastpath.ai.manager import AIPluginManager
from fastpath.ui.providers import TileImageProvider, ThumbnailProvider
from fastpath.ui.models import TileModel, RecentFilesModel, FileListModel
from fastpath.ui.navigator import SlideNavigator
from fastpath.ui.settings import Settings
from fastpath_core import RustTileScheduler

logger = logging.getLogger(__name__)


class PreprocessWorker(QThread):
    """Background worker for preprocessing slides."""

    progressChanged = Signal(float, str)  # progress (0-1), status message
    finished = Signal(str)  # result path or empty on error
    errorOccurred = Signal(str)  # error message

    def __init__(
        self,
        input_path: str,
        output_dir: str,
        tile_size: int = 512,
        quality: int = 95,
        method: str = "level1",
        force: bool = False,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.input_path = Path(input_path)
        self.output_dir = Path(output_dir)
        self.tile_size = tile_size
        self.quality = quality
        self.method = method
        self.force = force
        self._cancelled = False

    def cancel(self) -> None:
        """Request cancellation of preprocessing."""
        self._cancelled = True

    def run(self) -> None:
        """Run preprocessing in background thread."""
        try:
            from fastpath.preprocess.pyramid import (
                VipsPyramidBuilder,
                is_vips_dzsave_available,
            )

            self.progressChanged.emit(0.0, "Starting preprocessing...")

            # Check pyvips availability
            if not is_vips_dzsave_available():
                raise RuntimeError(
                    "FastPATH requires pyvips with OpenSlide support. "
                    "Please install libvips with OpenSlide enabled."
                )

            self.progressChanged.emit(0.05, "Initializing pyvips dzsave...")
            builder = VipsPyramidBuilder(
                tile_size=self.tile_size,
                jpeg_quality=self.quality,
                method=self.method,
            )

            def progress_callback(stage: str, current: int, total: int) -> None:
                if self._cancelled:
                    raise InterruptedError("Preprocessing cancelled")
                # Map stages to progress ranges
                if stage == "thumbnail":
                    progress = 0.1
                elif stage == "dzsave":
                    progress = 0.8
                elif stage.startswith("level_"):
                    progress = 0.8 + 0.15 * (current / max(total, 1))
                else:
                    progress = 0.5
                self.progressChanged.emit(progress, f"{stage}: {current}/{total}")

            self.progressChanged.emit(0.1, "Processing slide...")
            result = builder.build(
                self.input_path,
                self.output_dir,
                progress_callback=progress_callback,
                force=self.force,
            )

            if self._cancelled:
                self.errorOccurred.emit("Preprocessing cancelled")
                return

            self.progressChanged.emit(1.0, "Complete!")
            self.finished.emit(str(result) if result else "")

        except InterruptedError:
            self.errorOccurred.emit("Preprocessing cancelled")
        except Exception as e:
            logger.exception("Preprocessing failed")
            self.errorOccurred.emit(str(e))


class BatchPreprocessWorker(QThread):
    """Background worker for parallel batch preprocessing of multiple slides."""

    fileStatusChanged = Signal(int, str)  # index, status (pending/processing/done/skipped/error)
    fileProgress = Signal(int, float)  # index, progress (0-1)
    overallProgress = Signal(float)  # overall progress (0-1)
    allFinished = Signal(int, int, int, list)  # processed, skipped, errors, error_details

    def __init__(
        self,
        files: list[str],
        output_dir: str,
        tile_size: int = 512,
        quality: int = 95,
        method: str = "level1",
        force: bool = False,
        parallel_workers: int = 3,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._files = files
        self._output_dir = Path(output_dir)
        self._tile_size = tile_size
        self._quality = quality
        self._method = method
        self._force = force
        self._parallel = parallel_workers
        self._cancelled = False
        self._completed_count = 0
        self._lock = threading.Lock()

    def cancel(self) -> None:
        """Request cancellation of batch preprocessing."""
        self._cancelled = True

    def run(self) -> None:
        """Run parallel batch preprocessing."""
        from concurrent.futures import ThreadPoolExecutor, as_completed
        from fastpath.preprocess.pyramid import (
            VipsPyramidBuilder,
            check_pyramid_status,
            PyramidStatus,
        )

        processed = 0
        skipped = 0
        errors = 0
        error_details: list[tuple[str, str]] = []  # (filename, error_message)

        total_files = len(self._files)
        if total_files == 0:
            self.allFinished.emit(0, 0, 0, [])
            return

        def process_file(index: int, file_path: str) -> tuple[int, str, str | None]:
            """Process a single file. Returns (index, status, error_message)."""
            if self._cancelled:
                return (index, "pending", None)

            self.fileStatusChanged.emit(index, "processing")
            self.fileProgress.emit(index, 0.0)

            try:
                slide_path = Path(file_path)

                # Check if already exists
                pyramid_name = slide_path.stem + ".fastpath"
                pyramid_dir = self._output_dir / pyramid_name
                status = check_pyramid_status(pyramid_dir)

                if status == PyramidStatus.COMPLETE and not self._force:
                    self.fileProgress.emit(index, 1.0)
                    return (index, "skipped", None)

                # Build pyramid
                builder = VipsPyramidBuilder(
                    tile_size=self._tile_size,
                    jpeg_quality=self._quality,
                    method=self._method,
                )

                def progress_cb(stage: str, current: int, total: int) -> None:
                    if self._cancelled:
                        raise InterruptedError("Cancelled")
                    if stage == "dzsave":
                        self.fileProgress.emit(index, 0.8)
                    elif stage == "thumbnail":
                        self.fileProgress.emit(index, 0.1)

                result = builder.build(
                    slide_path,
                    self._output_dir,
                    progress_callback=progress_cb,
                    force=self._force,
                )

                self.fileProgress.emit(index, 1.0)

                if result is None:
                    return (index, "skipped", None)
                return (index, "done", None)

            except InterruptedError:
                return (index, "pending", "Cancelled")
            except Exception as e:
                logger.exception("Error processing %s", file_path)
                return (index, "error", str(e))

        # Process files in parallel using ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=self._parallel) as executor:
            futures = {
                executor.submit(process_file, i, f): (i, f)
                for i, f in enumerate(self._files)
            }

            for future in as_completed(futures):
                if self._cancelled:
                    break

                index, status, error_msg = future.result()
                self.fileStatusChanged.emit(index, status)

                if status == "done":
                    processed += 1
                elif status == "skipped":
                    skipped += 1
                elif status == "error":
                    errors += 1
                    file_name = Path(self._files[index]).name
                    error_details.append((file_name, error_msg or "Unknown error"))

                # Update overall progress
                with self._lock:
                    self._completed_count += 1
                    overall = self._completed_count / total_files
                    self.overallProgress.emit(overall)

        self.allFinished.emit(processed, skipped, errors, error_details)


class PreprocessController(QObject):
    """Controller for preprocessing mode exposed to QML."""

    # Single file mode signals
    isProcessingChanged = Signal()
    progressChanged = Signal()
    statusChanged = Signal()
    inputFileChanged = Signal()
    outputDirChanged = Signal()
    resultPathChanged = Signal()
    errorOccurred = Signal(str)
    preprocessingFinished = Signal(str)  # result path

    # Batch mode signals
    inputModeChanged = Signal()
    inputFolderChanged = Signal()
    overallProgressChanged = Signal()
    processedCountChanged = Signal()
    skippedCountChanged = Signal()
    errorCountChanged = Signal()
    forceChanged = Signal()
    parallelWorkersChanged = Signal()
    batchCompleteChanged = Signal()
    firstResultPathChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # Single file mode state
        self._is_processing = False
        self._progress = 0.0
        self._status = "Ready"
        self._input_file = ""
        self._output_dir = ""
        self._result_path = ""
        self._worker: PreprocessWorker | None = None

        # Batch mode state
        self._input_mode = "single"  # "single" or "folder"
        self._input_folder = ""
        self._file_list_model = FileListModel(self)
        self._batch_worker: BatchPreprocessWorker | None = None
        self._overall_progress = 0.0
        self._processed_count = 0
        self._skipped_count = 0
        self._error_count = 0
        self._force = False
        self._parallel_workers = 3
        self._batch_complete = False
        self._first_result_path = ""
        self._error_details: list[tuple[str, str]] = []

        # Settings with defaults
        self._tile_size = 512
        self._quality = 95

    @Property(bool, notify=isProcessingChanged)
    def isProcessing(self) -> bool:
        return self._is_processing

    @Property(float, notify=progressChanged)
    def progress(self) -> float:
        return self._progress

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    @Property(str, notify=inputFileChanged)
    def inputFile(self) -> str:
        return self._input_file

    @inputFile.setter
    def inputFile(self, value: str) -> None:
        if self._input_file != value:
            self._input_file = value
            self.inputFileChanged.emit()

    @Property(str, notify=outputDirChanged)
    def outputDir(self) -> str:
        return self._output_dir

    @outputDir.setter
    def outputDir(self, value: str) -> None:
        if self._output_dir != value:
            self._output_dir = value
            self.outputDirChanged.emit()

    @Property(str, notify=resultPathChanged)
    def resultPath(self) -> str:
        return self._result_path

    # Batch mode properties
    @Property(str, notify=inputModeChanged)
    def inputMode(self) -> str:
        return self._input_mode

    @inputMode.setter
    def inputMode(self, value: str) -> None:
        if self._input_mode != value:
            self._input_mode = value
            self.inputModeChanged.emit()

    @Property(str, notify=inputFolderChanged)
    def inputFolder(self) -> str:
        return self._input_folder

    @inputFolder.setter
    def inputFolder(self, value: str) -> None:
        if self._input_folder != value:
            self._input_folder = value
            self.inputFolderChanged.emit()

    @Property(QObject, constant=True)
    def fileListModel(self) -> FileListModel:
        return self._file_list_model

    @Property(float, notify=overallProgressChanged)
    def overallProgress(self) -> float:
        return self._overall_progress

    @Property(int, notify=processedCountChanged)
    def processedCount(self) -> int:
        return self._processed_count

    @Property(int, notify=skippedCountChanged)
    def skippedCount(self) -> int:
        return self._skipped_count

    @Property(int, notify=errorCountChanged)
    def errorCount(self) -> int:
        return self._error_count

    @Property(bool, notify=forceChanged)
    def force(self) -> bool:
        return self._force

    @force.setter
    def force(self, value: bool) -> None:
        if self._force != value:
            self._force = value
            self.forceChanged.emit()

    @Property(int, notify=parallelWorkersChanged)
    def parallelWorkers(self) -> int:
        return self._parallel_workers

    @parallelWorkers.setter
    def parallelWorkers(self, value: int) -> None:
        if self._parallel_workers != value:
            self._parallel_workers = max(1, min(8, value))  # Clamp 1-8
            self.parallelWorkersChanged.emit()

    @Property(bool, notify=batchCompleteChanged)
    def batchComplete(self) -> bool:
        return self._batch_complete

    @Property(str, notify=firstResultPathChanged)
    def firstResultPath(self) -> str:
        return self._first_result_path

    @Slot(str)
    def setInputMode(self, mode: str) -> None:
        """Set input mode (single or folder)."""
        self.inputMode = mode

    @Slot(str)
    def setInputFile(self, path: str) -> None:
        """Set input file from QML (handles file:// URLs)."""
        normalized = _normalize_file_url(path)
        self.inputFile = normalized

        # Auto-set output dir to same directory as input if not set
        if not self._output_dir:
            self.outputDir = str(Path(normalized).parent)

    @Slot(str)
    def setOutputDir(self, path: str) -> None:
        """Set output directory from QML (handles file:// URLs)."""
        self.outputDir = _normalize_file_url(path)

    @Slot(int, int, str)
    def startPreprocess(self, tile_size: int, quality: int, method: str = "level1") -> None:
        """Start preprocessing with given settings.

        Args:
            tile_size: Tile size in pixels (256, 512, or 1024)
            quality: JPEG quality (70-100)
            method: Extraction method - "level1" (extract level 1 directly)
                    or "level0_resized" (extract level 0 and resize to ~20x)
        """
        if self._is_processing:
            return

        if not self._input_file:
            self.errorOccurred.emit("No input file selected")
            return

        if not self._output_dir:
            self.errorOccurred.emit("No output directory selected")
            return

        # Validate input file exists
        input_path = Path(self._input_file)
        if not input_path.exists():
            self.errorOccurred.emit(f"Input file not found: {self._input_file}")
            return

        self._is_processing = True
        self.isProcessingChanged.emit()
        self._progress = 0.0
        self.progressChanged.emit()
        self._status = "Starting..."
        self.statusChanged.emit()
        self._result_path = ""
        self.resultPathChanged.emit()

        # Create and start worker
        self._worker = PreprocessWorker(
            self._input_file,
            self._output_dir,
            tile_size,
            quality,
            method,
            self._force,
            self,
        )
        self._worker.progressChanged.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.errorOccurred.connect(self._on_error)
        self._worker.start()

    @Slot()
    def cancelPreprocess(self) -> None:
        """Cancel ongoing preprocessing."""
        if self._worker:
            self._worker.cancel()
            self._status = "Cancelling..."
            self.statusChanged.emit()
        if self._batch_worker:
            self._batch_worker.cancel()
            self._status = "Cancelling..."
            self.statusChanged.emit()

    @Slot(str)
    def setInputFolder(self, path: str) -> None:
        """Set input folder for batch mode (handles file:// URLs)."""
        normalized = _normalize_file_url(path)
        self.inputFolder = normalized

        # Auto-set output dir to same directory if not set
        if not self._output_dir:
            self.outputDir = normalized

        # Scan for WSI files
        self._scan_input_folder()

    def _scan_input_folder(self) -> None:
        """Scan input folder for WSI files and populate file list model."""
        if not self._input_folder:
            self._file_list_model.clear()
            return

        folder = Path(self._input_folder)
        if not folder.exists() or not folder.is_dir():
            self._file_list_model.clear()
            return

        # Common WSI extensions
        wsi_extensions = {".svs", ".ndpi", ".tif", ".tiff", ".mrxs", ".vms", ".vmu", ".scn"}

        files = []
        for ext in wsi_extensions:
            files.extend(folder.glob(f"*{ext}"))
            files.extend(folder.glob(f"*{ext.upper()}"))

        # Sort by name and remove duplicates
        unique_files = sorted(set(str(f) for f in files))
        self._file_list_model.setFiles(unique_files)

    @Slot(bool)
    def setForce(self, value: bool) -> None:
        """Set force rebuild flag."""
        self.force = value

    @Slot(int)
    def setParallelWorkers(self, value: int) -> None:
        """Set number of parallel workers (1-8)."""
        self.parallelWorkers = value

    @Slot(int, int, str)
    def startBatchPreprocess(self, tile_size: int, quality: int, method: str = "level1") -> None:
        """Start batch preprocessing of all files in folder.

        Args:
            tile_size: Tile size in pixels (256, 512, or 1024)
            quality: JPEG quality (70-100)
            method: Extraction method
        """
        if self._is_processing:
            return

        files = self._file_list_model.getFiles()
        if not files:
            self.errorOccurred.emit("No WSI files found in folder")
            return

        if not self._output_dir:
            self.errorOccurred.emit("No output directory selected")
            return

        # Reset batch state
        self._is_processing = True
        self.isProcessingChanged.emit()
        self._overall_progress = 0.0
        self.overallProgressChanged.emit()
        self._processed_count = 0
        self.processedCountChanged.emit()
        self._skipped_count = 0
        self.skippedCountChanged.emit()
        self._error_count = 0
        self.errorCountChanged.emit()
        self._batch_complete = False
        self.batchCompleteChanged.emit()
        self._first_result_path = ""
        self.firstResultPathChanged.emit()
        self._error_details = []
        self._status = "Starting batch..."
        self.statusChanged.emit()

        # Create and start batch worker
        self._batch_worker = BatchPreprocessWorker(
            files,
            self._output_dir,
            tile_size,
            quality,
            method,
            self._force,
            self._parallel_workers,
            self,
        )
        self._batch_worker.fileStatusChanged.connect(self._on_batch_file_status)
        self._batch_worker.fileProgress.connect(self._on_batch_file_progress)
        self._batch_worker.overallProgress.connect(self._on_batch_overall_progress)
        self._batch_worker.allFinished.connect(self._on_batch_finished)
        self._batch_worker.start()

    def _on_batch_file_status(self, index: int, status: str) -> None:
        """Handle file status update from batch worker."""
        self._file_list_model.setStatus(index, status)
        # Track first successful result for "Open in Viewer"
        if status == "done" and not self._first_result_path:
            file_path = self._file_list_model.getFilePath(index)
            if file_path:
                pyramid_name = Path(file_path).stem + ".fastpath"
                self._first_result_path = str(Path(self._output_dir) / pyramid_name)
                self.firstResultPathChanged.emit()

    def _on_batch_file_progress(self, index: int, progress: float) -> None:
        """Handle file progress update from batch worker."""
        self._file_list_model.setProgress(index, progress)

    def _on_batch_overall_progress(self, progress: float) -> None:
        """Handle overall progress update from batch worker."""
        self._overall_progress = progress
        self.overallProgressChanged.emit()
        # Update status with count
        total = len(self._file_list_model.getFiles())
        completed = int(progress * total)
        self._status = f"Processing {completed} of {total} files..."
        self.statusChanged.emit()

    def _on_batch_finished(
        self, processed: int, skipped: int, errors: int, error_details: list
    ) -> None:
        """Handle batch preprocessing completion."""
        self._is_processing = False
        self.isProcessingChanged.emit()
        self._processed_count = processed
        self.processedCountChanged.emit()
        self._skipped_count = skipped
        self.skippedCountChanged.emit()
        self._error_count = errors
        self.errorCountChanged.emit()
        self._error_details = error_details
        self._batch_complete = True
        self.batchCompleteChanged.emit()
        self._status = "Batch complete!"
        self.statusChanged.emit()
        self._batch_worker = None

    @Slot()
    def resetBatch(self) -> None:
        """Reset batch state to start a new batch."""
        self._batch_complete = False
        self.batchCompleteChanged.emit()
        self._overall_progress = 0.0
        self.overallProgressChanged.emit()
        self._processed_count = 0
        self.processedCountChanged.emit()
        self._skipped_count = 0
        self.skippedCountChanged.emit()
        self._error_count = 0
        self.errorCountChanged.emit()
        self._first_result_path = ""
        self.firstResultPathChanged.emit()
        self._file_list_model.clear()
        self._input_folder = ""
        self.inputFolderChanged.emit()
        self._status = "Ready"
        self.statusChanged.emit()

    def _on_progress(self, progress: float, status: str) -> None:
        """Handle progress updates from worker."""
        self._progress = progress
        self._status = status
        self.progressChanged.emit()
        self.statusChanged.emit()

    def _on_finished(self, result_path: str) -> None:
        """Handle preprocessing completion."""
        self._is_processing = False
        self.isProcessingChanged.emit()
        self._result_path = result_path
        self.resultPathChanged.emit()
        self._status = "Complete!" if result_path else "Skipped (already exists)"
        self.statusChanged.emit()
        self.preprocessingFinished.emit(result_path)
        self._worker = None

    def _on_error(self, error: str) -> None:
        """Handle preprocessing errors."""
        self._is_processing = False
        self.isProcessingChanged.emit()
        self._status = f"Error: {error}"
        self.statusChanged.emit()
        self.errorOccurred.emit(error)
        self._worker = None


class AppController(QObject):
    """Main application controller exposed to QML."""

    slidePathChanged = Signal()
    scaleChanged = Signal()
    viewportChanged = Signal()
    errorOccurred = Signal(str)  # Error message signal for QML

    def __init__(
        self,
        slide_manager: SlideManager,
        annotation_manager: AnnotationManager,
        plugin_manager: AIPluginManager,
        rust_scheduler: RustTileScheduler,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._slide_manager = slide_manager
        self._annotation_manager = annotation_manager
        self._plugin_manager = plugin_manager
        self._rust_scheduler = rust_scheduler
        self._tile_model = TileModel(self)
        self._fallback_tile_model = TileModel(self)
        self._recent_files = RecentFilesModel(self)
        self._previous_level = -1
        self._current_path = ""
        self._scale = 1.0
        self._viewport_x = 0.0
        self._viewport_y = 0.0
        self._viewport_width = 0.0
        self._viewport_height = 0.0
        # Velocity tracking for prefetching
        self._velocity_x = 0.0
        self._velocity_y = 0.0
        # Race condition protection for slide loading
        self._loading = False
        self._loading_lock = threading.Lock()
        # Initial render flag - skip cache filtering on first render after load
        self._needs_initial_render = False
        # Multi-slide navigation
        self._navigator = SlideNavigator(self)

        # Connect signals
        self._slide_manager.slideLoaded.connect(self._on_slide_loaded)
        self._slide_manager.slideClosed.connect(self._on_slide_closed)

    @Property(QObject, constant=True)
    def slideManager(self) -> SlideManager:
        """Access to the slide manager."""
        return self._slide_manager

    @Property(QObject, constant=True)
    def annotationManager(self) -> AnnotationManager:
        """Access to the annotation manager."""
        return self._annotation_manager

    @Property(QObject, constant=True)
    def pluginManager(self) -> AIPluginManager:
        """Access to the AI plugin manager."""
        return self._plugin_manager

    @Property(QObject, constant=True)
    def tileModel(self) -> TileModel:
        """Model for visible tiles."""
        return self._tile_model

    @Property(QObject, constant=True)
    def fallbackTileModel(self) -> TileModel:
        """Model for fallback tiles (shown during zoom transitions)."""
        return self._fallback_tile_model

    @Property(QObject, constant=True)
    def recentFiles(self) -> RecentFilesModel:
        """Model for recent files."""
        return self._recent_files

    @Property(QObject, constant=True)
    def navigator(self) -> SlideNavigator:
        """Multi-slide navigator."""
        return self._navigator

    @Property(str, notify=slidePathChanged)
    def currentPath(self) -> str:
        """Current slide path."""
        return self._current_path

    @Property(float, notify=scaleChanged)
    def scale(self) -> float:
        """Current view scale."""
        return self._scale

    @scale.setter
    def scale(self, value: float) -> None:
        if self._scale != value:
            self._scale = value
            self.scaleChanged.emit()
            self._update_tiles()

    @Slot(str, result=bool)
    def openSlide(self, path: str) -> bool:
        """Open a slide from path.

        Includes race condition protection and comprehensive error handling.
        """
        # Race condition protection - prevent concurrent loads
        with self._loading_lock:
            if self._loading:
                logger.warning("Slide load already in progress, ignoring request")
                return False
            self._loading = True

        try:
            # Handle file:// URLs and normalize path
            path = _normalize_file_url(path)
            resolved = Path(path).resolve()

            if not resolved.exists():
                logger.error("Slide not found: %s", resolved)
                self.errorOccurred.emit(f"File not found: {resolved}")
                return False

            # Load with Rust scheduler FIRST (for tile loading)
            # This must happen before SlideManager.load() which emits slideLoaded signal
            self._rust_scheduler.load(str(resolved))

            # Pre-warm cache with low-resolution tiles for any initial zoom
            # This must complete BEFORE QML starts requesting tiles
            self._rust_scheduler.prefetch_low_res_levels()

            # Load with SlideManager (for metadata access in QML)
            # This emits slideLoaded signal which triggers QML to request tiles
            if not self._slide_manager.load(str(resolved)):
                self._rust_scheduler.close()
                self.errorOccurred.emit("Failed to load slide metadata")
                return False

            logger.info("Slide loaded: %s", resolved)

            self._current_path = str(resolved)
            self.slidePathChanged.emit()
            self._recent_files.addFile(str(resolved), resolved.name)
            self._navigator.scanDirectory(str(resolved))
            return True

        except Exception as e:
            logger.exception("Error opening slide: %s", path)
            self.errorOccurred.emit(str(e))
            return False
        finally:
            self._loading = False

    @Slot()
    def closeSlide(self) -> None:
        """Close the current slide."""
        self._slide_manager.close()
        self._rust_scheduler.close()
        self._current_path = ""
        self.slidePathChanged.emit()
        self._tile_model.clear()
        self._fallback_tile_model.clear()
        self._previous_level = -1

    @Slot(result=bool)
    def openNextSlide(self) -> bool:
        """Open the next slide in the directory."""
        path = self._navigator.nextSlide()
        return self.openSlide(path) if path else False

    @Slot(result=bool)
    def openPreviousSlide(self) -> bool:
        """Open the previous slide in the directory."""
        path = self._navigator.previousSlide()
        return self.openSlide(path) if path else False

    @Slot(float, float, float, float, float)
    def updateViewport(
        self, x: float, y: float, width: float, height: float, scale: float
    ) -> None:
        """Update the viewport and refresh visible tiles (without velocity)."""
        self.updateViewportWithVelocity(x, y, width, height, scale, 0.0, 0.0)

    @Slot(float, float, float, float, float, float, float)
    def updateViewportWithVelocity(
        self,
        x: float,
        y: float,
        width: float,
        height: float,
        scale: float,
        velocity_x: float,
        velocity_y: float,
    ) -> None:
        """Update the viewport with velocity for prefetching.

        Args:
            x: Viewport left in slide coordinates
            y: Viewport top in slide coordinates
            width: Viewport width in slide coordinates
            height: Viewport height in slide coordinates
            scale: Current view scale
            velocity_x: Horizontal pan velocity (pixels/second)
            velocity_y: Vertical pan velocity (pixels/second)
        """
        self._viewport_x = x
        self._viewport_y = y
        self._viewport_width = width
        self._viewport_height = height
        self._scale = scale
        self._velocity_x = velocity_x
        self._velocity_y = velocity_y

        # Notify Rust scheduler for prefetching
        if self._rust_scheduler.is_loaded:
            self._rust_scheduler.update_viewport(
                x, y, width, height, scale, velocity_x, velocity_y
            )

        self._update_tiles()
        self.viewportChanged.emit()

    def _update_tiles(self) -> None:
        """Update the tile model with visible tiles."""
        if not self._slide_manager.isLoaded:
            self._tile_model.clear()
            self._fallback_tile_model.clear()
            return

        # Get visible tile coordinates
        tile_coords = self._slide_manager.getVisibleTiles(
            self._viewport_x,
            self._viewport_y,
            self._viewport_width,
            self._viewport_height,
            self._scale,
        )
        logger.info(
            "_update_tiles: scale=%.4f level=%d viewport=(%.0f,%.0f,%.0f,%.0f) tiles=%d",
            self._scale,
            self._slide_manager.getLevelForScale(self._scale),
            self._viewport_x, self._viewport_y,
            self._viewport_width, self._viewport_height,
            len(tile_coords)
        )

        # On first render, show all visible tiles (don't filter to cached-only)
        # Only consume the flag if we actually have tiles to render
        if self._needs_initial_render:
            if tile_coords:
                cached_coords = tile_coords  # Don't filter - let provider load them
                self._needs_initial_render = False
            else:
                # Viewport not ready yet, keep flag for next update
                cached_coords = []
        elif self._rust_scheduler.is_loaded:
            # Filter to only show tiles that are already cached
            # This prevents flickering - fallback layer shows previous tiles for uncached regions
            tile_tuples = [tuple(coord) for coord in tile_coords]
            cached_coords = self._rust_scheduler.filter_cached_tiles(tile_tuples)

            # If most tiles are uncached, show all and let provider load them
            # This avoids prolonged gray screen at low zoom levels
            if tile_coords and len(cached_coords) < len(tile_coords) * CACHE_MISS_THRESHOLD:
                cached_coords = tile_coords
        else:
            cached_coords = tile_coords

        # Build tile data for cached tiles only
        tiles = []
        for coord in cached_coords:
            level, col, row = coord
            pos = self._slide_manager.getTilePosition(level, col, row)
            source = f"image://tiles/{level}/{col}_{row}"
            tiles.append({
                "level": level,
                "col": col,
                "row": row,
                "x": pos[0],
                "y": pos[1],
                "width": pos[2],
                "height": pos[3],
                "source": source,
            })

        # Only update fallback on level change (not during panning)
        current_level = self._slide_manager.getLevelForScale(self._scale)
        if current_level != self._previous_level:
            if self._tile_model.hasTiles():
                self._fallback_tile_model.batchUpdate(self._tile_model.getTiles())
            self._previous_level = current_level

        # Use batch update for main model (single signal instead of per-tile)
        self._tile_model.batchUpdate(tiles)

    def _on_slide_loaded(self) -> None:
        """Handle slide loaded signal."""
        # Reset viewport to show whole slide
        self._scale = 0.1
        self._viewport_x = 0
        self._viewport_y = 0
        self._needs_initial_render = True
        logger.info(
            "Slide loaded - initial scale=%.4f, level=%d",
            self._scale,
            self._slide_manager.getLevelForScale(self._scale)
        )
        self.scaleChanged.emit()

    def _on_slide_closed(self) -> None:
        """Handle slide closed signal."""
        self._tile_model.clear()
        self._fallback_tile_model.clear()
        self._previous_level = -1


def run_app(args: list[str] | None = None) -> int:
    """Run the FastPATH viewer application.

    Args:
        args: Command line arguments (defaults to sys.argv)

    Returns:
        Exit code
    """
    if args is None:
        args = sys.argv

    # Use Fusion style for consistent cross-platform appearance and full customization support
    QQuickStyle.setStyle("Fusion")

    app = QGuiApplication(args)
    app.setApplicationName("FastPATH")
    app.setOrganizationName("FastPATH")
    app.setOrganizationDomain("fastpath.local")

    # Create managers
    slide_manager = SlideManager()
    annotation_manager = AnnotationManager()
    plugin_manager = AIPluginManager()

    # Create Rust scheduler with configured cache and prefetch settings
    rust_scheduler = RustTileScheduler(
        cache_size_mb=TILE_CACHE_SIZE_MB, prefetch_distance=PREFETCH_DISTANCE
    )
    logger.info("Rust tile scheduler initialized")

    # Discover AI plugins
    plugin_manager.discoverPlugins()

    controller = AppController(
        slide_manager, annotation_manager, plugin_manager, rust_scheduler
    )
    preprocess_controller = PreprocessController()
    settings = Settings()

    # Apply saved settings to preprocess controller
    if settings.defaultOutputDir:
        preprocess_controller.outputDir = settings.defaultOutputDir

    # Create QML engine
    engine = QQmlApplicationEngine()

    # Register image providers
    engine.addImageProvider("tiles", TileImageProvider(rust_scheduler))
    engine.addImageProvider("thumbnail", ThumbnailProvider(slide_manager))

    # Expose objects to QML
    engine.rootContext().setContextProperty("App", controller)
    engine.rootContext().setContextProperty("Preprocess", preprocess_controller)
    engine.rootContext().setContextProperty("Settings", settings)
    engine.rootContext().setContextProperty("SlideManager", slide_manager)
    engine.rootContext().setContextProperty("AnnotationManager", annotation_manager)
    engine.rootContext().setContextProperty("PluginManager", plugin_manager)
    engine.rootContext().setContextProperty("Navigator", controller.navigator)

    # Load QML
    qml_dir = Path(__file__).parent / "qml"
    engine.load(QUrl.fromLocalFile(str(qml_dir / "main.qml")))

    if not engine.rootObjects():
        return -1

    # Handle command line slide path
    if len(args) > 1:
        slide_path = args[1]
        controller.openSlide(slide_path)

    return app.exec()
