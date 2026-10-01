"""Check clamped height-field geometry without creating a GUI window.

Requirements: numpy, opencv-python, PySide6, pyvista, pyvistaqt, vtk.
Usage: unittest discovery in this directory.
"""

import importlib
import importlib.util
import os
from pathlib import Path
import sys
import unittest

import numpy as np
from fixture_store import preserve_document
import pyvista as pv

os.environ["QT_API"] = "pyside6"
PACKAGE = Path(__file__).resolve().parents[1]
if "personal_npy_viewer" not in sys.modules:
    spec = importlib.util.spec_from_file_location("personal_npy_viewer", PACKAGE / "__init__.py",
                                                submodule_search_locations=[str(PACKAGE)])
    assert spec is not None and spec.loader is not None
    package = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = package
    spec.loader.exec_module(package)
model = importlib.import_module("personal_npy_viewer.data_model")
surface = importlib.import_module("personal_npy_viewer.surface_view")


class SurfaceClippingTests(unittest.TestCase):
    """Threshold caps preserve footprint and strictly bound displayed heights."""

    def test_caps_cover_exact_threshold_regions(self) -> None:
        """A ramp crossing both limits splits at the interpolated X positions."""
        source = np.array([[-4.0, 4.0], [-4.0, 4.0]])
        document = preserve_document(model.Document(Path("ramp.npy"), source), "unit-inputs/test_surface_clipping")
        frame = model.prepare_frame(document, model.default_selection(document),
                                    model.Limits(-2, 2, model.FilterMode.CLAMP), 0)
        mesh = pv.PolyData(frame.surface.points, frame.surface.faces)
        mesh.point_data["Value"] = mesh.points[:, 2]
        middle, caps = surface.SurfaceView._partition_surface(mesh, frame)
        self.assertEqual(len(caps), 2)
        np.testing.assert_allclose(middle.bounds[:2], [0.25, 0.75])
        for cap, expected_x, height in zip(caps, ((0, 0.25), (0.75, 1)), (-2, 2)):
            np.testing.assert_allclose(cap.bounds[:2], expected_x)
            np.testing.assert_array_equal(cap.points[:, 2], height)
            self.assertAlmostEqual(cap.area, 0.25)
        np.testing.assert_array_equal(frame.scalar, source)
        np.testing.assert_array_equal(mesh.points[:, 2], [-4, 4, -4, 4])

    def test_interpolated_vertices_cannot_overshoot(self) -> None:
        """VTK interpolation roundoff cannot leave normal vertices past a bound."""
        yy, xx = np.mgrid[:90, :140]
        source = 5 * np.sin(xx / 15) * np.cos(yy / 30)
        document = preserve_document(model.Document(Path("wave.npy"), source), "unit-inputs/test_surface_clipping")
        frame = model.prepare_frame(document, model.default_selection(document),
                                    model.Limits(-2, 2, model.FilterMode.CLAMP), 0)
        mesh = pv.PolyData(frame.surface.points, frame.surface.faces)
        mesh.point_data["Value"] = mesh.points[:, 2]
        middle, caps = surface.SurfaceView._partition_surface(mesh, frame)
        self.assertEqual(len(caps), 2)
        self.assertGreaterEqual(middle.points[:, 2].min(), -2)
        self.assertLessEqual(middle.points[:, 2].max(), 2)
        np.testing.assert_array_equal(middle.point_data["Value"], middle.points[:, 2])
        np.testing.assert_array_equal(frame.scalar, source)

    def test_clipping_interpolates_color_and_alpha(self) -> None:
        """Inserted threshold vertices carry interpolated colors and opacity."""
        source = np.array([[-4.0, 4.0], [-4.0, 4.0]])
        document = preserve_document(model.Document(Path("color-ramp.npy"), source), "unit-inputs/test_surface_clipping")
        frame = model.prepare_frame(document, model.default_selection(document),
                                    model.Limits(-2, 2, model.FilterMode.CLAMP), 0)
        mesh = pv.PolyData(frame.surface.points, frame.surface.faces)
        mesh.point_data["Value"] = np.asarray(mesh.points)[:, 2]
        mesh.point_data[surface.SOURCE_COLOR_FIELD] = np.array([[0, 0, 255, 0], [255, 0, 0, 255]] * 2, dtype=np.uint8)
        middle, caps = surface.SurfaceView._partition_surface(mesh, frame)
        for part in (middle, *caps):
            colors = np.asarray(part.point_data[surface.SOURCE_COLOR_FIELD])
            np.testing.assert_allclose(colors[:, 3], np.asarray(part.points)[:, 0] * 255, atol=1)
            self.assertEqual(colors.dtype, np.uint8)

    def test_point_cloud_clipping_keeps_colors(self) -> None:
        """Singleton image dimensions retain RGB(A) values on both clip outputs."""
        source = np.array([[-4.0, 0.0, 4.0]])
        document = preserve_document(model.Document(Path("color-points.npy"), source), "unit-inputs/test_surface_clipping")
        frame = model.prepare_frame(document, model.default_selection(document),
                                    model.Limits(-2, 2, model.FilterMode.CLAMP), 0)
        mesh = pv.PolyData(frame.surface.points)
        mesh.point_data["Value"] = source.ravel()
        colors = np.array([[10, 20, 30, 0], [40, 50, 60, 128], [70, 80, 90, 255]], dtype=np.uint8)
        mesh.point_data[surface.SOURCE_COLOR_FIELD] = colors
        middle, caps = surface.SurfaceView._partition_surface(mesh, frame)
        np.testing.assert_array_equal(middle.point_data[surface.SOURCE_COLOR_FIELD], colors[1:2])
        for part, index in zip(caps, (0, 2)):
            np.testing.assert_array_equal(part.point_data[surface.SOURCE_COLOR_FIELD], colors[index:index + 1])


if __name__ == "__main__":
    unittest.main()
