"""Tests for AppController -- critical load sequence, concurrency, and error recovery."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from fastpath.ui.app import AppController
from fastpath.ui.slide import SlideManager
from fastpath.ui.annotations import AnnotationManager
from fastpath.ui.project import ProjectManager
from fastpath.plugins.controller import PluginController
from fastpath.ui.settings import Settings


@pytest.fixture
def mock_rust_scheduler():
    """Create a mock RustTileScheduler."""
    scheduler = MagicMock()
    scheduler.is_loaded = False
    scheduler.load.return_value = True
    scheduler.cache_stats.return_value = {
        "hits": 0, "misses": 0, "hit_ratio": 0.0,
        "size_bytes": 0, "num_tiles": 0,
        "l2_hits": 0, "l2_misses": 0, "l2_hit_ratio": 0.0,
        "l2_size_bytes": 0, "l2_num_tiles": 0,
    }
    return scheduler


@pytest.fixture
def controller(qapp, mock_rust_scheduler, temp_dir):
    """Create an AppController with mocked dependencies.

    Uses an isolated QSettings (INI file in temp_dir) so tests don't
    pollute the real user settings (e.g. lastSlideDirUrl).
    """
    from PySide6.QtCore import QSettings

    slide_manager = SlideManager()
    annotation_manager = AnnotationManager()
    project_manager = ProjectManager()
    plugin_manager = PluginController()
    settings = Settings()
    # Redirect to a temp INI file so test writes don't leak to the registry
    settings._settings = QSettings(str(temp_dir / "test_settings.ini"), QSettings.Format.IniFormat)

    ctrl = AppController(
        slide_manager=slide_manager,
        annotation_manager=annotation_manager,
        project_manager=project_manager,
        plugin_manager=plugin_manager,
        rust_scheduler=mock_rust_scheduler,
        settings=settings,
    )
    return ctrl


class TestLoadOrder:
    """Verify the critical load order: Rust scheduler -> prefetch -> SlideManager."""

    def test_load_order(self, controller, mock_rust_scheduler, mock_fastpath_dir):
        """Rust scheduler.load() must be called before slide_manager.load().

        The load order is:
        1. rust_scheduler.load()
        2. rust_scheduler.prefetch_low_res_levels()
        3. slide_manager.load() (emits slideLoaded -> QML requests tiles)
        """
        call_order = []

        original_sm_load = controller._slide_manager.load

        def track_rust_load(*args, **kwargs):
            call_order.append("rust_load")
            return True

        def track_rust_prefetch(*args, **kwargs):
            call_order.append("rust_prefetch")

        def track_sm_load(*args, **kwargs):
            call_order.append("slide_manager_load")
            return original_sm_load(*args, **kwargs)

        mock_rust_scheduler.load.side_effect = track_rust_load
        mock_rust_scheduler.prefetch_low_res_levels.side_effect = track_rust_prefetch

        with patch.object(controller._slide_manager, "load", side_effect=track_sm_load):
            result = controller.openSlide(str(mock_fastpath_dir))

        assert result is True
        assert call_order == ["rust_load", "rust_prefetch", "slide_manager_load"]

    def test_rust_scheduler_receives_resolved_path(self, controller, mock_rust_scheduler, mock_fastpath_dir):
        """Rust scheduler.load() receives the resolved (absolute) path."""
        controller.openSlide(str(mock_fastpath_dir))

        mock_rust_scheduler.load.assert_called_once()
        loaded_path = mock_rust_scheduler.load.call_args[0][0]
        assert Path(loaded_path).is_absolute()
        assert Path(loaded_path).exists()


class TestConcurrentOpen:
    """Verify that concurrent openSlide() calls are serialized."""

    def test_concurrent_open_only_one_succeeds(self, controller, mock_rust_scheduler, mock_fastpath_dir):
        """Two threads calling openSlide() simultaneously: only one should succeed.

        The second call should return False because _loading is True.
        We use an event to ensure the second thread tries while the first is
        still inside the loading section (between acquiring and releasing _loading).
        """
        inside_load = threading.Event()
        proceed = threading.Event()
        results = [None, None]

        # Make rust_scheduler.load() block until we signal it to proceed
        def slow_load(*args, **kwargs):
            inside_load.set()  # signal that we're inside the load
            proceed.wait(timeout=5)  # wait for test to release us
            return True

        mock_rust_scheduler.load.side_effect = slow_load

        def open_slide_first():
            results[0] = controller.openSlide(str(mock_fastpath_dir))

        def open_slide_second():
            inside_load.wait(timeout=5)  # wait until first thread is inside load
            results[1] = controller.openSlide(str(mock_fastpath_dir))

        t1 = threading.Thread(target=open_slide_first)
        t2 = threading.Thread(target=open_slide_second)
        t1.start()
        t2.start()

        # Wait for the second thread to finish (it should return immediately with False)
        t2.join(timeout=10)
        assert results[1] is False, "Second concurrent openSlide() should return False"

        # Now let the first thread complete
        proceed.set()
        t1.join(timeout=10)
        assert results[0] is True, "First openSlide() should succeed"


class TestCloseDuringLoad:
    """Verify closeSlide() behavior when a load is in progress."""

    def test_close_during_load_blocked(self, controller, mock_rust_scheduler):
        """closeSlide() should be blocked if _loading_lock is held.

        The current implementation uses acquire(blocking=False), so closeSlide()
        returns immediately without closing the slide manager.
        """
        # Manually acquire the loading lock to simulate a load in progress
        controller._loading_lock.acquire()
        try:
            # closeSlide should detect the lock is held and skip closing
            controller.closeSlide()

            # slide_manager.close() should NOT have been called
            # (SlideManager.close is a real method, not a mock, but the manager
            # was never loaded so there's nothing to close anyway. The key check
            # is that the method returns without error.)
            assert controller._slide_manager.isLoaded is False
            mock_rust_scheduler.close.assert_not_called()
        finally:
            controller._loading_lock.release()


class TestErrorHandling:
    """Verify error signal emission and recovery."""

    def test_open_nonexistent_emits_error(self, controller, mock_rust_scheduler):
        """Opening a nonexistent path should emit errorOccurred with a user-friendly message."""
        errors = []
        controller.errorOccurred.connect(lambda msg: errors.append(msg))

        result = controller.openSlide(r"C:\nonexistent\fake_slide.fastpath")

        assert result is False
        assert len(errors) == 1
        assert "not found" in errors[0].lower() or "File not found" in errors[0]

    def test_open_empty_path(self, controller, mock_rust_scheduler):
        """Opening an empty/whitespace path should not crash."""
        result = controller.openSlide("")
        assert result is False

    def test_error_recovery_preserves_previous_slide(
        self, controller, mock_rust_scheduler, mock_fastpath_dir
    ):
        """After opening slide A, a failed open of slide B should keep slide A active.

        The current implementation clears visual state before trying the new slide.
        After a failure, currentPath should still reflect the previous slide's path
        if the implementation preserves it (Agent 2 is adding atomic switch logic).
        """
        # Open slide A successfully
        result_a = controller.openSlide(str(mock_fastpath_dir))
        assert result_a is True
        path_a = controller.currentPath
        assert path_a != ""

        # Attempt to open a nonexistent slide B
        errors = []
        controller.errorOccurred.connect(lambda msg: errors.append(msg))

        result_b = controller.openSlide(r"C:\nonexistent\fake_slide_b.fastpath")
        assert result_b is False
        assert len(errors) >= 1

        # After the atomic-switch changes from Agent 2, currentPath should be
        # preserved. In the current code, it remains as path_a because the error
        # path returns before updating _current_path.
        assert controller.currentPath == path_a

    def test_slide_manager_load_failure(self, controller, mock_rust_scheduler, mock_fastpath_dir):
        """If SlideManager.load() returns False, Rust scheduler should be closed."""
        with patch.object(controller._slide_manager, "load", return_value=False):
            errors = []
            controller.errorOccurred.connect(lambda msg: errors.append(msg))

            result = controller.openSlide(str(mock_fastpath_dir))

        assert result is False
        mock_rust_scheduler.close.assert_called_once()
        assert len(errors) == 1
        assert "metadata" in errors[0].lower()


class TestProjectLifecycle:
    """Tests for project open/save round trip."""

    def test_project_save_and_open(self, controller, mock_rust_scheduler, mock_fastpath_dir, temp_dir):
        """Save a project then reopen it and verify state is restored."""
        # Open a slide first
        result = controller.openSlide(str(mock_fastpath_dir))
        assert result is True

        # Set a viewport position
        controller.updateViewport(100.0, 200.0, 800.0, 600.0, 0.5)

        # Save as a new project
        project_path = temp_dir / "test_project.fpproj"
        result = controller.saveProjectAs(str(project_path))
        assert result is True
        assert project_path.exists()

        # Verify project file contains expected data
        with open(project_path) as f:
            data = json.load(f)
        assert data["slide_path"] == str(mock_fastpath_dir.resolve())
        assert data["view_state"]["x"] == 100.0
        assert data["view_state"]["y"] == 200.0
        assert data["view_state"]["scale"] == 0.5

    def test_open_project(self, controller, mock_rust_scheduler, mock_fastpath_dir, temp_dir):
        """Open a project file and verify the slide loads."""
        # Create a project file pointing to our mock slide
        project_path = temp_dir / "test.fpproj"
        annotations_path = temp_dir / "test.geojson"
        annotations_path.write_text('{"type": "FeatureCollection", "features": []}')

        project_data = {
            "version": "1.0",
            "slide_path": str(mock_fastpath_dir),
            "annotations_file": str(annotations_path),
            "view_state": {"x": 50.0, "y": 75.0, "scale": 0.3},
            "created_at": "2024-01-01T00:00:00Z",
            "modified_at": "2024-01-01T00:00:00Z",
            "metadata": {},
        }
        with open(project_path, "w") as f:
            json.dump(project_data, f)

        view_states = []
        controller.projectViewStateReady.connect(
            lambda x, y, s: view_states.append((x, y, s))
        )

        result = controller.openProject(str(project_path))
        assert result is True
        assert controller.currentPath != ""
        assert controller.projectLoaded is True

        # View state signal should have been emitted
        assert len(view_states) == 1
        assert view_states[0] == (50.0, 75.0, 0.3)

    def test_open_project_missing_slide(self, controller, mock_rust_scheduler, temp_dir):
        """Opening a project with a missing slide should fail with an error."""
        project_path = temp_dir / "bad_project.fpproj"
        project_data = {
            "version": "1.0",
            "slide_path": r"C:\nonexistent\missing.fastpath",
            "annotations_file": "",
            "view_state": {},
            "created_at": "",
            "modified_at": "",
            "metadata": {},
        }
        with open(project_path, "w") as f:
            json.dump(project_data, f)

        errors = []
        controller.errorOccurred.connect(lambda msg: errors.append(msg))

        result = controller.openProject(str(project_path))
        assert result is False
        assert len(errors) >= 1

    def test_save_project_empty_path(self, controller, mock_rust_scheduler):
        """saveProjectAs with empty path returns False."""
        result = controller.saveProjectAs("")
        assert result is False

    def test_save_without_slide_fails(self, controller, mock_rust_scheduler):
        """Saving a project without a loaded slide should fail."""
        result = controller.saveProject()
        assert result is False


class TestCloseSlide:
    """Tests for the closeSlide method."""

    def test_close_clears_state(self, controller, mock_rust_scheduler, mock_fastpath_dir):
        """Closing a slide should clear the current path and call scheduler.close()."""
        controller.openSlide(str(mock_fastpath_dir))
        assert controller.currentPath != ""

        controller.closeSlide()
        assert controller.currentPath == ""
        mock_rust_scheduler.close.assert_called()

    def test_close_emits_signal(self, controller, mock_rust_scheduler, mock_fastpath_dir):
        """Closing should emit slidePathChanged."""
        controller.openSlide(str(mock_fastpath_dir))

        changed = [0]
        controller.slidePathChanged.connect(lambda: changed.__setitem__(0, changed[0] + 1))

        controller.closeSlide()
        assert changed[0] >= 1


class TestSlideGeneration:
    """Test the generation counter used for cache-busting tile URLs."""

    def test_generation_increments_on_open(self, controller, mock_rust_scheduler, mock_fastpath_dir):
        """Each openSlide() should increment _slide_generation."""
        gen_before = controller._slide_generation

        controller.openSlide(str(mock_fastpath_dir))
        assert controller._slide_generation == gen_before + 1

        # Close and re-open
        controller.closeSlide()
        mock_rust_scheduler.reset_mock()
        mock_rust_scheduler.load.return_value = True

        controller.openSlide(str(mock_fastpath_dir))
        assert controller._slide_generation == gen_before + 2
