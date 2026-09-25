import math

import bpy
import pytest
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector

from blender_cam_mcp import animation as anim
from blender_cam_mcp.commands import CommandError


def _project(point, cam_name=None, frame=None):
    scene = bpy.context.scene
    if frame is not None:
        scene.frame_set(frame)
    cam = bpy.data.objects[cam_name] if cam_name else scene.camera
    return world_to_camera_view(scene, cam, Vector(point))


def _framing(result, name="Cube"):
    return next(f for f in result["framing"] if f["object"] == name)


def test_unknown_command_and_param(run):
    with pytest.raises(CommandError, match="Unknown command"):
        run("fly_to_moon", {})
    with pytest.raises(CommandError, match="Unknown parameter"):
        run("look_at", {"target": "Cube", "bogus": 1})
    with pytest.raises(CommandError, match="No object named"):
        run("look_at", {"target": "Nope"})


def test_scene_info(run):
    info = run("get_scene_info", {})
    assert info["active_camera"] == "Camera"
    names = {o["name"] for o in info["objects"]}
    assert {"Cube", "Light"} <= names
    cube = next(o for o in info["objects"] if o["name"] == "Cube")
    assert cube["size"] == [2.0, 2.0, 2.0]


def test_create_camera_look_at(run):
    run("create_camera", {"name": "A", "location": [4, -6, 2], "look_at": "Cube", "lens": 35})
    assert bpy.context.scene.camera.name == "A"
    p = _project((0, 0, 0), "A")
    assert p.x == pytest.approx(0.5, abs=1e-4) and p.y == pytest.approx(0.5, abs=1e-4)
    assert bpy.data.objects["A"].data.lens == 35


def test_fov_lens_roundtrip(run):
    run("set_camera_lens", {"fov_deg": 60})
    info = run("get_camera_info", {})
    assert info["fov_deg"]["horizontal"] == pytest.approx(60, abs=0.01)
    run("set_camera_lens", {"fov_deg": 30, "fov_axis": "vertical"})
    assert run("get_camera_info", {})["fov_deg"]["vertical"] == pytest.approx(30, abs=0.01)


@pytest.mark.parametrize("res", [(1920, 1080), (1080, 1920)])
def test_frame_objects_tight_fit(run, res):
    r = bpy.context.scene.render
    r.resolution_x, r.resolution_y = res
    out = run("frame_objects", {"objects": ["Cube"], "margin": 0.0})
    f = _framing(out)
    assert f["visibility"] == "fully_in_frame"
    bb = f["screen_bbox"]
    # Exactly touches one pair of frame edges.
    touches = min(bb["left"], bb["bottom"], 1 - bb["right"], 1 - bb["top"])
    assert touches == pytest.approx(0.0, abs=2e-3)
    out = run("frame_objects", {"objects": ["Cube"], "margin": 0.2, "azimuth_deg": 90, "elevation_deg": 30})
    f = _framing(out)
    assert f["visibility"] == "fully_in_frame"
    assert min(f["screen_bbox"]["left"], f["screen_bbox"]["bottom"]) > 0.03


def test_frame_objects_ortho(run):
    run("set_camera_lens", {"lens_type": "ORTHO"})
    f = _framing(run("frame_objects", {"objects": ["Cube"], "margin": 0.05}))
    assert f["visibility"] == "fully_in_frame"


def test_compose_line_keeps_other_axis(run):
    cube = bpy.data.objects["Cube"]
    cube.scale = (0.25, 0.15, 0.9)  # person-sized box
    bpy.context.view_layer.update()
    run("apply_shot_preset", {"subject": "Cube", "shot_size": "medium_closeup"})
    before = _project((0, 0, 0))
    headroom = _framing(run("apply_shot_preset", {"subject": "Cube", "shot_size": "medium_closeup"}))["headroom"]
    out = run("compose_subject", {"subject": "Cube", "position": "left_third"})
    after = _project((0, 0, 0))
    assert after.x == pytest.approx(1 / 3, abs=1e-3)
    assert after.y == pytest.approx(before.y, abs=0.02)  # pure pan: tiny perspective drift only
    assert _framing(out)["headroom"] == pytest.approx(headroom, abs=0.02)
    assert _framing(out)["headroom"] > 0


