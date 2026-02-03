"""Tests for PluginController annotation routing."""

from __future__ import annotations

from unittest.mock import MagicMock

from fastpath.plugins.controller import PluginController
from fastpath.plugins.types import PluginOutput


def test_processing_finished_routes_annotations(qapp):
    controller = PluginController()
    annotation_manager = MagicMock()
    controller.set_annotation_manager(annotation_manager)
    controller._current_plugin_name = "NuLite"

    output = PluginOutput(
        success=True,
        annotations=[
            {
                "type": "polygon",
                "coordinates": [[0, 0], [1, 0], [1, 1]],
                "label": "Test",
                "color": "#ffffff",
            }
        ],
    )

    results = []
    controller.processingFinished.connect(results.append)

    controller._on_finished(output)

    annotation_manager.addAnnotationsBatch.assert_called_once()
    assert results
    assert results[0]["annotationsRouted"] is True
    assert results[0]["annotationGroup"] == "NuLite"
    assert results[0]["annotationCount"] == 1
