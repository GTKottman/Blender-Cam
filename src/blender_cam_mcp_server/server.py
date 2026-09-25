"""MCP tools for AI-directed camera work in Blender.

Each tool forwards to the Camera MCP add-on running inside Blender. Tools are
grouped as: inspect -> set up -> position/frame -> animate -> review.
"""

import base64
import json
import os
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import Field

try:  # MCP Python SDK 2.x
    from mcp.server.mcpserver import Image
    from mcp.server.mcpserver import MCPServer as _Server
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # MCP Python SDK 1.x
    from mcp.server.fastmcp import FastMCP as _Server
    from mcp.server.fastmcp import Image
    from mcp.server.fastmcp.exceptions import ToolError

from .connection import BlenderConnection, BlenderError

INSTRUCTIONS = """\
Control Blender cameras: place, frame, compose and animate them, then look at the result.

Coordinates are Blender world units (metres), Z is up. Angles are degrees. Anywhere a
`target` is accepted you may pass an object name (its bounding-box centre is used) or an
[x, y, z] point. `camera` is optional everywhere and defaults to the scene's active camera.

Recommended workflow:
1. get_scene_info — learn object names, sizes, frame range and existing cameras.
2. create_camera / set_camera_lens — pick a lens (24mm wide, 35mm natural, 50mm normal,
   85mm portrait, 135mm+ telephoto compression).
3. Position: apply_shot_preset (cinematic shot sizes/angles), frame_objects (fit objects),
   place_camera_spherical, look_at, compose_subject (rule of thirds), move_camera.
4. Check composition numerically with analyze_framing, visually with render_preview.
5. Animate: animate_camera_move (dolly/truck/pan/tilt/crane/zoom/orbit, combinable),
   animate_orbit, animate_path (fly-through), animate_follow (chase cam), animate_dolly_zoom,
   animate_transition (A->B), animate_rack_focus, animate_whip_pan, set_camera_keyframes
   (hand-authored keys), add_camera_shake (handheld realism).
6. Review with get_camera_animation (numbers) and render_contact_sheet (images).
Multi-camera edits: create several cameras, then add_camera_cut to switch between them.
Animated moves bake keyframes over [start_frame, end_frame] and replace existing camera
keys in that range; start_frame defaults to the current frame.
"""

mcp = _Server("blender-camera", instructions=INSTRUCTIONS)
_blender = BlenderConnection()

Target = Union[str, list[float]]
Vec3 = Annotated[list[float], Field(min_length=3, max_length=3)]
Easing = Literal["linear", "ease_in", "ease_out", "ease_in_out", "ease_in_quad", "ease_out_quad",
                 "ease_in_out_quad", "ease_in_out_sine", "ease_in_out_expo", "smoothstep",
                 "smootherstep", "ease_out_back"]


def D(text):
    return Field(description=text)


CAMERA = "Camera object name. Omit to use the scene's active camera."
TARGET = "Object name (uses its bounding-box centre) or [x, y, z] world point."
KEYFRAME = "If set, also insert a keyframe of the new pose at this frame."
START = "First frame of the move. Defaults to the scene's current frame."
END = "Last frame of the move. Give end_frame or duration_frames."
DURATION = "Length of the move in frames (used when end_frame is omitted)."
STEP = "Bake a key every N frames (1 = exact every frame)."


def _call(command, **params):
    try:
        return _blender.send(command, params)
    except BlenderError as exc:
        # ToolError messages reach the model verbatim (other exceptions are masked).
        raise ToolError(str(exc)) from exc


def _out(result):
    return json.dumps(result, separators=(",", ":"))


def _image_result(result):
    data = base64.b64decode(result.pop("png_base64"))
    return [Image(data=data, format="png"), _out(result)]


# ---------------------------------------------------------------------------
# Inspect
# ---------------------------------------------------------------------------

@mcp.tool()
def get_scene_info(
    include_objects: Annotated[bool, D("Include every object's name, type, centre and size.")] = True,
    max_objects: Annotated[int, D("Cap on listed objects.")] = 100,
) -> str:
    """Scene overview: frame range, fps, resolution, cameras, camera cuts and object bounds.

    Call this first to learn object names and sizes before positioning cameras."""
    return _out(_call("get_scene_info", include_objects=include_objects, max_objects=max_objects))


@mcp.tool()
def list_cameras() -> str:
    """List cameras with location, direction, lens and field of view."""
    return _out(_call("list_cameras"))


@mcp.tool()
def get_camera_info(camera: Annotated[Optional[str], D(CAMERA)] = None) -> str:
    """Full camera details: world pose, heading/pitch/roll, lens, FOV, sensor, clipping, depth of
    field, constraints, keyed frames and shake."""
    return _out(_call("get_camera_info", camera=camera))


@mcp.tool()
def analyze_framing(
    objects: Annotated[Optional[list[str]], D("Objects to check. Omit for all visible geometry.")] = None,
    camera: Annotated[Optional[str], D(CAMERA)] = None,
    frame: Annotated[Optional[int], D("Evaluate at this frame (default: current).")] = None,
) -> str:
    """Report where objects land in the camera frame without rendering.

    Per object: visibility (fully/partially/out of frame, behind camera), screen-space
    bounding box and centre (0..1, origin bottom-left), frame coverage, height fraction,
    headroom, distance and the nearest rule-of-thirds point. Use it to verify composition."""
    return _out(_call("analyze_framing", objects=objects, camera=camera, frame=frame))


@mcp.tool()
def get_camera_animation(
    camera: Annotated[Optional[str], D(CAMERA)] = None,
    frame_start: Annotated[Optional[int], D("Start of sampled range (default: first key).")] = None,
    frame_end: Annotated[Optional[int], D("End of sampled range (default: last key).")] = None,
    step: Annotated[Optional[int], D("Sample every N frames (default: auto from max_samples).")] = None,
    max_samples: Annotated[int, D("Upper bound on returned samples.")] = 60,
) -> str:
    """Sample the evaluated camera motion: per-frame location, heading/pitch/roll, lens, focus and
    speed, plus keyed frames, F-Curve summary, path length and duration. Use it to review moves."""
    return _out(_call("get_camera_animation", camera=camera, frame_start=frame_start,
                      frame_end=frame_end, step=step, max_samples=max_samples))


# ---------------------------------------------------------------------------
# Set up
# ---------------------------------------------------------------------------

