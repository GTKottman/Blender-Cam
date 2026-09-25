# Tool reference (generated)

Generated from the MCP server's schemas by `scripts/gen_skill_reference.py`; do not edit by hand.
Parameters marked **required** have no default. Everything else can be omitted.

## Contents

- `add_camera_cut`
- `add_camera_shake`
- `add_track_constraint`
- `analyze_framing`
- `animate_camera_move`
- `animate_dolly_zoom`
- `animate_follow`
- `animate_orbit`
- `animate_path`
- `animate_rack_focus`
- `animate_transition`
- `animate_whip_pan`
- `apply_camera_bookmark`
- `apply_shot_preset`
- `clear_camera_animation`
- `clear_camera_cuts`
- `compose_subject`
- `create_camera`
- `delete_camera`
- `duplicate_camera`
- `frame_objects`
- `get_camera_animation`
- `get_camera_info`
- `get_scene_info`
- `insert_camera_keyframe`
- `list_camera_bookmarks`
- `list_camera_cuts`
- `list_cameras`
- `look_at`
- `move_camera`
- `place_camera_spherical`
- `remove_camera_constraints`
- `remove_camera_shake`
- `render_contact_sheet`
- `render_preview`
- `save_camera_bookmark`
- `set_active_camera`
- `set_camera_keyframes`
- `set_camera_lens`
- `set_camera_transform`
- `set_depth_of_field`
- `set_frame_range`
- `set_keyframe_interpolation`
- `set_render_settings`
- `view_through_camera`

## `add_camera_cut`

Edit between cameras: from this frame on, render through this camera (timeline marker).

- `camera` (string) **required** — Camera to cut to.
- `frame` (integer) **required** — Frame where this camera becomes active.

## `add_camera_shake`

Layer procedural noise shake on top of the camera's motion (non-destructive; uses delta transforms so existing keys are untouched). Replaces any previous shake.

- `preset` ('handheld' | 'subtle' | 'breathing' | 'walking' | 'running' | 'vehicle' | 'helicopter' | 'earthquake' | 'explosion') = `'handheld'` — Character of the shake.
- `intensity` (number) = `1.0` — Amplitude multiplier (0.5 = half, 2 = double).
- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.
- `start_frame` (integer) = `None` — Restrict shake to start here (default: always on).
- `end_frame` (integer) = `None` — Restrict shake to end here.
- `blend_in_frames` (integer) = `0` — Ramp the shake in over N frames (with a restricted range).
- `blend_out_frames` (integer) = `0` — Ramp the shake out over N frames.
- `rotation` (boolean) = `True` — Shake rotation.
- `location` (boolean) = `True` — Shake position.
- `seed` (integer) = `0` — Change for a different random pattern.
- `frequency_multiplier` (number) = `1.0` — >1 = faster jitter, <1 = slower sway.

## `add_track_constraint`

Live constraint that keeps the camera aimed at a (possibly moving) object. Overrides keyed rotation; use look_at/animate_* instead if you want baked, editable keys.

- `target` (string or list[number]) **required** — Object to track, or a point (an empty is created there). Object name (uses its bounding-box centre) or [x, y, z] world point.
- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.
- `constraint_type` ('TRACK_TO' | 'DAMPED_TRACK' | 'LOCKED_TRACK') = `'TRACK_TO'` — TRACK_TO keeps the horizon level.
- `influence` (number) = `1.0` — 0..1 blend.

## `analyze_framing`

Report where objects land in the camera frame without rendering. Per object: visibility (fully/partially/out of frame, behind camera), screen-space bounding box and centre (0..1, origin bottom-left), frame coverage, height fraction, headroom, distance and the nearest rule-of-thirds point. Use it to verify composition.

- `objects` (list[string]) = `None` — Objects to check. Omit for all visible geometry.
- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.
- `frame` (integer) = `None` — Evaluate at this frame (default: current).

## `animate_camera_move`

Animate classic camera moves from the current pose: dolly in/out, truck, pedestal/crane, pan, tilt, roll, zoom, orbit, push in/pull out — alone or combined (e.g. dolly + pan).

