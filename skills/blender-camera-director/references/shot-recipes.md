# Shot recipes

Worked tool sequences for common requests. Object names such as `Hero` and `Product` are
placeholders: substitute the real names from `get_scene_info`. The frame numbers assume
24 fps, so rescale them for the scene's fps. Always finish a recipe with the verification step
from SKILL.md.

## Contents
1. Product turntable (seamless loop)
2. Hero reveal (low angle, crane up + push in)
3. Dialogue coverage (wide + two over-the-shoulders, cuts)
4. Drone fly-through / establishing shot
5. Chase cam on a moving vehicle
6. Emotional close-up with focus pull
7. Vertigo shock moment
8. Architectural walkthrough
9. Whip-pan transition between two shots
10. Handheld documentary look

---

## 1. Product turntable (seamless loop)

Mood: premium, calm. Lens 85mm. No shake. The loop must not stutter.

```
create_camera        {"name": "CAM_turntable", "lens": 85}
frame_objects        {"objects": ["Product"], "margin": 0.15, "azimuth_deg": 30, "elevation_deg": 15}
analyze_framing      {"objects": ["Product"]}                       # expect fully_in_frame
set_frame_range      {"frame_start": 1, "frame_end": 120}
animate_orbit        {"target": "Product", "start_frame": 1, "end_frame": 121,
                      "angle_deg": 360, "easing": "linear"}
set_depth_of_field   {"focus_object": "Product", "fstop": 4}         # optional, subtle
render_contact_sheet {"count": 6, "frame_start": 1, "frame_end": 120, "max_size": 320}
```

`end_frame` 121 with a 1–120 range makes frame 121 equal frame 1, so the rendered loop has no
duplicate frame. `frame_objects` fits the product at the start angle only. For very wide
products, check `analyze_framing` at frames 30 and 60 as well, because the silhouette changes
while the camera orbits.

## 2. Hero reveal

Mood: heroic. Start low and full, then crane up while pushing in, ending on a low-angle
medium shot.

```
create_camera        {"name": "CAM_hero_reveal", "lens": 28}
apply_shot_preset    {"subject": "Hero", "shot_size": "full", "angle": "low", "side": "three_quarter_left"}
animate_camera_move  {"move_type": "push_in", "amount": 1.1, "target": [0, 0, 1.35],
                      "moves": [{"type": "crane", "amount": 0.9}],
                      "start_frame": 1, "duration_frames": 144, "easing": "ease_in_out"}
add_camera_shake     {"preset": "breathing", "intensity": 0.6}
analyze_framing      {"objects": ["Hero"], "frame": 145}
```

Two things make a push-in work:

- **Aim at what should end up centred.** Use the chest, not the object name. The object's
  centre is its waist, so pushing in on it enlarges the figure around the waist and crops the
  head. Here the chest point is the Hero's centre raised by 0.25 × its height (1.8 m tall,
  centred at z = 0.9).
- **Scale the amounts.** The `push_in` is about 35% of the `distance` that `apply_shot_preset`
  reported (3.2 m for this figure on a 28mm lens), and the crane is about half the subject's
  height.

The headroom at the last frame must stay positive.

## 3. Dialogue coverage

Two characters, `A` and `B`, facing each other, 1.8 m tall and standing at x = −1 and x = +1.
Keep every camera on the same side (here −Y) of the line through A and B. That's the 180° rule:
it keeps screen direction consistent, so A always looks right and B always looks left.

```
create_camera        {"name": "CAM_01_wide", "lens": 35}
frame_objects        {"camera": "CAM_01_wide", "objects": ["A", "B"], "margin": 0.25,
                      "azimuth_deg": 0, "elevation_deg": 5}

create_camera        {"name": "CAM_02_ots_on_B", "lens": 50}
set_camera_transform {"camera": "CAM_02_ots_on_B", "location": [-1.9, -0.45, 1.6], "look_at": [1, 0, 1.45]}
compose_subject      {"camera": "CAM_02_ots_on_B", "subject": [1, 0, 1.45], "position": "right_third"}

create_camera        {"name": "CAM_03_ots_on_A", "lens": 50}
set_camera_transform {"camera": "CAM_03_ots_on_A", "location": [1.9, -0.45, 1.6], "look_at": [-1, 0, 1.45]}
compose_subject      {"camera": "CAM_03_ots_on_A", "subject": [-1, 0, 1.45], "position": "left_third"}

add_camera_cut       {"camera": "CAM_01_wide", "frame": 1}
add_camera_cut       {"camera": "CAM_02_ots_on_B", "frame": 73}
add_camera_cut       {"camera": "CAM_03_ots_on_A", "frame": 145}
render_contact_sheet {"frames": [1, 73, 145], "columns": 3}
```

Presets can't build an over-the-shoulder shot, because at close-up distance the camera ends up
*in front of* the foreground character. Place it explicitly, working from the positions in
`get_scene_info`:

- **Camera location** = the foreground character's position − 0.9 × (unit vector toward the
  subject) + 0.45 m sideways toward the camera side of the line, at about 0.9 × their height.
- **Look at** the subject's head: centre z + about 0.3 × height.
- Put the subject on the third *away* from the foreground shoulder.

The foreground shoulder should fill the opposite edge of the frame. Confirm it on the contact
sheet.

## 4. Drone fly-through / establishing shot

