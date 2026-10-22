"""Collect PyVista's lazy VTK modules without importing the eager vtk shim.

Requirements: PyInstaller and PyVista 0.49's module maps. Used automatically by
MatrixViewer.spec; not a standalone tool. Rendering factories are side-effect
imports, so include them explicitly alongside the core/plotting class maps.
"""

from typing import cast

from PyInstaller.utils.hooks import get_module_attribute


core = cast(dict[str, tuple[str, ...]], get_module_attribute("pyvista._vtk", "_CORE_MODULES"))
plotting = cast(dict[str, tuple[str, ...]], get_module_attribute("pyvista._vtk", "_PLOTTING_MODULES"))
opengl = cast(dict[str, tuple[str, ...]], get_module_attribute("pyvista._vtk", "_OPENGL_MODULES"))
hiddenimports = sorted({f"vtkmodules.{name}" for name in (*core, *plotting, *opengl)} | {
    "vtkmodules.vtkRenderingContextOpenGL2",
    "vtkmodules.vtkRenderingFreeType",
    "vtkmodules.vtkRenderingMatplotlib",
    "vtkmodules.vtkRenderingOpenGL2",
    "vtkmodules.vtkInteractionStyle",
    "vtkmodules.vtkPythonContext2D",
})
