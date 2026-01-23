"""Example AI plugin demonstrating the plugin interface."""

from __future__ import annotations

import numpy as np

from fastpath.ai.base import (
    AIPlugin,
    InputType,
    OutputType,
    PluginMetadata,
    PluginResult,
)


class TissueClassifier(AIPlugin):
    """Example classifier that analyzes tissue color statistics.

    This is a simple demonstration plugin that doesn't use a real ML model.
    It classifies regions based on color histogram analysis.
    """

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="Tissue Classifier (Demo)",
            description="Classifies tissue regions based on color analysis. "
            "This is a demonstration plugin without a real ML model.",
            version="1.0.0",
            author="FastPATH",
            input_type=InputType.REGION,
            output_type=OutputType.CLASSIFICATION,
            labels=["Background", "Tissue", "Dense Tissue", "Artifact"],
        )

    def process(self, image: np.ndarray, context: dict) -> PluginResult:
        """Classify the region based on color statistics."""
        # Convert to float for analysis
        img = image.astype(np.float32) / 255.0

        # Calculate statistics
        mean_rgb = img.mean(axis=(0, 1))
        std_rgb = img.std(axis=(0, 1))

        # Simple heuristic classification
        brightness = mean_rgb.mean()
        saturation = std_rgb.mean()

        # Color analysis
        r, g, b = mean_rgb

        # Classification logic
        if brightness > 0.9:
            label = "Background"
            confidence = min(0.95, brightness)
        elif brightness < 0.3:
            label = "Artifact"
            confidence = 0.7
        elif r > b and saturation > 0.1:
            # Pinkish = likely tissue
            if saturation > 0.15:
                label = "Dense Tissue"
                confidence = 0.8
            else:
                label = "Tissue"
                confidence = 0.75
        else:
            label = "Tissue"
            confidence = 0.6

        return PluginResult(
            success=True,
            output_type=OutputType.CLASSIFICATION,
            data={
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
                    "brightness": float(brightness),
                    "saturation": float(saturation),
                },
            },
            message=f"Classified as {label} with {confidence:.1%} confidence",
        )


class ColorHistogramAnalyzer(AIPlugin):
    """Analyzes color distribution in a region."""

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="Color Histogram",
            description="Analyzes RGB color distribution in the selected region.",
            version="1.0.0",
            author="FastPATH",
            input_type=InputType.REGION,
            output_type=OutputType.CLASSIFICATION,
        )

    def process(self, image: np.ndarray, context: dict) -> PluginResult:
        """Compute color histogram statistics."""
        # Compute histograms for each channel
        histograms = {}
        for i, channel in enumerate(["red", "green", "blue"]):
            hist, _ = np.histogram(image[:, :, i], bins=256, range=(0, 256))
            histograms[channel] = {
                "mean": float(image[:, :, i].mean()),
                "std": float(image[:, :, i].std()),
                "min": int(image[:, :, i].min()),
                "max": int(image[:, :, i].max()),
                "median": float(np.median(image[:, :, i])),
            }

        # Overall statistics
        gray = np.mean(image, axis=2)

        return PluginResult(
            success=True,
            output_type=OutputType.CLASSIFICATION,
            data={
                "label": "Analysis Complete",
                "confidence": 1.0,
                "channels": histograms,
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
            message="Color histogram analysis complete",
        )