- `move_type` ('dolly' | 'truck' | 'pedestal' | 'crane' | 'pan' | 'tilt' | 'roll' | 'zoom' | 'orbit' | 'orbit_vertical' | 'push_in' | 'pull_out') = `None` — Move to animate. dolly: forward(+)/back(-) m; truck: right(+)/left(-) m; pedestal/crane: up(+)/down(-) m; pan: left(+)/right(-) deg; tilt: up(+)/down(-) deg; roll: counter-clockwise(+) deg; zoom: focal length change mm (+ tighter); orbit: around target, counter-clockwise from above(+) deg; orbit_vertical: over the target up(+) deg; push_in/pull_out: toward/away from target m.
- `amount` (number) = `None` — Total amount over the move (m, deg or mm).
- `moves` (list[object]) = `None` — Extra simultaneous moves, e.g. a crane up while orbiting: [{"type":"crane","amount":3}].
- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.
- `target` (string or list[number]) = `None` — Keep aiming at this subject during the move (needed for orbit and push_in). Object name (uses its bounding-box centre) or [x, y, z] world point.
- `start_frame` (integer) = `None` — First frame of the move. Defaults to the scene's current frame.
- `end_frame` (integer) = `None` — Last frame of the move. Give end_frame or duration_frames.
- `duration_frames` (integer) = `None` — Length of the move in frames (used when end_frame is omitted).
- `easing` ('linear' | 'ease_in' | 'ease_out' | 'ease_in_out' | 'ease_in_quad' | 'ease_out_quad' | 'ease_in_out_quad' | 'ease_in_out_sine' | 'ease_in_out_expo' | 'smoothstep' | 'smootherstep' | 'ease_out_back') = `'ease_in_out'` — Speed curve of the move.
- `key_step` (integer) = `1` — Bake a key every N frames (1 = exact every frame).

## `animate_dolly_zoom`

Hitchcock 'Vertigo' dolly zoom: move and zoom together so the subject stays the same size while the background perspective warps.

- `target` (string or list[number]) **required** — Subject that keeps its size. Object name (uses its bounding-box centre) or [x, y, z] world point.
- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.
- `start_frame` (integer) = `None` — First frame of the move. Defaults to the scene's current frame.
- `end_frame` (integer) = `None` — Last frame of the move. Give end_frame or duration_frames.
- `duration_frames` (integer) = `None` — Length of the move in frames (used when end_frame is omitted).
- `distance_change` (number) = `None` — Metres to move; negative = toward subject (background expands), positive = away (background compresses).
- `end_distance` (number) = `None` — Absolute end distance instead of distance_change. Default: half the current distance.
- `easing` ('linear' | 'ease_in' | 'ease_out' | 'ease_in_out' | 'ease_in_quad' | 'ease_out_quad' | 'ease_in_out_quad' | 'ease_in_out_sine' | 'ease_in_out_expo' | 'smoothstep' | 'smootherstep' | 'ease_out_back') = `'ease_in_out'` — Speed curve.
- `key_step` (integer) = `1` — Bake a key every N frames (1 = exact every frame).

## `animate_follow`

Chase / follow cam for an animated object with smooth, damped lag (baked to keys).

- `target` (string) **required** — Moving object to follow.
- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.
- `offset` (list[number]) = `[0.0, 6.0, 2.0]` — Camera offset from the target. In 'target' space +Y is behind a subject facing -Y, so [0, 6, 2] = behind and above.
- `offset_space` ('target' | 'world') = `'target'` — 'target' = offset rotates with the target (chase cam); 'world' = fixed direction.
- `look_offset` (list[number]) = `[0.0, 0.0, 0.0]` — Aim point relative to the target origin (same space).
- `start_frame` (integer) = `None` — First frame of the move. Defaults to the scene's current frame.
- `end_frame` (integer) = `None` — Last frame of the move. Give end_frame or duration_frames.
- `duration_frames` (integer) = `None` — Length of the move in frames (used when end_frame is omitted).
- `position_smoothing` (number) = `0.85` — 0 = rigid, 0.9 = lazy lag behind the target.
- `aim_smoothing` (number) = `0.6` — 0 = snap aim, 0.9 = lazy aim.
- `key_step` (integer) = `1` — Bake a key every N frames (1 = exact every frame).

## `animate_orbit`