@pytest.mark.parametrize("position,expected", [("lower_left_third", (1 / 3, 1 / 3)),
                                               ("upper_right_third", (2 / 3, 2 / 3)),
                                               ("center", (0.5, 0.5))])
def test_compose_subject(run, position, expected):
    run("compose_subject", {"subject": "Cube", "position": position})
    p = _project((0, 0, 0))
    assert (p.x, p.y) == pytest.approx(expected, abs=1e-3)
    # Horizon stays level.
    assert run("get_camera_info", {})["roll_deg"] == pytest.approx(0, abs=0.01)


def test_shot_preset_sizes(run):
    full = _framing(run("apply_shot_preset", {"subject": "Cube", "shot_size": "full"}))
    assert full["visibility"] == "fully_in_frame"
    assert 0.7 < full["height_fraction"] < 0.95
    close = _framing(run("apply_shot_preset", {"subject": "Cube", "shot_size": "closeup"}))
    assert close["visibility"] == "partially_in_frame"
    high = run("apply_shot_preset", {"subject": "Cube", "angle": "high", "side": "left"})
    cam = bpy.context.scene.camera
    assert cam.matrix_world.translation.x > 1  # subject faces -Y, so its left side is +X
    assert run("get_camera_info", {})["pitch_deg"] == pytest.approx(-25, abs=0.5)
    assert high["shot"]["side"] == "left"


@pytest.mark.parametrize("size,headroom", [("medium", 0.07), ("medium_closeup", 0.06), ("closeup", 0.04)])
def test_shot_preset_headroom(run, size, headroom):
    cube = bpy.data.objects["Cube"]
    cube.scale = (0.25, 0.15, 0.9)  # person-sized box
    bpy.context.view_layer.update()
    f = _framing(run("apply_shot_preset", {"subject": "Cube", "shot_size": size}))
    assert f["headroom"] == pytest.approx(headroom, abs=0.01)


def test_shot_preset_low_angle_stays_above_ground(run):
    out = run("apply_shot_preset", {"subject": "Cube", "shot_size": "wide", "angle": "worms_eye"})
    assert "adjusted" in out
    assert bpy.context.scene.camera.matrix_world.translation.z > -1.0  # cube base is z=-1
    assert _framing(out)["visibility"] == "fully_in_frame"
    out = run("apply_shot_preset", {"subject": "Cube", "shot_size": "wide", "angle": "worms_eye",
                                    "allow_below_base": True})
    assert "adjusted" not in out
    assert bpy.context.scene.camera.matrix_world.translation.z < -1.0


def test_analyze_uses_real_geometry(run):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=1, location=(0, 0, 0))
    bpy.context.object.name = "Ball"
    run("create_camera", {"name": "S", "location": [0, -3, 0], "look_at": [0, 0, 0]})
    f = run("analyze_framing", {"objects": ["Ball"]})["objects"][0]
    # A sphere of radius 1 seen from 3 m: tangent half-angle asin(1/3).
    half = math.tan(math.asin(1 / 3))
    info = run("get_camera_info", {})
    tan_v = math.tan(math.radians(info["fov_deg"]["vertical"]) / 2)
    assert f["height_fraction"] == pytest.approx(half / tan_v, rel=0.03)


def test_shot_preset_respects_subject_rotation(run):
    cube = bpy.data.objects["Cube"]
    cube.rotation_euler.z = math.radians(90)  # front (-Y local) now faces +X
    bpy.context.view_layer.update()
    run("apply_shot_preset", {"subject": "Cube", "shot_size": "full", "side": "front"})
    loc = bpy.context.scene.camera.matrix_world.translation
    assert loc.x > 3 and abs(loc.y) < 1e-3


