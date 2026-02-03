"""NuLite plugin package.

Imports are guarded to avoid hard dependency on torch/CUDA at startup.
"""

__all__: list[str] = []

try:
    import torch

    if torch.cuda.is_available():
        try:
            from .plugin import NuLitePlugin

            __all__ = ["NuLitePlugin"]
        except Exception:
            __all__ = []
except Exception:
    __all__ = []