SensorPreset = Literal["full_frame", "super35", "aps_c", "aps_c_canon", "micro_four_thirds", "super16",
                       "imax", "alexa_lf", "red_monstro", "one_inch", "smartphone"]


@mcp.tool()
def create_camera(
    name: Annotated[str, D("Name for the new camera.")] = "Camera",
    location: Annotated[Optional[Vec3], D("World position. Default [0, -10, 2].")] = None,
    look_at: Annotated[Optional[Target], D("Aim at this. " + TARGET)] = None,
    rotation_deg: Annotated[Optional[Vec3], D("XYZ Euler rotation (deg) if not using look_at.")] = None,
    lens: Annotated[Optional[float], D("Focal length in mm (default 50).")] = None,
    sensor_preset: Annotated[Optional[SensorPreset], D("Real-world sensor size.")] = None,
    set_active: Annotated[bool, D("Make it the scene's render camera.")] = True,
) -> str:
    """Create a new camera, optionally aimed at a target, and (by default) make it active."""
    return _out(_call("create_camera", name=name, location=location, look_at=look_at,
                      rotation_deg=rotation_deg, lens=lens, sensor_preset=sensor_preset,
                      set_active=set_active))


@mcp.tool()
def duplicate_camera(
    camera: Annotated[Optional[str], D(CAMERA)] = None,
    name: Annotated[Optional[str], D("Name for the copy.")] = None,
    copy_animation: Annotated[bool, D("Also copy keyframes.")] = False,
) -> str:
    """Copy a camera (pose + lens) as a starting point for an alternate angle."""
    return _out(_call("duplicate_camera", camera=camera, name=name, copy_animation=copy_animation))


@mcp.tool()
def delete_camera(camera: Annotated[str, D("Camera to delete.")]) -> str:
    """Delete a camera."""
    return _out(_call("delete_camera", camera=camera))


@mcp.tool()
def set_active_camera(camera: Annotated[str, D("Camera to render through.")]) -> str:
    """Make a camera the scene's active (render) camera."""
    return _out(_call("set_active_camera", camera=camera))


@mcp.tool()
def set_camera_lens(
    camera: Annotated[Optional[str], D(CAMERA)] = None,
    lens: Annotated[Optional[float], D("Focal length in mm.")] = None,
    fov_deg: Annotated[Optional[float], D("Alternatively set the field of view in degrees.")] = None,
    fov_axis: Annotated[Literal["horizontal", "vertical"], D("Axis fov_deg refers to.")] = "horizontal",
    lens_type: Annotated[Optional[Literal["PERSP", "ORTHO", "PANO"]], D("Projection.")] = None,
    sensor_preset: Annotated[Optional[SensorPreset], D("Real-world sensor size.")] = None,
    sensor_width: Annotated[Optional[float], D("Sensor width mm.")] = None,
    sensor_height: Annotated[Optional[float], D("Sensor height mm.")] = None,
    sensor_fit: Annotated[Optional[Literal["AUTO", "HORIZONTAL", "VERTICAL"]], D("Sensor fit.")] = None,
    ortho_scale: Annotated[Optional[float], D("Orthographic view width in metres.")] = None,
    clip_start: Annotated[Optional[float], D("Near clip distance.")] = None,
    clip_end: Annotated[Optional[float], D("Far clip distance.")] = None,
    shift_x: Annotated[Optional[float], D("Horizontal lens shift (fraction of frame).")] = None,
    shift_y: Annotated[Optional[float], D("Vertical lens shift, e.g. to keep verticals straight.")] = None,
    keyframe_frame: Annotated[Optional[int], D("Keyframe the focal length at this frame.")] = None,
) -> str:
    """Set focal length / field of view, projection, sensor, clipping and lens shift."""
    return _out(_call("set_camera_lens", camera=camera, lens=lens, fov_deg=fov_deg, fov_axis=fov_axis,
                      lens_type=lens_type, sensor_preset=sensor_preset, sensor_width=sensor_width,
                      sensor_height=sensor_height, sensor_fit=sensor_fit, ortho_scale=ortho_scale,
                      clip_start=clip_start, clip_end=clip_end, shift_x=shift_x, shift_y=shift_y,
                      keyframe_frame=keyframe_frame))


@mcp.tool()
def set_depth_of_field(
    camera: Annotated[Optional[str], D(CAMERA)] = None,
    enabled: Annotated[bool, D("Turn depth of field on/off.")] = True,
    focus_object: Annotated[Optional[str], D("Keep this object in focus (follows it). '' clears.")] = None,
    focus_point: Annotated[Optional[Target], D("Focus at the distance of this point. " + TARGET)] = None,
    focus_distance: Annotated[Optional[float], D("Focus distance in metres.")] = None,
    fstop: Annotated[Optional[float], D("Aperture f-stop; lower = shallower focus (1.4 dreamy, 8 deep).")] = None,
    blades: Annotated[Optional[int], D("Aperture blades (bokeh shape), 0 = round.")] = None,
    rotation_deg: Annotated[Optional[float], D("Aperture rotation.")] = None,
    ratio: Annotated[Optional[float], D("Anamorphic bokeh ratio (>1 = oval).")] = None,
    keyframe_frame: Annotated[Optional[int], D("Keyframe focus distance and f-stop at this frame.")] = None,
) -> str:
    """Configure depth of field (visible in EEVEE/Cycles)."""
    return _out(_call("set_depth_of_field", camera=camera, enabled=enabled, focus_object=focus_object,
                      focus_point=focus_point, focus_distance=focus_distance, fstop=fstop, blades=blades,
                      rotation_deg=rotation_deg, ratio=ratio, keyframe_frame=keyframe_frame))


# ---------------------------------------------------------------------------
# Position & frame
# ---------------------------------------------------------------------------

@mcp.tool()
def set_camera_transform(
    camera: Annotated[Optional[str], D(CAMERA)] = None,
    location: Annotated[Optional[Vec3], D("New world position (omit to keep).")] = None,
    rotation_deg: Annotated[Optional[Vec3], D("XYZ Euler rotation in degrees.")] = None,
    look_at: Annotated[Optional[Target], D("Aim at this instead of rotation_deg. " + TARGET)] = None,
    roll_deg: Annotated[float, D("Roll around the view axis when using look_at (dutch angle).")] = 0.0,
    keyframe_frame: Annotated[Optional[int], D(KEYFRAME)] = None,
) -> str:
    """Set the camera's world position and orientation directly."""
    return _out(_call("set_camera_transform", camera=camera, location=location, rotation_deg=rotation_deg,
                      look_at=look_at, roll_deg=roll_deg, keyframe_frame=keyframe_frame))


