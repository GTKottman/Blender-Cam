"""Camera command handlers.

Every public command is registered with :func:`command` and receives keyword
arguments decoded from JSON. Handlers run on Blender's main thread and return
JSON-serialisable data. Raise :class:`CommandError` for user-facing errors.
"""

import contextlib
import inspect
import io
import json
import math

import bpy
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Euler, Quaternion, Vector

from . import animation as anim
from . import camera_math as cm

COMMANDS = {}
BOOKMARK_KEY = "camera_mcp_bookmarks"
PYTHON_ALLOWED = {"value": False}


class CommandError(Exception):
    pass


def command(fn):
    COMMANDS[fn.__name__] = fn
    return fn


def dispatch(name, params):
    fn = COMMANDS.get(name)
    if fn is None:
        raise CommandError(
            "Unknown command '%s'. Available: %s" % (name, ", ".join(sorted(COMMANDS)))
        )
    params = params or {}
    sig = inspect.signature(fn)
    unknown = [k for k in params if k not in sig.parameters]
    if unknown:
        raise CommandError(
            "Unknown parameter(s) for %s: %s. Valid: %s"
            % (name, ", ".join(unknown), ", ".join(sig.parameters))
        )
    try:
        return fn(**params)
    except CommandError:
        raise
    except (ValueError, TypeError, KeyError) as exc:
        raise CommandError("%s: %s" % (type(exc).__name__, exc)) from exc


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def _r(v, nd=4):
    if isinstance(v, (int,)) and not isinstance(v, bool):
        return v
    if isinstance(v, float):
        return round(v, nd)
    try:
        return [round(float(x), nd) for x in v]
    except TypeError:
        return v


def _deg(euler):
    return [round(math.degrees(a), 3) for a in euler]


# ---------------------------------------------------------------------------
# Scene / object lookup
# ---------------------------------------------------------------------------

def _scene():
    return bpy.context.scene


def _camera_names():
    return [o.name for o in _scene().objects if o.type == "CAMERA"]


def _get_camera(name=None):
    scene = _scene()
    if name:
        obj = bpy.data.objects.get(name)
        if obj is None:
            raise CommandError(
                "No object named '%s'. Cameras in scene: %s" % (name, _camera_names() or "none")
            )
        if obj.type != "CAMERA":
            raise CommandError("Object '%s' is a %s, not a CAMERA" % (name, obj.type))
        return obj
    if scene.camera is None:
        cams = _camera_names()
        if cams:
            raise CommandError("Scene has no active camera. Cameras: %s. "
                               "Pass camera=<name> or call set_active_camera." % cams)
        raise CommandError("Scene has no camera. Call create_camera first.")
    return scene.camera


def _get_object(name):
    obj = bpy.data.objects.get(name)
    if obj is None:
        close = [o.name for o in _scene().objects if name.lower() in o.name.lower()][:10]
        raise CommandError("No object named '%s'.%s" % (
            name, (" Did you mean: %s?" % close) if close else ""))
    return obj


def _world_bbox(obj):
    """World-space bbox (min, max) of an object's evaluated geometry."""
    depsgraph = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(depsgraph)
    mw = ev.matrix_world
    if obj.type in {"MESH", "CURVE", "SURFACE", "FONT", "META", "LATTICE", "ARMATURE",
                    "GPENCIL", "GREASEPENCIL", "VOLUME", "POINTCLOUD", "CURVES"}:
        corners = [mw @ Vector(c) for c in ev.bound_box]
    else:
        corners = [mw.translation.copy()]
    mn = Vector((min(c.x for c in corners), min(c.y for c in corners), min(c.z for c in corners)))
    mx = Vector((max(c.x for c in corners), max(c.y for c in corners), max(c.z for c in corners)))
    return mn, mx


