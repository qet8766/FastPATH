"""Tests for the plugin system."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from fastpath.plugins.base import ModelPlugin, Plugin, ProgressCallback
from fastpath.plugins.context import SlideContext
from fastpath.plugins.controller import PluginController
from fastpath.plugins.executor import PluginExecutor
from fastpath.plugins.registry import PluginRegistry
from fastpath.plugins.types import (
    InputType,
    OutputType,
    PluginInput,
    PluginMetadata,
    PluginOutput,
    RegionOfInterest,
    ResolutionSpec,
)
from fastpath.plugins.examples.tissue_classifier import TissueClassifier
from fastpath.plugins.examples.color_histogram import ColorHistogramAnalyzer
from fastpath.plugins.examples.tissue_detector import TissueDetector


# ------------------------------------------------------------------
# SlideContext tests
# ------------------------------------------------------------------


class TestSlideContext:
    """Tests for SlideContext."""

    def test_metadata_loading(self, mock_fastpath_dir: Path):
        ctx = SlideContext(mock_fastpath_dir)
        assert ctx.source_file == "test_slide.svs"
        assert ctx.source_mpp == 0.25
        assert ctx.pyramid_mpp == 0.5
        assert ctx.tile_size == 512
        assert ctx.dimensions == (2048, 2048)

    def test_levels(self, mock_fastpath_dir: Path):
        ctx = SlideContext(mock_fastpath_dir)
        levels = ctx.levels
        assert len(levels) == 3
        assert levels[0].level == 0
        assert levels[2].level == 2

    def test_level_mpp(self, mock_fastpath_dir: Path):
        ctx = SlideContext(mock_fastpath_dir)
        # Level 0 has downsample=4, pyramid_mpp=0.5 → mpp=2.0
        assert ctx.level_mpp(0) == pytest.approx(2.0)
        # Level 1 has downsample=2 → mpp=1.0
        assert ctx.level_mpp(1) == pytest.approx(1.0)
        # Level 2 has downsample=1 → mpp=0.5
        assert ctx.level_mpp(2) == pytest.approx(0.5)

    def test_level_for_mpp(self, mock_fastpath_dir: Path):
        ctx = SlideContext(mock_fastpath_dir)
        # Requesting 0.5 MPP → level 2 (ds=1, mpp=0.5, exact match)
        assert ctx.level_for_mpp(0.5) == 2
        # Requesting 1.0 MPP → level 1 is coarsest that fits (mpp=1.0 <= 1.0)
        assert ctx.level_for_mpp(1.0) == 1
        # Requesting 2.0 MPP → level 0 (mpp=2.0 <= 2.0)
        assert ctx.level_for_mpp(2.0) == 0
        # Requesting 8.0 MPP → level 0 is coarsest (mpp=2.0 <= 8.0)
        assert ctx.level_for_mpp(8.0) == 0
        # Requesting 0.25 MPP → nothing qualifies, returns highest-res fallback (level 2)
        assert ctx.level_for_mpp(0.25) == 2

    def test_get_tile(self, mock_fastpath_dir: Path):
        ctx = SlideContext(mock_fastpath_dir)
        tile = ctx.get_tile(2, 0, 0)
        assert tile is not None
        assert tile.ndim == 3
        assert tile.shape[2] == 3

    def test_get_tile_missing(self, mock_fastpath_dir: Path):
        ctx = SlideContext(mock_fastpath_dir)
        tile = ctx.get_tile(2, 99, 99)
        assert tile is None

    def test_iter_tiles(self, mock_fastpath_dir: Path):
        ctx = SlideContext(mock_fastpath_dir)
        tiles = list(ctx.iter_tiles(0))
        # Level 0 has 1x1 grid
        assert len(tiles) == 1
        assert tiles[0].col == 0
        assert tiles[0].row == 0
        assert tiles[0].image.ndim == 3

    def test_iter_tiles_with_roi(self, mock_fastpath_dir: Path):
        ctx = SlideContext(mock_fastpath_dir)
        # Level 2 has 4x4 grid, tile_size=512, ds=1
        # ROI covers top-left quarter → should get tiles at (0,0), (0,1), (1,0), (1,1)
        roi = RegionOfInterest(x=0, y=0, w=1024, h=1024)
        tiles = list(ctx.iter_tiles(2, roi=roi))
        assert len(tiles) == 4
        coords = {(t.col, t.row) for t in tiles}
        assert coords == {(0, 0), (0, 1), (1, 0), (1, 1)}

    def test_get_region(self, mock_fastpath_dir: Path):
        ctx = SlideContext(mock_fastpath_dir)
        region = ctx.get_region(2, 0, 0, 256, 256)
        assert region.shape == (256, 256, 3)

    def test_to_slide(self, mock_fastpath_dir: Path):
        ctx = SlideContext(mock_fastpath_dir)
        # Level 1 has downsample=2
        sx, sy = ctx.to_slide(1, 100, 200)
        assert sx == pytest.approx(200.0)
        assert sy == pytest.approx(400.0)

    def test_to_level(self, mock_fastpath_dir: Path):
        ctx = SlideContext(mock_fastpath_dir)
        # Level 1 has downsample=2
        lx, ly = ctx.to_level(1, 200, 400)
        assert lx == pytest.approx(100.0)
        assert ly == pytest.approx(200.0)

    def test_tile_bounds(self, mock_fastpath_dir: Path):
        ctx = SlideContext(mock_fastpath_dir)
        # Level 2, ds=1, tile_size=512
        bx, by, bw, bh = ctx.tile_bounds(2, 1, 2)
        assert bx == pytest.approx(512.0)
        assert by == pytest.approx(1024.0)
        assert bw == pytest.approx(512.0)
        assert bh == pytest.approx(512.0)

    def test_get_level_info(self, mock_fastpath_dir: Path):
        ctx = SlideContext(mock_fastpath_dir)
        info = ctx.get_level_info(0)
        assert info.level == 0
        assert info.downsample == 4
        assert info.cols == 1
        assert info.rows == 1

        info2 = ctx.get_level_info(2)
        assert info2.level == 2
        assert info2.downsample == 1
        assert info2.cols == 4
        assert info2.rows == 4

    def test_get_level_info_invalid(self, mock_fastpath_dir: Path):
        ctx = SlideContext(mock_fastpath_dir)
        with pytest.raises(ValueError, match="Unknown level"):
            ctx.get_level_info(99)

    def test_missing_metadata_error(self, temp_dir: Path):
        empty_dir = temp_dir / "empty.fastpath"
        empty_dir.mkdir()
        with pytest.raises(FileNotFoundError, match="metadata.json"):
            SlideContext(empty_dir)

    def test_missing_path_error(self, temp_dir: Path):
        with pytest.raises(FileNotFoundError, match="not found"):
            SlideContext(temp_dir / "nonexistent.fastpath")


# ------------------------------------------------------------------
# PluginMetadata / ResolutionSpec tests
# ------------------------------------------------------------------


class TestPluginMetadata:
    """Tests for PluginMetadata."""

    def test_defaults(self):
        meta = PluginMetadata(name="Test", description="Test plugin")
        assert meta.name == "Test"
        assert meta.version == "1.0.0"
        assert meta.input_type == InputType.REGION
        assert meta.output_types == [OutputType.CLASSIFICATION]
        assert meta.labels == []
        assert meta.wants_image is True

    def test_custom_values(self):
        meta = PluginMetadata(
            name="Custom",
            description="Custom plugin",
            version="2.0.0",
            author="Test Author",
            input_type=InputType.TILE,
            output_types=[OutputType.MASK, OutputType.MEASUREMENTS],
            input_size=(512, 512),
            labels=["A", "B", "C"],
        )
        assert meta.version == "2.0.0"
        assert meta.author == "Test Author"
        assert meta.input_type == InputType.TILE
        assert OutputType.MASK in meta.output_types
        assert meta.input_size == (512, 512)
        assert meta.labels == ["A", "B", "C"]

    def test_resolution_spec(self):
        spec = ResolutionSpec(working_mpp=0.5)
        assert not spec.needs_original_wsi

        spec_fine = ResolutionSpec(working_mpp=0.25)
        assert spec_fine.needs_original_wsi

        spec_context = ResolutionSpec(working_mpp=0.5, context_mpp=0.3)
        assert spec_context.needs_original_wsi


# ------------------------------------------------------------------
# PluginOutput tests
# ------------------------------------------------------------------


class TestPluginOutput:
    """Tests for PluginOutput."""

    def test_classification_to_dict(self):
        output = PluginOutput(
            success=True,
            message="done",
            classification={"label": "Tumor", "confidence": 0.95},
        )
        d = output.to_dict()
        assert d["success"] is True
        assert d["outputType"] == "classification"
        assert d["classification"]["label"] == "Tumor"

    def test_heatmap_signals_presence(self):
        heatmap = np.random.rand(10, 10).astype(np.float32)
        output = PluginOutput(success=True, heatmap=heatmap, heatmap_level=2)
        d = output.to_dict()
        assert d["hasHeatmap"] is True
        assert d["outputType"] == "heatmap"
        # Numpy array should NOT be serialized
        assert "heatmap" not in d or not isinstance(d.get("heatmap"), list)

    def test_tile_scores_to_dict(self):
        scores = np.array([[0.1, 0.9], [0.5, 0.3]], dtype=np.float32)
        output = PluginOutput(
            success=True,
            tile_scores=scores,
            tile_level=0,
            measurements={"tissue_fraction": 0.5},
        )
        d = output.to_dict()
        assert d["outputType"] == "tile_scores"
        assert d["tileScores"] == scores.tolist()
        assert d["tileLevel"] == 0
        assert d["hasTileScores"] is True
        assert d["measurements"]["tissue_fraction"] == 0.5

    def test_output_type_in_dict(self):
        output = PluginOutput(
            success=True,
            classification={"label": "Normal", "confidence": 0.8},
        )
        d = output.to_dict()
        # QML formatResult() reads this key
        assert "outputType" in d
        assert d["outputType"] == "classification"

    def test_mask_presence_flag(self):
        mask = np.zeros((64, 64), dtype=np.uint8)
        output = PluginOutput(success=True, mask=mask, mask_level=2)
        d = output.to_dict()
        assert d["hasMask"] is True
        assert d["outputType"] == "mask"

    def test_measurements_output(self):
        output = PluginOutput(
            success=True,
            measurements={"mean": 42.0, "count": 100},
        )
        d = output.to_dict()
        assert d["outputType"] == "measurements"
        assert d["measurements"]["mean"] == 42.0

    def test_annotations_to_dict(self):
        """Gap 2: PluginOutput.to_dict() for annotations output type."""
        annotations = [
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [100, 200]},
                "properties": {"label": "Mitosis"},
            },
            {
                "type": "Feature",
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 0]]]},
                "properties": {"label": "Region"},
            },
        ]
        output = PluginOutput(success=True, annotations=annotations)
        d = output.to_dict()
        assert d["success"] is True
        assert d["outputType"] == "annotations"
        assert d["annotations"] == annotations
        assert len(d["annotations"]) == 2


# ------------------------------------------------------------------
# Plugin ABC tests
# ------------------------------------------------------------------


class TestPlugin:
    """Tests for creating custom plugins."""

    def test_custom_plugin(self):
        class TestPlugin(Plugin):
            @property
            def metadata(self) -> PluginMetadata:
                return PluginMetadata(
                    name="Test Plugin",
                    description="A test plugin",
                    labels=["A", "B"],
                )

            def process(self, plugin_input, progress_callback=None):
                return PluginOutput(
                    success=True,
                    classification={"label": "A", "confidence": 1.0},
                )

        plugin = TestPlugin()
        assert plugin.name == "Test Plugin"
        assert plugin.description == "A test plugin"

    def test_validate_input(self, mock_fastpath_dir: Path):
        class TestPlugin(Plugin):
            @property
            def metadata(self) -> PluginMetadata:
                return PluginMetadata(name="V", description="V")

            def process(self, plugin_input, progress_callback=None):
                return PluginOutput(success=True)

        plugin = TestPlugin()
        ctx = SlideContext(mock_fastpath_dir)

        # Valid RGB image
        good_input = PluginInput(slide=ctx, image=np.zeros((64, 64, 3), dtype=np.uint8))
        valid, err = plugin.validate_input(good_input)
        assert valid

        # Wrong dimensions
        bad_input = PluginInput(slide=ctx, image=np.zeros((64, 64), dtype=np.uint8))
        valid, err = plugin.validate_input(bad_input)
        assert not valid
        assert "3D" in err

        # Wrong channels
        bad_input2 = PluginInput(slide=ctx, image=np.zeros((64, 64, 4), dtype=np.uint8))
        valid, err = plugin.validate_input(bad_input2)
        assert not valid
        assert "3 channels" in err

    def test_validate_input_with_input_size(self, mock_fastpath_dir: Path):
        """Gap 3: validate_input with input_size constraint."""
        class SizedPlugin(Plugin):
            @property
            def metadata(self) -> PluginMetadata:
                return PluginMetadata(
                    name="Sized",
                    description="Plugin with input_size",
                    input_size=(256, 256),
                )

            def process(self, plugin_input, progress_callback=None):
                return PluginOutput(success=True)

        plugin = SizedPlugin()
        ctx = SlideContext(mock_fastpath_dir)

        # Matching size: (256, 256)
        good_input = PluginInput(
            slide=ctx, image=np.zeros((256, 256, 3), dtype=np.uint8)
        )
        valid, err = plugin.validate_input(good_input)
        assert valid
        assert err == ""

        # Non-matching size: (128, 128)
        bad_input = PluginInput(
            slide=ctx, image=np.zeros((128, 128, 3), dtype=np.uint8)
        )
        valid, err = plugin.validate_input(bad_input)
        assert not valid
        assert "256" in err

        # Non-matching size: (512, 256) — width matches but height doesn't
        bad_input2 = PluginInput(
            slide=ctx, image=np.zeros((512, 256, 3), dtype=np.uint8)
        )
        valid, err = plugin.validate_input(bad_input2)
        assert not valid


# ------------------------------------------------------------------
# ModelPlugin tests
# ------------------------------------------------------------------


class TestModelPlugin:
    """Tests for ModelPlugin load/unload lifecycle."""

    def test_load_unload(self):
        class TestModel(ModelPlugin):
            @property
            def metadata(self) -> PluginMetadata:
                return PluginMetadata(name="Model", description="Model test")

            def process(self, plugin_input, progress_callback=None):
                return PluginOutput(success=True)

        plugin = TestModel()
        assert not plugin.is_loaded

        plugin.load_model()
        assert plugin.is_loaded

        plugin.unload_model()
        assert not plugin.is_loaded


# ------------------------------------------------------------------
# PluginRegistry tests
# ------------------------------------------------------------------


class TestPluginRegistry:
    """Tests for PluginRegistry."""

    def test_register_and_get(self):
        registry = PluginRegistry()
        plugin = TissueClassifier()
        registry.register(plugin)

        assert registry.count == 1
        assert registry.get("Tissue Classifier (Demo)") is plugin

    def test_unregister(self):
        registry = PluginRegistry()
        plugin = TissueClassifier()
        registry.register(plugin)

        removed = registry.unregister("Tissue Classifier (Demo)")
        assert removed is plugin
        assert registry.count == 0

    def test_unregister_nonexistent(self):
        registry = PluginRegistry()
        removed = registry.unregister("Nonexistent")
        assert removed is None

    def test_discover_builtin(self):
        registry = PluginRegistry()
        registry.discover()
        # Should find at least 3 built-in plugins
        assert registry.count >= 3


# ------------------------------------------------------------------
# PluginController tests
# ------------------------------------------------------------------


def _make_simple_plugin(name: str = "Simple") -> Plugin:
    """Helper to create a minimal plugin for controller tests."""

    class _SimplePlugin(Plugin):
        @property
        def metadata(self) -> PluginMetadata:
            return PluginMetadata(name=name, description="Simple test plugin")

        def process(self, plugin_input, progress_callback=None):
            return PluginOutput(
                success=True,
                classification={"label": "ok", "confidence": 1.0},
            )

    return _SimplePlugin()


def _make_simple_model_plugin(name: str = "SimpleModel") -> ModelPlugin:
    """Helper to create a minimal ModelPlugin for controller tests."""

    class _SimpleModelPlugin(ModelPlugin):
        @property
        def metadata(self) -> PluginMetadata:
            return PluginMetadata(name=name, description="Simple model plugin")

        def process(self, plugin_input, progress_callback=None):
            return PluginOutput(success=True)

    return _SimpleModelPlugin()


class TestPluginController:
    """Tests for PluginController (QML facade)."""

    def test_initial_state(self, qapp):
        controller = PluginController()
        assert controller.pluginCount == 0
        assert controller.getPluginList() == []

    def test_discover_and_list(self, qapp):
        controller = PluginController()
        controller.discoverPlugins()
        plugins = controller.getPluginList()
        assert len(plugins) >= 3

        names = {p["name"] for p in plugins}
        assert "Tissue Classifier (Demo)" in names
        assert "Color Histogram" in names
        assert "Tissue Detector" in names

    def test_get_plugin_info(self, qapp):
        controller = PluginController()
        controller.register_plugin(TissueClassifier())

        info = controller.getPluginInfo("Tissue Classifier (Demo)")
        assert info is not None
        assert info["name"] == "Tissue Classifier (Demo)"
        assert info["inputType"] == "region"
        assert info["outputTypes"] == ["classification"]
        assert "workingMpp" in info

    def test_nonexistent_plugin(self, qapp):
        controller = PluginController()
        info = controller.getPluginInfo("Unknown")
        assert info is None

    # Gap 1: register/unregister + loadModel/unloadModel lifecycle
    def test_register_and_unregister(self, qapp):
        controller = PluginController()
        plugin = _make_simple_plugin("RegTest")
        controller.register_plugin(plugin)

        assert controller.pluginCount == 1
        info = controller.getPluginInfo("RegTest")
        assert info is not None
        assert info["name"] == "RegTest"

        controller.unregister_plugin("RegTest")
        assert controller.pluginCount == 0
        assert controller.getPluginInfo("RegTest") is None

    def test_load_and_unload_model(self, qapp):
        controller = PluginController()
        plugin = _make_simple_model_plugin("LoadTest")
        controller.register_plugin(plugin)

        # Initially not loaded
        info = controller.getPluginInfo("LoadTest")
        assert info["isLoaded"] is False
        assert info["hasModel"] is True

        # Load model
        controller.loadModel("LoadTest")
        info = controller.getPluginInfo("LoadTest")
        assert info["isLoaded"] is True
        assert plugin.is_loaded

        # Unload model
        controller.unloadModel("LoadTest")
        info = controller.getPluginInfo("LoadTest")
        assert info["isLoaded"] is False
        assert not plugin.is_loaded

    def test_unregister_unloads_model(self, qapp):
        controller = PluginController()
        plugin = _make_simple_model_plugin("UnregModel")
        controller.register_plugin(plugin)
        controller.loadModel("UnregModel")
        assert plugin.is_loaded

        controller.unregister_plugin("UnregModel")
        assert not plugin.is_loaded
        assert controller.pluginCount == 0

    # Gap 4: processRegion() integration
    def test_process_region(self, qapp, mock_fastpath_dir: Path):
        controller = PluginController()
        controller.register_plugin(TissueClassifier())

        started_signals = []
        finished_signals = []
        controller.processingStarted.connect(started_signals.append)
        controller.processingFinished.connect(finished_signals.append)

        controller.processRegion(
            "Tissue Classifier (Demo)",
            str(mock_fastpath_dir),
            0.0, 0.0, 512.0, 512.0, 0.5,
        )

        # Wait for the worker thread to finish (max 10s)
        import time
        deadline = time.time() + 10
        while not finished_signals and time.time() < deadline:
            qapp.processEvents()
            time.sleep(0.05)

        assert len(started_signals) == 1
        assert started_signals[0] == "Tissue Classifier (Demo)"
        assert len(finished_signals) == 1
        assert finished_signals[0]["success"] is True

    # Gap 6: Error path tests
    def test_process_region_unknown_plugin(self, qapp):
        controller = PluginController()
        errors = []
        controller.processingError.connect(errors.append)

        controller.processRegion(
            "NonexistentPlugin",
            "some/path",
            0.0, 0.0, 100.0, 100.0, 0.5,
        )

        assert len(errors) == 1
        assert "not found" in errors[0].lower()

    def test_process_region_while_running(self, qapp, mock_fastpath_dir: Path):
        """Calling processRegion while another is running emits an error."""
        import time

        # Create a plugin that takes a while
        class SlowPlugin(Plugin):
            @property
            def metadata(self) -> PluginMetadata:
                return PluginMetadata(
                    name="Slow",
                    description="Takes time",
                    wants_image=False,
                )

            def process(self, plugin_input, progress_callback=None):
                time.sleep(2)
                return PluginOutput(success=True)

        controller = PluginController()
        controller.register_plugin(SlowPlugin())
        controller.register_plugin(TissueClassifier())

        errors = []
        controller.processingError.connect(errors.append)

        # Start slow plugin
        controller.processRegion(
            "Slow", str(mock_fastpath_dir),
            0.0, 0.0, 100.0, 100.0, 0.5,
        )

        # Let the worker thread start
        qapp.processEvents()
        time.sleep(0.1)
        qapp.processEvents()

        # Try to start another while it's running
        controller.processRegion(
            "Tissue Classifier (Demo)", str(mock_fastpath_dir),
            0.0, 0.0, 100.0, 100.0, 0.5,
        )

        assert len(errors) == 1
        assert "already running" in errors[0].lower()

        # Cleanup: wait for the slow worker to finish
        controller.cleanup()


# ------------------------------------------------------------------
# PluginExecutor tests
# ------------------------------------------------------------------


class TestPluginExecutor:
    """Tests for PluginExecutor."""

    def test_execute_with_image(self, qapp, mock_fastpath_dir: Path):
        """Gap 5: Image assembly path (wants_image=True with region)."""
        executor = PluginExecutor()
        executor.set_slide(mock_fastpath_dir)

        plugin = TissueClassifier()  # wants_image=True by default
        region = RegionOfInterest(x=0, y=0, w=512, h=512)

        results = []
        worker = executor.execute(plugin, region=region)
        worker.finished.connect(results.append)

        # Wait for completion
        worker.wait(10000)
        qapp.processEvents()

        assert len(results) == 1
        assert results[0].success

        executor.cleanup()

    def test_execute_without_image(self, qapp, mock_fastpath_dir: Path):
        """Gap 5: No-image path (wants_image=False)."""
        executor = PluginExecutor()
        executor.set_slide(mock_fastpath_dir)

        plugin = TissueDetector()  # wants_image=False
        results = []
        worker = executor.execute(plugin)
        worker.finished.connect(results.append)

        worker.wait(10000)
        qapp.processEvents()

        assert len(results) == 1
        assert results[0].success
        assert results[0].tile_scores is not None

        executor.cleanup()

    def test_execute_no_slide_raises(self, qapp):
        executor = PluginExecutor()
        plugin = TissueClassifier()

        with pytest.raises(RuntimeError, match="No slide loaded"):
            executor.execute(plugin)

    def test_set_and_clear_slide(self, mock_fastpath_dir: Path):
        executor = PluginExecutor()
        executor.set_slide(mock_fastpath_dir)
        assert executor.context is not None

        executor.clear_slide()
        assert executor.context is None


# ------------------------------------------------------------------
# Example plugin tests
# ------------------------------------------------------------------


@pytest.fixture
def sample_tissue_array() -> np.ndarray:
    """Pinkish tissue-like image."""
    return np.full((256, 256, 3), [220, 180, 200], dtype=np.uint8)


@pytest.fixture
def sample_white_array() -> np.ndarray:
    """White (background) image."""
    return np.full((256, 256, 3), 255, dtype=np.uint8)


class TestTissueClassifier:
    """Tests for the TissueClassifier example plugin."""

    def test_classify_tissue(self, mock_fastpath_dir: Path, sample_tissue_array: np.ndarray):
        plugin = TissueClassifier()
        ctx = SlideContext(mock_fastpath_dir)
        inp = PluginInput(slide=ctx, image=sample_tissue_array)
        result = plugin.process(inp)

        assert result.success
        assert result.classification is not None
        assert result.classification["label"] in ["Tissue", "Dense Tissue"]

    def test_classify_background(self, mock_fastpath_dir: Path, sample_white_array: np.ndarray):
        plugin = TissueClassifier()
        ctx = SlideContext(mock_fastpath_dir)
        inp = PluginInput(slide=ctx, image=sample_white_array)
        result = plugin.process(inp)

        assert result.success
        assert result.classification is not None
        assert result.classification["label"] == "Background"


class TestColorHistogram:
    """Tests for the ColorHistogramAnalyzer example plugin."""

    def test_measurements_with_channels(
        self, mock_fastpath_dir: Path, sample_tissue_array: np.ndarray
    ):
        plugin = ColorHistogramAnalyzer()
        ctx = SlideContext(mock_fastpath_dir)
        inp = PluginInput(slide=ctx, image=sample_tissue_array)
        result = plugin.process(inp)

        assert result.success
        assert result.measurements is not None
        assert "channels" in result.measurements
        assert "red" in result.measurements["channels"]
        assert "green" in result.measurements["channels"]
        assert "blue" in result.measurements["channels"]

        red = result.measurements["channels"]["red"]
        assert "mean" in red
        assert "std" in red


class TestTissueDetector:
    """Tests for the TissueDetector example plugin."""

    def test_whole_slide_tile_scores(self, mock_fastpath_dir: Path):
        plugin = TissueDetector()
        ctx = SlideContext(mock_fastpath_dir)
        inp = PluginInput(slide=ctx)
        result = plugin.process(inp)

        assert result.success
        assert result.tile_scores is not None
        assert result.tile_level is not None
        # Score shape should match the grid at the chosen level
        info = ctx.get_level_info(result.tile_level)
        assert result.tile_scores.shape == (info.rows, info.cols)
        assert result.measurements is not None
        assert "tissue_fraction" in result.measurements
