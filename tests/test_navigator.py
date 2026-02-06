"""Tests for SlideNavigator -- multi-slide directory navigation."""

from __future__ import annotations

from pathlib import Path

import pytest

from fastpath.ui.navigator import SlideNavigator


@pytest.fixture
def navigator(qapp):
    """Create a fresh SlideNavigator."""
    return SlideNavigator()


@pytest.fixture
def multi_slide_dir(temp_dir):
    """Create a temp directory with multiple fake .fastpath directories."""
    for name in ["alpha.fastpath", "beta.fastpath", "gamma.fastpath"]:
        (temp_dir / name).mkdir()
    return temp_dir


class TestSlideNavigatorInitial:
    """Tests for initial state."""

    def test_initial_state(self, navigator):
        """Fresh navigator has currentIndex=-1, totalSlides=0, hasMultipleSlides=False."""
        assert navigator.currentIndex == -1
        assert navigator.totalSlides == 0
        assert navigator.hasMultipleSlides is False
        assert navigator.currentSlideName == ""


class TestSlideNavigatorScan:
    """Tests for directory scanning."""

    def test_scan_directory_finds_fastpath_dirs(self, navigator, multi_slide_dir):
        """Scan a .fastpath dir and verify all siblings found."""
        navigator.scanDirectory(str(multi_slide_dir / "alpha.fastpath"))
        assert navigator.totalSlides == 3
        assert navigator.currentIndex == 0

    def test_scan_directory_sets_current_index(self, navigator, multi_slide_dir):
        """Scanning beta.fastpath should set currentIndex=1."""
        navigator.scanDirectory(str(multi_slide_dir / "beta.fastpath"))
        assert navigator.currentIndex == 1

    def test_scan_directory_gamma(self, navigator, multi_slide_dir):
        """Scanning gamma.fastpath should set currentIndex=2."""
        navigator.scanDirectory(str(multi_slide_dir / "gamma.fastpath"))
        assert navigator.currentIndex == 2

    def test_empty_directory(self, navigator, temp_dir):
        """Scan a directory with no .fastpath dirs."""
        empty = temp_dir / "empty_subdir"
        empty.mkdir()
        # scanDirectory expects a file path, scan from within the empty dir
        # Create a dummy path inside to scan its parent
        navigator.scanDirectory(str(empty / "fake.fastpath"))
        assert navigator.totalSlides == 0
        assert navigator.currentIndex == -1

    def test_single_slide(self, navigator, temp_dir):
        """Directory with one .fastpath dir: hasMultipleSlides=False, nextSlide=''."""
        (temp_dir / "only.fastpath").mkdir()
        navigator.scanDirectory(str(temp_dir / "only.fastpath"))
        assert navigator.totalSlides == 1
        assert navigator.hasMultipleSlides is False
        assert navigator.nextSlide() == ""

    def test_non_fastpath_dirs_ignored(self, navigator, temp_dir):
        """Directories without .fastpath suffix are ignored."""
        (temp_dir / "alpha.fastpath").mkdir()
        (temp_dir / "regular_dir").mkdir()
        (temp_dir / "other.tiff").mkdir()
        navigator.scanDirectory(str(temp_dir / "alpha.fastpath"))
        assert navigator.totalSlides == 1


class TestSlideNavigatorNavigation:
    """Tests for next/previous navigation."""

    def test_next_slide_cycling(self, navigator, multi_slide_dir):
        """Start at alpha, next->beta, next->gamma, next->'' (at end)."""
        navigator.scanDirectory(str(multi_slide_dir / "alpha.fastpath"))
        assert navigator.currentIndex == 0

        path1 = navigator.nextSlide()
        assert "beta.fastpath" in path1
        assert navigator.currentIndex == 1

        path2 = navigator.nextSlide()
        assert "gamma.fastpath" in path2
        assert navigator.currentIndex == 2

        # At the end, returns empty
        path3 = navigator.nextSlide()
        assert path3 == ""
        assert navigator.currentIndex == 2  # stays at end

    def test_previous_slide_cycling(self, navigator, multi_slide_dir):
        """Start at gamma, prev->beta, prev->alpha, prev->'' (at beginning)."""
        navigator.scanDirectory(str(multi_slide_dir / "gamma.fastpath"))
        assert navigator.currentIndex == 2

        path1 = navigator.previousSlide()
        assert "beta.fastpath" in path1
        assert navigator.currentIndex == 1

        path2 = navigator.previousSlide()
        assert "alpha.fastpath" in path2
        assert navigator.currentIndex == 0

        # At the beginning, returns empty
        path3 = navigator.previousSlide()
        assert path3 == ""
        assert navigator.currentIndex == 0  # stays at beginning

    def test_next_then_previous(self, navigator, multi_slide_dir):
        """Navigate forward then backward."""
        navigator.scanDirectory(str(multi_slide_dir / "alpha.fastpath"))
        navigator.nextSlide()  # -> beta
        assert navigator.currentIndex == 1

        path = navigator.previousSlide()
        assert "alpha.fastpath" in path
        assert navigator.currentIndex == 0

    def test_navigation_with_no_slides(self, navigator):
        """next/previous on empty navigator returns ''."""
        assert navigator.nextSlide() == ""
        assert navigator.previousSlide() == ""


class TestSlideNavigatorProperties:
    """Tests for property accessors."""

    def test_get_slide_paths(self, navigator, multi_slide_dir):
        """get_slide_paths() returns all paths as strings, sorted."""
        navigator.scanDirectory(str(multi_slide_dir / "alpha.fastpath"))
        paths = navigator.get_slide_paths()
        assert len(paths) == 3
        # Should be sorted alphabetically
        assert "alpha.fastpath" in paths[0]
        assert "beta.fastpath" in paths[1]
        assert "gamma.fastpath" in paths[2]

    def test_current_slide_name(self, navigator, multi_slide_dir):
        """currentSlideName returns the stem of the current slide."""
        navigator.scanDirectory(str(multi_slide_dir / "beta.fastpath"))
        assert navigator.currentSlideName == "beta"

    def test_has_multiple_slides(self, navigator, multi_slide_dir):
        """hasMultipleSlides is True with > 1 slide."""
        navigator.scanDirectory(str(multi_slide_dir / "alpha.fastpath"))
        assert navigator.hasMultipleSlides is True

    def test_signals_emitted(self, navigator, multi_slide_dir):
        """Signals are emitted on scan and navigation."""
        list_changed = [0]
        index_changed = [0]

        navigator.slideListChanged.connect(lambda: list_changed.__setitem__(0, list_changed[0] + 1))
        navigator.currentIndexChanged.connect(lambda: index_changed.__setitem__(0, index_changed[0] + 1))

        navigator.scanDirectory(str(multi_slide_dir / "alpha.fastpath"))
        assert list_changed[0] == 1
        assert index_changed[0] == 1

        navigator.nextSlide()
        assert index_changed[0] == 2  # incremented on next
