"""Foundation types for the plugin system.

All dataclasses and enums — no Qt dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from fastpath.plugins.context import SlideContext


class InputType(str, Enum):
    """Types of input a plugin can accept."""

    TILE = "tile"
    REGION = "region"
    WHOLE_SLIDE = "whole_slide"
    ANNOTATIONS = "annotations"


class OutputType(str, Enum):
    """Types of output a plugin can produce."""

    CLASSIFICATION = "classification"
    MASK = "mask"
    ANNOTATIONS = "annotations"
    HEATMAP = "heatmap"
    IMAGE = "image"
    MEASUREMENTS = "measurements"
    TILE_SCORES = "tile_scores"
    TILE_LABELS = "tile_labels"


@dataclass
class ResolutionSpec:
    """Resolution requirements for a plugin.

    Attributes:
        working_mpp: MPP the plugin operates at (default 0.5 = 20x).
        context_mpp: Optional coarser MPP for context tiles.
    """

    working_mpp: float = 0.5
    context_mpp: float | None = None

    @property
    def needs_original_wsi(self) -> bool:
        """True if any requested MPP is finer than the pyramid's 0.5 MPP."""
        if self.working_mpp < 0.5:
            return True
        if self.context_mpp is not None and self.context_mpp < 0.5:
            return True
        return False


@dataclass
class RegionOfInterest:
    """A rectangular region in slide coordinates."""

    x: float
    y: float
    w: float
    h: float


@dataclass
class PluginMetadata:
    """Metadata describing a plugin."""

    name: str
    description: str
    version: str = "1.0.0"
    author: str = ""
    input_type: InputType = InputType.REGION
    output_types: list[OutputType] = field(default_factory=lambda: [OutputType.CLASSIFICATION])
    resolution: ResolutionSpec = field(default_factory=ResolutionSpec)
    input_size: tuple[int, int] | None = None
    labels: list[str] = field(default_factory=list)
    wants_image: bool = True


@dataclass
class PluginInput:
    """Input bundle passed to a plugin's process() method."""

    slide: SlideContext
    region: RegionOfInterest | None = None
    image: np.ndarray | None = None
    image_level: int | None = None
    annotations: list[dict] | None = None


@dataclass
class PluginOutput:
    """Output from a plugin execution.

    Typed fields for each output kind. Raster arrays (mask, heatmap, image)
    are NOT serialized to JSON — ``to_dict()`` signals their presence via
    boolean flags so QML's ``formatResult()`` can decide how to render.
    """

    success: bool
    message: str = ""
    processing_time: float = 0.0

    # Classification
    classification: dict | None = None

    # Vector annotations (GeoJSON features in slide coords)
    annotations: list[dict] | None = None

    # Raster outputs (at a specific pyramid level)
    mask: np.ndarray | None = None
    mask_level: int | None = None
    heatmap: np.ndarray | None = None
    heatmap_level: int | None = None
    image: np.ndarray | None = None

    # Measurements
    measurements: dict | None = None

    # Whole-slide grid outputs
    tile_scores: np.ndarray | None = None
    tile_labels: np.ndarray | None = None
    tile_level: int | None = None

    def to_dict(self) -> dict:
        """Convert to a JSON-safe dict for QML.

        Numpy arrays are NOT serialized — their presence is signaled via
        boolean flags (``hasMask``, ``hasHeatmap``, etc.).
        """
        result: dict[str, Any] = {
            "success": self.success,
            "message": self.message,
            "processingTime": self.processing_time,
        }

        # Determine primary output type for backward compat
        if self.classification is not None:
            result["outputType"] = OutputType.CLASSIFICATION.value
            result["classification"] = self.classification
        elif self.tile_scores is not None:
            result["outputType"] = OutputType.TILE_SCORES.value
            result["tileScores"] = self.tile_scores.tolist()
            if self.tile_labels is not None:
                result["tileLabels"] = self.tile_labels.tolist()
            if self.tile_level is not None:
                result["tileLevel"] = self.tile_level
        elif self.measurements is not None:
            result["outputType"] = OutputType.MEASUREMENTS.value
            result["measurements"] = self.measurements
        elif self.annotations is not None:
            result["outputType"] = OutputType.ANNOTATIONS.value
            result["annotations"] = self.annotations
        elif self.mask is not None:
            result["outputType"] = OutputType.MASK.value
        elif self.heatmap is not None:
            result["outputType"] = OutputType.HEATMAP.value
        elif self.image is not None:
            result["outputType"] = OutputType.IMAGE.value
        else:
            result["outputType"] = OutputType.CLASSIFICATION.value

        # Boolean presence flags for raster data (not serialized)
        result["hasMask"] = self.mask is not None
        result["hasHeatmap"] = self.heatmap is not None
        result["hasImage"] = self.image is not None
        result["hasTileScores"] = self.tile_scores is not None

        # Include measurements alongside other output types
        if self.measurements is not None and "measurements" not in result:
            result["measurements"] = self.measurements

        return result
