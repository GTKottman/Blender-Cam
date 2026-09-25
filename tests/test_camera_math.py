import math

import pytest
from mathutils import Vector

from blender_cam_mcp import camera_math as cm


@pytest.mark.parametrize("name", sorted(cm.EASINGS))
def test_easing_endpoints(name):
    assert cm.ease(name, 0.0) == pytest.approx(0.0, abs=1e-6)
    assert cm.ease(name, 1.0) == pytest.approx(1.0, abs=1e-6)


def test_unknown_easing():
    with pytest.raises(ValueError):
        cm.ease("wobble", 0.5)


def test_spherical_roundtrip():
    off = cm.spherical_offset(math.radians(30), math.radians(20), 7.0)
    az, el, d = cm.spherical_from_offset(off)
    assert math.degrees(az) == pytest.approx(30)
    assert math.degrees(el) == pytest.approx(20)
    assert d == pytest.approx(7.0)
    # azimuth 0 sits on the -Y side.
    assert cm.spherical_offset(0, 0, 1).y == pytest.approx(-1)


def test_look_quat_points_and_is_level():
    q = cm.look_quat((5, -5, 3), (0, 0, 0))
    fwd, right, up = cm.camera_axes(q)
    assert (fwd - (-Vector((5, -5, 3))).normalized()).length < 1e-6
    assert abs(right.z) < 1e-6
    assert up.z > 0
    assert cm.camera_roll(q) == pytest.approx(0, abs=1e-6)
    q2 = cm.look_quat((5, -5, 3), (0, 0, 0), math.radians(20))
    assert math.degrees(cm.camera_roll(q2)) == pytest.approx(20, abs=1e-4)


def test_polyline_constant_speed_and_endpoints():
    pts = [(0, 0, 0), (1, 0, 0), (10, 0, 0)]
    poly = cm.Polyline(cm.smooth_path(pts))
    assert poly.at_fraction(0) == Vector(pts[0])
    assert (poly.at_fraction(1) - Vector(pts[-1])).length < 1e-6
    assert poly.at_fraction(0.5).x == pytest.approx(poly.length / 2, rel=0.02)


def test_smooth_path_passes_through_waypoints():
    pts = [Vector(p) for p in [(0, 0, 0), (3, 4, 0), (6, 0, 2), (9, 5, 1)]]
    dense = cm.smooth_path(pts, samples_per_segment=16)
    for p in pts:
        assert min((d - p).length for d in dense) < 1e-6
