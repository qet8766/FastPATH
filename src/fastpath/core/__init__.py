"""Core managers for FastPATH viewer."""

from .slide import SlideManager
from .annotations import AnnotationManager, Annotation, AnnotationType
from .project import ProjectManager, ProjectData

__all__ = [
    "SlideManager",
    "AnnotationManager",
    "Annotation",
    "AnnotationType",
    "ProjectManager",
    "ProjectData",
]