@mcp.tool()
def look_at(
    target: Annotated[Target, D(TARGET)],
    camera: Annotated[Optional[str], D(CAMERA)] = None,
    roll_deg: Annotated[float, D("Roll around the view axis (positive = counter-clockwise).")] = 0.0,
    keyframe_frame: Annotated[Optional[int], D(KEYFRAME)] = None,
) -> str:
    """Rotate the camera in place so it points at a target, horizon level (plus optional roll)."""
    return _out(_call("look_at", target=target, camera=camera, roll_deg=roll_deg,
                      keyframe_frame=keyframe_frame))


MoveType = Literal["dolly", "truck", "pedestal", "crane", "pan", "tilt", "roll", "zoom", "orbit",
                   "orbit_vertical", "push_in", "pull_out"]
MOVE_HELP = (
    "dolly: forward(+)/back(-) m; truck: right(+)/left(-) m; pedestal/crane: up(+)/down(-) m; "
    "pan: left(+)/right(-) deg; tilt: up(+)/down(-) deg; roll: counter-clockwise(+) deg; "
    "zoom: focal length change mm (+ tighter); orbit: around target, counter-clockwise from above(+) deg; "
    "orbit_vertical: over the target up(+) deg; push_in/pull_out: toward/away from target m.")


MoveSpec = Annotated[dict[str, Any], Field(description='{"type": <move type>, "amount": <number>}')]


@mcp.tool()
def move_camera(
    move_type: Annotated[Optional[MoveType], D("Move to apply. " + MOVE_HELP)] = None,
    amount: Annotated[Optional[float], D("Amount (metres, degrees or mm depending on type).")] = None,
    moves: Annotated[Optional[list[MoveSpec]], D("Extra moves applied together, e.g. "
                                                 '[{"type":"truck","amount":2},{"type":"pan","amount":-10}].')] = None,
    camera: Annotated[Optional[str], D(CAMERA)] = None,
    target: Annotated[Optional[Target], D("Subject for orbit/push_in; if given, the camera keeps aiming "
                                          "at it after translating. " + TARGET)] = None,
    keyframe_frame: Annotated[Optional[int], D(KEYFRAME)] = None,
) -> str:
    """Instantly apply real-world camera moves relative to the current pose (camera-local axes)."""
    return _out(_call("move_camera", move_type=move_type, amount=amount, moves=moves, camera=camera,
                      target=target, keyframe_frame=keyframe_frame))


@mcp.tool()
def place_camera_spherical(
    target: Annotated[Target, D(TARGET)],
    azimuth_deg: Annotated[float, D("Around the target: 0 = in front (-Y side), 90 = +X side, "
                                    "180 = behind, -90 = -X side.")] = 0.0,
    elevation_deg: Annotated[float, D("Height angle above the target's horizon (negative = below).")] = 15.0,
    distance: Annotated[float, D("Distance from the target in metres.")] = 10.0,
    camera: Annotated[Optional[str], D(CAMERA)] = None,
    roll_deg: Annotated[float, D("Roll around the view axis.")] = 0.0,
    relative_to_target_front: Annotated[bool, D("Measure azimuth from the target object's own front "
                                                "(its local -Y) instead of world -Y.")] = False,
    keyframe_frame: Annotated[Optional[int], D(KEYFRAME)] = None,
) -> str:
    """Place the camera on a sphere around a target and aim at it."""
    return _out(_call("place_camera_spherical", target=target, azimuth_deg=azimuth_deg,
                      elevation_deg=elevation_deg, distance=distance, camera=camera, roll_deg=roll_deg,
                      relative_to_target_front=relative_to_target_front, keyframe_frame=keyframe_frame))


@mcp.tool()
def frame_objects(
    objects: Annotated[list[str], D("Objects that must all be in frame.")],
    camera: Annotated[Optional[str], D(CAMERA)] = None,
    margin: Annotated[float, D("Breathing room as a fraction of the frame (0.1 = 10%).")] = 0.1,
    azimuth_deg: Annotated[Optional[float], D("View from this azimuth (see place_camera_spherical).")] = None,
    elevation_deg: Annotated[Optional[float], D("View from this elevation.")] = None,
    keep_direction: Annotated[bool, D("Keep the current viewing direction (just dolly to fit).")] = True,
    lens: Annotated[Optional[float], D("Set this focal length before fitting.")] = None,
    keyframe_frame: Annotated[Optional[int], D(KEYFRAME)] = None,
) -> str:
    """Move the camera so the objects exactly fill the frame (like 'View Selected' for cameras).
    Orthographic cameras adjust ortho_scale instead. Returns the resulting framing."""
    return _out(_call("frame_objects", objects=objects, camera=camera, margin=margin, azimuth_deg=azimuth_deg,
                      elevation_deg=elevation_deg, keep_direction=keep_direction, lens=lens,
                      keyframe_frame=keyframe_frame))


@mcp.tool()
def apply_shot_preset(
    subject: Annotated[str, D("Subject object (e.g. a character).")],
    shot_size: Annotated[Literal["extreme_wide", "wide", "full", "medium_wide", "cowboy", "medium",
                                 "medium_closeup", "closeup", "extreme_closeup"],
                         D("How much of the subject fills the frame (subject height based).")] = "medium",
    angle: Annotated[Literal["eye_level", "high", "low", "birds_eye", "overhead", "worms_eye", "dutch",
                             "dutch_low"], D("Vertical camera angle / roll.")] = "eye_level",
    side: Annotated[Literal["front", "three_quarter_left", "left", "profile_left", "back_left", "back",
                            "over_the_shoulder", "back_right", "right", "profile_right",
                            "three_quarter_right"],
                    D("Which side of the subject (relative to the subject's facing, local -Y).")] = "front",
    camera: Annotated[Optional[str], D(CAMERA)] = None,
    lens: Annotated[Optional[float], D("Focal length to use (e.g. 85 for flattering close-ups).")] = None,
    azimuth_offset_deg: Annotated[float, D("Extra rotation around the subject.")] = 0.0,
    use_subject_facing: Annotated[bool, D("Use the subject's rotation to find its front.")] = True,
    allow_below_base: Annotated[bool, D("Allow low angles to put the camera below the subject's base "
                                        "(normally the ground). Off by default.")] = False,
    keyframe_frame: Annotated[Optional[int], D(KEYFRAME)] = None,
) -> str:
    """Position the camera for a classic cinematography shot (size x angle x side) of a subject.

    Shot sizes assume a standing figure (character, statue, person-sized prop): closer shots crop
    to the upper body and aim toward the head. For products, vehicles or buildings use
    frame_objects instead. Returns the resulting framing so you can verify it."""
    return _out(_call("apply_shot_preset", subject=subject, shot_size=shot_size, angle=angle, side=side,
                      camera=camera, lens=lens, azimuth_offset_deg=azimuth_offset_deg,
                      use_subject_facing=use_subject_facing, allow_below_base=allow_below_base,
                      keyframe_frame=keyframe_frame))


