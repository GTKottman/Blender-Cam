"""F-Curve / keyframe helpers that work on Blender 4.2 LTS through 5.x.

Blender 4.4 introduced slotted (layered) actions and 5.0 removed the legacy
``Action.fcurves`` accessor, so all F-Curve access goes through here.
"""

import bpy

INTERPOLATIONS = ("CONSTANT", "LINEAR", "BEZIER", "SINE", "QUAD", "CUBIC",
                  "QUART", "QUINT", "EXPO", "CIRC", "BACK", "BOUNCE", "ELASTIC")
EASING_MODES = ("AUTO", "EASE_IN", "EASE_OUT", "EASE_IN_OUT")
HANDLE_TYPES = ("FREE", "ALIGNED", "VECTOR", "AUTO", "AUTO_CLAMPED")


def fcurves(id_data):
    """All F-Curves animating ``id_data`` (empty list if none)."""
    ad = getattr(id_data, "animation_data", None)
    if ad is None or ad.action is None:
        return []
    action = ad.action
    slot = getattr(ad, "action_slot", None)
    if slot is not None:
        try:
            from bpy_extras import anim_utils
            channelbag = anim_utils.action_get_channelbag_for_slot(action, slot)
        except (ImportError, AttributeError):
            channelbag = None
        if channelbag is not None:
            return list(channelbag.fcurves)
        if not hasattr(action, "fcurves"):
            return []
    return list(getattr(action, "fcurves", []))


def find_fcurve(id_data, data_path, index=0):
    for fc in fcurves(id_data):
        if fc.data_path == data_path and fc.array_index == index:
            return fc
    return None


def remove_fcurve(id_data, fc):
    ad = id_data.animation_data
    action = ad.action
    slot = getattr(ad, "action_slot", None)
    if slot is not None:
        try:
            from bpy_extras import anim_utils
            channelbag = anim_utils.action_get_channelbag_for_slot(action, slot)
        except (ImportError, AttributeError):
            channelbag = None
        if channelbag is not None:
            channelbag.fcurves.remove(fc)
            return
    action.fcurves.remove(fc)


def keyframe_frames(id_data, data_paths=None):
    frames = set()
    for fc in fcurves(id_data):
        if data_paths and fc.data_path not in data_paths:
            continue
        for kp in fc.keyframe_points:
            frames.add(round(kp.co.x, 3))
    return sorted(frames)


def set_interpolation(id_data, interpolation=None, easing=None, handle_type=None,
                      frame_start=None, frame_end=None, data_paths=None):
    """Set interpolation/easing/handles for keys in an (inclusive) frame range."""
    if interpolation and interpolation not in INTERPOLATIONS:
        raise ValueError("interpolation must be one of %s" % ", ".join(INTERPOLATIONS))
    if easing and easing not in EASING_MODES:
        raise ValueError("easing must be one of %s" % ", ".join(EASING_MODES))
    if handle_type and handle_type not in HANDLE_TYPES:
        raise ValueError("handle_type must be one of %s" % ", ".join(HANDLE_TYPES))
    count = 0
    for fc in fcurves(id_data):
        if data_paths and fc.data_path not in data_paths:
            continue
        for kp in fc.keyframe_points:
            f = kp.co.x
            if frame_start is not None and f < frame_start - 1e-4:
                continue
            if frame_end is not None and f > frame_end + 1e-4:
                continue
            if interpolation:
                kp.interpolation = interpolation
            if easing:
                kp.easing = easing
            if handle_type:
                kp.handle_left_type = handle_type
                kp.handle_right_type = handle_type
            count += 1
        fc.update()
    return count


def clear_keys(id_data, data_paths=None, frame_start=None, frame_end=None):
    """Delete keys (optionally only in a frame range / for some data paths).

    F-Curves left without keys (and without modifiers) are removed.
    Returns the number of keyframes removed.
    """
    removed = 0
    for fc in list(fcurves(id_data)):
        if data_paths and fc.data_path not in data_paths:
            continue
        if frame_start is None and frame_end is None:
            removed += len(fc.keyframe_points)
            remove_fcurve(id_data, fc)
            continue
        points = fc.keyframe_points
        for i in range(len(points) - 1, -1, -1):
            f = points[i].co.x
            if frame_start is not None and f < frame_start - 1e-4:
                continue
            if frame_end is not None and f > frame_end + 1e-4:
                continue
            points.remove(points[i], fast=True)
            removed += 1
        fc.update()
        if len(fc.keyframe_points) == 0 and len(fc.modifiers) == 0:
            remove_fcurve(id_data, fc)
    return removed


def fcurve_summary(id_data):
    out = []
    for fc in fcurves(id_data):
        kps = fc.keyframe_points
        entry = {
            "data_path": fc.data_path,
            "index": fc.array_index,
            "keys": len(kps),
        }
        if len(kps):
            entry["frame_range"] = [round(kps[0].co.x, 2), round(kps[-1].co.x, 2)]
            entry["interpolations"] = sorted({kp.interpolation for kp in kps})
        if len(fc.modifiers):
            entry["modifiers"] = [m.type for m in fc.modifiers]
        out.append(entry)
    return out


def ensure_fcurve(id_data, data_path, index, frame):
    """Return the F-Curve for ``data_path[index]``, keying the current value if needed."""
    fc = find_fcurve(id_data, data_path, index)
    if fc is None:
        id_data.keyframe_insert(data_path, index=index, frame=frame)
        fc = find_fcurve(id_data, data_path, index)
    return fc


def version():
    return tuple(bpy.app.version)
