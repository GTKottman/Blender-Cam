import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "addon"))
sys.path.insert(0, os.path.join(ROOT, "src"))

bpy = pytest.importorskip("bpy", reason="needs the 'bpy' module (pip install bpy)")


@pytest.fixture
def scene():
    """Fresh default scene (Cube at origin, Camera, Light)."""
    bpy.ops.wm.read_factory_settings(use_empty=False)
    return bpy.context.scene


@pytest.fixture
def run(scene):
    from blender_cam_mcp.commands import dispatch

    return dispatch