@mcp.tool()
def compose_subject(
    subject: Annotated[Target, D(TARGET)],
    position: Annotated[Literal["center", "left_third", "right_third", "upper_third", "lower_third",
                                "upper_left_third", "upper_right_third", "lower_left_third",
                                "lower_right_third", "golden_left", "golden_right"],
                        D("Composition point to put the subject on.")] = "left_third",
    screen_x: Annotated[Optional[float], D("Custom horizontal position 0 (left) .. 1 (right).")] = None,
    screen_y: Annotated[Optional[float], D("Custom vertical position 0 (bottom) .. 1 (top).")] = None,
    camera: Annotated[Optional[str], D(CAMERA)] = None,
    keep_roll: Annotated[bool, D("Keep the current roll (otherwise level the horizon).")] = True,
    keyframe_frame: Annotated[Optional[int], D(KEYFRAME)] = None,
) -> str:
    """Pan/tilt the camera (without moving it) so the subject sits on a rule-of-thirds / golden
    point or any screen position. Tip: leave look room on the side the subject faces."""
    return _out(_call("compose_subject", subject=subject, position=position, screen_x=screen_x,
                      screen_y=screen_y, camera=camera, keep_roll=keep_roll, keyframe_frame=keyframe_frame))


# ---------------------------------------------------------------------------
# Keyframes
# ---------------------------------------------------------------------------

KeySpec = Annotated[dict[str, Any], Field(description=(
    'One key: {"frame": int, optional "location": [x,y,z], "look_at": object|[x,y,z], '
    '"rotation_deg": [x,y,z], "roll_deg": float, "lens": mm, "focus_distance": m, '
    '"focus_on": object|[x,y,z], "fstop": float}. Omitted location/rotation carry over from the '
    'previous key.'))]


@mcp.tool()
def set_camera_keyframes(
    keyframes: Annotated[list[KeySpec], D("Keys to set, in any order.")],
    camera: Annotated[Optional[str], D(CAMERA)] = None,
    interpolation: Annotated[Literal["CONSTANT", "LINEAR", "BEZIER", "SINE", "QUAD", "CUBIC", "EXPO",
                                     "BACK", "BOUNCE", "ELASTIC"], D("Interpolation between keys.")] = "BEZIER",
    easing: Annotated[Literal["AUTO", "EASE_IN", "EASE_OUT", "EASE_IN_OUT"], D("Easing for non-Bezier modes.")] = "AUTO",
    handle_type: Annotated[Literal["FREE", "ALIGNED", "VECTOR", "AUTO", "AUTO_CLAMPED"],
                           D("Bezier handles; AUTO_CLAMPED avoids overshoot.")] = "AUTO_CLAMPED",
    clear_existing: Annotated[bool, D("Delete all existing camera keys first.")] = False,
) -> str:
    """Author a camera animation from a list of key poses in one call (the most flexible way
    to choreograph a custom move)."""
    return _out(_call("set_camera_keyframes", keyframes=keyframes, camera=camera, interpolation=interpolation,
                      easing=easing, handle_type=handle_type, clear_existing=clear_existing))


@mcp.tool()
def insert_camera_keyframe(
    frame: Annotated[Optional[int], D("Frame (default current).")] = None,
    camera: Annotated[Optional[str], D(CAMERA)] = None,
    properties: Annotated[Optional[list[Literal["location", "rotation", "lens", "focus_distance", "fstop",
                                                "shift", "all"]]],
                          D("What to key (default location, rotation, lens).")] = None,
) -> str:
    """Keyframe the camera's current state."""
    return _out(_call("insert_camera_keyframe", frame=frame, camera=camera, properties=properties))


@mcp.tool()
def clear_camera_animation(
    camera: Annotated[Optional[str], D(CAMERA)] = None,
    frame_start: Annotated[Optional[int], D("Only clear keys from this frame.")] = None,
    frame_end: Annotated[Optional[int], D("Only clear keys up to this frame.")] = None,
    include_lens: Annotated[bool, D("Also clear lens/focus keys.")] = True,
    include_shake: Annotated[bool, D("Also remove shake (only when clearing everything).")] = True,
) -> str:
    """Delete camera keyframes (all, or within a frame range)."""
    return _out(_call("clear_camera_animation", camera=camera, frame_start=frame_start, frame_end=frame_end,
                      include_lens=include_lens, include_shake=include_shake))


@mcp.tool()
def set_keyframe_interpolation(
    interpolation: Annotated[Literal["CONSTANT", "LINEAR", "BEZIER", "SINE", "QUAD", "CUBIC", "QUART",
                                     "QUINT", "EXPO", "CIRC", "BACK", "BOUNCE", "ELASTIC"],
                             D("LINEAR = constant speed, BEZIER = smooth ease, CONSTANT = hard cuts.")] = "BEZIER",
    camera: Annotated[Optional[str], D(CAMERA)] = None,
    easing: Annotated[Optional[Literal["AUTO", "EASE_IN", "EASE_OUT", "EASE_IN_OUT"]], D("Easing.")] = None,
    handle_type: Annotated[Optional[Literal["FREE", "ALIGNED", "VECTOR", "AUTO", "AUTO_CLAMPED"]],
                           D("Bezier handle type.")] = None,
    frame_start: Annotated[Optional[int], D("Only keys from this frame.")] = None,
    frame_end: Annotated[Optional[int], D("Only keys up to this frame.")] = None,
    include_lens: Annotated[bool, D("Also affect lens/focus keys.")] = True,
) -> str:
    """Change how the camera moves between existing keys."""
    return _out(_call("set_keyframe_interpolation", camera=camera, interpolation=interpolation, easing=easing,
                      handle_type=handle_type, frame_start=frame_start, frame_end=frame_end,
                      include_lens=include_lens))


