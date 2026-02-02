"""QML controller and workers for preprocessing mode."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Property, QThread, Slot

from fastpath.config import WSI_EXTENSIONS
from fastpath.ui.models import (
    FileListModel,
    STATUS_PENDING,
    STATUS_PROCESSING,
    STATUS_DONE,
    STATUS_SKIPPED,
    STATUS_ERROR,
)

logger = logging.getLogger(__name__)


def _normalize_file_url(path: str) -> str:
    """Convert file:// URL to local filesystem path.

    Handles both file:/// (Windows) and file:// (Unix) prefixes.
    """
    if path.startswith("file:///"):
        return path[8:]
    elif path.startswith("file://"):
        return path[7:]
    return path


def _map_stage_to_progress(stage: str, current: int, total: int) -> float:
    """Map preprocessing stage name to a progress value (0.0-1.0)."""
    if stage == "thumbnail":
        return 0.1
    elif stage == "dzsave":
        return 0.8
    elif stage.startswith("level_"):
        return 0.8 + 0.15 * (current / max(total, 1))
    return 0.5


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
        force: bool = False,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.input_path = Path(input_path)
        self.output_dir = Path(output_dir)
        self.tile_size = tile_size
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
            builder = VipsPyramidBuilder(tile_size=self.tile_size)

            def progress_callback(stage: str, current: int, total: int) -> None:
                if self._cancelled:
                    raise InterruptedError("Preprocessing cancelled")
                progress = _map_stage_to_progress(stage, current, total)
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
        force: bool = False,
        parallel_workers: int = 3,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._files = files
        self._output_dir = Path(output_dir)
        self._tile_size = tile_size
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
        from fastpath.preprocess.metadata import check_pyramid_status, PyramidStatus
        from fastpath.preprocess.pyramid import VipsPyramidBuilder

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
                return (index, STATUS_PENDING, None)

            self.fileStatusChanged.emit(index, STATUS_PROCESSING)
            self.fileProgress.emit(index, 0.0)

            try:
                slide_path = Path(file_path)

                # Check if already exists
                pyramid_name = slide_path.stem + ".fastpath"
                pyramid_dir = self._output_dir / pyramid_name
                status = check_pyramid_status(pyramid_dir)

                if status == PyramidStatus.COMPLETE and not self._force:
                    self.fileProgress.emit(index, 1.0)
                    return (index, STATUS_SKIPPED, None)

                # Build pyramid
                builder = VipsPyramidBuilder(tile_size=self._tile_size)

                def progress_cb(stage: str, current: int, total: int) -> None:
                    if self._cancelled:
                        raise InterruptedError("Cancelled")
                    self.fileProgress.emit(index, _map_stage_to_progress(stage, current, total))

                result = builder.build(
                    slide_path,
                    self._output_dir,
                    progress_callback=progress_cb,
                    force=self._force,
                )

                self.fileProgress.emit(index, 1.0)

                if result is None:
                    return (index, STATUS_SKIPPED, None)
                return (index, STATUS_DONE, None)

            except InterruptedError:
                return (index, STATUS_PENDING, "Cancelled")
            except Exception as e:
                logger.exception("Error processing %s", file_path)
                return (index, STATUS_ERROR, str(e))

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

                if status == STATUS_DONE:
                    processed += 1
                elif status == STATUS_SKIPPED:
                    skipped += 1
                elif status == STATUS_ERROR:
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

    def _set_processing_active(self, status: str) -> None:
        """Set processing state to active with the given status message."""
        self._is_processing = True
        self.isProcessingChanged.emit()
        self._status = status
        self.statusChanged.emit()

    def _reset_batch_state(self) -> None:
        """Reset batch counters and progress to initial values."""
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

    @Slot(int)
    def startPreprocess(self, tile_size: int) -> None:
        """Start preprocessing with given tile size. Always 0.5 MPP, JPEG Q80."""
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

        self._set_processing_active("Starting...")
        self._progress = 0.0
        self.progressChanged.emit()
        self._result_path = ""
        self.resultPathChanged.emit()

        # Create and start worker
        self._worker = PreprocessWorker(
            self._input_file,
            self._output_dir,
            tile_size,
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

        files = []
        for ext in WSI_EXTENSIONS:
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

    @Slot(int)
    def startBatchPreprocess(self, tile_size: int) -> None:
        """Start batch preprocessing of all files in folder. Always 0.5 MPP, JPEG Q80."""
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
        self._reset_batch_state()
        self._set_processing_active("Starting batch...")

        # Create and start batch worker
        self._batch_worker = BatchPreprocessWorker(
            files,
            self._output_dir,
            tile_size,
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
        if status == STATUS_DONE and not self._first_result_path:
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
        self._reset_batch_state()
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
