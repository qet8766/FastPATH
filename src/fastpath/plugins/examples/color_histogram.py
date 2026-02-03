"""Color histogram analyzer example plugin — REGION -> MEASUREMENTS."""

from __future__ import annotations

import numpy as np

from fastpath.plugins.base import Plugin, ProgressCallback
from fastpath.plugins.types import (
    InputType,
    OutputType,
    PluginInput,
    PluginMetadata,
    PluginOutput,
)


class ColorHistogramAnalyzer(Plugin):
    """Analyzes RGB color distribution in a region."""

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="Color Histogram",
            description="Analyzes RGB color distribution in the selected region.",
            version="1.0.0",
            author="FastPATH",
            input_type=InputType.REGION,
            output_types=[OutputType.MEASUREMENTS],
        )

    def process(
        self,
        plugin_input: PluginInput,
        progress_callback: ProgressCallback | None = None,
    ) -> PluginOutput:
        image = plugin_input.image
        if image is None:
            return PluginOutput(success=False, message="No image provided")

        channels: dict[str, dict] = {}
        for i, channel in enumerate(["red", "green", "blue"]):
            ch = image[:, :, i]
            channels[channel] = {
                "mean": float(ch.mean()),
                "std": float(ch.std()),
                "min": int(ch.min()),
                "max": int(ch.max()),
                "median": float(np.median(ch)),
            }

        gray = np.mean(image, axis=2)

        if progress_callback is not None:
            progress_callback(100)

        return PluginOutput(
            success=True,
            message="Color histogram analysis complete",
            measurements={
                "channels": channels,
                "grayscale": {
                    "mean": float(gray.mean()),
                    "std": float(gray.std()),
                },
                "region_size": {
                    "width": image.shape[1],
                    "height": image.shape[0],
                    "pixels": image.shape[0] * image.shape[1],
                },
            },
        )