# ---------------------------------------------------------------------------
# Animated moves
# ---------------------------------------------------------------------------

@mcp.tool()
def animate_camera_move(
    move_type: Annotated[Optional[MoveType], D("Move to animate. " + MOVE_HELP)] = None,
    amount: Annotated[Optional[float], D("Total amount over the move (m, deg or mm).")] = None,
    moves: Annotated[Optional[list[MoveSpec]], D("Extra simultaneous moves, e.g. a crane up while "
                                                 'orbiting: [{"type":"crane","amount":3}].')] = None,
    camera: Annotated[Optional[str], D(CAMERA)] = None,
    target: Annotated[Optional[Target], D("Keep aiming at this subject during the move (needed for orbit "
                                          "and push_in). " + TARGET)] = None,
    start_frame: Annotated[Optional[int], D(START)] = None,
    end_frame: Annotated[Optional[int], D(END)] = None,
    duration_frames: Annotated[Optional[int], D(DURATION)] = None,
    easing: Annotated[Easing, D("Speed curve of the move.")] = "ease_in_out",
    key_step: Annotated[int, D(STEP)] = 1,
) -> str:
    """Animate classic camera moves from the current pose: dolly in/out, truck, pedestal/crane,
    pan, tilt, roll, zoom, orbit, push in/pull out — alone or combined (e.g. dolly + pan)."""
    return _out(_call("animate_camera_move", move_type=move_type, amount=amount, moves=moves, camera=camera,
                      target=target, start_frame=start_frame, end_frame=end_frame,
                      duration_frames=duration_frames, easing=easing, key_step=key_step))


@mcp.tool()
def animate_orbit(
    target: Annotated[Target, D("Centre of the orbit. " + TARGET)],
    camera: Annotated[Optional[str], D(CAMERA)] = None,
    start_frame: Annotated[Optional[int], D(START)] = None,
    end_frame: Annotated[Optional[int], D(END)] = None,
    duration_frames: Annotated[Optional[int], D(DURATION)] = None,
    angle_deg: Annotated[float, D("Sweep; 360 = full turntable, negative = clockwise from above.")] = 360.0,
    radius: Annotated[Optional[float], D("Horizontal distance (default: current).")] = None,
    end_radius: Annotated[Optional[float], D("Radius at the end (spiral in/out).")] = None,
    height: Annotated[Optional[float], D("Height above the target (default: current).")] = None,
    end_height: Annotated[Optional[float], D("Height at the end (rising/descending orbit).")] = None,
    start_azimuth_deg: Annotated[Optional[float], D("Start angle (0 = -Y side); default current.")] = None,
    easing: Annotated[Easing, D("'linear' gives a seamless loop for 360 deg.")] = "linear",
    roll_deg: Annotated[float, D("Constant roll.")] = 0.0,
    key_step: Annotated[int, D(STEP)] = 1,
) -> str:
    """Orbit around a subject while keeping it centred: turntables, arc shots, spirals, rising orbits."""
    return _out(_call("animate_orbit", target=target, camera=camera, start_frame=start_frame, end_frame=end_frame,
                      duration_frames=duration_frames, angle_deg=angle_deg, radius=radius, end_radius=end_radius,
                      height=height, end_height=end_height, start_azimuth_deg=start_azimuth_deg,
                      easing=easing, roll_deg=roll_deg, key_step=key_step))


@mcp.tool()
def animate_dolly_zoom(
    target: Annotated[Target, D("Subject that keeps its size. " + TARGET)],
    camera: Annotated[Optional[str], D(CAMERA)] = None,
    start_frame: Annotated[Optional[int], D(START)] = None,
    end_frame: Annotated[Optional[int], D(END)] = None,
    duration_frames: Annotated[Optional[int], D(DURATION)] = None,
    distance_change: Annotated[Optional[float], D("Metres to move; negative = toward subject (background "
                                                  "expands), positive = away (background compresses).")] = None,
    end_distance: Annotated[Optional[float], D("Absolute end distance instead of distance_change. "
                                               "Default: half the current distance.")] = None,
    easing: Annotated[Easing, D("Speed curve.")] = "ease_in_out",
    key_step: Annotated[int, D(STEP)] = 1,
) -> str:
    """Hitchcock 'Vertigo' dolly zoom: move and zoom together so the subject stays the same size
    while the background perspective warps."""
    return _out(_call("animate_dolly_zoom", target=target, camera=camera, start_frame=start_frame,
                      end_frame=end_frame, duration_frames=duration_frames, distance_change=distance_change,
                      end_distance=end_distance, easing=easing, key_step=key_step))


@mcp.tool()
def animate_path(
    points: Annotated[list[Target], D("Waypoints: [x, y, z] points and/or object names (>= 2).")],
    camera: Annotated[Optional[str], D(CAMERA)] = None,
    start_frame: Annotated[Optional[int], D(START)] = None,
    end_frame: Annotated[Optional[int], D(END)] = None,
    duration_frames: Annotated[Optional[int], D(DURATION)] = None,
    look_mode: Annotated[Literal["forward", "target", "fixed"],
                         D("forward = look along the path, target = keep aiming at look_target, "
                           "fixed = keep current orientation.")] = "forward",
    look_target: Annotated[Optional[Target], D("Aim point for look_mode='target'. " + TARGET)] = None,
    look_ahead_frames: Annotated[int, D("How far ahead to look in forward mode (smoother with more).")] = 10,
    smooth: Annotated[bool, D("Smooth spline through the points (false = straight segments).")] = True,
    closed: Annotated[bool, D("Loop back to the first point.")] = False,
    constant_speed: Annotated[bool, D("Even speed along the path regardless of waypoint spacing.")] = True,
    easing: Annotated[Easing, D("Speed curve along the whole path.")] = "linear",
    bank_factor: Annotated[float, D("Roll into turns like a drone/plane (0 = none, 0.5 = moderate).")] = 0.0,
    create_guide_curve: Annotated[bool, D("Add a visible curve object showing the path.")] = False,
    key_step: Annotated[int, D(STEP)] = 1,
) -> str:
    """Fly the camera through waypoints on a smooth spline: fly-throughs, drone shots, reveals,
    walk-throughs, track-along-a-subject moves."""
    return _out(_call("animate_path", points=points, camera=camera, start_frame=start_frame, end_frame=end_frame,
                      duration_frames=duration_frames, look_mode=look_mode, look_target=look_target,
                      look_ahead_frames=look_ahead_frames, smooth=smooth, closed=closed,
                      constant_speed=constant_speed, easing=easing, bank_factor=bank_factor,
                      create_guide_curve=create_guide_curve, key_step=key_step))


