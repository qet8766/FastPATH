"""Plugin abstract base classes.

No Qt imports — pure Python ABCs.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable

from .types import PluginInput, PluginMetadata, PluginOutput

ProgressCallback = Callable[[int], None]


class Plugin(ABC):
    """Abstract base class for FastPATH plugins.

    Subclass this to create plugins that work with preprocessed tile pyramids.
    """

    @property
    @abstractmethod
    def metadata(self) -> PluginMetadata:
        """Return plugin metadata."""
        ...

    @abstractmethod
    def process(
        self,
        plugin_input: PluginInput,
        progress_callback: ProgressCallback | None = None,
    ) -> PluginOutput:
        """Process input and return results.

        Args:
            plugin_input: Bundle containing SlideContext, optional region/image/annotations.
            progress_callback: Optional callable accepting an int (0-100) for progress updates.

        Returns:
            PluginOutput with the analysis results.
        """
        ...

    def validate_input(self, plugin_input: PluginInput) -> tuple[bool, str]:
        """Validate input before processing.

        Args:
            plugin_input: The input to validate.

        Returns:
            Tuple of (is_valid, error_message).
        """
        if plugin_input.image is not None:
            img = plugin_input.image
            if img.ndim != 3:
                return False, f"Expected 3D array, got {img.ndim}D"
            if img.shape[2] != 3:
                return False, f"Expected 3 channels (RGB), got {img.shape[2]}"

            expected_size = self.metadata.input_size
            if expected_size is not None:
                h, w = img.shape[:2]
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


class ModelPlugin(Plugin):
    """Plugin that manages a loadable model.

    Adds ``load_model()`` / ``unload_model()`` lifecycle.
    """

    _model_loaded: bool = False

    def load_model(self) -> None:
        """Load the model into memory.

        Override to load weights, initialize frameworks, etc.
        """
        self._model_loaded = True

    def unload_model(self) -> None:
        """Unload the model and free resources."""
        self._model_loaded = False

    @property
    def is_loaded(self) -> bool:
        """Whether the model is currently loaded."""
        return self._model_loaded
