"""Tissue detector example plugin — WHOLE_SLIDE -> TILE_SCORES."""

from __future__ import annotations

import numpy as np

from fastpath.plugins.base import Plugin, ProgressCallback
from fastpath.plugins.types import (
    InputType,
    OutputType,
    PluginInput,
    PluginMetadata,
    PluginOutput,
    ResolutionSpec,
)


class TissueDetector(Plugin):
    """Detects tissue regions across the whole slide.

    Uses ``iter_tiles()`` at ~8.0 MPP (low res) to compute a brightness-based
    tissue score per tile. Emits ``tile_scores`` and a ``measurements`` dict
    with the overall tissue fraction.
    """

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="Tissue Detector",
            description="Detects tissue regions across the whole slide using brightness analysis.",
            version="1.0.0",
            author="FastPATH",
            input_type=InputType.WHOLE_SLIDE,
            output_types=[OutputType.TILE_SCORES, OutputType.MEASUREMENTS],
            resolution=ResolutionSpec(working_mpp=8.0),
            wants_image=False,
        )

    def process(
        self,
        plugin_input: PluginInput,
        progress_callback: ProgressCallback | None = None,
    ) -> PluginOutput:
        slide = plugin_input.slide

        # Pick best level for ~8.0 MPP
        level = slide.level_for_mpp(self.metadata.resolution.working_mpp)
        info = slide.get_level_info(level)

        rows = info.rows
        cols = info.cols
        scores = np.zeros((rows, cols), dtype=np.float32)
        total_tiles = rows * cols
        processed = 0

        for tile_info in slide.iter_tiles(level):
            r, c = tile_info.row, tile_info.col
            img = tile_info.image.astype(np.float32) / 255.0
            brightness = float(img.mean())
            # Tissue score: darker = more tissue (invert brightness)
            scores[r, c] = max(0.0, 1.0 - brightness)
            processed += 1
            if progress_callback is not None and total_tiles > 0:
                progress_callback(int(processed / total_tiles * 100))

        tissue_threshold = 0.15
        tissue_tiles = int((scores > tissue_threshold).sum())
        tissue_fraction = tissue_tiles / max(total_tiles, 1)

        return PluginOutput(
            success=True,
            message=f"Detected tissue in {tissue_tiles}/{total_tiles} tiles ({tissue_fraction:.1%})",
            tile_scores=scores,
            tile_level=level,
            measurements={
                "tissue_tiles": tissue_tiles,
                "total_tiles": total_tiles,
                "tissue_fraction": tissue_fraction,
            },
        )