Orbit around a subject while keeping it centred: turntables, arc shots, spirals, rising orbits.

- `target` (string or list[number]) **required** — Centre of the orbit. Object name (uses its bounding-box centre) or [x, y, z] world point.
- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.
- `start_frame` (integer) = `None` — First frame of the move. Defaults to the scene's current frame.
- `end_frame` (integer) = `None` — Last frame of the move. Give end_frame or duration_frames.
- `duration_frames` (integer) = `None` — Length of the move in frames (used when end_frame is omitted).
- `angle_deg` (number) = `360.0` — Sweep; 360 = full turntable, negative = clockwise from above.
- `radius` (number) = `None` — Horizontal distance (default: current).
- `end_radius` (number) = `None` — Radius at the end (spiral in/out).
- `height` (number) = `None` — Height above the target (default: current).
- `end_height` (number) = `None` — Height at the end (rising/descending orbit).
- `start_azimuth_deg` (number) = `None` — Start angle (0 = -Y side); default current.
- `easing` ('linear' | 'ease_in' | 'ease_out' | 'ease_in_out' | 'ease_in_quad' | 'ease_out_quad' | 'ease_in_out_quad' | 'ease_in_out_sine' | 'ease_in_out_expo' | 'smoothstep' | 'smootherstep' | 'ease_out_back') = `'linear'` — 'linear' gives a seamless loop for 360 deg.
- `roll_deg` (number) = `0.0` — Constant roll.
- `key_step` (integer) = `1` — Bake a key every N frames (1 = exact every frame).

## `animate_path`

Fly the camera through waypoints on a smooth spline: fly-throughs, drone shots, reveals, walk-throughs, track-along-a-subject moves.

- `points` (list[string or list[number]]) **required** — Waypoints: [x, y, z] points and/or object names (>= 2).
- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.
- `start_frame` (integer) = `None` — First frame of the move. Defaults to the scene's current frame.
- `end_frame` (integer) = `None` — Last frame of the move. Give end_frame or duration_frames.
- `duration_frames` (integer) = `None` — Length of the move in frames (used when end_frame is omitted).
- `look_mode` ('forward' | 'target' | 'fixed') = `'forward'` — forward = look along the path, target = keep aiming at look_target, fixed = keep current orientation.
- `look_target` (string or list[number]) = `None` — Aim point for look_mode='target'. Object name (uses its bounding-box centre) or [x, y, z] world point.
- `look_ahead_frames` (integer) = `10` — How far ahead to look in forward mode (smoother with more).
- `smooth` (boolean) = `True` — Smooth spline through the points (false = straight segments).
- `closed` (boolean) = `False` — Loop back to the first point.
- `constant_speed` (boolean) = `True` — Even speed along the path regardless of waypoint spacing.
- `easing` ('linear' | 'ease_in' | 'ease_out' | 'ease_in_out' | 'ease_in_quad' | 'ease_out_quad' | 'ease_in_out_quad' | 'ease_in_out_sine' | 'ease_in_out_expo' | 'smoothstep' | 'smootherstep' | 'ease_out_back') = `'linear'` — Speed curve along the whole path.
- `bank_factor` (number) = `0.0` — Roll into turns like a drone/plane (0 = none, 0.5 = moderate).
- `create_guide_curve` (boolean) = `False` — Add a visible curve object showing the path.
- `key_step` (integer) = `1` — Bake a key every N frames (1 = exact every frame).

## `animate_rack_focus`

Rack/pull focus between subjects over time (enables depth of field).

- `focus_targets` (list[string or list[number] or number]) **required** — Things to focus on in order: object names, [x,y,z] points or distances (m).
- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.
- `frames` (list[integer]) = `None` — Frame for each focus target (else spread evenly).
- `start_frame` (integer) = `None` — First frame of the move. Defaults to the scene's current frame.
- `end_frame` (integer) = `None` — Last frame of the move. Give end_frame or duration_frames.
- `duration_frames` (integer) = `None` — Length of the move in frames (used when end_frame is omitted).
- `fstop` (number) = `None` — Aperture; 1.4-2.8 makes the pull obvious.
- `easing` ('linear' | 'ease_in' | 'ease_out' | 'ease_in_out' | 'ease_in_quad' | 'ease_out_quad' | 'ease_in_out_quad' | 'ease_in_out_sine' | 'ease_in_out_expo' | 'smoothstep' | 'smootherstep' | 'ease_out_back') = `'ease_in_out'` — Speed curve of each pull.
- `key_step` (integer) = `1` — Bake a key every N frames (1 = exact every frame).

