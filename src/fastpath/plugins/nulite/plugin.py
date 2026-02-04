"""NuLite nucleus segmentation plugin."""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Iterable, TYPE_CHECKING

import numpy as np

from fastpath.plugins.base import ModelPlugin, ProgressCallback
from fastpath.plugins.types import (
    InputType,
    OutputType,
    PluginInput,
    PluginMetadata,
    PluginOutput,
    ResolutionSpec,
)

if TYPE_CHECKING:
    import torch
    from .model import NuLite


def _unflatten_dict(data: dict, sep: str = ".") -> dict:
    output: dict = {}
    for key, value in data.items():
        keys = key.split(sep)
        cursor = output
        for part in keys[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[keys[-1]] = value
    return output


class NuLitePlugin(ModelPlugin):
    """NuLite nucleus segmentation using original WSI pixels."""

    PATCH_SIZE = 1024
    PATCH_OVERLAP = 64
    STRIDE = PATCH_SIZE - PATCH_OVERLAP
    TARGET_MPP = 0.25

    CELL_TYPES = {
        1: ("Neoplastic", "#ff0000"),
        2: ("Inflammatory", "#22dd4d"),
        3: ("Connective", "#235cec"),
        4: ("Dead", "#feff00"),
        5: ("Epithelial", "#ff9f44"),
    }

    def __init__(self) -> None:
        super().__init__()
        self._model: "NuLite | None" = None
        self._torch: "torch | None" = None
        self._device: "torch.device | None" = None
        self._mean: "torch.Tensor | None" = None
        self._std: "torch.Tensor | None" = None
        self._weights_path: Path | None = None

    @property
    def metadata(self) -> PluginMetadata:
        return PluginMetadata(
            name="NuLite",
            description="NuLite nucleus segmentation (WSI inference)",
            version="1.0.0",
            author="NuLite",
            input_type=InputType.REGION,
            output_types=[OutputType.ANNOTATIONS, OutputType.MEASUREMENTS],
            labels=[label for label, _color in self.CELL_TYPES.values()],
            resolution=ResolutionSpec(working_mpp=self.TARGET_MPP),
            wants_image=False,
        )

    # ------------------------------------------------------------------
    # Model lifecycle
    # ------------------------------------------------------------------

    def _resolve_weights_path(self) -> Path:
        if self._weights_path is not None:
            return self._weights_path

        env_path = os.environ.get("FASTPATH_NULITE_WEIGHTS")
        if env_path:
            self._weights_path = Path(env_path)
        else:
            self._weights_path = (
                Path(__file__).parent / "weights" / "NuLite-T-Weights.pth"
            )
        return self._weights_path

    def load_model(self) -> None:
        torch = self._import_torch()
        if not torch.cuda.is_available():
            raise RuntimeError("CUDA is required for NuLite inference.")

        weights_path = self._resolve_weights_path()
        if not weights_path.exists():
            raise FileNotFoundError(
                "NuLite weights not found. Copy NuLite-T-Weights.pth to "
                f"{weights_path} or set FASTPATH_NULITE_WEIGHTS."
            )

        checkpoint = torch.load(weights_path, map_location="cpu", weights_only=False)
        config = _unflatten_dict(checkpoint.get("config", {}), ".")
        backbone = config.get("model", {}).get("backbone", "fastvit_t8")
        normalize = config.get("transformations", {}).get("normalize", {})
        mean = normalize.get("mean", (0.5, 0.5, 0.5))
        std = normalize.get("std", (0.5, 0.5, 0.5))

        from .model import NuLite

        model = NuLite(
            num_nuclei_classes=6,
            num_tissue_classes=19,
            vit_structure=backbone,
        )
        model.load_state_dict(checkpoint["model_state_dict"])
        model.reparameterize_encoder()
        model.eval()

        self._torch = torch
        self._device = torch.device("cuda")
        model.to(self._device)

        self._mean = torch.tensor(mean, dtype=torch.float32, device=self._device).view(
            1, 3, 1, 1
        )
        self._std = torch.tensor(std, dtype=torch.float32, device=self._device).view(
            1, 3, 1, 1
        )
        self._model = model
        self._model_loaded = True

    def unload_model(self) -> None:
        if self._model is not None:
            del self._model
            self._model = None
        torch = self._torch
        self._torch = None
        self._device = None
        self._mean = None
        self._std = None
        self._model_loaded = False
        if torch is not None and torch.cuda.is_available():
            torch.cuda.empty_cache()

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate_input(self, plugin_input: PluginInput) -> tuple[bool, str]:
        if plugin_input.region is None:
            return False, "NuLite requires a selected region (ROI)."
        if plugin_input.slide.source_mpp > 0.5:
            return False, "NuLite requires source_mpp <= 0.5 (20x or higher)."
        return True, ""

    # ------------------------------------------------------------------
    # Processing
    # ------------------------------------------------------------------

    def process(
        self,
        plugin_input: PluginInput,
        progress_callback: ProgressCallback | None = None,
    ) -> PluginOutput:
        if self._model is None or self._device is None:
            raise RuntimeError("NuLite model is not loaded")
        torch = self._require_torch()

        slide = plugin_input.slide
        region = plugin_input.region
        if region is None:
            return PluginOutput(success=False, message="No region provided")

        scale = slide.slide_to_wsi_scale
        roi_wsi_x = int(round(region.x * scale))
        roi_wsi_y = int(round(region.y * scale))
        roi_wsi_w = int(round(region.w * scale))
        roi_wsi_h = int(round(region.h * scale))

        grid_cols = self._num_patches(roi_wsi_w)
        grid_rows = self._num_patches(roi_wsi_h)

        patch_origins = [
            (roi_wsi_x + col * self.STRIDE, roi_wsi_y + row * self.STRIDE)
            for row in range(grid_rows)
            for col in range(grid_cols)
        ]

        cells: list[dict] = []
        total_patches = len(patch_origins)
        processed = 0
        batch_size = 8

        with torch.inference_mode():
            for batch_start in range(0, total_patches, batch_size):
                batch_origins = patch_origins[batch_start: batch_start + batch_size]
                tensors = []
                for px, py in batch_origins:
                    patch = slide.get_original_region(
                        int(px), int(py), self.PATCH_SIZE, self.PATCH_SIZE
                    )
                    tensors.append(self._prepare_patch(patch))

                batch = torch.stack(tensors).to(self._device, non_blocking=True)
                batch = batch.float() / 255.0
                if self._mean is not None and self._std is not None:
                    batch = (batch - self._mean) / self._std

                with torch.autocast(device_type="cuda", dtype=torch.float16):
                    predictions = self._model(batch, retrieve_tokens=False)

                nuclei_binary_map = torch.softmax(
                    predictions["nuclei_binary_map"], dim=1
                )
                nuclei_type_map = torch.softmax(
                    predictions["nuclei_type_map"], dim=1
                )

                _instance_map, instance_types = self._model.calculate_instance_map(
                    {
                        "nuclei_binary_map": nuclei_binary_map,
                        "nuclei_type_map": nuclei_type_map,
                        "hv_map": predictions["hv_map"],
                    },
                    magnification=self._magnification_from_mpp(slide.source_mpp),
                )

                for (px, py), patch_cells in zip(batch_origins, instance_types):
                    offset = np.array([px, py], dtype=np.float32)
                    for cell in patch_cells.values():
                        if cell.get("type", 0) == 0:
                            continue
                        contour = np.asarray(cell["contour"], dtype=np.float32)
                        if contour.shape[0] < 3:
                            continue
                        centroid = np.asarray(cell["centroid"], dtype=np.float32)
                        cells.append(
                            {
                                "contour": contour + offset,
                                "centroid": centroid + offset,
                                "type": int(cell.get("type", 0)),
                                "type_prob": float(cell.get("type_prob", 0.0)),
                                "patch_origin": (float(px), float(py)),
                            }
                        )

                processed += len(batch_origins)
                if progress_callback is not None and total_patches > 0:
                    progress_callback(int(processed / total_patches * 100))

        kept_cells = self._deduplicate_cells(
            cells,
            roi_wsi_x,
            roi_wsi_y,
            roi_wsi_w,
            roi_wsi_h,
        )

        annotations: list[dict] = []
        counts: dict[str, int] = {}
        for cell in kept_cells:
            label, color = self.CELL_TYPES.get(
                cell["type"], ("Unknown", "#808080")
            )
            contour = cell["contour"] / scale
            coordinates = contour.tolist()
            if len(coordinates) < 3:
                continue
            annotations.append(
                {
                    "type": "polygon",
                    "coordinates": coordinates,
                    "label": label,
                    "color": color,
                }
            )
            counts[label] = counts.get(label, 0) + 1

        return PluginOutput(
            success=True,
            message=f"Detected {len(annotations)} nuclei",
            annotations=annotations,
            measurements={
                "counts_by_type": counts,
                "total_cells": len(annotations),
            },
        )

    def _prepare_patch(self, patch: np.ndarray):
        torch = self._require_torch()
        if patch.ndim != 3 or patch.shape[2] != 3:
            raise ValueError("Expected RGB patch array")
        return torch.from_numpy(patch).permute(2, 0, 1).contiguous()

    @classmethod
    def _num_patches(cls, length: int) -> int:
        if length <= cls.PATCH_SIZE:
            return 1
        return int(math.ceil((length - cls.PATCH_SIZE) / cls.STRIDE)) + 1

    @classmethod
    def _magnification_from_mpp(cls, source_mpp: float) -> int:
        if source_mpp <= 0:
            return 40
        magnification = int(round(10.0 / source_mpp))
        return 40 if magnification >= 30 else 20

    def _deduplicate_cells(
        self,
        cells: Iterable[dict],
        roi_x: int,
        roi_y: int,
        roi_w: int,
        roi_h: int,
    ) -> list[dict]:
        margin = self.PATCH_OVERLAP // 2
        kept: list[dict] = []
        roi_x2 = roi_x + roi_w
        roi_y2 = roi_y + roi_h

        for cell in cells:
            cx, cy = cell["centroid"]
            px, py = cell["patch_origin"]
            core_x1 = px + self.PATCH_SIZE - margin
            core_y1 = py + self.PATCH_SIZE - margin
            core_x0 = px + margin
            core_y0 = py + margin

            if px <= roi_x:
                core_x0 = px
            if py <= roi_y:
                core_y0 = py
            if px + self.STRIDE >= roi_x2:
                core_x1 = px + self.PATCH_SIZE
            if py + self.STRIDE >= roi_y2:
                core_y1 = py + self.PATCH_SIZE

            if core_x0 <= cx < core_x1 and core_y0 <= cy < core_y1:
                kept.append(cell)

        return kept

    def _import_torch(self):
        try:
            import torch  # type: ignore
        except Exception as exc:
            raise RuntimeError("PyTorch is required for NuLite inference.") from exc
        return torch

    def _require_torch(self):
        if self._torch is None:
            self._torch = self._import_torch()
        return self._torch
