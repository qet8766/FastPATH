"""Built-in example plugins for FastPATH."""

from .tissue_classifier import TissueClassifier
from .color_histogram import ColorHistogramAnalyzer
from .tissue_detector import TissueDetector

__all__ = ["TissueClassifier", "ColorHistogramAnalyzer", "TissueDetector"]
