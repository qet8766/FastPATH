"""QML application setup for FastPATH viewer."""

from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Slot, Signal, Property
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

from fastpath.config import L1_CACHE_SIZE_MB, L2_CACHE_SIZE_MB, PREFETCH_DISTANCE, CACHE_MISS_THRESHOLD
from fastpath.core.paths import to_local_path
from fastpath.core.slide import SlideManager
from fastpath.core.annotations import AnnotationManager
from fastpath.core.project import ProjectManager
from fastpath.plugins.controller import PluginController
from fastpath.ui.providers import TileImageProvider, ThumbnailProvider, AnnotationTileImageProvider
from fastpath.ui.models import TileModel, RecentFilesModel
from fastpath.ui.navigator import SlideNavigator
from fastpath.ui.settings import Settings
from fastpath.ui.preprocess import PreprocessController
from fastpath_core import RustTileScheduler, is_debug_build

logger = logging.getLogger(__name__)


class CacheStatsProvider(QObject):
    """Polls Rust cache stats and exposes them to QML."""

    statsUpdated = Signal()

    def __init__(self, scheduler: RustTileScheduler, parent: QObject | None = None):
        super().__init__(parent)
        self._scheduler = scheduler
        self._size_mb = 0.0
        self._hit_ratio = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._poll)

    @Slot()
    def _poll(self):
        stats = self._scheduler.cache_stats()
        size_mb = round(stats["size_bytes"] / (1024 * 1024), 1)
        total = stats.get("hits", 0) + stats.get("misses", 0)
        ratio = stats["hits"] / total if total > 0 else 0.0
        hit_ratio = round(stats.get("hit_ratio", ratio) * 100, 1)
        if size_mb != self._size_mb or hit_ratio != self._hit_ratio:
            self._size_mb = size_mb
            self._hit_ratio = hit_ratio
            self.statsUpdated.emit()

    @Property(float, notify=statsUpdated)
    def sizeMb(self) -> float:
        return self._size_mb

    @Property(float, notify=statsUpdated)
    def hitRatio(self) -> float:
        return self._hit_ratio

    @Slot()
    def start(self):
        self._timer.start()

    @Slot()
    def stop(self):
        self._timer.stop()