@mcp.tool()
def animate_follow(
    target: Annotated[str, D("Moving object to follow.")],
    camera: Annotated[Optional[str], D(CAMERA)] = None,
    offset: Annotated[Vec3, D("Camera offset from the target. In 'target' space +Y is behind a subject "
                              "facing -Y, so [0, 6, 2] = behind and above.")] = [0.0, 6.0, 2.0],
    offset_space: Annotated[Literal["target", "world"], D("'target' = offset rotates with the target "
                                                          "(chase cam); 'world' = fixed direction.")] = "target",
    look_offset: Annotated[Vec3, D("Aim point relative to the target origin (same space).")] = [0.0, 0.0, 0.0],
    start_frame: Annotated[Optional[int], D(START)] = None,
    end_frame: Annotated[Optional[int], D(END)] = None,
    duration_frames: Annotated[Optional[int], D(DURATION)] = None,
    position_smoothing: Annotated[float, D("0 = rigid, 0.9 = lazy lag behind the target.")] = 0.85,
    aim_smoothing: Annotated[float, D("0 = snap aim, 0.9 = lazy aim.")] = 0.6,
    key_step: Annotated[int, D(STEP)] = 1,
) -> str:
    """Chase / follow cam for an animated object with smooth, damped lag (baked to keys)."""
    return _out(_call("animate_follow", target=target, camera=camera, offset=offset, offset_space=offset_space,
                      look_offset=look_offset, start_frame=start_frame, end_frame=end_frame,
                      duration_frames=duration_frames, position_smoothing=position_smoothing,
                      aim_smoothing=aim_smoothing, key_step=key_step))


@mcp.tool()
def animate_transition(
    camera: Annotated[Optional[str], D(CAMERA)] = None,
    to_camera: Annotated[Optional[str], D("Move to match this other camera's pose and lens.")] = None,
    to_location: Annotated[Optional[Vec3], D("Or: end position.")] = None,
    to_look_at: Annotated[Optional[Target], D("End aim target. " + TARGET)] = None,
    to_rotation_deg: Annotated[Optional[Vec3], D("End rotation if not using to_look_at.")] = None,
    to_lens: Annotated[Optional[float], D("End focal length.")] = None,
    start_frame: Annotated[Optional[int], D(START)] = None,
    end_frame: Annotated[Optional[int], D(END)] = None,
    duration_frames: Annotated[Optional[int], D(DURATION)] = None,
    easing: Annotated[Easing, D("Speed curve.")] = "ease_in_out",
    arc_height: Annotated[float, D("Lift the path into an arc by this many metres at the midpoint.")] = 0.0,
    look_at_during: Annotated[Optional[Target], D("Keep aiming at this during the move. " + TARGET)] = None,
    key_step: Annotated[int, D(STEP)] = 1,
) -> str:
    """Smoothly move from the current pose to a new pose (or another camera's pose): position,
    rotation (slerp) and lens together, optionally arcing or keeping a subject in view."""
    return _out(_call("animate_transition", camera=camera, to_camera=to_camera, to_location=to_location,
                      to_look_at=to_look_at, to_rotation_deg=to_rotation_deg, to_lens=to_lens,
                      start_frame=start_frame, end_frame=end_frame, duration_frames=duration_frames,
                      easing=easing, arc_height=arc_height, look_at_during=look_at_during, key_step=key_step))


@mcp.tool()
def animate_rack_focus(
    focus_targets: Annotated[list[Union[str, list[float], float]],
                             D("Things to focus on in order: object names, [x,y,z] points or distances (m).")],
    camera: Annotated[Optional[str], D(CAMERA)] = None,
    frames: Annotated[Optional[list[int]], D("Frame for each focus target (else spread evenly).")] = None,
    start_frame: Annotated[Optional[int], D(START)] = None,
    end_frame: Annotated[Optional[int], D(END)] = None,
    duration_frames: Annotated[Optional[int], D(DURATION)] = None,
    fstop: Annotated[Optional[float], D("Aperture; 1.4-2.8 makes the pull obvious.")] = None,
    easing: Annotated[Easing, D("Speed curve of each pull.")] = "ease_in_out",
    key_step: Annotated[int, D(STEP)] = 1,
) -> str:
    """Rack/pull focus between subjects over time (enables depth of field)."""
    return _out(_call("animate_rack_focus", focus_targets=focus_targets, camera=camera, frames=frames,
                      start_frame=start_frame, end_frame=end_frame, duration_frames=duration_frames,
                      fstop=fstop, easing=easing, key_step=key_step))


@mcp.tool()
def animate_whip_pan(
    angle_deg: Annotated[float, D("Pan angle; positive = left.")] = 90.0,
    camera: Annotated[Optional[str], D(CAMERA)] = None,
    start_frame: Annotated[Optional[int], D(START)] = None,
    duration_frames: Annotated[int, D("Frames for the whip (6-12 feels snappy).")] = 8,
    easing: Annotated[Easing, D("Speed curve.")] = "ease_in_out_expo",
    enable_motion_blur: Annotated[bool, D("Turn on render motion blur for the smear.")] = True,
    key_step: Annotated[int, D(STEP)] = 1,
) -> str:
    """Very fast whip/swish pan, typically used as a transition between shots."""
    return _out(_call("animate_whip_pan", angle_deg=angle_deg, camera=camera, start_frame=start_frame,
                      duration_frames=duration_frames, easing=easing, enable_motion_blur=enable_motion_blur,
                      key_step=key_step))