## `animate_transition`

Smoothly move from the current pose to a new pose (or another camera's pose): position, rotation (slerp) and lens together, optionally arcing or keeping a subject in view.

- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.
- `to_camera` (string) = `None` — Move to match this other camera's pose and lens.
- `to_location` (list[number]) = `None` — Or: end position.
- `to_look_at` (string or list[number]) = `None` — End aim target. Object name (uses its bounding-box centre) or [x, y, z] world point.
- `to_rotation_deg` (list[number]) = `None` — End rotation if not using to_look_at.
- `to_lens` (number) = `None` — End focal length.
- `start_frame` (integer) = `None` — First frame of the move. Defaults to the scene's current frame.
- `end_frame` (integer) = `None` — Last frame of the move. Give end_frame or duration_frames.
- `duration_frames` (integer) = `None` — Length of the move in frames (used when end_frame is omitted).
- `easing` ('linear' | 'ease_in' | 'ease_out' | 'ease_in_out' | 'ease_in_quad' | 'ease_out_quad' | 'ease_in_out_quad' | 'ease_in_out_sine' | 'ease_in_out_expo' | 'smoothstep' | 'smootherstep' | 'ease_out_back') = `'ease_in_out'` — Speed curve.
- `arc_height` (number) = `0.0` — Lift the path into an arc by this many metres at the midpoint.
- `look_at_during` (string or list[number]) = `None` — Keep aiming at this during the move. Object name (uses its bounding-box centre) or [x, y, z] world point.
- `key_step` (integer) = `1` — Bake a key every N frames (1 = exact every frame).

## `animate_whip_pan`

Very fast whip/swish pan, typically used as a transition between shots.

- `angle_deg` (number) = `90.0` — Pan angle; positive = left.
- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.
- `start_frame` (integer) = `None` — First frame of the move. Defaults to the scene's current frame.
- `duration_frames` (integer) = `8` — Frames for the whip (6-12 feels snappy).
- `easing` ('linear' | 'ease_in' | 'ease_out' | 'ease_in_out' | 'ease_in_quad' | 'ease_out_quad' | 'ease_in_out_quad' | 'ease_in_out_sine' | 'ease_in_out_expo' | 'smoothstep' | 'smootherstep' | 'ease_out_back') = `'ease_in_out_expo'` — Speed curve.
- `enable_motion_blur` (boolean) = `True` — Turn on render motion blur for the smear.
- `key_step` (integer) = `1` — Bake a key every N frames (1 = exact every frame).

## `apply_camera_bookmark`

Restore a saved pose (optionally keyframing it — handy for building key-to-key moves).

- `name` (string) **required** — Bookmark to restore.
- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.
- `keyframe_frame` (integer) = `None` — If set, also insert a keyframe of the new pose at this frame.

## `apply_shot_preset`

Position the camera for a classic cinematography shot (size x angle x side) of a subject. Shot sizes assume a standing figure (character, statue, person-sized prop): closer shots crop to the upper body and aim toward the head. For products, vehicles or buildings use frame_objects instead. Returns the resulting framing so you can verify it.

- `subject` (string) **required** — Subject object (e.g. a character).
- `shot_size` ('extreme_wide' | 'wide' | 'full' | 'medium_wide' | 'cowboy' | 'medium' | 'medium_closeup' | 'closeup' | 'extreme_closeup') = `'medium'` — How much of the subject fills the frame (subject height based).
- `angle` ('eye_level' | 'high' | 'low' | 'birds_eye' | 'overhead' | 'worms_eye' | 'dutch' | 'dutch_low') = `'eye_level'` — Vertical camera angle / roll.
- `side` ('front' | 'three_quarter_left' | 'left' | 'profile_left' | 'back_left' | 'back' | 'over_the_shoulder' | 'back_right' | 'right' | 'profile_right' | 'three_quarter_right') = `'front'` — Which side of the subject (relative to the subject's facing, local -Y).
- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.
- `lens` (number) = `None` — Focal length to use (e.g. 85 for flattering close-ups).
- `azimuth_offset_deg` (number) = `0.0` — Extra rotation around the subject.
- `use_subject_facing` (boolean) = `True` — Use the subject's rotation to find its front.
- `allow_below_base` (boolean) = `False` — Allow low angles to put the camera below the subject's base (normally the ground). Off by default.
- `keyframe_frame` (integer) = `None` — If set, also insert a keyframe of the new pose at this frame.

## `clear_camera_animation`

Delete camera keyframes (all, or within a frame range).

- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.
- `frame_start` (integer) = `None` — Only clear keys from this frame.
- `frame_end` (integer) = `None` — Only clear keys up to this frame.
- `include_lens` (boolean) = `True` — Also clear lens/focus keys.
- `include_shake` (boolean) = `True` — Also remove shake (only when clearing everything).

## `clear_camera_cuts`

Remove camera cuts.

- `frame` (integer) = `None` — Only the cut at this frame.

## `compose_subject`

Pan/tilt the camera (without moving it) so the subject sits on a rule-of-thirds / golden point or any screen position. Line positions (left/right_third, golden_left/right) only move the subject horizontally and keep its current height in frame; upper/lower_third only move it vertically; corner points and center set both. Tip: leave look room on the side the subject faces.

- `subject` (string or list[number]) **required** — Object name (uses its bounding-box centre) or [x, y, z] world point.
- `position` ('center' | 'left_third' | 'right_third' | 'upper_third' | 'lower_third' | 'upper_left_third' | 'upper_right_third' | 'lower_left_third' | 'lower_right_third' | 'golden_left' | 'golden_right') = `'left_third'` — Composition point to put the subject on.
- `screen_x` (number) = `None` — Custom horizontal position 0 (left) .. 1 (right).
- `screen_y` (number) = `None` — Custom vertical position 0 (bottom) .. 1 (top).
- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.
- `keep_roll` (boolean) = `True` — Keep the current roll (otherwise level the horizon).
- `keyframe_frame` (integer) = `None` — If set, also insert a keyframe of the new pose at this frame.

## `create_camera`

Create a new camera, optionally aimed at a target, and (by default) make it active.

- `name` (string) = `'Camera'` — Name for the new camera.
- `location` (list[number]) = `None` — World position. Default [0, -10, 2].
- `look_at` (string or list[number]) = `None` — Aim at this. Object name (uses its bounding-box centre) or [x, y, z] world point.
- `rotation_deg` (list[number]) = `None` — XYZ Euler rotation (deg) if not using look_at.
- `lens` (number) = `None` — Focal length in mm (default 50).
- `sensor_preset` ('full_frame' | 'super35' | 'aps_c' | 'aps_c_canon' | 'micro_four_thirds' | 'super16' | 'imax' | 'alexa_lf' | 'red_monstro' | 'one_inch' | 'smartphone') = `None` — Real-world sensor size.
- `set_active` (boolean) = `True` — Make it the scene's render camera.

## `delete_camera`

Delete a camera.

- `camera` (string) **required** — Camera to delete.

## `duplicate_camera`

Copy a camera (pose + lens) as a starting point for an alternate angle.

- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.
- `name` (string) = `None` — Name for the copy.
- `copy_animation` (boolean) = `False` — Also copy keyframes.

## `frame_objects`

Move the camera so the objects exactly fill the frame (like 'View Selected' for cameras). Orthographic cameras adjust ortho_scale instead. Returns the resulting framing.

- `objects` (list[string]) **required** — Objects that must all be in frame.
- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.
- `margin` (number) = `0.1` — Breathing room as a fraction of the frame (0.1 = 10%).
- `azimuth_deg` (number) = `None` — View from this azimuth (see place_camera_spherical).
- `elevation_deg` (number) = `None` — View from this elevation.
- `keep_direction` (boolean) = `True` — Keep the current viewing direction (just dolly to fit).
- `lens` (number) = `None` — Set this focal length before fitting.
- `keyframe_frame` (integer) = `None` — If set, also insert a keyframe of the new pose at this frame.

## `get_camera_animation`

Sample the evaluated camera motion: per-frame location, heading/pitch/roll, lens, focus and speed, plus keyed frames, F-Curve summary, path length and duration. Use it to review moves.

- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.
- `frame_start` (integer) = `None` — Start of sampled range (default: first key).
- `frame_end` (integer) = `None` — End of sampled range (default: last key).
- `step` (integer) = `None` — Sample every N frames (default: auto from max_samples).
- `max_samples` (integer) = `60` — Upper bound on returned samples.

## `get_camera_info`

Full camera details: world pose, heading/pitch/roll, lens, FOV, sensor, clipping, depth of field, constraints, keyed frames and shake.

- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.

## `get_scene_info`

Scene overview: frame range, fps, resolution, cameras, camera cuts and object bounds. Call this first to learn object names and sizes before positioning cameras.

- `include_objects` (boolean) = `True` — Include every object's name, type, centre and size.
- `max_objects` (integer) = `100` — Cap on listed objects.

## `insert_camera_keyframe`

Keyframe the camera's current state.

- `frame` (integer) = `None` — Frame (default current).
- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.
- `properties` (list['location' | 'rotation' | 'lens' | 'focus_distance' | 'fstop' | 'shift' | 'all']) = `None` — What to key (default location, rotation, lens).

## `list_camera_bookmarks`

List saved camera bookmarks.

_No parameters._

## `list_camera_cuts`

List camera cuts (frame -> camera).

_No parameters._

## `list_cameras`

List cameras with location, direction, lens and field of view.

_No parameters._

## `look_at`

Rotate the camera in place so it points at a target, horizon level (plus optional roll).

- `target` (string or list[number]) **required** — Object name (uses its bounding-box centre) or [x, y, z] world point.
- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.
- `roll_deg` (number) = `0.0` — Roll around the view axis (positive = counter-clockwise).
- `keyframe_frame` (integer) = `None` — If set, also insert a keyframe of the new pose at this frame.

## `move_camera`

Instantly apply real-world camera moves relative to the current pose (camera-local axes).

- `move_type` ('dolly' | 'truck' | 'pedestal' | 'crane' | 'pan' | 'tilt' | 'roll' | 'zoom' | 'orbit' | 'orbit_vertical' | 'push_in' | 'pull_out') = `None` — Move to apply. dolly: forward(+)/back(-) m; truck: right(+)/left(-) m; pedestal/crane: up(+)/down(-) m; pan: left(+)/right(-) deg; tilt: up(+)/down(-) deg; roll: counter-clockwise(+) deg; zoom: focal length change mm (+ tighter); orbit: around target, counter-clockwise from above(+) deg; orbit_vertical: over the target up(+) deg; push_in/pull_out: toward/away from target m.
- `amount` (number) = `None` — Amount (metres, degrees or mm depending on type).
- `moves` (list[object]) = `None` — Extra moves applied together, e.g. [{"type":"truck","amount":2},{"type":"pan","amount":-10}].
- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.
- `target` (string or list[number]) = `None` — Subject for orbit/push_in; if given, the camera keeps aiming at it after translating. Object name (uses its bounding-box centre) or [x, y, z] world point.
- `keyframe_frame` (integer) = `None` — If set, also insert a keyframe of the new pose at this frame.

## `place_camera_spherical`

Place the camera on a sphere around a target and aim at it.

- `target` (string or list[number]) **required** — Object name (uses its bounding-box centre) or [x, y, z] world point.
- `azimuth_deg` (number) = `0.0` — Around the target: 0 = in front (-Y side), 90 = +X side, 180 = behind, -90 = -X side.
- `elevation_deg` (number) = `15.0` — Height angle above the target's horizon (negative = below).
- `distance` (number) = `10.0` — Distance from the target in metres.
- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.
- `roll_deg` (number) = `0.0` — Roll around the view axis.
- `relative_to_target_front` (boolean) = `False` — Measure azimuth from the target object's own front (its local -Y) instead of world -Y.
- `keyframe_frame` (integer) = `None` — If set, also insert a keyframe of the new pose at this frame.

## `remove_camera_constraints`

Remove camera constraints.

- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.
- `constraint_type` (string) = `None` — Only remove this type (e.g. TRACK_TO).
- `bake_current_pose` (boolean) = `True` — Keep the pose the constraint produced.

## `remove_camera_shake`

Remove shake added by add_camera_shake.

- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.

## `render_contact_sheet`

Render several frames of the animation into one tiled image (left-to-right, top-to-bottom) to review a camera move at a glance.

- `camera` (string) = `None` — Camera; omit to follow camera cuts / active camera.
- `frames` (list[integer]) = `None` — Exact frames to render (max 24).
- `count` (integer) = `6` — Otherwise render this many evenly spaced frames.
- `columns` (integer) = `3` — Tiles per row.
- `frame_start` (integer) = `None` — Range start for evenly spaced frames.
- `frame_end` (integer) = `None` — Range end for evenly spaced frames.
- `max_size` (integer) = `384` — Longest side of each tile in pixels.
- `engine` ('AUTO' | 'WORKBENCH' | 'EEVEE' | 'CYCLES' | 'CURRENT') = `'AUTO'` — Render engine for the tiles.
- `samples` (integer) = `8` — Samples for EEVEE/Cycles.
- `filepath` (string) = `None` — Also save the PNG here.

## `render_preview`

Render what the camera sees and return the image, so you can judge composition.

- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.
- `frame` (integer) = `None` — Frame to render (default current).
- `max_size` (integer) = `768` — Longest side in pixels (keeps the render aspect).
- `engine` ('AUTO' | 'WORKBENCH' | 'EEVEE' | 'CYCLES' | 'CURRENT') = `'AUTO'` — AUTO = fast Workbench in the UI (Cycles when headless). Use EEVEE/CYCLES to see depth of field, lighting and motion blur.
- `samples` (integer) = `16` — Samples for EEVEE/Cycles.
- `filepath` (string) = `None` — Also save the PNG here.

## `save_camera_bookmark`

Remember the camera's current pose and lens so you can return to it or animate to it later.

- `name` (string) **required** — Bookmark name, e.g. 'hero_wide'.
- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.

## `set_active_camera`

Make a camera the scene's active (render) camera.

- `camera` (string) **required** — Camera to render through.

## `set_camera_keyframes`

Author a camera animation from a list of key poses in one call (the most flexible way to choreograph a custom move).

- `keyframes` (list[object]) **required** — Keys to set, in any order.
- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.
- `interpolation` ('CONSTANT' | 'LINEAR' | 'BEZIER' | 'SINE' | 'QUAD' | 'CUBIC' | 'EXPO' | 'BACK' | 'BOUNCE' | 'ELASTIC') = `'BEZIER'` — Interpolation between keys.
- `easing` ('AUTO' | 'EASE_IN' | 'EASE_OUT' | 'EASE_IN_OUT') = `'AUTO'` — Easing for non-Bezier modes.
- `handle_type` ('FREE' | 'ALIGNED' | 'VECTOR' | 'AUTO' | 'AUTO_CLAMPED') = `'AUTO_CLAMPED'` — Bezier handles; AUTO_CLAMPED avoids overshoot.
- `clear_existing` (boolean) = `False` — Delete all existing camera keys first.

## `set_camera_lens`

Set focal length / field of view, projection, sensor, clipping and lens shift.

- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.
- `lens` (number) = `None` — Focal length in mm.
- `fov_deg` (number) = `None` — Alternatively set the field of view in degrees.
- `fov_axis` ('horizontal' | 'vertical') = `'horizontal'` — Axis fov_deg refers to.
- `lens_type` ('PERSP' | 'ORTHO' | 'PANO') = `None` — Projection.
- `sensor_preset` ('full_frame' | 'super35' | 'aps_c' | 'aps_c_canon' | 'micro_four_thirds' | 'super16' | 'imax' | 'alexa_lf' | 'red_monstro' | 'one_inch' | 'smartphone') = `None` — Real-world sensor size.
- `sensor_width` (number) = `None` — Sensor width mm.
- `sensor_height` (number) = `None` — Sensor height mm.
- `sensor_fit` ('AUTO' | 'HORIZONTAL' | 'VERTICAL') = `None` — Sensor fit.
- `ortho_scale` (number) = `None` — Orthographic view width in metres.
- `clip_start` (number) = `None` — Near clip distance.
- `clip_end` (number) = `None` — Far clip distance.
- `shift_x` (number) = `None` — Horizontal lens shift (fraction of frame).
- `shift_y` (number) = `None` — Vertical lens shift, e.g. to keep verticals straight.
- `keyframe_frame` (integer) = `None` — Keyframe the focal length at this frame.

## `set_camera_transform`

Set the camera's world position and orientation directly.

- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.
- `location` (list[number]) = `None` — New world position (omit to keep).
- `rotation_deg` (list[number]) = `None` — XYZ Euler rotation in degrees.
- `look_at` (string or list[number]) = `None` — Aim at this instead of rotation_deg. Object name (uses its bounding-box centre) or [x, y, z] world point.
- `roll_deg` (number) = `0.0` — Roll around the view axis when using look_at (dutch angle).
- `keyframe_frame` (integer) = `None` — If set, also insert a keyframe of the new pose at this frame.

## `set_depth_of_field`

Configure depth of field (visible in EEVEE/Cycles).

- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.
- `enabled` (boolean) = `True` — Turn depth of field on/off.
- `focus_object` (string) = `None` — Keep this object in focus (follows it). '' clears.
- `focus_point` (string or list[number]) = `None` — Focus at the distance of this point. Object name (uses its bounding-box centre) or [x, y, z] world point.
- `focus_distance` (number) = `None` — Focus distance in metres.
- `fstop` (number) = `None` — Aperture f-stop; lower = shallower focus (1.4 dreamy, 8 deep).
- `blades` (integer) = `None` — Aperture blades (bokeh shape), 0 = round.
- `rotation_deg` (number) = `None` — Aperture rotation.
- `ratio` (number) = `None` — Anamorphic bokeh ratio (>1 = oval).
- `keyframe_frame` (integer) = `None` — Keyframe focus distance and f-stop at this frame.

## `set_frame_range`

Set the scene's frame range, frame rate and/or current frame.

- `frame_start` (integer) = `None` — First frame.
- `frame_end` (integer) = `None` — Last frame.
- `fps` (number) = `None` — Frame rate, e.g. 24, 25, 30, 29.97, 60.
- `current_frame` (integer) = `None` — Jump to this frame.

## `set_keyframe_interpolation`

Change how the camera moves between existing keys.

- `interpolation` ('CONSTANT' | 'LINEAR' | 'BEZIER' | 'SINE' | 'QUAD' | 'CUBIC' | 'QUART' | 'QUINT' | 'EXPO' | 'CIRC' | 'BACK' | 'BOUNCE' | 'ELASTIC') = `'BEZIER'` — LINEAR = constant speed, BEZIER = smooth ease, CONSTANT = hard cuts.
- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.
- `easing` ('AUTO' | 'EASE_IN' | 'EASE_OUT' | 'EASE_IN_OUT') = `None` — Easing.
- `handle_type` ('FREE' | 'ALIGNED' | 'VECTOR' | 'AUTO' | 'AUTO_CLAMPED') = `None` — Bezier handle type.
- `frame_start` (integer) = `None` — Only keys from this frame.
- `frame_end` (integer) = `None` — Only keys up to this frame.
- `include_lens` (boolean) = `True` — Also affect lens/focus keys.

## `set_render_settings`

Frame format and render settings that affect how camera work reads.

- `aspect_preset` ('16:9' | '4k_16:9' | '2.39:1' | '2.35:1' | '1.85:1' | '4:3' | '1:1' | '9:16' | '4:5' | '21:9') = `None` — Common delivery formats (2.39:1 = anamorphic widescreen, 9:16 = vertical).
- `resolution_x` (integer) = `None` — Width in pixels.
- `resolution_y` (integer) = `None` — Height in pixels.
- `resolution_percentage` (integer) = `None` — Render scale %.
- `motion_blur` (boolean) = `None` — Render motion blur.
- `shutter` (number) = `None` — Shutter in frames (0.5 = 180 degree shutter).
- `engine` ('WORKBENCH' | 'EEVEE' | 'CYCLES') = `None` — Render engine.

## `view_through_camera`

Make the camera active and switch the user's 3D viewports to look through it.

- `camera` (string) = `None` — Camera object name. Omit to use the scene's active camera.