def test_move_camera_types(run):
    run("create_camera", {"name": "M", "location": [0, -10, 1], "look_at": [0, 0, 1]})
    run("move_camera", {"move_type": "dolly", "amount": 2})
    assert bpy.data.objects["M"].matrix_world.translation.y == pytest.approx(-8, abs=1e-4)
    run("move_camera", {"move_type": "truck", "amount": 1})
    assert bpy.data.objects["M"].matrix_world.translation.x == pytest.approx(1, abs=1e-4)
    run("move_camera", {"move_type": "pan", "amount": 90})
    info = run("get_camera_info", {})
    assert info["heading_deg"] == pytest.approx(180, abs=1e-3)
    run("move_camera", {"move_type": "tilt", "amount": 10})
    assert run("get_camera_info", {})["pitch_deg"] == pytest.approx(10, abs=1e-3)
    run("move_camera", {"move_type": "zoom", "amount": 15})
    assert bpy.data.objects["M"].data.lens == pytest.approx(65)
    run("move_camera", {"move_type": "orbit", "amount": 90, "target": [0, 0, 1]})
    p = _project((0, 0, 1), "M")
    assert (p.x, p.y) == pytest.approx((0.5, 0.5), abs=1e-4)
    with pytest.raises(CommandError, match="Unknown move type"):
        run("move_camera", {"move_type": "teleport", "amount": 1})


def test_animate_orbit_loop(run):
    run("create_camera", {"name": "O", "location": [0, -8, 2], "look_at": "Cube"})
    res = run("animate_orbit", {"target": "Cube", "start_frame": 1, "end_frame": 97})
    assert res["loopable"] and res["keyframes"] == 97
    cam = bpy.data.objects["O"]
    scene = bpy.context.scene
    positions = []
    for f in (1, 25, 49, 73, 97):
        p = _project((0, 0, 0), "O", f)
        assert (p.x, p.y) == pytest.approx((0.5, 0.5), abs=1e-3)
        positions.append(cam.matrix_world.translation.copy())
        assert (positions[-1].xy.length) == pytest.approx(8, abs=1e-3)
    assert (positions[0] - positions[-1]).length < 1e-3
    assert positions[1].x == pytest.approx(8, abs=1e-3)  # counter-clockwise from -Y goes to +X
    # Euler continuity: no 360 jumps between consecutive frames.
    rz = []
    for f in range(1, 98):
        scene.frame_set(f)
        rz.append(cam.rotation_euler.z)
    assert max(abs(a - b) for a, b in zip(rz, rz[1:])) < math.radians(10)


def test_animate_move_with_target_and_zoom(run):
    run("create_camera", {"name": "C", "location": [0, -10, 0], "look_at": "Cube"})
    run("animate_camera_move", {"move_type": "crane", "amount": 4, "target": "Cube", "start_frame": 1,
                                "end_frame": 40, "moves": [{"type": "zoom", "amount": 10}]})
    cam = bpy.data.objects["C"]
    for f in (1, 20, 40):
        p = _project((0, 0, 0), "C", f)
        assert (p.x, p.y) == pytest.approx((0.5, 0.5), abs=1e-3)
    bpy.context.scene.frame_set(40)
    assert cam.matrix_world.translation.z == pytest.approx(4, abs=1e-3)
    assert cam.data.lens == pytest.approx(60, abs=1e-3)


def test_dolly_zoom_keeps_subject_size(run):
    run("create_camera", {"name": "V", "location": [0, -10, 0], "look_at": "Cube"})
    run("animate_dolly_zoom", {"target": "Cube", "start_frame": 1, "end_frame": 30, "distance_change": -5})
    scene = bpy.context.scene
    heights = []
    for f in (1, 15, 30):
        top = _project((0, 0, 1), "V", f)
        bottom = _project((0, 0, -1), "V", f)
        heights.append(top.y - bottom.y)
    assert heights[0] == pytest.approx(heights[1], rel=0.01)
    assert heights[0] == pytest.approx(heights[2], rel=0.01)
    scene.frame_set(30)
    assert bpy.data.objects["V"].data.lens == pytest.approx(25, abs=1e-3)