@mcp.tool()
def add_camera_shake(
    preset: Annotated[Literal["handheld", "subtle", "breathing", "walking", "running", "vehicle", "helicopter",
                              "earthquake", "explosion"], D("Character of the shake.")] = "handheld",
    intensity: Annotated[float, D("Amplitude multiplier (0.5 = half, 2 = double).")] = 1.0,
    camera: Annotated[Optional[str], D(CAMERA)] = None,
    start_frame: Annotated[Optional[int], D("Restrict shake to start here (default: always on).")] = None,
    end_frame: Annotated[Optional[int], D("Restrict shake to end here.")] = None,
    blend_in_frames: Annotated[int, D("Ramp the shake in over N frames (with a restricted range).")] = 0,
    blend_out_frames: Annotated[int, D("Ramp the shake out over N frames.")] = 0,
    rotation: Annotated[bool, D("Shake rotation.")] = True,
    location: Annotated[bool, D("Shake position.")] = True,
    seed: Annotated[int, D("Change for a different random pattern.")] = 0,
    frequency_multiplier: Annotated[float, D(">1 = faster jitter, <1 = slower sway.")] = 1.0,
) -> str:
    """Layer procedural noise shake on top of the camera's motion (non-destructive; uses delta
    transforms so existing keys are untouched). Replaces any previous shake."""
    return _out(_call("add_camera_shake", preset=preset, intensity=intensity, camera=camera,
                      start_frame=start_frame, end_frame=end_frame, blend_in_frames=blend_in_frames,
                      blend_out_frames=blend_out_frames, rotation=rotation, location=location, seed=seed,
                      frequency_multiplier=frequency_multiplier))


@mcp.tool()
def remove_camera_shake(camera: Annotated[Optional[str], D(CAMERA)] = None) -> str:
    """Remove shake added by add_camera_shake."""
    return _out(_call("remove_camera_shake", camera=camera))


@mcp.tool()
def add_track_constraint(
    target: Annotated[Target, D("Object to track, or a point (an empty is created there). " + TARGET)],
    camera: Annotated[Optional[str], D(CAMERA)] = None,
    constraint_type: Annotated[Literal["TRACK_TO", "DAMPED_TRACK", "LOCKED_TRACK"],
                               D("TRACK_TO keeps the horizon level.")] = "TRACK_TO",
    influence: Annotated[float, D("0..1 blend.")] = 1.0,
) -> str:
    """Live constraint that keeps the camera aimed at a (possibly moving) object. Overrides keyed
    rotation; use look_at/animate_* instead if you want baked, editable keys."""
    return _out(_call("add_track_constraint", target=target, camera=camera, constraint_type=constraint_type,
                      influence=influence))


@mcp.tool()
def remove_camera_constraints(
    camera: Annotated[Optional[str], D(CAMERA)] = None,
    constraint_type: Annotated[Optional[str], D("Only remove this type (e.g. TRACK_TO).")] = None,
    bake_current_pose: Annotated[bool, D("Keep the pose the constraint produced.")] = True,
) -> str:
    """Remove camera constraints."""
    return _out(_call("remove_camera_constraints", camera=camera, constraint_type=constraint_type,
                      bake_current_pose=bake_current_pose))


# ---------------------------------------------------------------------------
# Timeline, cuts, render settings, bookmarks
# ---------------------------------------------------------------------------

@mcp.tool()
def set_frame_range(
    frame_start: Annotated[Optional[int], D("First frame.")] = None,
    frame_end: Annotated[Optional[int], D("Last frame.")] = None,
    fps: Annotated[Optional[float], D("Frame rate, e.g. 24, 25, 30, 29.97, 60.")] = None,
    current_frame: Annotated[Optional[int], D("Jump to this frame.")] = None,
) -> str:
    """Set the scene's frame range, frame rate and/or current frame."""
    return _out(_call("set_frame_range", frame_start=frame_start, frame_end=frame_end, fps=fps,
                      current_frame=current_frame))


@mcp.tool()
def add_camera_cut(
    camera: Annotated[str, D("Camera to cut to.")],
    frame: Annotated[int, D("Frame where this camera becomes active.")],
) -> str:
    """Edit between cameras: from this frame on, render through this camera (timeline marker)."""
    return _out(_call("add_camera_cut", camera=camera, frame=frame))


@mcp.tool()
def list_camera_cuts() -> str:
    """List camera cuts (frame -> camera)."""
    return _out(_call("list_camera_cuts"))


@mcp.tool()
def clear_camera_cuts(frame: Annotated[Optional[int], D("Only the cut at this frame.")] = None) -> str:
    """Remove camera cuts."""
    return _out(_call("clear_camera_cuts", frame=frame))


@mcp.tool()
def set_render_settings(
    aspect_preset: Annotated[Optional[Literal["16:9", "4k_16:9", "2.39:1", "2.35:1", "1.85:1", "4:3", "1:1",
                                              "9:16", "4:5", "21:9"]],
                             D("Common delivery formats (2.39:1 = anamorphic widescreen, 9:16 = vertical).")] = None,
    resolution_x: Annotated[Optional[int], D("Width in pixels.")] = None,
    resolution_y: Annotated[Optional[int], D("Height in pixels.")] = None,
    resolution_percentage: Annotated[Optional[int], D("Render scale %.")] = None,
    motion_blur: Annotated[Optional[bool], D("Render motion blur.")] = None,
    shutter: Annotated[Optional[float], D("Shutter in frames (0.5 = 180 degree shutter).")] = None,
    engine: Annotated[Optional[Literal["WORKBENCH", "EEVEE", "CYCLES"]], D("Render engine.")] = None,
) -> str:
    """Frame format and render settings that affect how camera work reads."""
    return _out(_call("set_render_settings", aspect_preset=aspect_preset, resolution_x=resolution_x,
                      resolution_y=resolution_y, resolution_percentage=resolution_percentage,
                      motion_blur=motion_blur, shutter=shutter, engine=engine))


@mcp.tool()
def view_through_camera(camera: Annotated[Optional[str], D(CAMERA)] = None) -> str:
    """Make the camera active and switch the user's 3D viewports to look through it."""
    return _out(_call("view_through_camera", camera=camera))


@mcp.tool()
def save_camera_bookmark(
    name: Annotated[str, D("Bookmark name, e.g. 'hero_wide'.")],
    camera: Annotated[Optional[str], D(CAMERA)] = None,
) -> str:
    """Remember the camera's current pose and lens so you can return to it or animate to it later."""
    return _out(_call("save_camera_bookmark", name=name, camera=camera))


@mcp.tool()
def apply_camera_bookmark(
    name: Annotated[str, D("Bookmark to restore.")],
    camera: Annotated[Optional[str], D(CAMERA)] = None,
    keyframe_frame: Annotated[Optional[int], D(KEYFRAME)] = None,
) -> str:
    """Restore a saved pose (optionally keyframing it — handy for building key-to-key moves)."""
    return _out(_call("apply_camera_bookmark", name=name, camera=camera, keyframe_frame=keyframe_frame))


@mcp.tool()
def list_camera_bookmarks() -> str:
    """List saved camera bookmarks."""
    return _out(_call("list_camera_bookmarks"))


