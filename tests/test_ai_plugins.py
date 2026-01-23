"""Tests for the AI plugin system."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from fastpath.ai.base import (
    AIPlugin,
    InputType,
    OutputType,
    PluginMetadata,
    PluginResult,
)
from fastpath.ai.manager import AIPluginManager
from fastpath.ai.plugins.example import TissueClassifier, ColorHistogramAnalyzer


@pytest.fixture(scope="session")
def qapp():
    """Create a Qt application for testing."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture
def sample_tissue_array() -> np.ndarray:
    """Create a sample tissue-like image array."""
    # Pinkish tissue color
    img = np.full((256, 256, 3), [220, 180, 200], dtype=np.uint8)
    return img


@pytest.fixture
def sample_white_array() -> np.ndarray:
    """Create a white (background) image array."""
    return np.full((256, 256, 3), 255, dtype=np.uint8)


@pytest.fixture
def sample_dark_array() -> np.ndarray:
    """Create a dark image array."""
    return np.full((256, 256, 3), 30, dtype=np.uint8)


class TestPluginMetadata:
    """Tests for PluginMetadata."""

    def test_default_values(self):
        """Should have sensible defaults."""
        meta = PluginMetadata(name="Test", description="Test plugin")

        assert meta.name == "Test"
        assert meta.version == "1.0.0"
        assert meta.input_type == InputType.REGION
        assert meta.output_type == OutputType.CLASSIFICATION
        assert meta.labels == []

    def test_custom_values(self):
        """Should accept custom values."""
        meta = PluginMetadata(
            name="Custom",
            description="Custom plugin",
            version="2.0.0",
            author="Test Author",
            input_type=InputType.TILE,
            output_type=OutputType.MASK,
            input_size=(512, 512),
            labels=["A", "B", "C"],
        )

        assert meta.version == "2.0.0"
        assert meta.author == "Test Author"
        assert meta.input_type == InputType.TILE
        assert meta.output_type == OutputType.MASK
        assert meta.input_size == (512, 512)
        assert meta.labels == ["A", "B", "C"]


class TestPluginResult:
    """Tests for PluginResult."""

    def test_classification_result(self):
        """Should create classification result."""
        result = PluginResult(
            success=True,
            output_type=OutputType.CLASSIFICATION,
            data={"label": "Tumor", "confidence": 0.95},
            message="Classification complete",
            processing_time=0.5,
        )

        assert result.success
        assert result.output_type == OutputType.CLASSIFICATION
        assert result.data["label"] == "Tumor"

    def test_to_dict_classification(self):
        """Should convert classification to dict."""
        result = PluginResult(
            success=True,
            output_type=OutputType.CLASSIFICATION,
            data={"label": "Normal", "confidence": 0.8},
        )

        d = result.to_dict()
        assert d["success"] is True
        assert d["outputType"] == "classification"
        assert d["classification"]["label"] == "Normal"

    def test_to_dict_mask(self):
        """Should convert mask result to dict."""
        mask = np.array([[0, 1], [1, 0]], dtype=np.uint8)
        result = PluginResult(
            success=True,
            output_type=OutputType.MASK,
            data=mask,
        )

        d = result.to_dict()
        assert d["outputType"] == "mask"
        assert d["mask"] == [[0, 1], [1, 0]]


class TestTissueClassifier:
    """Tests for the example TissueClassifier plugin."""

    def test_metadata(self):
        """Should have correct metadata."""
        plugin = TissueClassifier()
        meta = plugin.metadata

        assert meta.name == "Tissue Classifier (Demo)"
        assert meta.input_type == InputType.REGION
        assert meta.output_type == OutputType.CLASSIFICATION
        assert "Background" in meta.labels
        assert "Tissue" in meta.labels

    def test_classify_tissue(self, sample_tissue_array: np.ndarray):
        """Should classify pinkish regions as tissue."""
        plugin = TissueClassifier()
        result = plugin.process(sample_tissue_array, {})

        assert result.success
        assert result.data["label"] in ["Tissue", "Dense Tissue"]

    def test_classify_background(self, sample_white_array: np.ndarray):
        """Should classify white regions as background."""
        plugin = TissueClassifier()
        result = plugin.process(sample_white_array, {})

        assert result.success
        assert result.data["label"] == "Background"

    def test_classify_artifact(self, sample_dark_array: np.ndarray):
        """Should classify dark regions as artifact."""
        plugin = TissueClassifier()
        result = plugin.process(sample_dark_array, {})

        assert result.success
        assert result.data["label"] == "Artifact"

    def test_result_has_statistics(self, sample_tissue_array: np.ndarray):
        """Result should include image statistics."""
        plugin = TissueClassifier()
        result = plugin.process(sample_tissue_array, {})

        assert "statistics" in result.data
        assert "brightness" in result.data["statistics"]
        assert "saturation" in result.data["statistics"]


