"""Tissue classifier example plugin — REGION -> CLASSIFICATION."""

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


class TissueClassifier(Plugin):
    """Classifies tissue regions based on color statistics.

    A demonstration plugin that doesn't use a real ML model.
    """

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="Tissue Classifier (Demo)",
            description=(
                "Classifies tissue regions based on color analysis. "
                "This is a demonstration plugin without a real ML model."
            ),
            version="1.0.0",
            author="FastPATH",
            input_type=InputType.REGION,
            output_types=[OutputType.CLASSIFICATION],
            labels=["Background", "Tissue", "Dense Tissue", "Artifact"],
        )

    def process(
        self,
        plugin_input: PluginInput,
        progress_callback: ProgressCallback | None = None,
    ) -> PluginOutput:
        image = plugin_input.image
        if image is None:
            return PluginOutput(success=False, message="No image provided")

        img = image.astype(np.float32) / 255.0

        mean_rgb = img.mean(axis=(0, 1))
        std_rgb = img.std(axis=(0, 1))

        brightness = float(mean_rgb.mean())
        saturation = float(std_rgb.mean())
        r, g, b = mean_rgb

        if brightness > 0.9:
            label = "Background"
            confidence = min(0.95, brightness)
        elif brightness < 0.3:
            label = "Artifact"
            confidence = 0.7
        elif r > b and saturation > 0.1:
            if saturation > 0.15:
                label = "Dense Tissue"
                confidence = 0.8
            else:
                label = "Tissue"
                confidence = 0.75
        else:
            label = "Tissue"
            confidence = 0.6

        if progress_callback is not None:
            progress_callback(100)

        return PluginOutput(
            success=True,
            message=f"Classified as {label} with {confidence:.1%} confidence",
            classification={
                "label": label,
                "confidence": float(confidence),
                "probabilities": {
                    "Background": float(1.0 - saturation) if brightness > 0.8 else 0.1,
                    "Tissue": 0.5 if label == "Tissue" else 0.2,
                    "Dense Tissue": 0.3 if label == "Dense Tissue" else 0.1,
                    "Artifact": 0.1 if brightness < 0.4 else 0.05,
                },
                "statistics": {
                    "mean_rgb": mean_rgb.tolist(),
                    "std_rgb": std_rgb.tolist(),
                    "brightness": brightness,
                    "saturation": saturation,
                },
            },
        )