# ---------------------------------------------------------------------------
# Visual review
# ---------------------------------------------------------------------------

Engine = Literal["AUTO", "WORKBENCH", "EEVEE", "CYCLES", "CURRENT"]


@mcp.tool()
def render_preview(
    camera: Annotated[Optional[str], D(CAMERA)] = None,
    frame: Annotated[Optional[int], D("Frame to render (default current).")] = None,
    max_size: Annotated[int, D("Longest side in pixels (keeps the render aspect).")] = 768,
    engine: Annotated[Engine, D("AUTO = fast Workbench in the UI (Cycles when headless). Use EEVEE/CYCLES "
                                "to see depth of field, lighting and motion blur.")] = "AUTO",
    samples: Annotated[int, D("Samples for EEVEE/Cycles.")] = 16,
    filepath: Annotated[Optional[str], D("Also save the PNG here.")] = None,
):
    """Render what the camera sees and return the image, so you can judge composition."""
    return _image_result(_call("render_preview", camera=camera, frame=frame, max_size=max_size, engine=engine,
                               samples=samples, filepath=filepath))


@mcp.tool()
def render_contact_sheet(
    camera: Annotated[Optional[str], D("Camera; omit to follow camera cuts / active camera.")] = None,
    frames: Annotated[Optional[list[int]], D("Exact frames to render (max 24).")] = None,
    count: Annotated[int, D("Otherwise render this many evenly spaced frames.")] = 6,
    columns: Annotated[int, D("Tiles per row.")] = 3,
    frame_start: Annotated[Optional[int], D("Range start for evenly spaced frames.")] = None,
    frame_end: Annotated[Optional[int], D("Range end for evenly spaced frames.")] = None,
    max_size: Annotated[int, D("Longest side of each tile in pixels.")] = 384,
    engine: Annotated[Engine, D("Render engine for the tiles.")] = "AUTO",
    samples: Annotated[int, D("Samples for EEVEE/Cycles.")] = 8,
    filepath: Annotated[Optional[str], D("Also save the PNG here.")] = None,
):
    """Render several frames of the animation into one tiled image (left-to-right, top-to-bottom)
    to review a camera move at a glance."""
    return _image_result(_call("render_contact_sheet", camera=camera, frames=frames, count=count, columns=columns,
                               frame_start=frame_start, frame_end=frame_end, max_size=max_size, engine=engine,
                               samples=samples, filepath=filepath))


if os.environ.get("BLENDER_CAM_ENABLE_PYTHON_TOOL", "").lower() in {"1", "true", "yes"}:
    @mcp.tool()
    def execute_python(code: Annotated[str, D("Python to run in Blender; assign to `result` to return data.")]) -> str:
        """Run arbitrary Python inside Blender (also requires 'Allow arbitrary Python' in the add-on)."""
        return _out(_call("execute_python", code=code))


# ---------------------------------------------------------------------------
# Guidance
# ---------------------------------------------------------------------------

CINEMATOGRAPHY_GUIDE = """\
# Camera language cheat sheet

Shot sizes (apply_shot_preset): extreme_wide (establish place) > wide > full (whole body) >
medium_wide/cowboy (mid-thigh up) > medium (waist up) > medium_closeup (chest up) > closeup (face)
> extreme_closeup (eyes/detail).

Angles: eye_level (neutral), high (subject looks small/vulnerable), low (powerful/heroic),
birds_eye/overhead (map-like, detached), worms_eye (monumental), dutch (unease).

Lenses: 14-24mm wide (space, distortion, energy when close), 35mm (natural, documentary),
50mm (neutral), 85mm (portrait, flattering), 135-200mm (compression, isolation).
Low f-stop (1.4-2.8) + long lens = shallow depth of field.

Moves and what they say:
- Push in (dolly toward subject): growing importance, realisation, tension.
- Pull out: reveal context, isolation, ending.
- Truck/tracking alongside: travel with a subject.
- Pedestal/crane up: reveal scale, uplift; crane down: arriving into a scene.
- Pan/tilt: survey or follow while the camera stays put.
- Orbit/arc: heroic moment, show a subject in 3D (product turntable = 360 linear).
- Dolly zoom: vertigo, shock.
- Whip pan: energetic transition.
- Handheld shake: urgency, realism; subtle/breathing: 'alive' static shots.
- Rack focus: shift attention between subjects.

Timing (at 24 fps): slow cinematic move 5-10 s (120-240 frames); standard 3-5 s; whip 6-10 frames.
Ease in/out for most moves; linear for loops and continuous tracking.

Composition: put subjects on thirds (compose_subject), leave look room in the direction they face,
keep headroom small in close-ups (analyze_framing reports it), avoid tangents with frame edges.
"""


@mcp.resource("camera://guide")
def cinematography_guide() -> str:
    """Cinematography cheat sheet: shot sizes, angles, lenses, moves and timing."""
    return CINEMATOGRAPHY_GUIDE


@mcp.prompt()
def plan_camera_shot(subject: str, mood: str = "cinematic", duration_seconds: str = "5") -> str:
    """Plan and execute a camera shot for a subject with a given mood."""
    return (
        "You are a cinematographer working in Blender through the camera tools.\n"
        f"Subject: {subject}. Mood: {mood}. Duration: about {duration_seconds} seconds.\n\n"
        "1. Call get_scene_info to learn the scene and frame rate.\n"
        "2. Choose shot size, angle, lens and a camera move that express the mood; explain why briefly.\n"
        "3. Set up the start pose (create_camera, set_camera_lens, apply_shot_preset / compose_subject).\n"
        "4. Animate it (animate_* tools or set_camera_keyframes), add subtle shake only if it fits.\n"
        "5. Verify with get_camera_animation and render_contact_sheet; fix framing problems.\n\n"
        + CINEMATOGRAPHY_GUIDE
    )


def main():
    import argparse

    parser = argparse.ArgumentParser(description="MCP server for AI camera control in Blender")
    parser.add_argument("--host", default=None, help="Blender add-on host (env BLENDER_CAM_HOST)")
    parser.add_argument("--port", type=int, default=None, help="Blender add-on port (env BLENDER_CAM_PORT)")
    parser.add_argument("--transport", default="stdio", choices=["stdio", "sse", "streamable-http"])
    args = parser.parse_args()
    if args.host:
        _blender.host = args.host
    if args.port:
        _blender.port = args.port
    mcp.run(transport=args.transport)


if __name__ == "__main__":
    main()
