"""FastPATH plugin system.

Pyramid-native plugin framework — plugins work directly with preprocessed tiles.
"""

from .base import ModelPlugin, Plugin
from .context import SlideContext
from .controller import PluginController
from .types import (
    InputType,
    OutputType,
    PluginInput,
    PluginMetadata,
    PluginOutput,
    RegionOfInterest,
    ResolutionSpec,
)

__all__ = [
    "InputType",
    "ModelPlugin",
    "OutputType",
    "Plugin",
    "PluginController",
    "PluginInput",
    "PluginMetadata",
    "PluginOutput",
    "RegionOfInterest",
    "ResolutionSpec",
    "SlideContext",
]