def test_animate_path_through_waypoints(run):
    pts = [[0, -10, 2], [8, -4, 3], [6, 6, 4], [-6, 6, 2]]
    res = run("animate_path", {"points": pts, "start_frame": 1, "end_frame": 121, "look_mode": "target",
                               "look_target": "Cube", "create_guide_curve": True})
    assert res["guide_curve"] in bpy.data.objects
    cam = bpy.context.scene.camera
    bpy.context.scene.frame_set(1)
    assert (cam.matrix_world.translation - Vector(pts[0])).length < 1e-3
    bpy.context.scene.frame_set(121)
    assert (cam.matrix_world.translation - Vector(pts[-1])).length < 1e-3
    p = _project((0, 0, 0), frame=60)
    assert (p.x, p.y) == pytest.approx((0.5, 0.5), abs=1e-3)
    # Forward mode looks along the direction of travel.
    run("animate_path", {"points": [[0, -10, 1], [0, 10, 1]], "start_frame": 1, "end_frame": 50})
    bpy.context.scene.frame_set(25)
    assert run("get_camera_info", {})["heading_deg"] == pytest.approx(90, abs=0.5)


def test_follow_cam(run):
    cube = bpy.data.objects["Cube"]
    cube.location = (0, 0, 0)
    cube.keyframe_insert("location", frame=1)
    cube.location = (0, -20, 0)
    cube.keyframe_insert("location", frame=60)
    run("animate_follow", {"target": "Cube", "offset": [0, 6, 2], "start_frame": 1, "end_frame": 60,
                           "position_smoothing": 0.0, "aim_smoothing": 0.0})
    scene = bpy.context.scene
    cam = scene.camera
    for f in (1, 30, 60):
        scene.frame_set(f)
        assert (cam.matrix_world.translation - (cube.matrix_world.translation + Vector((0, 6, 2)))).length < 1e-3


def test_transition_to_camera(run):
    run("create_camera", {"name": "B", "location": [6, 2, 3], "look_at": "Cube", "lens": 85,
                          "set_active": False})
    run("create_camera", {"name": "A", "location": [-6, -6, 1], "look_at": "Cube"})
    run("animate_transition", {"to_camera": "B", "start_frame": 1, "end_frame": 30, "arc_height": 2})
    bpy.context.scene.frame_set(30)
    a, b = bpy.data.objects["A"], bpy.data.objects["B"]
    assert (a.matrix_world.translation - b.matrix_world.translation).length < 1e-3
    assert a.data.lens == pytest.approx(85)
    assert a.matrix_world.to_quaternion().rotation_difference(b.matrix_world.to_quaternion()).angle < 1e-3


def test_keyframes_and_interpolation(run):
    res = run("set_camera_keyframes", {"keyframes": [
        {"frame": 1, "location": [0, -10, 2], "look_at": "Cube", "lens": 35},
        {"frame": 48, "location": [5, -5, 3], "look_at": "Cube", "lens": 50, "focus_on": "Cube"},
        {"frame": 96, "location": [5, 5, 1], "look_at": [0, 0, 1]},
    ], "clear_existing": True})
    assert res["frames"] == [1, 48, 96]
    cam = bpy.context.scene.camera
    assert anim.keyframe_frames(cam) == [1.0, 48.0, 96.0]
    run("set_keyframe_interpolation", {"interpolation": "LINEAR"})
    assert all(i == ["LINEAR"] for i in
               [e["interpolations"] for e in anim.fcurve_summary(cam)])
    data = run("get_camera_animation", {"step": 12})
    assert data["samples"][0]["frame"] == 1 and data["samples"][-1]["frame"] == 96
    assert data["path_length"] > 10
    removed = run("clear_camera_animation", {"frame_start": 40, "frame_end": 50})
    assert removed["keyframes_removed"] > 0
    assert anim.keyframe_frames(cam) == [1.0, 96.0]
    run("clear_camera_animation", {})
    assert anim.keyframe_frames(cam) == []


def test_shake_add_remove(run):
    run("set_camera_keyframes", {"keyframes": [{"frame": 1, "location": [0, -10, 0], "look_at": "Cube"}]})
    res = run("add_camera_shake", {"preset": "handheld", "intensity": 2, "start_frame": 10, "end_frame": 50,
                                   "blend_in_frames": 5})
    assert res["channels"] == 6
    cam = bpy.context.scene.camera
    scene = bpy.context.scene
    scene.frame_set(30)
    moved = cam.matrix_world.copy()
    scene.frame_set(33)
    assert (moved.translation - cam.matrix_world.translation).length > 1e-5
    scene.frame_set(5)  # outside the restricted range: no shake
    assert cam.delta_rotation_euler.to_quaternion().angle < 1e-6
    assert run("get_camera_info", {})["shake"]["active"]
    assert run("remove_camera_shake", {})["removed_channels"] == 6
    assert not run("get_camera_info", {})["shake"]["active"]


