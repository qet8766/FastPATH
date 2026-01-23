"""Abstract base class for AI plugins."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np


class InputType(str, Enum):
    """Types of input an AI plugin can accept.

    Determines how the plugin receives image data from the viewer.
    """

    TILE = "tile"
    """Single tile at native resolution (typically 512x512 pixels).
    Use for tile-level analysis like tissue detection or quality control."""

    REGION = "region"
    """User-selected rectangular region at current zoom level.
    Use for interactive analysis where the user draws a bounding box."""

    WHOLE_SLIDE = "whole_slide"
    """Entire slide processed tile-by-tile internally.
    Use for whole-slide analysis like tumor detection or cell counting."""


class OutputType(str, Enum):
    """Types of output an AI plugin can produce.

    Determines how results are displayed in the viewer.
    """

    CLASSIFICATION = "classification"
    """Class label with confidence score (e.g., {"label": "Tumor", "confidence": 0.95}).
    Displayed as text overlay on the selected region."""

    MASK = "mask"
    """Binary or multi-class segmentation mask as numpy array.
    Overlaid semi-transparently on the slide."""

    ANNOTATIONS = "annotations"
    """Vector annotations (points, polygons, bounding boxes).
    Added to the annotation layer for editing and export."""

    HEATMAP = "heatmap"
    """Probability heatmap as 2D numpy array (values 0-1).
    Rendered as color-mapped overlay on the slide."""


@dataclass
class PluginMetadata:
    """Metadata describing an AI plugin."""

    name: str
    description: str
    version: str = "1.0.0"
    author: str = ""
    input_type: InputType = InputType.REGION
    output_type: OutputType = OutputType.CLASSIFICATION
    input_size: tuple[int, int] | None = None  # Required input dimensions
    labels: list[str] = field(default_factory=list)  # Class labels for classification


@dataclass
class PluginResult:
    """Result from an AI plugin execution."""

    success: bool
    output_type: OutputType
    data: Any  # Type depends on output_type
    message: str = ""
    processing_time: float = 0.0  # Seconds

    def to_dict(self) -> dict:
        """Convert to dictionary for QML."""
        result = {
            "success": self.success,
            "outputType": self.output_type.value,
            "message": self.message,
            "processingTime": self.processing_time,
        }

        if self.output_type == OutputType.CLASSIFICATION:
            result["classification"] = self.data
        elif self.output_type == OutputType.MASK:
            # Mask is numpy array, convert to list for JSON
            if isinstance(self.data, np.ndarray):
                result["mask"] = self.data.tolist()
            else:
                result["mask"] = self.data
        elif self.output_type == OutputType.ANNOTATIONS:
            result["annotations"] = self.data
        elif self.output_type == OutputType.HEATMAP:
            if isinstance(self.data, np.ndarray):
                result["heatmap"] = self.data.tolist()
            else:
                result["heatmap"] = self.data

        return result


class AIPlugin(ABC):
    """Abstract base class for AI plugins.

    Subclass this to create custom AI analysis plugins for FastPATH.

    Example:
        class MyClassifier(AIPlugin):
            @property
            def metadata(self) -> PluginMetadata:
                return PluginMetadata(
                    name="My Classifier",
                    description="Classifies tissue regions",
                    input_type=InputType.REGION,
                    output_type=OutputType.CLASSIFICATION,
                    labels=["Normal", "Tumor", "Stroma"],
                )

            def process(self, image: np.ndarray, context: dict) -> PluginResult:
                # Your inference code here
                return PluginResult(
                    success=True,
                    output_type=OutputType.CLASSIFICATION,
                    data={"label": "Tumor", "confidence": 0.95},
                )
    """

    @property
    @abstractmethod
    def metadata(self) -> PluginMetadata:
        """Return plugin metadata."""
        ...

    @abstractmethod
    def process(self, image: np.ndarray, context: dict) -> PluginResult:
        """Process an image and return results.

        Args:
            image: Input image as numpy array (H, W, C) in RGB format
            context: Additional context including:
                - 'mpp': Microns per pixel at the input resolution
                - 'region': (x, y, width, height) in slide coordinates
                - 'slide_path': Path to the .fastpath directory

        Returns:
            PluginResult with the analysis output
        """
        ...

    def load_model(self) -> None:
        """Load the model into memory.

        Override this to load weights, initialize frameworks, etc.
        Called when the plugin is first used.
        """
        pass

    def unload_model(self) -> None:
        """Unload the model from memory.

        Override this to free resources when the plugin is no longer needed.
        """
        pass

    def validate_input(self, image: np.ndarray) -> tuple[bool, str]:
        """Validate input image dimensions and format.

        Args:
            image: Input image array

        Returns:
            Tuple of (is_valid, error_message)
        """
        if image is None:
            return False, "Image is None"

        if image.ndim != 3:
            return False, f"Expected 3D array, got {image.ndim}D"

        if image.shape[2] != 3:
            return False, f"Expected 3 channels (RGB), got {image.shape[2]}"

        expected_size = self.metadata.input_size
        if expected_size is not None:
            h, w = image.shape[:2]
            if (h, w) != expected_size:
                return False, f"Expected size {expected_size}, got ({h}, {w})"

        return True, ""

    @property
    def name(self) -> str:
        """Convenience accessor for plugin name."""
        return self.metadata.name

    @property
    def description(self) -> str:
        """Convenience accessor for plugin description."""
        return self.metadata.description

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}: {self.name}>"
