"""QML controller and workers for preprocessing mode."""

from __future__ import annotations

import logging
import os
import tempfile
import threading
import time
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Property, QThread, Slot

from fastpath.core.paths import to_local_path
from fastpath.config import VIPS_CONCURRENCY, WSI_EXTENSIONS
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
    """Convert a QML ``file://`` URL or plain path to a local path string."""
    return str(to_local_path(path))


def _map_stage_to_progress(stage: str, current: int, total: int) -> float:
    """Map preprocessing stage name to a progress value (0.0-1.0).

    Thumbnail extraction and load/resize are near-instant (embedded image
    or shrink-on-load), so they get a tiny slice. dzsave_progress covers
    94% of the bar since tile generation dominates wall-clock time.
    """
    if stage == "thumbnail":
        return 0.01
    elif stage == "load":
        return 0.02
    elif stage == "resize":
        return 0.03
    elif stage == "dzsave":
        return 0.04
    elif stage == "dzsave_progress":
        # Map 0-100% dzsave progress to 0.04-0.98 overall range
        return 0.04 + 0.94 * (current / max(total, 1))
    elif stage.startswith("level_"):
        return 0.98 + 0.02 * (current / max(total, 1))
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

            builder = VipsPyramidBuilder(tile_size=self.tile_size)

            _stage_labels = {
                "load": "Loading slide...",
                "resize": "Resizing to target resolution...",
                "thumbnail": "Generating thumbnail...",
                "dzsave": "Starting tile generation...",
            }

            def progress_callback(stage: str, current: int, total: int) -> None:
                if self._cancelled:
                    raise InterruptedError("Preprocessing cancelled")
                progress = _map_stage_to_progress(stage, current, total)
                if stage == "dzsave_progress":
                    status = f"Generating tiles: {current}%"
                else:
                    status = _stage_labels.get(stage, f"{stage}: {current}/{total}")
                self.progressChanged.emit(progress, status)

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


_vips_concurrency_declared = False


def _ensure_vips_concurrency_cffi() -> None:
    """Declare vips_concurrency_get/set in pyvips cffi if not already present."""
    global _vips_concurrency_declared
    if _vips_concurrency_declared:
        return
    import pyvips
    pyvips.ffi.cdef("int vips_concurrency_get(void);")
    pyvips.ffi.cdef("void vips_concurrency_set(int concurrency);")
    _vips_concurrency_declared = True


def _set_vips_concurrency(n: int) -> None:
    """Set VIPS concurrency at runtime via cffi."""
    import pyvips
    _ensure_vips_concurrency_cffi()
    pyvips.vips_lib.vips_concurrency_set(n)


def _get_vips_concurrency() -> int:
    """Get current VIPS concurrency via cffi."""
    import pyvips
    _ensure_vips_concurrency_cffi()
    return pyvips.vips_lib.vips_concurrency_get()