```
get_scene_info                                    # scene_bounds gives the size of the world
create_camera   {"name": "CAM_drone", "lens": 24}
animate_path    {"points": [[-40, -60, 25], [-10, -25, 18], [8, -5, 12], [14, 8, 20]],
                 "look_mode": "target", "look_target": "Tower",
                 "start_frame": 1, "duration_frames": 240, "easing": "ease_in_out_sine",
                 "bank_factor": 0.4, "create_guide_curve": true}
get_camera_animation {"max_samples": 20}          # speeds should be smooth, not spiky
render_contact_sheet {"count": 8, "columns": 4}
```

Pick waypoints from `scene_bounds`: start outside and high, get lower and closer, and keep
every point above the tallest object nearby. End at least 2–3 × the landmark's width away
from it, because a wide lens right next to a wall just shows the wall. For a first-person feel, use
`"look_mode": "forward"` with `look_ahead_frames` 15–25. When you finish, tell the user the
guide curve exists (it is hidden in renders).

## 5. Chase cam on a moving vehicle

The vehicle (`Car`) must already be animated.

```
create_camera   {"name": "CAM_chase", "lens": 28}
animate_follow  {"target": "Car", "offset": [0, 7, 2.2], "offset_space": "target",
                 "look_offset": [0, -3, 0.8], "start_frame": 1, "end_frame": 240,
                 "position_smoothing": 0.8, "aim_smoothing": 0.5}
add_camera_shake {"preset": "vehicle", "intensity": 0.8}
```

`look_offset` [0, −3, 0.8] aims slightly ahead of the car (it faces −Y), which feels more
dynamic. If the car's "forward" is +Y, flip the signs of both offsets' Y values. Higher
smoothing makes the camera lag behind in turns. Check `analyze_framing` at the frames where the
car turns hardest.

## 6. Emotional close-up with focus pull

```
create_camera        {"name": "CAM_closeup", "lens": 85}
apply_shot_preset    {"subject": "Hero", "shot_size": "closeup", "angle": "eye_level",
                      "side": "three_quarter_right"}
compose_subject      {"subject": "Hero", "position": "left_third"}
animate_camera_move  {"move_type": "push_in", "amount": 0.3, "target": "Hero",
                      "start_frame": 1, "duration_frames": 168, "easing": "ease_in_out_sine"}
animate_rack_focus   {"focus_targets": ["Background_Object", "Hero"], "frames": [24, 60], "fstop": 1.8}
add_camera_shake     {"preset": "subtle", "intensity": 0.7}
render_preview       {"frame": 90, "engine": "EEVEE", "max_size": 512}
```

Use EEVEE or Cycles to review depth of field, because Workbench doesn't show it.

## 7. Vertigo shock moment

```
apply_shot_preset   {"subject": "Hero", "shot_size": "medium", "lens": 35}
animate_dolly_zoom  {"target": "Hero", "start_frame": 100, "duration_frames": 48}
```

With no distance given, the camera moves to half its current distance (the lens halves too),
so the background appears to stretch away. That works at any scale. For a different strength,
read `distance` from the `apply_shot_preset` result and pass `end_distance`: about 0.4–0.6×
for a push toward the subject, or 1.5–2.5× to pull away and compress the background. Keep the
resulting lens between about 15 and 200mm (the tool warns when it's more extreme).

## 8. Architectural walkthrough

Eye height is about 1.6 m, the lens 18–24mm, and the verticals should stay straight: no tilt
and no bank. Shift the lens for headroom instead of tilting the camera.

```
create_camera    {"name": "CAM_walk", "lens": 20}
animate_path     {"points": [[0, -12, 1.6], [0, -4, 1.6], [3, 2, 1.6], [3, 9, 1.6]],
                  "look_mode": "forward", "look_ahead_frames": 30,
                  "start_frame": 1, "duration_frames": 360, "easing": "ease_in_out_sine"}
set_camera_lens  {"shift_y": 0.1}
```

Walking pace is roughly 1–1.4 m/s. Check `average_speed_m_per_s` in the result and change the
duration to match.

## 9. Whip-pan transition

Shot A ends with a whip. The cut to shot B happens mid-blur, and shot B starts with a matching
whip that lands on its framing. Both whips turn the same way, so the blur reads as one
continuous move.

```
animate_whip_pan {"camera": "CAM_A", "angle_deg": 80, "start_frame": 116, "duration_frames": 8}
move_camera      {"camera": "CAM_B", "move_type": "pan", "amount": -80, "keyframe_frame": 116}
animate_whip_pan {"camera": "CAM_B", "angle_deg": 80, "start_frame": 116, "duration_frames": 8}
add_camera_cut   {"camera": "CAM_A", "frame": 1}
add_camera_cut   {"camera": "CAM_B", "frame": 120}
```

Set up CAM_B's final framing first. The `move_camera` pan of −80 keyed at the whip's start
frame pre-rotates the camera, and the +80 whip then arrives exactly on that framing at frame 124.

## 10. Handheld documentary look

```
set_camera_lens  {"lens": 35}
add_camera_shake {"preset": "handheld", "intensity": 0.8, "seed": 3}
```

Combine this with small, imperfect moves. For example, use `set_camera_keyframes` with 3–4
keys a few centimetres apart, each with a slightly different `look_at`. Avoid perfectly
smooth, geometric paths.
