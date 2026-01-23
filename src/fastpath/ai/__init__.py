"""AI plugin system for FastPATH."""

from .base import AIPlugin, PluginMetadata, PluginResult, InputType, OutputType
from .manager import AIPluginManager

__all__ = [
    "AIPlugin",
    "PluginMetadata",
    "PluginResult",
    "InputType",
    "OutputType",
    "AIPluginManager",
]