class AppController(QObject):
    """Main application controller exposed to QML."""

    slidePathChanged = Signal()
    scaleChanged = Signal()
    viewportChanged = Signal()
    errorOccurred = Signal(str)  # Error message signal for QML
    projectChanged = Signal()
    projectViewStateReady = Signal(float, float, float)  # x, y, scale

    def __init__(
        self,
        slide_manager: SlideManager,
        annotation_manager: AnnotationManager,
        project_manager: ProjectManager,
        plugin_manager: PluginController,
        rust_scheduler: RustTileScheduler,
        settings: Settings,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._slide_manager = slide_manager
        self._annotation_manager = annotation_manager
        self._project_manager = project_manager
        self._plugin_manager = plugin_manager
        self._rust_scheduler = rust_scheduler
        self._settings = settings
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
        # Generation counter for cache-busting QML image URLs on slide switch
        self._slide_generation = 0
        # Multi-slide navigation
        self._navigator = SlideNavigator(self)

        # Load persisted recent slides
        self._recent_files.setPaths(self._settings.get_recent_slide_paths())

        # Connect signals
        self._slide_manager.slideLoaded.connect(self._on_slide_loaded)
        self._slide_manager.slideClosed.connect(self._on_slide_closed)
        for sig in (
            self._project_manager.projectLoaded,
            self._project_manager.projectSaved,
            self._project_manager.projectClosed,
            self._project_manager.dirtyChanged,
        ):
            sig.connect(self.projectChanged.emit)

    @Property(QObject, constant=True)
    def slideManager(self) -> SlideManager:
        """Access to the slide manager."""
        return self._slide_manager

    @Property(QObject, constant=True)
    def annotationManager(self) -> AnnotationManager:
        """Access to the annotation manager."""
        return self._annotation_manager

    @Property(QObject, constant=True)
    def pluginManager(self) -> PluginController:
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

    @Property(bool, notify=projectChanged)
    def projectLoaded(self) -> bool:
        return self._project_manager.isLoaded

    @Property(bool, notify=projectChanged)
    def projectDirty(self) -> bool:
        return self._project_manager.isDirty

    @Property(str, notify=projectChanged)
    def projectPath(self) -> str:
        return self._project_manager.projectPath

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
            resolved = to_local_path(path).expanduser().resolve()

            if not resolved.exists():
                logger.error("Slide not found: %s", resolved)
                self.errorOccurred.emit(f"File not found: {resolved}")
                return False

            # Clear all visual state from previous slide BEFORE loading new one.
            # This prevents stale tiles from flashing during the transition:
            # - tile model: QML main layer still referencing old source URLs
            # - fallback model: QML fallback layer (z:0) showing old slide's tiles
            # - previous_level: stale value causes _update_fallback_on_level_change
            #   to skip the update or copy wrong tiles on first render
            self._tile_model.clear()
            self._fallback_tile_model.clear()
            self._previous_level = -1

            # Bump generation so tile URLs change, forcing QML to re-request images
            self._slide_generation += 1

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

            self._plugin_manager.set_slide(str(resolved))
            self._current_path = str(resolved)
            self.slidePathChanged.emit()
            self._recent_files.addFile(str(resolved), resolved.name)
            self._settings.set_recent_slide_paths(self._recent_files.getPaths())
            self._settings.lastSlideDirUrl = QUrl.fromLocalFile(
                str(resolved.parent)
            ).toString()
            self._navigator.scanDirectory(str(resolved))
            self._start_bulk_preload()
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
        self._rust_scheduler.cancel_bulk_preload()
        self._rust_scheduler.close()
        self._plugin_manager.clear_slide()
        self._current_path = ""
        self.slidePathChanged.emit()
        self._tile_model.clear()
        self._fallback_tile_model.clear()
        self._previous_level = -1

    @Slot()
    def clearRecentSlides(self) -> None:
        """Clear the persisted recent slide list."""
        self._recent_files.clear()
        self._settings.set_recent_slide_paths([])

    @Slot(str, result=bool)
    def openProject(self, path: str) -> bool:
        """Open a project file (.fpproj) and restore slide/view/annotations."""
        if not path.strip():
            return False

        project_path = to_local_path(path).expanduser()
        if not project_path.exists():
            self.errorOccurred.emit(f"Project file not found: {project_path}")
            return False

        if not self._project_manager.loadProject(str(project_path)):
            self.errorOccurred.emit(f"Failed to load project: {project_path}")
            return False

        slide_path_str = self._project_manager.slidePath
        if not slide_path_str:
            self.errorOccurred.emit("Project is missing a slide path")
            return False

        slide_path = to_local_path(slide_path_str).expanduser()
        if not slide_path.exists():
            self.errorOccurred.emit(f"Slide not found: {slide_path}")
            return False

        if not self.openSlide(str(slide_path)):
            return False

        # Restore annotations
        self._annotation_manager.reset()
        annotations_path = self._project_manager.annotationsFile
        if annotations_path:
            self._annotation_manager.load(annotations_path)

        # Restore view state (QML applies it to SlideViewer)
        view_state = self._project_manager.getViewState()
        if view_state:
            try:
                x = float(view_state.get("x", 0.0))
                y = float(view_state.get("y", 0.0))
                scale = float(view_state.get("scale", 0.1))
                self.projectViewStateReady.emit(x, y, scale)
            except (TypeError, ValueError):
                pass

        return True

    @Slot(result=bool)
    def saveProject(self) -> bool:
        """Save the current project to its existing path."""
        if not self._project_manager.isLoaded or not self._project_manager.projectPath:
            return False

        return self._save_project(Path(self._project_manager.projectPath))

    @Slot(str, result=bool)
    def saveProjectAs(self, path: str) -> bool:
        """Save the current project to a new path (Save As...)."""
        if not path.strip():
            return False

        project_path = to_local_path(path).expanduser()
        return self._save_project(project_path)

    def _save_project(self, project_path: Path) -> bool:
        """Persist project + annotations."""
        if not self._slide_manager.isLoaded or not self._current_path:
            self.errorOccurred.emit("No slide loaded")
            return False

        project_path.parent.mkdir(parents=True, exist_ok=True)

        if not self._project_manager.isLoaded:
            annotations_path = str(project_path.with_suffix(".geojson"))
            self._project_manager.newProject(self._current_path, annotations_path)
        else:
            annotations_path = self._project_manager.annotationsFile
            if not annotations_path:
                annotations_path = str(project_path.with_suffix(".geojson"))
                self._project_manager.setAnnotationsFile(annotations_path)

        # Capture current view state (viewport top-left in slide coords)
        self._project_manager.setSlidePath(self._current_path)
        self._project_manager.updateViewState(self._viewport_x, self._viewport_y, self._scale)

        try:
            self._annotation_manager.save(annotations_path)
        except Exception as e:
            self.errorOccurred.emit(f"Failed to save annotations: {e}")
            return False

        if not self._project_manager.saveProject(str(project_path)):
            self.errorOccurred.emit(f"Failed to save project: {project_path}")
            return False

        return True

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

    def _start_bulk_preload(self) -> None:
        """Start background preloading of nearby slides into L2 cache."""
        slides = self._navigator.get_slide_paths()
        idx = self._navigator.currentIndex
        if len(slides) <= 1:
            return

        # Priority order: current slide first, then alternating outward
        ordered: list[str] = [slides[idx]]
        for delta in range(1, len(slides)):
            if idx + delta < len(slides):
                ordered.append(slides[idx + delta])
            if idx - delta >= 0:
                ordered.append(slides[idx - delta])

        self._rust_scheduler.start_bulk_preload(ordered)

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
        logger.debug(
            "_update_tiles: scale=%.4f level=%d viewport=(%.0f,%.0f,%.0f,%.0f) tiles=%d",
            self._scale,
            self._slide_manager.getLevelForScale(self._scale),
            self._viewport_x, self._viewport_y,
            self._viewport_width, self._viewport_height,
            len(tile_coords)
        )

        cached_coords = self._filter_cached_tiles(tile_coords)
        tiles = self._build_tile_data(cached_coords)
        self._update_fallback_on_level_change()
        self._tile_model.batchUpdate(tiles)

    def _filter_cached_tiles(self, tile_coords: list) -> list:
        """Filter tile coordinates to only those already in cache.

        On initial render, returns all tiles unfiltered. Otherwise filters
        through the Rust scheduler's cache, falling back to all tiles when
        the cache miss ratio exceeds CACHE_MISS_THRESHOLD.
        """
        if self._needs_initial_render:
            if tile_coords:
                self._needs_initial_render = False
                return tile_coords
            return []

        if self._rust_scheduler.is_loaded:
            tile_tuples = [tuple(coord) for coord in tile_coords]
            cached_coords = self._rust_scheduler.filter_cached_tiles(tile_tuples)
            if tile_coords and len(cached_coords) < len(tile_coords) * CACHE_MISS_THRESHOLD:
                return tile_coords
            return cached_coords

        return tile_coords

    def _build_tile_data(self, coords: list) -> list[dict]:
        """Convert tile coordinates into tile dicts with position and source URL."""
        tiles = []
        for coord in coords:
            level, col, row = coord
            pos = self._slide_manager.getTilePosition(level, col, row)
            tiles.append({
                "level": level,
                "col": col,
                "row": row,
                "x": pos[0],
                "y": pos[1],
                "width": pos[2],
                "height": pos[3],
                "source": f"image://tiles/{level}/{col}_{row}?g={self._slide_generation}",
            })
        return tiles

    def _update_fallback_on_level_change(self) -> None:
        """Copy current tiles to fallback model when the pyramid level changes."""
        current_level = self._slide_manager.getLevelForScale(self._scale)
        if current_level != self._previous_level:
            if self._tile_model.hasTiles():
                self._fallback_tile_model.batchUpdate(self._tile_model.getTiles())
            self._previous_level = current_level

    def _on_slide_loaded(self) -> None:
        """Handle slide loaded signal."""
        # Clear fallback model — guardrail against stale tiles surviving into
        # the new slide's first render (openSlide already clears, but this
        # covers any signal-driven re-entry before _update_tiles runs)
        self._fallback_tile_model.clear()
        self._previous_level = -1

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
    plugin_manager = PluginController()
    settings = Settings()
    project_manager = ProjectManager()

    plugin_manager.set_annotation_manager(annotation_manager)

    # Create Rust scheduler with configured cache and prefetch settings
    rust_scheduler = RustTileScheduler(
        cache_size_mb=L1_CACHE_SIZE_MB,
        l2_cache_size_mb=L2_CACHE_SIZE_MB,
        prefetch_distance=PREFETCH_DISTANCE,
    )
    logger.info("Rust tile scheduler initialized")

    # Discover AI plugins
    plugin_manager.discoverPlugins()

    # Ensure plugin resources are freed on app shutdown
    app.aboutToQuit.connect(plugin_manager.cleanup)

    cache_stats_provider = CacheStatsProvider(rust_scheduler)

    controller = AppController(
        slide_manager,
        annotation_manager,
        project_manager,
        plugin_manager,
        rust_scheduler,
        settings,
    )
    preprocess_controller = PreprocessController(settings=settings)

    # Apply saved settings to preprocess controller
    if settings.defaultOutputDir:
        preprocess_controller.outputDir = settings.defaultOutputDir

    # Create QML engine
    engine = QQmlApplicationEngine()

    # Register image providers
    engine.addImageProvider("tiles", TileImageProvider(rust_scheduler))
    engine.addImageProvider("thumbnail", ThumbnailProvider(slide_manager))
    engine.addImageProvider("annotations", AnnotationTileImageProvider(annotation_manager, slide_manager))

    # Expose objects to QML
    engine.rootContext().setContextProperty("App", controller)
    engine.rootContext().setContextProperty("Preprocess", preprocess_controller)
    engine.rootContext().setContextProperty("Settings", settings)
    engine.rootContext().setContextProperty("SlideManager", slide_manager)
    engine.rootContext().setContextProperty("AnnotationManager", annotation_manager)
    engine.rootContext().setContextProperty("PluginManager", plugin_manager)
    engine.rootContext().setContextProperty("Navigator", controller.navigator)
    engine.rootContext().setContextProperty("CacheStats", cache_stats_provider)
    engine.rootContext().setContextProperty("IsDebugBuild", is_debug_build())
    assets_dir = str(Path(__file__).parent.parent.parent.parent / "assets")
    engine.rootContext().setContextProperty("AssetsDir", assets_dir)

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