def _object_points(obj, max_points=4000):
    """World-space points describing an object's shape.

    Uses evaluated mesh vertices (subsampled) so framing matches the real
    silhouette; falls back to bounding-box corners for other object types.
    """
    depsgraph = bpy.context.evaluated_depsgraph_get()
    ev = obj.evaluated_get(depsgraph)
    mw = ev.matrix_world
    if obj.type == "MESH":
        mesh = ev.data
        n = len(mesh.vertices)
        if 0 < n:
            stride = max(1, n // max_points)
            verts = mesh.vertices
            return [mw @ verts[i].co for i in range(0, n, stride)]
    mn, mx = _world_bbox(obj)
    return cm.bbox_corners(mn, mx)


def _union_bbox(names):
    if isinstance(names, str):
        names = [names]
    if not names:
        raise CommandError("Provide at least one object name")
    mn = Vector((math.inf,) * 3)
    mx = Vector((-math.inf,) * 3)
    for n in names:
        a, b = _world_bbox(_get_object(n))
        mn = Vector((min(mn[i], a[i]) for i in range(3)))
        mx = Vector((max(mx[i], b[i]) for i in range(3)))
    return mn, mx


def _resolve_point(target, what="target"):
    """Object name (-> bbox centre) or [x, y, z] -> Vector."""
    if target is None:
        raise CommandError("%s is required (object name or [x, y, z])" % what)
    if isinstance(target, str):
        mn, mx = _world_bbox(_get_object(target))
        return (mn + mx) / 2.0
    if isinstance(target, dict):
        if "object" in target:
            p = _resolve_point(target["object"], what)
            return p + Vector(target.get("offset", (0, 0, 0)))
        raise CommandError("%s dict must contain 'object'" % what)
    try:
        v = Vector([float(x) for x in target])
    except (TypeError, ValueError):
        raise CommandError("%s must be an object name or [x, y, z]" % what) from None
    if len(v) != 3:
        raise CommandError("%s must have 3 components" % what)
    return v


def _vec3(v, what):
    try:
        out = Vector([float(x) for x in v])
    except (TypeError, ValueError):
        raise CommandError("%s must be [x, y, z]" % what) from None
    if len(out) != 3:
        raise CommandError("%s must have 3 components" % what)
    return out


# ---------------------------------------------------------------------------
# Camera pose helpers
# ---------------------------------------------------------------------------

def _prepare_rotation_mode(obj):
    if obj.rotation_mode == "AXIS_ANGLE":
        obj.rotation_mode = "XYZ"


def _rot_path(obj):
    return "rotation_quaternion" if obj.rotation_mode == "QUATERNION" else "rotation_euler"


def _pose(obj):
    """World (location, quaternion) of an object."""
    loc, rot, _scale = obj.matrix_world.decompose()
    return loc, rot


def _set_pose(obj, loc, quat, previous=None):
    """Set the world pose while keeping rotations continuous with ``previous``."""
    _prepare_rotation_mode(obj)
    scale = obj.matrix_world.to_scale()
    obj.matrix_world = cm.to_matrix(loc, quat, scale)
    if obj.rotation_mode == "QUATERNION":
        prev = previous if isinstance(previous, Quaternion) else None
        obj.rotation_quaternion = cm.compat_quat(obj.rotation_quaternion, prev)
    elif previous is not None and isinstance(previous, Euler):
        obj.rotation_euler = obj.rotation_euler.to_matrix().to_euler(obj.rotation_mode, previous)


def _rotation_state(obj):
    if obj.rotation_mode == "QUATERNION":
        return obj.rotation_quaternion.copy()
    return obj.rotation_euler.copy()


def _key_transform(obj, frame):
    obj.keyframe_insert("location", frame=frame)
    obj.keyframe_insert(_rot_path(obj), frame=frame)


def _key_lens(cam, frame):
    cam.data.keyframe_insert("lens", frame=frame)


def _key_focus(cam, frame):
    cam.data.keyframe_insert("dof.focus_distance", frame=frame)


def _camera_summary(cam, brief=False):
    scene = _scene()
    loc, quat = _pose(cam)
    forward, _right, up = cm.camera_axes(quat)
    hfov, vfov = cm.camera_fov(cam.data, scene)
    d = cam.data
    info = {
        "name": cam.name,
        "active": scene.camera == cam,
        "location": _r(loc),
        "rotation_deg": _deg(quat.to_euler("XYZ")),
        "forward": _r(forward),
        "lens_mm": _r(d.lens, 3),
    }
    if d.type == "ORTHO":
        info["ortho_scale"] = _r(d.ortho_scale, 3)
    else:
        info["fov_deg"] = {"horizontal": _r(math.degrees(hfov), 2), "vertical": _r(math.degrees(vfov), 2)}
    if brief:
        return info
    heading, pitch = cm.heading_pitch(forward)
    info.update({
        "type": d.type,
        "local_location": _r(cam.location),
        "rotation_mode": cam.rotation_mode,
        "up": _r(up),
        "heading_deg": _r(math.degrees(heading), 2),
        "pitch_deg": _r(math.degrees(pitch), 2),
        "roll_deg": _r(math.degrees(cm.camera_roll(quat)), 2),
        "sensor": {"width_mm": _r(d.sensor_width, 3), "height_mm": _r(d.sensor_height, 3), "fit": d.sensor_fit},
        "shift": [_r(d.shift_x, 4), _r(d.shift_y, 4)],
        "clip": [_r(d.clip_start, 4), _r(d.clip_end, 3)],
        "dof": {
            "enabled": d.dof.use_dof,
            "focus_object": d.dof.focus_object.name if d.dof.focus_object else None,
            "focus_distance": _r(d.dof.focus_distance, 4),
            "fstop": _r(d.dof.aperture_fstop, 3),
        },
        "parent": cam.parent.name if cam.parent else None,
        "constraints": [{"name": c.name, "type": c.type,
                         "target": getattr(getattr(c, "target", None), "name", None),
                         "influence": _r(c.influence, 3), "enabled": not c.mute}
                        for c in cam.constraints],
        "keyframes": {
            "object": anim.keyframe_frames(cam),
            "camera_data": anim.keyframe_frames(cam.data),
        },
        "shake": _shake_info(cam),
    })
    return info


def _shake_info(cam):
    mods = []
    for fc in anim.fcurves(cam):
        if fc.data_path.startswith("delta_"):
            for m in fc.modifiers:
                if m.type == "NOISE":
                    mods.append(fc.data_path)
                    break
    return {"active": bool(mods), "channels": len(mods)}


def _frame_args(start_frame, end_frame, duration=None):
    scene = _scene()
    start = int(scene.frame_current if start_frame is None else start_frame)
    if end_frame is None:
        if duration is not None:
            end = start + int(duration)
        else:
            end = scene.frame_end if scene.frame_end > start else start + 5 * int(round(scene.render.fps / scene.render.fps_base))
    else:
        end = int(end_frame)
    if end <= start:
        raise CommandError("end_frame (%d) must be after start_frame (%d)" % (end, start))
    return start, end


def _extend_scene(end, start=None):
    scene = _scene()
    changed = False
    if end > scene.frame_end:
        scene.frame_end = end
        changed = True
    if start is not None and start < scene.frame_start:
        scene.frame_start = start
        changed = True
    return changed


def _key_frames(start, end, step):
    step = max(1, int(step))
    frames = list(range(start, end + 1, step))
    if frames[-1] != end:
        frames.append(end)
    return frames


def _eval_camera_pose(cam, frame):
    """Evaluated world pose of the camera at a frame (restores current frame)."""
    scene = _scene()
    current = scene.frame_current
    if frame != current:
        scene.frame_set(frame)
    loc, quat = _pose(cam)
    lens = cam.data.lens
    if frame != current:
        scene.frame_set(current)
    return loc, quat, lens


def _bake(cam, frames, pose_fn, start, end, interpolation="LINEAR", key_lens=False,
          key_focus=False, clear_existing=True):
    """Keyframe the camera at ``frames`` using ``pose_fn(t) -> dict``.

    ``pose_fn`` returns {"location", "rotation" (Quaternion), "lens"?, "focus"?}.
    """
    if clear_existing:
        anim.clear_keys(cam, ["location", "rotation_euler", "rotation_quaternion"], start, end)
        if key_lens:
            anim.clear_keys(cam.data, ["lens"], start, end)
        if key_focus:
            anim.clear_keys(cam.data, ["dof.focus_distance"], start, end)
    _prepare_rotation_mode(cam)
    previous = _rotation_state(cam)
    span = float(end - start)
    for f in frames:
        t = (f - start) / span
        pose = pose_fn(t)
        _set_pose(cam, pose["location"], pose["rotation"], previous)
        previous = _rotation_state(cam)
        _key_transform(cam, f)
        if key_lens and pose.get("lens") is not None:
            cam.data.lens = max(1.0, pose["lens"])
            _key_lens(cam, f)
        if key_focus and pose.get("focus") is not None:
            cam.data.dof.focus_distance = max(0.0, pose["focus"])
            _key_focus(cam, f)
    anim.set_interpolation(cam, interpolation, frame_start=start, frame_end=end,
                           data_paths=["location", "rotation_euler", "rotation_quaternion"])
    if key_lens or key_focus:
        anim.set_interpolation(cam.data, interpolation, frame_start=start, frame_end=end)
    extended = _extend_scene(end, start)
    _scene().frame_set(_scene().frame_current)
    return {
        "camera": cam.name,
        "frame_range": [start, end],
        "keyframes": len(frames),
        "scene_range_extended": extended,
    }


def _warn_constraints(cam):
    tracking = [c.name for c in cam.constraints
                if c.type in {"TRACK_TO", "DAMPED_TRACK", "LOCKED_TRACK", "CHILD_OF",
                              "FOLLOW_PATH", "COPY_ROTATION", "COPY_TRANSFORMS"} and not c.mute]
    if tracking:
        return ("Camera has active constraints %s that override keyed rotation/location. "
                "Use remove_camera_constraints if the motion does not look right." % tracking)
    return None


def _with_warning(result, cam):
    w = _warn_constraints(cam)
    if w:
        result["warning"] = w
    return result


# ---------------------------------------------------------------------------
# Info commands
# ---------------------------------------------------------------------------

@command
def ping():
    return {"pong": True, "blender_version": bpy.app.version_string}


@command
def list_commands():
    out = {}
    for name, fn in sorted(COMMANDS.items()):
        doc = (fn.__doc__ or "").strip().splitlines()
        out[name] = {"params": list(inspect.signature(fn).parameters), "doc": doc[0] if doc else ""}
    return out


@command
def get_scene_info(include_objects=True, max_objects=100):
    """Scene summary: frame range, fps, resolution, cameras and object bounds."""
    scene = _scene()
    r = scene.render
    info = {
        "scene": scene.name,
        "blender_version": bpy.app.version_string,
        "frame_start": scene.frame_start,
        "frame_end": scene.frame_end,
        "frame_current": scene.frame_current,
        "fps": _r(r.fps / r.fps_base, 3),
        "resolution": [r.resolution_x, r.resolution_y, r.resolution_percentage],
        "aspect": _r(cm.render_aspect(scene), 4),
        "render_engine": r.engine,
        "motion_blur": r.use_motion_blur,
        "active_camera": scene.camera.name if scene.camera else None,
        "cameras": [_camera_summary(o, brief=True) for o in scene.objects if o.type == "CAMERA"],
        "camera_cuts": _camera_cuts(),
        "unit_scale": scene.unit_settings.scale_length,
    }
    if include_objects:
        objs = []
        for o in scene.objects:
            if o.type == "CAMERA":
                continue
            if len(objs) >= max_objects:
                info["objects_truncated"] = True
                break
            mn, mx = _world_bbox(o)
            objs.append({
                "name": o.name,
                "type": o.type,
                "location": _r(o.matrix_world.translation, 3),
                "center": _r((mn + mx) / 2.0, 3),
                "size": _r(mx - mn, 3),
                "animated": bool(o.animation_data and o.animation_data.action),
                "visible": o.visible_get(),
            })
        info["objects"] = objs
        if objs:
            mn, mx = _union_bbox([o["name"] for o in objs if o["type"] not in {"LIGHT", "EMPTY"}] or
                                 [o["name"] for o in objs])
            info["scene_bounds"] = {"min": _r(mn, 3), "max": _r(mx, 3), "center": _r((mn + mx) / 2, 3)}
    return info


@command
def list_cameras():
    """List all cameras with brief pose/lens info."""
    return [_camera_summary(o, brief=True) for o in _scene().objects if o.type == "CAMERA"]


@command
def get_camera_info(camera=None):
    """Full camera details: pose, lens, sensor, DOF, constraints, keyframes."""
    return _camera_summary(_get_camera(camera))


# ---------------------------------------------------------------------------
# Camera management
# ---------------------------------------------------------------------------

@command
def create_camera(name="Camera", location=None, look_at=None, rotation_deg=None, lens=None,
                  sensor_preset=None, set_active=True, collection=None):
    """Create a camera, optionally aimed at a target, and make it active."""
    scene = _scene()
    data = bpy.data.cameras.new(name)
    obj = bpy.data.objects.new(name, data)
    coll = bpy.data.collections.get(collection) if collection else scene.collection
    if coll is None:
        raise CommandError("No collection named '%s'" % collection)
    coll.objects.link(obj)
    obj.rotation_mode = "XYZ"
    loc = _vec3(location, "location") if location is not None else Vector((0.0, -10.0, 2.0))
    if lens is not None:
        data.lens = float(lens)
    if sensor_preset:
        _apply_sensor_preset(data, sensor_preset)
    data.clip_end = max(data.clip_end, 1000.0)
    if look_at is not None:
        quat = cm.look_quat(loc, _resolve_point(look_at, "look_at"))
    elif rotation_deg is not None:
        quat = Euler([math.radians(a) for a in rotation_deg], "XYZ").to_quaternion()
    else:
        quat = cm.look_quat(loc, Vector((0.0, 0.0, 0.0)) if loc.length > 1e-6 else Vector((0, 1, 0)))
    _set_pose(obj, loc, quat)
    if set_active:
        scene.camera = obj
    bpy.context.view_layer.update()
    return _camera_summary(obj)


@command
def delete_camera(camera):
    """Delete a camera object (and its data if unused)."""
    obj = _get_camera(camera)
    data = obj.data
    bpy.data.objects.remove(obj, do_unlink=True)
    if data.users == 0:
        bpy.data.cameras.remove(data)
    scene = _scene()
    return {"deleted": camera, "active_camera": scene.camera.name if scene.camera else None}


@command
def duplicate_camera(camera=None, name=None, copy_animation=False):
    """Duplicate a camera (pose + lens settings) to create an alternate angle."""
    src = _get_camera(camera)
    obj = src.copy()
    obj.data = src.data.copy()
    if name:
        obj.name = name
        obj.data.name = name
    if not copy_animation:
        obj.animation_data_clear()
        obj.data.animation_data_clear()
        obj.matrix_world = src.matrix_world.copy()
    for coll in src.users_collection:
        coll.objects.link(obj)
    bpy.context.view_layer.update()
    return _camera_summary(obj, brief=True)


@command
def set_active_camera(camera):
    """Make a camera the scene's render camera."""
    obj = _get_camera(camera)
    _scene().camera = obj
    return {"active_camera": obj.name}


def _apply_sensor_preset(data, preset):
    key = preset.lower().replace("-", "_").replace(" ", "_")
    if key not in cm.SENSOR_PRESETS:
        raise CommandError("Unknown sensor_preset '%s'. Valid: %s" % (preset, ", ".join(cm.SENSOR_PRESETS)))
    w, h = cm.SENSOR_PRESETS[key]
    data.sensor_width = w
    data.sensor_height = h


@command
def set_camera_lens(camera=None, lens=None, fov_deg=None, fov_axis="horizontal", lens_type=None,
                    sensor_preset=None, sensor_width=None, sensor_height=None, sensor_fit=None,
                    ortho_scale=None, clip_start=None, clip_end=None, shift_x=None, shift_y=None,
                    keyframe_frame=None):
    """Set focal length / field of view / sensor / projection / clipping / lens shift."""
    cam = _get_camera(camera)
    d = cam.data
    if lens_type:
        lens_type = lens_type.upper()
        if lens_type not in {"PERSP", "ORTHO", "PANO"}:
            raise CommandError("lens_type must be PERSP, ORTHO or PANO")
        d.type = lens_type
    if sensor_preset:
        _apply_sensor_preset(d, sensor_preset)
    if sensor_width is not None:
        d.sensor_width = float(sensor_width)
    if sensor_height is not None:
        d.sensor_height = float(sensor_height)
    if sensor_fit:
        d.sensor_fit = sensor_fit.upper()
    if lens is not None:
        d.lens = float(lens)
    if fov_deg is not None:
        if not 0.1 < float(fov_deg) < 179.0:
            raise CommandError("fov_deg must be between 0.1 and 179")
        d.lens = cm.lens_for_fov(d, _scene(), math.radians(float(fov_deg)), fov_axis)
    if ortho_scale is not None:
        d.ortho_scale = float(ortho_scale)
    if clip_start is not None:
        d.clip_start = float(clip_start)
    if clip_end is not None:
        d.clip_end = float(clip_end)
    if shift_x is not None:
        d.shift_x = float(shift_x)
    if shift_y is not None:
        d.shift_y = float(shift_y)
    if keyframe_frame is not None:
        _key_lens(cam, int(keyframe_frame))
    return _camera_summary(cam)


@command
def set_depth_of_field(camera=None, enabled=True, focus_object=None, focus_distance=None,
                       focus_point=None, fstop=None, blades=None, rotation_deg=None, ratio=None,
                       keyframe_frame=None):
    """Configure depth of field: focus on an object, a point, or a distance."""
    cam = _get_camera(camera)
    dof = cam.data.dof
    dof.use_dof = bool(enabled)
    if focus_object is not None:
        dof.focus_object = _get_object(focus_object) if focus_object else None
    if focus_point is not None:
        dof.focus_object = None
        dof.focus_distance = _focus_distance_to(cam, _resolve_point(focus_point, "focus_point"))
    if focus_distance is not None:
        dof.focus_object = None
        dof.focus_distance = float(focus_distance)
    if fstop is not None:
        dof.aperture_fstop = float(fstop)
    if blades is not None:
        dof.aperture_blades = int(blades)
    if rotation_deg is not None:
        dof.aperture_rotation = math.radians(float(rotation_deg))
    if ratio is not None:
        dof.aperture_ratio = float(ratio)
    if keyframe_frame is not None:
        _key_focus(cam, int(keyframe_frame))
        cam.data.keyframe_insert("dof.aperture_fstop", frame=int(keyframe_frame))
    return _camera_summary(cam)["dof"]


def _focus_distance_to(cam, point):
    """Distance along the view axis (what Blender uses for focus)."""
    loc, quat = _pose(cam)
    forward, _r_, _u = cm.camera_axes(quat)
    return max(0.0, (point - loc).dot(forward))


# ---------------------------------------------------------------------------
# Instant positioning
# ---------------------------------------------------------------------------

def _maybe_key(cam, keyframe_frame, lens=False):
    if keyframe_frame is None:
        return
    f = int(keyframe_frame)
    _key_transform(cam, f)
    if lens:
        _key_lens(cam, f)
    _extend_scene(f)


@command
def set_camera_transform(camera=None, location=None, rotation_deg=None, look_at=None, roll_deg=0.0,
                         keyframe_frame=None):
    """Place a camera by world location and either Euler rotation or a look-at target."""
    cam = _get_camera(camera)
    loc, quat = _pose(cam)
    if location is not None:
        loc = _vec3(location, "location")
    if look_at is not None:
        quat = cm.look_quat(loc, _resolve_point(look_at, "look_at"), math.radians(roll_deg or 0.0))
    elif rotation_deg is not None:
        quat = Euler([math.radians(a) for a in rotation_deg], "XYZ").to_quaternion()
    _set_pose(cam, loc, quat, _rotation_state(cam))
    _maybe_key(cam, keyframe_frame)
    bpy.context.view_layer.update()
    return _with_warning(_camera_summary(cam, brief=True), cam)


@command
def look_at(target, camera=None, roll_deg=0.0, keyframe_frame=None):
    """Rotate the camera (in place) so it points at an object or point."""
    cam = _get_camera(camera)
    loc, _q = _pose(cam)
    quat = cm.look_quat(loc, _resolve_point(target), math.radians(roll_deg or 0.0))
    _set_pose(cam, loc, quat, _rotation_state(cam))
    _maybe_key(cam, keyframe_frame)
    bpy.context.view_layer.update()
    return _with_warning(_camera_summary(cam, brief=True), cam)


MOVE_TYPES = {
    "dolly": "move forward (+) / backward (-) along the view direction (m)",
    "truck": "move right (+) / left (-) (m)",
    "pedestal": "move up (+) / down (-) along world Z (m)",
    "crane": "alias for pedestal; combine with target to keep the subject framed",
    "pan": "rotate left (+) / right (-) around world Z (deg)",
    "tilt": "rotate up (+) / down (-) (deg)",
    "roll": "rotate counter-clockwise (+) around the view axis (deg)",
    "zoom": "change focal length by N mm (+ = tighter)",
    "orbit": "circle the target horizontally, counter-clockwise (+) seen from above (deg); needs target",
    "orbit_vertical": "arc over the target, up (+) / down (-) (deg); needs target",
    "push_in": "move toward the target (m); needs target (or uses view direction)",
    "pull_out": "move away from the target (m); needs target (or uses view direction)",
}


def _normalize_moves(move_type, amount, moves):
    out = []
    if move_type is not None:
        out.append({"type": move_type, "amount": amount if amount is not None else 0.0})
    for m in moves or []:
        out.append(m)
    if not out:
        raise CommandError("Provide move_type + amount, or a moves list. Types: %s" % MOVE_TYPES)
    norm = []
    for m in out:
        t = str(m.get("type", "")).lower()
        if t not in MOVE_TYPES:
            raise CommandError("Unknown move type '%s'. Valid: %s" % (t, MOVE_TYPES))
        norm.append((t, float(m.get("amount", 0.0))))
    return norm


def _apply_moves(loc0, quat0, lens0, moves, target, t):
    """Pose after applying ``moves`` scaled by ``t`` (0..1) to a start pose."""
    fwd, right, _up = cm.camera_axes(quat0)
    loc = loc0.copy()
    lens = lens0
    pan = tilt = roll = 0.0
    orbit_h = orbit_v = 0.0
    for kind, amount in moves:
        a = amount * t
        if kind == "dolly":
            loc += fwd * a
        elif kind == "truck":
            loc += right * a
        elif kind in ("pedestal", "crane"):
            loc += Vector((0.0, 0.0, a))
        elif kind == "pan":
            pan += math.radians(a)
        elif kind == "tilt":
            tilt += math.radians(a)
        elif kind == "roll":
            roll += math.radians(a)
        elif kind == "zoom":
            lens += a
        elif kind == "orbit":
            orbit_h += math.radians(a)
        elif kind == "orbit_vertical":
            orbit_v += math.radians(a)
        elif kind in ("push_in", "pull_out"):
            sign = 1.0 if kind == "push_in" else -1.0
            direction = (target - loc0).normalized() if target is not None else fwd
            loc += direction * a * sign

    if (orbit_h or orbit_v) and target is None:
        raise CommandError("orbit moves need a target")
    if orbit_h or orbit_v:
        offset = loc - target
        az, el, dist = cm.spherical_from_offset(offset)
        el = max(math.radians(-89.5), min(math.radians(89.5), el + orbit_v))
        loc = target + cm.spherical_offset(az + orbit_h, el, dist)

    if target is not None:
        quat = cm.look_quat(loc, target, cm.camera_roll(quat0) + roll)
        if pan or tilt:
            quat = Quaternion((0, 0, 1), pan) @ quat @ Quaternion((1, 0, 0), tilt)
    else:
        quat = Quaternion((0, 0, 1), pan) @ quat0 @ Quaternion((1, 0, 0), tilt) @ Quaternion((0, 0, 1), roll)
    return loc, quat, max(1.0, lens)


@command
def move_camera(move_type=None, amount=None, moves=None, camera=None, target=None, keyframe_frame=None):
    """Instantly apply camera moves (dolly/truck/pedestal/pan/tilt/roll/zoom/orbit/push_in/pull_out)."""
    cam = _get_camera(camera)
    norm = _normalize_moves(move_type, amount, moves)
    tgt = _resolve_point(target) if target is not None else None
    loc0, quat0 = _pose(cam)
    loc, quat, lens = _apply_moves(loc0, quat0, cam.data.lens, norm, tgt, 1.0)
    _set_pose(cam, loc, quat, _rotation_state(cam))
    cam.data.lens = lens
    _maybe_key(cam, keyframe_frame, lens=any(k == "zoom" for k, _ in norm))
    bpy.context.view_layer.update()
    return _with_warning(_camera_summary(cam, brief=True), cam)


@command
def place_camera_spherical(target, azimuth_deg=0.0, elevation_deg=15.0, distance=10.0, camera=None,
                           roll_deg=0.0, relative_to_target_front=False, keyframe_frame=None):
    """Place the camera around a target using azimuth/elevation/distance and aim at it."""
    cam = _get_camera(camera)
    tgt = _resolve_point(target)
    az = math.radians(azimuth_deg)
    if relative_to_target_front and isinstance(target, str):
        az += _front_heading_offset(_get_object(target))
    loc = tgt + cm.spherical_offset(az, math.radians(elevation_deg), float(distance))
    _set_pose(cam, loc, cm.look_quat(loc, tgt, math.radians(roll_deg or 0.0)), _rotation_state(cam))
    _maybe_key(cam, keyframe_frame)
    bpy.context.view_layer.update()
    return _with_warning(_camera_summary(cam, brief=True), cam)


def _front_heading_offset(obj):
    """Azimuth (radians) of the object's front (-Y local) relative to world -Y."""
    front = obj.matrix_world.to_3x3() @ Vector((0.0, -1.0, 0.0))
    front.z = 0.0
    if front.length < 1e-6:
        return 0.0
    az, _el, _d = cm.spherical_from_offset(front)
    return az


def _fit_camera(cam, corners, center, quat, margin):
    scene = _scene()
    forward, right, up = cm.camera_axes(quat)
    d = cam.data
    if d.type == "ORTHO":
        aspect = cm.render_aspect(scene)
        xs = max(abs((c - center).dot(right)) for c in corners)
        ys = max(abs((c - center).dot(up)) for c in corners)
        depth = max(abs((c - center).dot(forward)) for c in corners)
        fit = d.sensor_fit if d.sensor_fit != "AUTO" else ("HORIZONTAL" if aspect >= 1 else "VERTICAL")
        if fit == "HORIZONTAL":
            d.ortho_scale = max(2 * xs, 2 * ys * aspect) * (1.0 + margin)
        else:
            d.ortho_scale = max(2 * ys, 2 * xs / aspect) * (1.0 + margin)
        dist = depth + max(d.clip_start * 2, (xs + ys))
    else:
        hfov, vfov = cm.camera_fov(d, scene)
        tan_h = math.tan(hfov / 2.0) / (1.0 + margin)
        tan_v = math.tan(vfov / 2.0) / (1.0 + margin)
        dist = cm.fit_distance(corners, center, forward, right, up, tan_h, tan_v, near=d.clip_start * 1.5)
    loc = center - forward * dist
    far = max((c - loc).length for c in corners)
    if far > d.clip_end:
        d.clip_end = far * 1.5
    return loc, dist


@command
def frame_objects(objects, camera=None, margin=0.1, azimuth_deg=None, elevation_deg=None,
                  keep_direction=True, lens=None, keyframe_frame=None):
    """Move the camera so the given objects exactly fill the frame (plus margin)."""
    cam = _get_camera(camera)
    if lens is not None:
        cam.data.lens = float(lens)
    names = [objects] if isinstance(objects, str) else list(objects)
    mn, mx = _union_bbox(names)
    corners = [p for n in names for p in _object_points(_get_object(n), max_points=2000)]
    center = (mn + mx) / 2.0
    _loc0, quat0 = _pose(cam)
    if azimuth_deg is not None or elevation_deg is not None or not keep_direction:
        fwd0, _r0, _u0 = cm.camera_axes(quat0)
        az0, el0, _ = cm.spherical_from_offset(-fwd0)
        az = math.radians(azimuth_deg) if azimuth_deg is not None else az0
        el = math.radians(elevation_deg) if elevation_deg is not None else el0
        if not keep_direction and azimuth_deg is None and elevation_deg is None:
            az, el = math.radians(30.0), math.radians(20.0)
        quat = cm.direction_quat(-cm.spherical_offset(az, el, 1.0))
    else:
        fwd0, _r0, _u0 = cm.camera_axes(quat0)
        quat = cm.direction_quat(fwd0, cm.camera_roll(quat0))
    loc, dist = _fit_camera(cam, corners, center, quat, float(margin))
    _set_pose(cam, loc, quat, _rotation_state(cam))
    _maybe_key(cam, keyframe_frame, lens=lens is not None)
    bpy.context.view_layer.update()
    result = _camera_summary(cam, brief=True)
    result["distance_to_center"] = _r(dist, 3)
    result["framing"] = _analyze(cam, names)
    return _with_warning(result, cam)


SHOT_SIZES = {
    # name: (visible frame height as a multiple of subject height, aim height fraction)
    "extreme_wide": (8.0, 0.5),
    "wide": (3.0, 0.5),
    "full": (1.25, 0.5),
    "medium_wide": (0.8, 0.6),
    "cowboy": (0.8, 0.6),
    "medium": (0.55, 0.72),
    "medium_closeup": (0.36, 0.8),
    "closeup": (0.22, 0.87),
    "extreme_closeup": (0.09, 0.91),
}

SHOT_ANGLES = {
    # name: (elevation_deg, roll_deg)
    "eye_level": (0.0, 0.0),
    "high": (25.0, 0.0),
    "low": (-18.0, 0.0),
    "birds_eye": (70.0, 0.0),
    "overhead": (89.0, 0.0),
    "worms_eye": (-55.0, 0.0),
    "dutch": (0.0, 15.0),
    "dutch_low": (-15.0, 15.0),
}

SHOT_SIDES = {
    # azimuth (deg) relative to the subject's front; the subject's front is local -Y.
    "front": 0.0,
    "three_quarter_left": 45.0,
    "left": 90.0,
    "profile_left": 90.0,
    "back_left": 135.0,
    "back": 180.0,
    "over_the_shoulder": 160.0,
    "back_right": -135.0,
    "right": -90.0,
    "profile_right": -90.0,
    "three_quarter_right": -45.0,
}


@command
def apply_shot_preset(subject, shot_size="medium", angle="eye_level", side="front", camera=None,
                      lens=None, azimuth_offset_deg=0.0, use_subject_facing=True, allow_below_base=False,
                      keyframe_frame=None):
    """Position the camera for a classic cinematography shot of a subject."""
    cam = _get_camera(camera)
    try:
        frame_mult, aim_frac = SHOT_SIZES[shot_size]
    except KeyError:
        raise CommandError("shot_size must be one of %s" % list(SHOT_SIZES)) from None
    try:
        elevation, roll = SHOT_ANGLES[angle]
    except KeyError:
        raise CommandError("angle must be one of %s" % list(SHOT_ANGLES)) from None
    try:
        side_az = SHOT_SIDES[side]
    except KeyError:
        raise CommandError("side must be one of %s" % list(SHOT_SIDES)) from None

    if lens is not None:
        cam.data.lens = float(lens)
    obj = _get_object(subject)
    mn, mx = _world_bbox(obj)
    height = mx.z - mn.z
    if height < 1e-3:
        height = max(mx.x - mn.x, mx.y - mn.y, 1e-3)
    aim = Vector(((mn.x + mx.x) / 2.0, (mn.y + mx.y) / 2.0, mn.z + height * aim_frac))
    visible = height * frame_mult
    _hfov, vfov = cm.camera_fov(cam.data, _scene())
    depth_pad = max(mx.x - mn.x, mx.y - mn.y) / 2.0
    distance = (visible / 2.0) / math.tan(vfov / 2.0) + depth_pad * 0.5
    az = math.radians(side_az + azimuth_offset_deg)
    if use_subject_facing:
        az += _front_heading_offset(obj)
    loc = aim + cm.spherical_offset(az, math.radians(elevation), distance)
    adjusted = None
    min_z = mn.z + max(0.05, 0.03 * height)
    if not allow_below_base and loc.z < min_z:
        # Low angles on wide shots would sink the camera below the subject's base (the ground).
        # Keep the same line of sight distance but raise the camera to just above the base.
        horiz = Vector((loc.x - aim.x, loc.y - aim.y, 0.0))
        dz = min_z - aim.z
        flat = math.sqrt(max(distance ** 2 - dz ** 2, 1e-6))
        loc = aim + horiz.normalized() * flat + Vector((0.0, 0.0, dz))
        adjusted = ("Camera raised to z=%.3f to stay above the subject's base (ground level); "
                    "pass allow_below_base=true to disable." % min_z)
    _set_pose(cam, loc, cm.look_quat(loc, aim, math.radians(roll)), _rotation_state(cam))
    if distance * 2 > cam.data.clip_end:
        cam.data.clip_end = distance * 3
    _maybe_key(cam, keyframe_frame, lens=lens is not None)
    bpy.context.view_layer.update()
    result = _camera_summary(cam, brief=True)
    result.update({"shot": {"size": shot_size, "angle": angle, "side": side},
                   "distance": _r(distance, 3), "aim_point": _r(aim, 3),
                   "framing": _analyze(cam, [subject])})
    if adjusted:
        result["adjusted"] = adjusted
    return _with_warning(result, cam)


COMPOSITION_POINTS = {
    "center": (0.5, 0.5),
    "left_third": (1 / 3, 0.5),
    "right_third": (2 / 3, 0.5),
    "upper_third": (0.5, 2 / 3),
    "lower_third": (0.5, 1 / 3),
    "upper_left_third": (1 / 3, 2 / 3),
    "upper_right_third": (2 / 3, 2 / 3),
    "lower_left_third": (1 / 3, 1 / 3),
    "lower_right_third": (2 / 3, 1 / 3),
    "golden_left": (0.382, 0.5),
    "golden_right": (0.618, 0.5),
}


def _aim_for_screen_point(loc, target, sx, sy, cam_data, roll=0.0):
    """Orientation (level horizon + roll) placing ``target`` at screen (sx, sy)."""
    hfov, vfov = cm.camera_fov(cam_data, _scene())
    tx = (sx - 0.5) * 2.0 * math.tan(hfov / 2.0)
    ty = (sy - 0.5) * 2.0 * math.tan(vfov / 2.0)
    heading, pitch = cm.heading_pitch(target - loc)
    quat = cm.direction_quat(cm.direction_from_heading_pitch(heading, pitch), roll)
    for _ in range(12):
        v = quat.inverted() @ (target - loc)
        if v.z >= -1e-9:
            break
        cx = v.x / -v.z
        cy = v.y / -v.z
        if abs(cx - tx) < 1e-6 and abs(cy - ty) < 1e-6:
            break
        heading += math.atan(tx) - math.atan(cx)
        pitch -= math.atan(ty) - math.atan(cy)
        pitch = max(-math.pi / 2 + 1e-3, min(math.pi / 2 - 1e-3, pitch))
        quat = cm.direction_quat(cm.direction_from_heading_pitch(heading, pitch), roll)
    return quat


@command
def compose_subject(subject, position="left_third", screen_x=None, screen_y=None, camera=None,
                    keep_roll=True, keyframe_frame=None):
    """Rotate the camera (in place) so a subject lands on a composition point (rule of thirds etc.)."""
    cam = _get_camera(camera)
    if screen_x is None or screen_y is None:
        try:
            sx, sy = COMPOSITION_POINTS[position]
        except KeyError:
            raise CommandError("position must be one of %s (or give screen_x/screen_y)"
                               % list(COMPOSITION_POINTS)) from None
        sx = sx if screen_x is None else float(screen_x)
        sy = sy if screen_y is None else float(screen_y)
    else:
        sx, sy = float(screen_x), float(screen_y)
    loc, quat0 = _pose(cam)
    target = _resolve_point(subject)
    roll = cm.camera_roll(quat0) if keep_roll else 0.0
    quat = _aim_for_screen_point(loc, target, sx, sy, cam.data, roll)
    _set_pose(cam, loc, quat, _rotation_state(cam))
    _maybe_key(cam, keyframe_frame)
    bpy.context.view_layer.update()
    result = _camera_summary(cam, brief=True)
    if isinstance(subject, str):
        result["framing"] = _analyze(cam, [subject])
    return _with_warning(result, cam)


# ---------------------------------------------------------------------------
# Framing analysis
# ---------------------------------------------------------------------------

def _analyze(cam, names):
    scene = _scene()
    loc, quat = _pose(cam)
    forward, _r_, _u = cm.camera_axes(quat)
    out = []
    for name in names:
        obj = _get_object(name)
        mn, mx = _world_bbox(obj)
        center = (mn + mx) / 2.0
        points = _object_points(obj)
        proj = [world_to_camera_view(scene, cam, c) for c in points]
        near = max(cam.data.clip_start, 1e-4)
        front = [p for p in proj if p.z > near]
        c_proj = world_to_camera_view(scene, cam, center)
        entry = {"object": name, "distance": _r((center - loc).length, 3),
                 "depth": _r((center - loc).dot(forward), 3)}
        if not front:
            entry.update({"visibility": "behind_camera", "in_frame": False})
            out.append(entry)
            continue
        x0 = min(p.x for p in front)
        x1 = max(p.x for p in front)
        y0 = min(p.y for p in front)
        y1 = max(p.y for p in front)
        cx0, cx1 = max(0.0, x0), min(1.0, x1)
        cy0, cy1 = max(0.0, y0), min(1.0, y1)
        visible_area = max(0.0, cx1 - cx0) * max(0.0, cy1 - cy0)
        eps = 1e-3
        full = len(front) == len(proj) and x0 >= -eps and x1 <= 1 + eps and y0 >= -eps and y1 <= 1 + eps
        if full:
            vis = "fully_in_frame"
        elif visible_area > 0:
            vis = "partially_in_frame"
        else:
            vis = "out_of_frame"
        screen_center = [c_proj.x, c_proj.y]
        nearest = min(COMPOSITION_POINTS.items(),
                      key=lambda kv: (kv[1][0] - c_proj.x) ** 2 + (kv[1][1] - c_proj.y) ** 2)
        entry.update({
            "visibility": vis,
            "in_frame": vis != "out_of_frame",
            "screen_center": _r(screen_center, 3),
            "screen_bbox": {"left": _r(x0, 3), "right": _r(x1, 3), "bottom": _r(y0, 3), "top": _r(y1, 3)},
            "frame_coverage": _r(visible_area, 3),
            "height_fraction": _r(y1 - y0, 3),
            "width_fraction": _r(x1 - x0, 3),
            "headroom": _r(1.0 - y1, 3),
            "nearest_composition_point": nearest[0],
        })
        if c_proj.z > 0 and (c_proj.z < cam.data.clip_start or c_proj.z > cam.data.clip_end):
            entry["clipped"] = True
        out.append(entry)
    return out


@command
def analyze_framing(objects=None, camera=None, frame=None):
    """Where objects appear in the camera frame (screen bbox, coverage, headroom)."""
    cam = _get_camera(camera)
    scene = _scene()
    current = scene.frame_current
    if frame is not None and int(frame) != current:
        scene.frame_set(int(frame))
    try:
        if objects is None:
            names = [o.name for o in scene.objects
                     if o.type in {"MESH", "CURVE", "SURFACE", "FONT", "META", "ARMATURE",
                                   "GPENCIL", "GREASEPENCIL", "VOLUME", "POINTCLOUD", "CURVES"}
                     and o.visible_get()][:50]
        else:
            names = [objects] if isinstance(objects, str) else list(objects)
        result = {"camera": cam.name, "frame": scene.frame_current,
                  "screen_coords": "x/y in 0..1, origin bottom-left",
                  "objects": _analyze(cam, names)}
    finally:
        if scene.frame_current != current:
            scene.frame_set(current)
    return result


# ---------------------------------------------------------------------------
# Keyframing
# ---------------------------------------------------------------------------

@command
def insert_camera_keyframe(frame=None, camera=None, properties=None):
    """Keyframe the camera's current state at a frame."""
    cam = _get_camera(camera)
    f = int(_scene().frame_current if frame is None else frame)
    props = properties or ["location", "rotation", "lens"]
    if "all" in props:
        props = ["location", "rotation", "lens", "focus_distance", "fstop", "shift"]
    for p in props:
        if p == "location":
            cam.keyframe_insert("location", frame=f)
        elif p == "rotation":
            cam.keyframe_insert(_rot_path(cam), frame=f)
        elif p == "lens":
            _key_lens(cam, f)
        elif p == "focus_distance":
            _key_focus(cam, f)
        elif p == "fstop":
            cam.data.keyframe_insert("dof.aperture_fstop", frame=f)
        elif p == "shift":
            cam.data.keyframe_insert("shift_x", frame=f)
            cam.data.keyframe_insert("shift_y", frame=f)
        else:
            raise CommandError("Unknown property '%s'. Valid: location, rotation, lens, "
                               "focus_distance, fstop, shift, all" % p)
    _extend_scene(f)
    return {"camera": cam.name, "frame": f, "properties": props}


@command
def set_camera_keyframes(keyframes, camera=None, interpolation="BEZIER", easing="AUTO",
                         handle_type="AUTO_CLAMPED", clear_existing=False):
    """Keyframe a sequence of camera states in one call (location/look_at/rotation/lens/focus)."""
    cam = _get_camera(camera)
    if not keyframes:
        raise CommandError("keyframes must be a non-empty list")
    keys = sorted(keyframes, key=lambda k: k["frame"])
    if clear_existing:
        anim.clear_keys(cam)
        anim.clear_keys(cam.data)
    _prepare_rotation_mode(cam)
    previous = _rotation_state(cam)
    loc_prev, quat_prev = _pose(cam)
    frames = []
    for k in keys:
        if "frame" not in k:
            raise CommandError("every keyframe needs a 'frame'")
        f = int(k["frame"])
        loc = _vec3(k["location"], "location") if k.get("location") is not None else loc_prev
        roll = math.radians(k.get("roll_deg", 0.0))
        if k.get("look_at") is not None:
            quat = cm.look_quat(loc, _resolve_point(k["look_at"], "look_at"), roll)
        elif k.get("rotation_deg") is not None:
            quat = Euler([math.radians(a) for a in k["rotation_deg"]], "XYZ").to_quaternion()
        else:
            quat = quat_prev
        _set_pose(cam, loc, quat, previous)
        previous = _rotation_state(cam)
        loc_prev, quat_prev = loc, quat
        _key_transform(cam, f)
        if k.get("lens") is not None:
            cam.data.lens = float(k["lens"])
            _key_lens(cam, f)
        if k.get("focus_distance") is not None or k.get("focus_on") is not None:
            cam.data.dof.use_dof = True
            cam.data.dof.focus_object = None
            if k.get("focus_on") is not None:
                cam.data.dof.focus_distance = _focus_distance_to(cam, _resolve_point(k["focus_on"]))
            else:
                cam.data.dof.focus_distance = float(k["focus_distance"])
            _key_focus(cam, f)
        if k.get("fstop") is not None:
            cam.data.dof.aperture_fstop = float(k["fstop"])
            cam.data.keyframe_insert("dof.aperture_fstop", frame=f)
        frames.append(f)
    lo, hi = frames[0], frames[-1]
    anim.set_interpolation(cam, interpolation, easing, handle_type, lo, hi)
    anim.set_interpolation(cam.data, interpolation, easing, handle_type, lo, hi)
    extended = _extend_scene(hi, lo)
    _scene().frame_set(_scene().frame_current)
    return _with_warning({"camera": cam.name, "frames": frames, "scene_range_extended": extended}, cam)


@command
def clear_camera_animation(camera=None, frame_start=None, frame_end=None, include_lens=True,
                           include_shake=True):
    """Remove camera keyframes (optionally only within a frame range)."""
    cam = _get_camera(camera)
    removed = anim.clear_keys(cam, ["location", "rotation_euler", "rotation_quaternion", "scale"],
                              frame_start, frame_end)
    if include_lens:
        removed += anim.clear_keys(cam.data, None, frame_start, frame_end)
    shake_removed = False
    if include_shake and frame_start is None and frame_end is None:
        shake_removed = remove_camera_shake(camera=cam.name)["removed_channels"] > 0
    return {"camera": cam.name, "keyframes_removed": removed, "shake_removed": shake_removed}


@command
def set_keyframe_interpolation(camera=None, interpolation="BEZIER", easing=None, handle_type=None,
                               frame_start=None, frame_end=None, include_lens=True):
    """Change interpolation/easing/handles of existing camera keys (e.g. LINEAR for constant speed)."""
    cam = _get_camera(camera)
    n = anim.set_interpolation(cam, interpolation, easing, handle_type, frame_start, frame_end)
    if include_lens:
        n += anim.set_interpolation(cam.data, interpolation, easing, handle_type, frame_start, frame_end)
    return {"camera": cam.name, "keys_changed": n}


@command
def get_camera_animation(camera=None, frame_start=None, frame_end=None, step=None, max_samples=60):
    """Sample the evaluated camera motion over a frame range (pose, lens, speed)."""
    cam = _get_camera(camera)
    scene = _scene()
    frames_keyed = sorted(set(anim.keyframe_frames(cam)) | set(anim.keyframe_frames(cam.data)))
    start = int(frame_start if frame_start is not None else (frames_keyed[0] if frames_keyed else scene.frame_start))
    end = int(frame_end if frame_end is not None else (frames_keyed[-1] if frames_keyed else scene.frame_end))
    if end < start:
        start, end = end, start
    if step is None:
        step = max(1, int(math.ceil((end - start + 1) / float(max_samples))))
    fps = scene.render.fps / scene.render.fps_base
    current = scene.frame_current
    samples = []
    prev = None
    path_len = 0.0
    try:
        for f in _key_frames(start, max(end, start + 1), step) if end > start else [start]:
            scene.frame_set(f)
            loc, quat = _pose(cam)
            fwd, _r_, _u = cm.camera_axes(quat)
            heading, pitch = cm.heading_pitch(fwd)
            s = {"frame": f, "location": _r(loc, 3), "heading_deg": _r(math.degrees(heading), 2),
                 "pitch_deg": _r(math.degrees(pitch), 2), "roll_deg": _r(math.degrees(cm.camera_roll(quat)), 2),
                 "lens": _r(cam.data.lens, 2)}
            if cam.data.dof.use_dof:
                s["focus_distance"] = _r(cam.data.dof.focus_distance, 3)
            if prev is not None:
                d = (loc - prev[1]).length
                path_len += d
                s["speed_m_per_s"] = _r(d / ((f - prev[0]) / fps), 3)
            prev = (f, loc)
            samples.append(s)
    finally:
        scene.frame_set(current)
    return {
        "camera": cam.name,
        "keyed_frames": frames_keyed[:200],
        "fcurves": anim.fcurve_summary(cam) + [dict(c, id="camera_data") for c in anim.fcurve_summary(cam.data)],
        "sampled_range": [start, end],
        "step": step,
        "path_length": _r(path_len, 3),
        "duration_seconds": _r((end - start) / fps, 3),
        "samples": samples,
    }


# ---------------------------------------------------------------------------
# Animated moves
# ---------------------------------------------------------------------------

@command
def animate_camera_move(move_type=None, amount=None, moves=None, camera=None, target=None,
                        start_frame=None, end_frame=None, duration_frames=None, easing="ease_in_out",
                        key_step=1):
    """Animate one or more combined moves (dolly, truck, pan, tilt, crane, zoom, orbit...) over time."""
    cam = _get_camera(camera)
    norm = _normalize_moves(move_type, amount, moves)
    start, end = _frame_args(start_frame, end_frame, duration_frames)
    tgt = _resolve_point(target) if target is not None else None
    loc0, quat0, lens0 = _eval_camera_pose(cam, start)
    zoom = any(k == "zoom" for k, _ in norm)

    def pose(t):
        loc, quat, lens = _apply_moves(loc0, quat0, lens0, norm, tgt, cm.ease(easing, t))
        return {"location": loc, "rotation": quat, "lens": lens}

    result = _bake(cam, _key_frames(start, end, key_step), pose, start, end, key_lens=zoom)
    result["moves"] = [{"type": k, "amount": a} for k, a in norm]
    return _with_warning(result, cam)


@command
def animate_orbit(target, camera=None, start_frame=None, end_frame=None, duration_frames=None,
                  angle_deg=360.0, radius=None, end_radius=None, height=None, end_height=None,
                  start_azimuth_deg=None, easing="linear", roll_deg=0.0, key_step=1):
    """Orbit (turntable / arc / spiral) around a target while keeping it centred."""
    cam = _get_camera(camera)
    start, end = _frame_args(start_frame, end_frame, duration_frames)
    center = _resolve_point(target)
    loc0, _q0, _lens0 = _eval_camera_pose(cam, start)
    offset = loc0 - center
    horiz = Vector((offset.x, offset.y, 0.0))
    r0 = float(radius) if radius is not None else max(horiz.length, 0.5)
    r1 = float(end_radius) if end_radius is not None else r0
    h0 = float(height) if height is not None else offset.z
    h1 = float(end_height) if end_height is not None else h0
    if start_azimuth_deg is not None:
        az0 = math.radians(start_azimuth_deg)
    else:
        az0 = math.atan2(offset.x, -offset.y) if horiz.length > 1e-6 else 0.0
    sweep = math.radians(angle_deg)
    roll = math.radians(roll_deg or 0.0)

    def pose(t):
        e = cm.ease(easing, t)
        az = az0 + sweep * e
        r = cm.lerp(r0, r1, e)
        h = cm.lerp(h0, h1, e)
        loc = center + Vector((math.sin(az) * r, -math.cos(az) * r, h))
        return {"location": loc, "rotation": cm.look_quat(loc, center, roll)}

    result = _bake(cam, _key_frames(start, end, key_step), pose, start, end)
    result.update({"center": _r(center, 3), "radius": [_r(r0, 3), _r(r1, 3)],
                   "height": [_r(h0, 3), _r(h1, 3)], "angle_deg": angle_deg,
                   "loopable": abs(abs(angle_deg) % 360.0) < 1e-6 and easing == "linear"})
    return _with_warning(result, cam)


@command
def animate_dolly_zoom(target, camera=None, start_frame=None, end_frame=None, duration_frames=None,
                       distance_change=None, end_distance=None, easing="ease_in_out", key_step=1):
    """Vertigo / Hitchcock zoom: dolly while zooming so the subject stays the same size."""
    cam = _get_camera(camera)
    if cam.data.type != "PERSP":
        raise CommandError("dolly zoom needs a perspective camera")
    start, end = _frame_args(start_frame, end_frame, duration_frames)
    tgt = _resolve_point(target)
    loc0, _q0, lens0 = _eval_camera_pose(cam, start)
    d0 = (tgt - loc0).length
    if d0 < 1e-3:
        raise CommandError("camera is at the target")
    if end_distance is not None:
        d1 = float(end_distance)
    elif distance_change is not None:
        d1 = d0 + float(distance_change)
    else:
        d1 = d0 * 0.5
    if d1 <= 0.01:
        raise CommandError("end distance must be positive (got %.3f)" % d1)
    direction = (loc0 - tgt).normalized()
    lens1 = lens0 * d1 / d0
    warning = None
    if lens1 < 6 or lens1 > 1200:
        warning = "End focal length %.1fmm is extreme; consider a smaller distance change." % lens1

    def pose(t):
        e = cm.ease(easing, t)
        d = cm.lerp(d0, d1, e)
        loc = tgt + direction * d
        return {"location": loc, "rotation": cm.look_quat(loc, tgt), "lens": lens0 * d / d0}

    result = _bake(cam, _key_frames(start, end, key_step), pose, start, end, key_lens=True)
    result.update({"start_distance": _r(d0, 3), "end_distance": _r(d1, 3),
                   "start_lens": _r(lens0, 2), "end_lens": _r(lens1, 2)})
    if warning:
        result["lens_warning"] = warning
    return _with_warning(result, cam)


@command
def animate_path(points, camera=None, start_frame=None, end_frame=None, duration_frames=None,
                 look_mode="forward", look_target=None, look_ahead_frames=10, smooth=True, closed=False,
                 constant_speed=True, easing="linear", bank_factor=0.0, create_guide_curve=False,
                 key_step=1):
    """Fly the camera along waypoints (smooth spline) looking forward, at a target, or fixed."""
    cam = _get_camera(camera)
    start, end = _frame_args(start_frame, end_frame, duration_frames)
    pts = [_resolve_point(p, "point") for p in points]
    if len(pts) < 2:
        raise CommandError("points needs at least 2 waypoints")
    dense = cm.smooth_path(pts, closed=closed) if smooth else cm.linear_path(pts + ([pts[0]] if closed else []))
    poly = cm.Polyline(dense)
    if poly.length < 1e-6:
        raise CommandError("path has zero length")
    look_mode = look_mode.lower()
    if look_mode not in {"forward", "target", "fixed"}:
        raise CommandError("look_mode must be forward, target or fixed")
    tgt = _resolve_point(look_target, "look_target") if look_mode == "target" else None
    _loc0, quat0, _lens0 = _eval_camera_pose(cam, start)
    ahead = max(1, int(look_ahead_frames)) / float(end - start)

    def pos(t):
        e = cm.ease(easing, t)
        return poly.at_fraction(e) if constant_speed else poly.at_index_fraction(e)

    def pose(t):
        loc = pos(t)
        if look_mode == "target":
            quat = cm.look_quat(loc, tgt)
        elif look_mode == "fixed":
            quat = quat0
        else:
            t2 = t + ahead
            if t2 <= 1.0 or closed:
                aim = pos(t2 % 1.0 if closed and t2 > 1.0 else t2)
            else:
                aim = loc + (loc - pos(max(0.0, t - ahead)))
            if (aim - loc).length < 1e-6:
                aim = loc + cm.camera_axes(quat0)[0]
            roll = 0.0
            if bank_factor:
                back = pos(max(0.0, t - ahead)) if t > 0 else loc
                d1 = (loc - back)
                d2 = (aim - loc)
                d1.z = d2.z = 0.0
                if d1.length > 1e-6 and d2.length > 1e-6:
                    turn = math.atan2(d1.cross(d2).z, d1.dot(d2))
                    roll = -turn * float(bank_factor)
            quat = cm.look_quat(loc, aim, roll)
        return {"location": loc, "rotation": quat}

    result = _bake(cam, _key_frames(start, end, key_step), pose, start, end)
    fps = _scene().render.fps / _scene().render.fps_base
    result.update({"path_length": _r(poly.length, 3),
                   "average_speed_m_per_s": _r(poly.length / ((end - start) / fps), 3)})
    if create_guide_curve:
        result["guide_curve"] = _create_curve("%s_Path" % cam.name, dense[::4] + [dense[-1]], closed)
    return _with_warning(result, cam)


def _create_curve(name, points, closed=False):
    data = bpy.data.curves.new(name, "CURVE")
    data.dimensions = "3D"
    spline = data.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for p, co in zip(spline.points, points):
        p.co = (co.x, co.y, co.z, 1.0)
    spline.use_cyclic_u = closed
    obj = bpy.data.objects.new(name, data)
    obj.hide_render = True
    _scene().collection.objects.link(obj)
    return obj.name


@command
def animate_follow(target, camera=None, offset=(0.0, 6.0, 2.0), offset_space="target",
                   look_offset=(0.0, 0.0, 0.0), start_frame=None, end_frame=None, duration_frames=None,
                   position_smoothing=0.85, aim_smoothing=0.6, key_step=1):
    """Chase / follow cam: track a moving object with a smoothed offset (baked keys)."""
    cam = _get_camera(camera)
    obj = _get_object(target)
    start, end = _frame_args(start_frame, end_frame, duration_frames)
    offset = _vec3(offset, "offset")
    look_offset = _vec3(look_offset, "look_offset")
    if offset_space not in {"target", "world"}:
        raise CommandError("offset_space must be 'target' or 'world'")
    ps = min(max(float(position_smoothing), 0.0), 0.99)
    as_ = min(max(float(aim_smoothing), 0.0), 0.99)
    scene = _scene()
    current = scene.frame_current
    frames = _key_frames(start, end, key_step)
    poses = {}
    cam_pos = aim_pos = None
    try:
        for f in range(start, end + 1):
            scene.frame_set(f)
            mw = obj.matrix_world
            anchor = mw.translation.copy()
            if offset_space == "target":
                rot = mw.to_quaternion()
                desired = anchor + rot @ offset
                aim = anchor + rot @ look_offset
            else:
                desired = anchor + offset
                aim = anchor + look_offset
            if cam_pos is None:
                cam_pos, aim_pos = desired, aim
            else:
                cam_pos = cam_pos.lerp(desired, 1.0 - ps)
                aim_pos = aim_pos.lerp(aim, 1.0 - as_)
            poses[f] = (cam_pos.copy(), aim_pos.copy())
    finally:
        scene.frame_set(current)

    span = float(end - start)

    def pose(t):
        f = int(round(start + t * span))
        loc, aim = poses[f]
        return {"location": loc, "rotation": cm.look_quat(loc, aim)}

    result = _bake(cam, frames, pose, start, end)
    result["target"] = obj.name
    return _with_warning(result, cam)


@command
def animate_rack_focus(focus_targets, camera=None, frames=None, start_frame=None, end_frame=None,
                       duration_frames=None, fstop=None, easing="ease_in_out", key_step=1):
    """Pull focus between subjects (or distances) over time; enables depth of field."""
    cam = _get_camera(camera)
    if not focus_targets or len(focus_targets) < 2:
        raise CommandError("focus_targets needs at least 2 entries (object names, points or distances)")
    if frames is not None:
        stops = [int(f) for f in frames]
        if len(stops) != len(focus_targets):
            raise CommandError("frames must have one entry per focus target")
    else:
        start, end = _frame_args(start_frame, end_frame, duration_frames)
        n = len(focus_targets) - 1
        stops = [int(round(start + (end - start) * i / n)) for i in range(n + 1)]
    d = cam.data
    d.dof.use_dof = True
    d.dof.focus_object = None
    if fstop is not None:
        d.dof.aperture_fstop = float(fstop)
    anim.clear_keys(d, ["dof.focus_distance"], stops[0], stops[-1])
    distances = []
    scene = _scene()
    current = scene.frame_current
    try:
        for i, ft in enumerate(focus_targets):
            scene.frame_set(stops[i])
            if isinstance(ft, (int, float)):
                distances.append(float(ft))
            else:
                distances.append(_focus_distance_to(cam, _resolve_point(ft, "focus target")))
    finally:
        scene.frame_set(current)
    for i in range(len(stops) - 1):
        a, b = stops[i], stops[i + 1]
        for f in _key_frames(a, b, key_step):
            t = (f - a) / float(b - a) if b > a else 1.0
            d.dof.focus_distance = cm.lerp(distances[i], distances[i + 1], cm.ease(easing, t))
            _key_focus(cam, f)
    anim.set_interpolation(d, "LINEAR", frame_start=stops[0], frame_end=stops[-1],
                           data_paths=["dof.focus_distance"])
    _extend_scene(stops[-1], stops[0])
    return {"camera": cam.name, "stops": [{"frame": f, "focus_distance": _r(x, 3)}
                                          for f, x in zip(stops, distances)],
            "fstop": _r(d.dof.aperture_fstop, 2),
            "note": "Depth of field is visible in EEVEE/Cycles renders, not Workbench."}


@command
def animate_whip_pan(angle_deg=90.0, camera=None, start_frame=None, duration_frames=8, easing="ease_in_out_expo",
                     enable_motion_blur=True, key_step=1):
    """Fast whip/swish pan (with motion blur) — great as a transition."""
    cam = _get_camera(camera)
    start, end = _frame_args(start_frame, None, duration_frames)
    loc0, quat0, _lens0 = _eval_camera_pose(cam, start)
    sweep = math.radians(angle_deg)

    def pose(t):
        return {"location": loc0, "rotation": Quaternion((0, 0, 1), sweep * cm.ease(easing, t)) @ quat0}

    result = _bake(cam, _key_frames(start, end, key_step), pose, start, end)
    if enable_motion_blur:
        _scene().render.use_motion_blur = True
        result["motion_blur"] = True
    return _with_warning(result, cam)


@command
def animate_transition(camera=None, to_camera=None, to_location=None, to_look_at=None, to_rotation_deg=None,
                       to_lens=None, start_frame=None, end_frame=None, duration_frames=None,
                       easing="ease_in_out", arc_height=0.0, look_at_during=None, key_step=1):
    """Smoothly move the camera from its current pose to another camera's pose or a new pose."""
    cam = _get_camera(camera)
    start, end = _frame_args(start_frame, end_frame, duration_frames)
    loc0, quat0, lens0 = _eval_camera_pose(cam, start)
    if to_camera:
        other = _get_camera(to_camera)
        loc1, quat1 = _pose(other)
        lens1 = other.data.lens
    else:
        loc1 = _vec3(to_location, "to_location") if to_location is not None else loc0
        if to_look_at is not None:
            quat1 = cm.look_quat(loc1, _resolve_point(to_look_at, "to_look_at"))
        elif to_rotation_deg is not None:
            quat1 = Euler([math.radians(a) for a in to_rotation_deg], "XYZ").to_quaternion()
        else:
            quat1 = quat0
        lens1 = lens0
    if to_lens is not None:
        lens1 = float(to_lens)
    during = _resolve_point(look_at_during, "look_at_during") if look_at_during is not None else None
    arc = float(arc_height or 0.0)
    q1 = cm.compat_quat(quat1, quat0)

    def pose(t):
        e = cm.ease(easing, t)
        loc = loc0.lerp(loc1, e) + Vector((0.0, 0.0, arc * 4.0 * e * (1.0 - e)))
        if during is not None:
            quat = cm.look_quat(loc, during)
        else:
            quat = quat0.slerp(q1, e)
        return {"location": loc, "rotation": quat, "lens": cm.lerp(lens0, lens1, e)}

    result = _bake(cam, _key_frames(start, end, key_step), pose, start, end,
                   key_lens=abs(lens1 - lens0) > 1e-6)
    result.update({"from": _r(loc0, 3), "to": _r(loc1, 3)})
    return _with_warning(result, cam)


# ---------------------------------------------------------------------------
# Shake
# ---------------------------------------------------------------------------

SHAKE_PRESETS = {
    # rotation amplitude (deg), rotation period (frames), location amplitude (m), location period
    "handheld": (0.6, 22.0, 0.012, 30.0),
    "subtle": (0.2, 45.0, 0.004, 60.0),
    "breathing": (0.12, 70.0, 0.006, 90.0),
    "walking": (0.9, 11.0, 0.03, 13.0),
    "running": (1.8, 6.0, 0.06, 7.0),
    "vehicle": (0.4, 4.0, 0.015, 5.0),
    "helicopter": (0.35, 3.0, 0.02, 25.0),
    "earthquake": (2.5, 3.0, 0.12, 3.5),
    "explosion": (4.0, 2.0, 0.2, 2.5),
}


@command
def add_camera_shake(preset="handheld", intensity=1.0, camera=None, start_frame=None, end_frame=None,
                     blend_in_frames=0, blend_out_frames=0, rotation=True, location=True, seed=0,
                     frequency_multiplier=1.0):
    """Procedural camera shake (noise) layered on top of existing motion via delta transforms."""
    cam = _get_camera(camera)
    if cam.rotation_mode == "QUATERNION":
        raise CommandError("Camera uses quaternion rotation; shake needs an Euler rotation_mode")
    try:
        rot_amp, rot_period, loc_amp, loc_period = SHAKE_PRESETS[preset]
    except KeyError:
        raise CommandError("preset must be one of %s" % list(SHAKE_PRESETS)) from None
    remove_camera_shake(camera=cam.name)
    freq = max(0.01, float(frequency_multiplier))
    scene = _scene()
    key_frame = int(start_frame) if start_frame is not None else scene.frame_start
    channels = []
    if rotation:
        channels += [("delta_rotation_euler", i, math.radians(rot_amp) * intensity, rot_period / freq)
                     for i in range(3)]
    if location:
        channels += [("delta_location", i, loc_amp * intensity, loc_period / freq) for i in range(3)]
    for n, (path, idx, amp, period) in enumerate(channels):
        fc = anim.ensure_fcurve(cam, path, idx, key_frame)
        mod = fc.modifiers.new("NOISE")
        mod.blend_type = "ADD"
        mod.scale = max(0.5, period)
        mod.strength = amp * 2.0
        mod.phase = 1.0 + seed * 7.31 + n * 13.37
        mod.offset = seed * 101.0 + n * 17.0
        if hasattr(mod, "depth"):
            mod.depth = 1
        if start_frame is not None or end_frame is not None:
            mod.use_restricted_range = True
            mod.frame_start = int(start_frame) if start_frame is not None else scene.frame_start
            mod.frame_end = int(end_frame) if end_frame is not None else scene.frame_end
            mod.blend_in = float(blend_in_frames)
            mod.blend_out = float(blend_out_frames)
    result = {"camera": cam.name, "preset": preset, "intensity": intensity, "channels": len(channels),
              "rotation_amplitude_deg": _r(rot_amp * intensity, 3),
              "location_amplitude_m": _r(loc_amp * intensity, 4)}
    if rotation and _warn_constraints(cam):
        result["warning"] = ("Tracking constraints override rotation shake; only location shake "
                             "will be visible. Bake the aim with look_at keys instead.")
    return result


@command
def remove_camera_shake(camera=None):
    """Remove procedural shake added by add_camera_shake."""
    cam = _get_camera(camera)
    removed = 0
    for fc in list(anim.fcurves(cam)):
        if fc.data_path in {"delta_rotation_euler", "delta_location"}:
            if any(m.type == "NOISE" for m in fc.modifiers):
                anim.remove_fcurve(cam, fc)
                removed += 1
    if removed:
        cam.delta_rotation_euler = (0.0, 0.0, 0.0)
        cam.delta_location = (0.0, 0.0, 0.0)
    return {"camera": cam.name, "removed_channels": removed}


# ---------------------------------------------------------------------------
# Constraints
# ---------------------------------------------------------------------------

@command
def add_track_constraint(target, camera=None, constraint_type="TRACK_TO", influence=1.0,
                         target_name="CameraTarget"):
    """Make the camera always aim at an object (or at a new empty placed at a point)."""
    cam = _get_camera(camera)
    constraint_type = constraint_type.upper()
    if constraint_type not in {"TRACK_TO", "DAMPED_TRACK", "LOCKED_TRACK"}:
        raise CommandError("constraint_type must be TRACK_TO, DAMPED_TRACK or LOCKED_TRACK")
    if isinstance(target, str):
        tgt_obj = _get_object(target)
        created = None
    else:
        tgt_obj = bpy.data.objects.new(target_name, None)
        tgt_obj.empty_display_type = "SPHERE"
        tgt_obj.empty_display_size = 0.25
        tgt_obj.location = _vec3(target, "target")
        _scene().collection.objects.link(tgt_obj)
        created = tgt_obj.name
    c = cam.constraints.new(constraint_type)
    c.target = tgt_obj
    c.influence = float(influence)
    if constraint_type == "TRACK_TO":
        c.track_axis = "TRACK_NEGATIVE_Z"
        c.up_axis = "UP_Y"
    elif constraint_type == "DAMPED_TRACK":
        c.track_axis = "TRACK_NEGATIVE_Z"
    else:
        c.track_axis = "TRACK_NEGATIVE_Z"
        c.lock_axis = "LOCK_Z"
    bpy.context.view_layer.update()
    return {"camera": cam.name, "constraint": c.name, "target": tgt_obj.name, "created_empty": created}


@command
def remove_camera_constraints(camera=None, constraint_type=None, bake_current_pose=True):
    """Remove camera constraints; by default keeps the pose they produced at the current frame."""
    cam = _get_camera(camera)
    mw = cam.matrix_world.copy()
    removed = []
    for c in list(cam.constraints):
        if constraint_type and c.type != constraint_type.upper():
            continue
        removed.append(c.name)
        cam.constraints.remove(c)
    if bake_current_pose and removed:
        cam.matrix_world = mw
    bpy.context.view_layer.update()
    return {"camera": cam.name, "removed": removed}


# ---------------------------------------------------------------------------
# Timeline, cuts, render settings
# ---------------------------------------------------------------------------

@command
def set_frame_range(frame_start=None, frame_end=None, fps=None, current_frame=None):
    """Set scene frame range, frame rate and/or current frame."""
    scene = _scene()
    if frame_start is not None:
        scene.frame_start = int(frame_start)
    if frame_end is not None:
        scene.frame_end = int(frame_end)
    if fps is not None:
        fps = float(fps)
        whole = round(fps)
        if abs(fps - whole) < 1e-6:
            scene.render.fps, scene.render.fps_base = int(whole), 1.0
        else:
            scene.render.fps = int(math.ceil(fps))
            scene.render.fps_base = math.ceil(fps) / fps
    if current_frame is not None:
        scene.frame_set(int(current_frame))
    r = scene.render
    return {"frame_start": scene.frame_start, "frame_end": scene.frame_end,
            "fps": _r(r.fps / r.fps_base, 3), "current_frame": scene.frame_current}


def _camera_cuts():
    return [{"frame": m.frame, "camera": m.camera.name, "marker": m.name}
            for m in sorted(_scene().timeline_markers, key=lambda m: m.frame) if m.camera]


@command
def add_camera_cut(camera, frame):
    """Switch the active camera at a frame (timeline marker bound to the camera)."""
    cam = _get_camera(camera)
    scene = _scene()
    for m in list(scene.timeline_markers):
        if m.frame == int(frame) and m.camera:
            scene.timeline_markers.remove(m)
    m = scene.timeline_markers.new("cut_%s" % cam.name, frame=int(frame))
    m.camera = cam
    scene.frame_set(scene.frame_current)
    return {"cuts": _camera_cuts()}


@command
def list_camera_cuts():
    """List camera switch markers."""
    return {"cuts": _camera_cuts()}


@command
def clear_camera_cuts(frame=None):
    """Remove camera switch markers (all, or only at one frame)."""
    scene = _scene()
    n = 0
    for m in list(scene.timeline_markers):
        if m.camera and (frame is None or m.frame == int(frame)):
            scene.timeline_markers.remove(m)
            n += 1
    return {"removed": n, "cuts": _camera_cuts()}


ASPECT_PRESETS = {
    "16:9": (1920, 1080), "4k_16:9": (3840, 2160), "2.39:1": (1920, 804), "2.35:1": (1920, 817),
    "1.85:1": (1998, 1080), "4:3": (1440, 1080), "1:1": (1080, 1080), "9:16": (1080, 1920),
    "4:5": (1080, 1350), "21:9": (2560, 1080),
}


@command
def set_render_settings(resolution_x=None, resolution_y=None, aspect_preset=None, resolution_percentage=None,
                        motion_blur=None, shutter=None, engine=None):
    """Resolution / aspect ratio / motion blur / render engine."""
    r = _scene().render
    if aspect_preset:
        try:
            r.resolution_x, r.resolution_y = ASPECT_PRESETS[aspect_preset]
        except KeyError:
            raise CommandError("aspect_preset must be one of %s" % list(ASPECT_PRESETS)) from None
    if resolution_x is not None:
        r.resolution_x = int(resolution_x)
    if resolution_y is not None:
        r.resolution_y = int(resolution_y)
    if resolution_percentage is not None:
        r.resolution_percentage = int(resolution_percentage)
    if motion_blur is not None:
        r.use_motion_blur = bool(motion_blur)
    if shutter is not None:
        r.motion_blur_shutter = float(shutter)
    if engine:
        r.engine = _engine_id(engine)
    return {"resolution": [r.resolution_x, r.resolution_y, r.resolution_percentage],
            "motion_blur": r.use_motion_blur, "shutter": _r(r.motion_blur_shutter, 3), "engine": r.engine}


def _engine_id(name):
    """Map a friendly engine name to the identifier this Blender build accepts."""
    name = name.upper()
    aliases = {
        "WORKBENCH": ["BLENDER_WORKBENCH"],
        "EEVEE": ["BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"],
        "BLENDER_EEVEE": ["BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"],
        "BLENDER_EEVEE_NEXT": ["BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"],
        "CYCLES": ["CYCLES"],
    }
    if name == "CURRENT":
        return _scene().render.engine
    if name == "AUTO":
        # Workbench is fastest but needs a GPU context, which background Blender may lack.
        name = "CYCLES" if bpy.app.background else "WORKBENCH"
    r = _scene().render
    original = r.engine
    try:
        for cand in aliases.get(name, [name]):
            try:
                r.engine = cand
            except TypeError:
                continue
            return cand
    finally:
        r.engine = original
    raise CommandError("Unknown render engine '%s'. Use AUTO, WORKBENCH, EEVEE, CYCLES or CURRENT." % name)


# ---------------------------------------------------------------------------
# Viewport
# ---------------------------------------------------------------------------

@command
def view_through_camera(camera=None):
    """Set camera active and switch 3D viewports to look through it (UI sessions only)."""
    cam = _get_camera(camera)
    _scene().camera = cam
    switched = 0
    wm = bpy.context.window_manager
    for window in getattr(wm, "windows", []):
        for area in window.screen.areas:
            if area.type == "VIEW_3D":
                area.spaces.active.region_3d.view_perspective = "CAMERA"
                area.tag_redraw()
                switched += 1
    return {"active_camera": cam.name, "viewports_switched": switched}


# ---------------------------------------------------------------------------
# Bookmarks
# ---------------------------------------------------------------------------

def _bookmarks():
    raw = _scene().get(BOOKMARK_KEY)
    return json.loads(raw) if raw else {}


@command
def save_camera_bookmark(name, camera=None):
    """Remember the camera's current pose + lens under a name."""
    cam = _get_camera(camera)
    loc, quat = _pose(cam)
    marks = _bookmarks()
    marks[name] = {"location": list(loc), "rotation_quat": list(quat), "lens": cam.data.lens,
                   "focus_distance": cam.data.dof.focus_distance, "camera": cam.name}
    _scene()[BOOKMARK_KEY] = json.dumps(marks)
    return {"saved": name, "bookmarks": sorted(marks)}


@command
def apply_camera_bookmark(name, camera=None, keyframe_frame=None):
    """Restore a saved camera pose (optionally keyframing it)."""
    cam = _get_camera(camera)
    marks = _bookmarks()
    if name not in marks:
        raise CommandError("No bookmark '%s'. Saved: %s" % (name, sorted(marks)))
    m = marks[name]
    _set_pose(cam, Vector(m["location"]), Quaternion(m["rotation_quat"]), _rotation_state(cam))
    cam.data.lens = m["lens"]
    cam.data.dof.focus_distance = m.get("focus_distance", cam.data.dof.focus_distance)
    _maybe_key(cam, keyframe_frame, lens=True)
    bpy.context.view_layer.update()
    return _camera_summary(cam, brief=True)


@command
def list_camera_bookmarks():
    """List saved camera bookmarks."""
    return {name: {"location": _r(v["location"], 3), "lens": _r(v["lens"], 2), "camera": v.get("camera")}
            for name, v in _bookmarks().items()}


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

from . import render as _render  # noqa: E402  (needs helpers above)


@command
def render_preview(camera=None, frame=None, max_size=768, engine="AUTO", samples=16,
                   filepath=None):
    """Render a still from a camera and return it as base64 PNG."""
    cam = _get_camera(camera)
    return _render.render_still(_scene(), cam, frame, int(max_size), _engine_id(engine), int(samples), filepath)


@command
def render_contact_sheet(camera=None, frames=None, count=6, columns=3, frame_start=None, frame_end=None,
                         max_size=384, engine="AUTO", samples=8, filepath=None):
    """Render several frames of the camera animation tiled into one PNG (base64)."""
    scene = _scene()
    use_cuts = camera is None and bool(_camera_cuts())
    cam = None if use_cuts else _get_camera(camera)
    if frames is None:
        a = int(frame_start if frame_start is not None else scene.frame_start)
        b = int(frame_end if frame_end is not None else scene.frame_end)
        count = max(1, min(int(count), 24))
        frames = [a] if count == 1 else [int(round(a + (b - a) * i / (count - 1))) for i in range(count)]
    frames = [int(f) for f in frames][:24]
    return _render.contact_sheet(scene, cam, frames, int(columns), int(max_size), _engine_id(engine),
                                 int(samples), filepath)


# ---------------------------------------------------------------------------
# Escape hatch
# ---------------------------------------------------------------------------

@command
def execute_python(code):
    """Run arbitrary Python in Blender (disabled unless enabled in add-on preferences)."""
    if not PYTHON_ALLOWED["value"]:
        raise CommandError("execute_python is disabled. Enable 'Allow arbitrary Python' in the "
                           "Camera MCP add-on preferences.")
    buf = io.StringIO()
    namespace = {"bpy": bpy, "mathutils": __import__("mathutils"), "math": math, "result": None}
    with contextlib.redirect_stdout(buf):
        exec(compile(code, "<mcp>", "exec"), namespace)  # noqa: S102
    result = namespace.get("result")
    try:
        json.dumps(result)
    except TypeError:
        result = repr(result)
    return {"stdout": buf.getvalue()[-10000:], "result": result}