def test_rack_focus(run):
    run("create_camera", {"name": "F", "location": [0, -10, 0], "look_at": "Cube"})
    res = run("animate_rack_focus", {"focus_targets": ["Cube", 20.0], "start_frame": 1, "end_frame": 25,
                                     "fstop": 1.8})
    assert res["stops"][0]["focus_distance"] == pytest.approx(10, abs=1e-3)
    cam = bpy.data.objects["F"]
    bpy.context.scene.frame_set(25)
    assert cam.data.dof.focus_distance == pytest.approx(20, abs=1e-3)
    assert cam.data.dof.use_dof and cam.data.dof.aperture_fstop == pytest.approx(1.8)


def test_whip_pan(run):
    run("create_camera", {"name": "W", "location": [0, -10, 0], "look_at": [0, 0, 0]})
    run("animate_whip_pan", {"angle_deg": 90, "start_frame": 1, "duration_frames": 8})
    bpy.context.scene.frame_set(9)
    assert run("get_camera_info", {})["heading_deg"] == pytest.approx(180, abs=1e-3)
    assert bpy.context.scene.render.use_motion_blur


def test_track_constraint(run):
    res = run("add_track_constraint", {"target": [1, 2, 3]})
    assert res["created_empty"] in bpy.data.objects
    bpy.context.view_layer.update()
    p = _project((1, 2, 3))
    assert (p.x, p.y) == pytest.approx((0.5, 0.5), abs=1e-4)
    assert "warning" in run("look_at", {"target": "Cube"})
    run("remove_camera_constraints", {})
    assert not bpy.context.scene.camera.constraints


def test_camera_cuts(run):
    run("create_camera", {"name": "Wide", "location": [0, -15, 3], "look_at": "Cube"})
    run("create_camera", {"name": "Close", "location": [0, -4, 1], "look_at": "Cube"})
    run("add_camera_cut", {"camera": "Wide", "frame": 1})
    cuts = run("add_camera_cut", {"camera": "Close", "frame": 50})["cuts"]
    assert [c["camera"] for c in cuts] == ["Wide", "Close"]
    scene = bpy.context.scene
    scene.frame_set(60)
    assert scene.camera.name == "Close"
    assert run("clear_camera_cuts", {})["removed"] == 2


def test_bookmarks(run):
    run("create_camera", {"name": "K", "location": [3, -3, 3], "look_at": "Cube", "lens": 70})
    run("save_camera_bookmark", {"name": "hero"})
    run("move_camera", {"move_type": "dolly", "amount": -5})
    bpy.data.objects["K"].data.lens = 20
    run("apply_camera_bookmark", {"name": "hero", "keyframe_frame": 10})
    assert (bpy.data.objects["K"].matrix_world.translation - Vector((3, -3, 3))).length < 1e-4
    assert bpy.data.objects["K"].data.lens == pytest.approx(70)
    assert "hero" in run("list_camera_bookmarks", {})


def test_render_preview_and_sheet(run):
    r = run("render_preview", {"max_size": 96, "engine": "CYCLES", "samples": 1})
    assert r["width"] == 96 and r["height"] == 54
    import base64
    assert base64.b64decode(r["png_base64"]).startswith(b"\x89PNG")
    s = run("render_contact_sheet", {"count": 3, "columns": 3, "max_size": 64, "engine": "CYCLES", "samples": 1,
                                     "frame_start": 1, "frame_end": 20})
    assert s["frames"] == [1, 10, 20]
    assert s["layout"]["rows"] == 1
    # Render settings restored.
    assert bpy.context.scene.render.resolution_x == 1920


def test_execute_python_gated(run):
    from blender_cam_mcp import commands

    with pytest.raises(CommandError, match="disabled"):
        run("execute_python", {"code": "result = 1"})
    commands.PYTHON_ALLOWED["value"] = True
    try:
        assert run("execute_python", {"code": "print('hi'); result = len(bpy.data.objects)"}) == {
            "stdout": "hi\n", "result": 3}
    finally:
        commands.PYTHON_ALLOWED["value"] = False