class BenchmarkWorker(QThread):
    """Background worker that benchmarks VIPS dzsave with different thread counts."""

    progressChanged = Signal(float, str)  # progress (0-1), status message
    finished = Signal(str, int, float)  # results text, best thread count, best time
    errorOccurred = Signal(str)  # error message

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cancelled = False

    def cancel(self) -> None:
        """Request cancellation of the benchmark."""
        self._cancelled = True

    # Number of repetitions per thread count (take median)
    REPEATS = 3

    def run(self) -> None:
        """Run the benchmark across candidate thread counts."""
        try:
            import statistics

            import numpy as np
            import pyvips

            cpu_count = os.cpu_count() or 4

            # Dense candidate list: 1-8 individually, then powers/multiples
            # of cpu_count to cover the full range
            raw = set(range(1, min(cpu_count, 8) + 1))
            for mult in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0):
                v = int(cpu_count * mult)
                if v >= 1:
                    raw.add(v)
            # Also add some specific powers of 2 up to 2*cpu_count
            for p in (8, 12, 16, 24, 32, 48, 64):
                if p <= cpu_count * 2:
                    raw.add(p)
            candidates = sorted(raw)

            original_concurrency = _get_vips_concurrency()
            total_steps = len(candidates) * self.REPEATS
            results: list[tuple[int, float]] = []  # (threads, median_time)

            # Generate a synthetic test image — 16384x12288 (roughly 200 MP)
            # random noise to defeat any compression shortcuts
            self.progressChanged.emit(0.0, "Generating test image...")
            rng = np.random.default_rng(42)
            width, height = 16384, 12288
            data = rng.integers(0, 256, (height, width, 3), dtype=np.uint8)
            test_image = pyvips.Image.new_from_memory(
                data.tobytes(), width, height, 3, "uchar"
            )

            step = 0
            for i, n_threads in enumerate(candidates):
                if self._cancelled:
                    break

                timings: list[float] = []
                for rep in range(self.REPEATS):
                    if self._cancelled:
                        break

                    step += 1
                    self.progressChanged.emit(
                        step / total_steps,
                        f"Testing {n_threads} threads (run {rep + 1}/{self.REPEATS},"
                        f" candidate {i + 1}/{len(candidates)})...",
                    )

                    # Flush VIPS operation cache for fair measurement
                    old_max = pyvips.cache_get_max()
                    pyvips.cache_set_max(0)
                    pyvips.cache_set_max(old_max)

                    _set_vips_concurrency(n_threads)

                    with tempfile.TemporaryDirectory() as tmp_dir:
                        out_path = str(Path(tmp_dir) / "bench")
                        t0 = time.perf_counter()
                        test_image.dzsave(
                            out_path,
                            tile_size=512,
                            overlap=0,
                            suffix=".jpg[Q=80]",
                            depth="one",
                        )
                        elapsed = time.perf_counter() - t0

                    timings.append(elapsed)
                    logger.info(
                        "Benchmark: %d threads, run %d -> %.2fs",
                        n_threads, rep + 1, elapsed,
                    )

                if timings:
                    median = statistics.median(timings)
                    results.append((n_threads, median))

            # Restore original concurrency
            _set_vips_concurrency(original_concurrency)

            if self._cancelled:
                self.errorOccurred.emit("Benchmark cancelled")
                return

            # Format results table
            best_threads, best_time = min(results, key=lambda r: r[1])
            lines = [f"Threads   Median ({self.REPEATS} runs)"]
            lines.append("─────────────────────")
            for n_threads, median in results:
                marker = " *" if n_threads == best_threads else ""
                lines.append(f"  {n_threads:>4d}    {median:>6.2f}s{marker}")
            lines.append("")
            lines.append(f"Best: {best_threads} threads ({best_time:.2f}s)")
            result_text = "\n".join(lines)

            self.progressChanged.emit(1.0, "Benchmark complete!")
            self.finished.emit(result_text, best_threads, best_time)

        except Exception as e:
            logger.exception("Benchmark failed")
            self.errorOccurred.emit(str(e))


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

    # Benchmark signals
    benchmarkRunningChanged = Signal()
    benchmarkProgressChanged = Signal()
    benchmarkStatusChanged = Signal()
    benchmarkResultChanged = Signal()
    benchmarkBestThreadsChanged = Signal()

    def __init__(self, settings: object | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._settings = settings

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

        # Benchmark state
        self._benchmark_running = False
        self._benchmark_progress = 0.0
        self._benchmark_status = ""
        self._benchmark_result = ""
        self._benchmark_best_threads = 0
        self._benchmark_worker: BenchmarkWorker | None = None

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

    # Benchmark properties
    @Property(bool, notify=benchmarkRunningChanged)
    def benchmarkRunning(self) -> bool:
        return self._benchmark_running

    @Property(float, notify=benchmarkProgressChanged)
    def benchmarkProgress(self) -> float:
        return self._benchmark_progress

    @Property(str, notify=benchmarkStatusChanged)
    def benchmarkStatus(self) -> str:
        return self._benchmark_status

    @Property(str, notify=benchmarkResultChanged)
    def benchmarkResult(self) -> str:
        return self._benchmark_result

    @Property(int, notify=benchmarkBestThreadsChanged)
    def benchmarkBestThreads(self) -> int:
        return self._benchmark_best_threads

    @Property(int, constant=False, notify=benchmarkBestThreadsChanged)
    def savedVipsConcurrency(self) -> int:
        """Return persisted VIPS concurrency (0 = use default)."""
        if self._settings is not None:
            return self._settings.vipsConcurrency
        return 0

    @Property(int, constant=True)
    def defaultVipsConcurrency(self) -> int:
        """Return the config default VIPS concurrency."""
        try:
            return int(VIPS_CONCURRENCY)
        except (ValueError, TypeError):
            return 24

    @Slot()
    def startBenchmark(self) -> None:
        """Start the VIPS concurrency benchmark."""
        if self._benchmark_running or self._is_processing:
            return

        self._benchmark_running = True
        self.benchmarkRunningChanged.emit()
        self._benchmark_progress = 0.0
        self.benchmarkProgressChanged.emit()
        self._benchmark_status = "Starting benchmark..."
        self.benchmarkStatusChanged.emit()
        self._benchmark_result = ""
        self.benchmarkResultChanged.emit()
        self._benchmark_best_threads = 0
        self.benchmarkBestThreadsChanged.emit()

        self._benchmark_worker = BenchmarkWorker(self)
        self._benchmark_worker.progressChanged.connect(self._on_benchmark_progress)
        self._benchmark_worker.finished.connect(self._on_benchmark_finished)
        self._benchmark_worker.errorOccurred.connect(self._on_benchmark_error)
        self._benchmark_worker.start()

    @Slot()
    def cancelBenchmark(self) -> None:
        """Cancel the running benchmark."""
        if self._benchmark_worker:
            self._benchmark_worker.cancel()
            self._benchmark_status = "Cancelling..."
            self.benchmarkStatusChanged.emit()

    @Slot()
    def applyBenchmarkResult(self) -> None:
        """Apply the benchmark result to settings."""
        if self._settings is not None and self._benchmark_best_threads > 0:
            self._settings.vipsConcurrency = self._benchmark_best_threads
            self.benchmarkBestThreadsChanged.emit()

    @Slot()
    def clearBenchmarkResult(self) -> None:
        """Dismiss/clear the benchmark result."""
        self._benchmark_result = ""
        self.benchmarkResultChanged.emit()
        self._benchmark_best_threads = 0
        self.benchmarkBestThreadsChanged.emit()
        self._benchmark_status = ""
        self.benchmarkStatusChanged.emit()
        self._benchmark_progress = 0.0
        self.benchmarkProgressChanged.emit()

    def _on_benchmark_progress(self, progress: float, status: str) -> None:
        """Handle benchmark progress updates."""
        self._benchmark_progress = progress
        self.benchmarkProgressChanged.emit()
        self._benchmark_status = status
        self.benchmarkStatusChanged.emit()

    def _on_benchmark_finished(self, result_text: str, best_threads: int, best_time: float) -> None:
        """Handle benchmark completion."""
        self._benchmark_running = False
        self.benchmarkRunningChanged.emit()
        self._benchmark_result = result_text
        self.benchmarkResultChanged.emit()
        self._benchmark_best_threads = best_threads
        self.benchmarkBestThreadsChanged.emit()
        self._benchmark_status = f"Best: {best_threads} threads ({best_time:.2f}s)"
        self.benchmarkStatusChanged.emit()
        self._benchmark_worker = None

    def _on_benchmark_error(self, error: str) -> None:
        """Handle benchmark errors."""
        self._benchmark_running = False
        self.benchmarkRunningChanged.emit()
        self._benchmark_status = f"Error: {error}"
        self.benchmarkStatusChanged.emit()
        self._benchmark_worker = None

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

    def _apply_saved_concurrency(self) -> None:
        """Apply saved VIPS concurrency setting before starting preprocessing."""
        if self._settings is not None:
            saved = self._settings.vipsConcurrency
            if saved > 0:
                logger.info("Applying saved VIPS concurrency: %d threads", saved)
                _set_vips_concurrency(saved)

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

        self._apply_saved_concurrency()
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

        self._apply_saved_concurrency()

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