class TestColorHistogramAnalyzer:
    """Tests for the ColorHistogramAnalyzer plugin."""

    def test_metadata(self):
        """Should have correct metadata."""
        plugin = ColorHistogramAnalyzer()
        meta = plugin.metadata

        assert meta.name == "Color Histogram"
        assert meta.input_type == InputType.REGION

    def test_analyze_image(self, sample_tissue_array: np.ndarray):
        """Should analyze color distribution."""
        plugin = ColorHistogramAnalyzer()
        result = plugin.process(sample_tissue_array, {})

        assert result.success
        assert "channels" in result.data
        assert "red" in result.data["channels"]
        assert "green" in result.data["channels"]
        assert "blue" in result.data["channels"]

    def test_channel_statistics(self, sample_tissue_array: np.ndarray):
        """Should compute per-channel statistics."""
        plugin = ColorHistogramAnalyzer()
        result = plugin.process(sample_tissue_array, {})

        red_stats = result.data["channels"]["red"]
        assert "mean" in red_stats
        assert "std" in red_stats
        assert "min" in red_stats
        assert "max" in red_stats
        assert "median" in red_stats

    def test_region_size(self, sample_tissue_array: np.ndarray):
        """Should report region size."""
        plugin = ColorHistogramAnalyzer()
        result = plugin.process(sample_tissue_array, {})

        assert result.data["region_size"]["width"] == 256
        assert result.data["region_size"]["height"] == 256
        assert result.data["region_size"]["pixels"] == 256 * 256


class TestAIPluginValidation:
    """Tests for plugin input validation."""

    def test_validate_valid_input(self, sample_tissue_array: np.ndarray):
        """Should accept valid 3-channel RGB input."""
        plugin = TissueClassifier()
        valid, error = plugin.validate_input(sample_tissue_array)

        assert valid
        assert error == ""

    def test_validate_none_input(self):
        """Should reject None input."""
        plugin = TissueClassifier()
        valid, error = plugin.validate_input(None)

        assert not valid
        assert "None" in error

    def test_validate_wrong_dimensions(self):
        """Should reject 2D input."""
        plugin = TissueClassifier()
        img = np.zeros((256, 256), dtype=np.uint8)
        valid, error = plugin.validate_input(img)

        assert not valid
        assert "3D" in error

    def test_validate_wrong_channels(self):
        """Should reject non-RGB input."""
        plugin = TissueClassifier()
        img = np.zeros((256, 256, 4), dtype=np.uint8)  # RGBA
        valid, error = plugin.validate_input(img)

        assert not valid
        assert "3 channels" in error


class TestAIPluginManager:
    """Tests for the AIPluginManager."""

    def test_initial_state(self, qapp):
        """Manager should start empty."""
        manager = AIPluginManager()
        assert manager.pluginCount == 0

    def test_register_plugin(self, qapp):
        """Should register a plugin."""
        manager = AIPluginManager()
        plugin = TissueClassifier()
        manager.register_plugin(plugin)

        assert manager.pluginCount == 1

    def test_get_plugin_list(self, qapp):
        """Should return list of registered plugins."""
        manager = AIPluginManager()
        manager.register_plugin(TissueClassifier())
        manager.register_plugin(ColorHistogramAnalyzer())

        plugins = manager.getPluginList()
        assert len(plugins) == 2

        names = {p["name"] for p in plugins}
        assert "Tissue Classifier (Demo)" in names
        assert "Color Histogram" in names

    def test_get_plugin_info(self, qapp):
        """Should return info for specific plugin."""
        manager = AIPluginManager()
        manager.register_plugin(TissueClassifier())

        info = manager.getPluginInfo("Tissue Classifier (Demo)")
        assert info is not None
        assert info["name"] == "Tissue Classifier (Demo)"
        assert info["inputType"] == "region"
        assert info["outputType"] == "classification"

    def test_get_nonexistent_plugin(self, qapp):
        """Should return None for unknown plugin."""
        manager = AIPluginManager()
        info = manager.getPluginInfo("Unknown Plugin")
        assert info is None

    def test_unregister_plugin(self, qapp):
        """Should unregister a plugin."""
        manager = AIPluginManager()
        manager.register_plugin(TissueClassifier())
        assert manager.pluginCount == 1

        manager.unregister_plugin("Tissue Classifier (Demo)")
        assert manager.pluginCount == 0

    def test_load_unload_model(self, qapp):
        """Should track model loading state."""
        manager = AIPluginManager()
        manager.register_plugin(TissueClassifier())

        # Initially not loaded
        info = manager.getPluginInfo("Tissue Classifier (Demo)")
        assert not info["isLoaded"]

        # Load model
        manager.loadModel("Tissue Classifier (Demo)")
        info = manager.getPluginInfo("Tissue Classifier (Demo)")
        assert info["isLoaded"]

        # Unload model
        manager.unloadModel("Tissue Classifier (Demo)")
        info = manager.getPluginInfo("Tissue Classifier (Demo)")
        assert not info["isLoaded"]

    def test_discover_builtin_plugins(self, qapp):
        """Should discover built-in plugins."""
        manager = AIPluginManager()
        manager.discoverPlugins()

        # Should have at least the example plugins
        assert manager.pluginCount >= 2


class TestCustomPlugin:
    """Tests for creating custom plugins."""

    def test_create_custom_plugin(self, sample_tissue_array: np.ndarray):
        """Should be able to create and use custom plugin."""

        class CustomPlugin(AIPlugin):
            @property
            def metadata(self) -> PluginMetadata:
                return PluginMetadata(
                    name="Custom Test Plugin",
                    description="A custom test plugin",
                    labels=["A", "B"],
                )

            def process(self, image: np.ndarray, context: dict) -> PluginResult:
                return PluginResult(
                    success=True,
                    output_type=OutputType.CLASSIFICATION,
                    data={"label": "A", "confidence": 1.0},
                )

        plugin = CustomPlugin()
        assert plugin.name == "Custom Test Plugin"

        result = plugin.process(sample_tissue_array, {})
        assert result.success
        assert result.data["label"] == "A"
