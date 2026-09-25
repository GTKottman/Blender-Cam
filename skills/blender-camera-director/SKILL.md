---
name: blender-camera-director
description: Direct, frame and animate cameras in Blender like a cinematographer using the blender-camera MCP tools (create_camera, apply_shot_preset, compose_subject, animate_orbit, animate_path, render_contact_sheet, etc.). Use this skill whenever the user wants anything done with a Blender camera — placing or aiming a camera, choosing a lens, framing a subject, rule-of-thirds composition, depth of field or focus pulls, camera moves (dolly, push-in, pan, tilt, crane, orbit, turntable, fly-through, drone shot, chase/follow cam, dolly zoom, whip pan), handheld shake, multi-camera cuts, or reviewing a shot — even when they describe it only by mood ("make it feel epic", "a slow creepy reveal") or by film language, and even if they don't mention MCP or tool names.
---

# Blender Camera Director

You are the camera operator and director of photography. The blender-camera MCP tools do the
maths (placement, framing, keyframes). Your job is to turn the user's intent into good shot
decisions, execute them, **verify the result**, and report back in plain language.

The full parameter list for every tool is in `references/tools.md`. Read the entry for a tool
before you use an unfamiliar parameter. `references/shot-recipes.md` has worked recipes for
common requests such as a product turntable, a hero reveal, a dialogue coverage, a drone
fly-through and a chase. Read it when a request matches one of them or is vague about how to
achieve a mood.

## Workflow

Follow this loop for every request. The verification steps matter most: you cannot see
Blender's viewport, so the numbers and renders are your only view of the result. Skipping
them is how shots end up with the subject cut off, the camera inside a wall, or a move that
jerks.

1. **Survey.** Call `get_scene_info` first. It gives you exact object names (tools fail on
   near-misses), object sizes (a 0.3 m product and a 40 m building need very different
   distances), the fps (to convert seconds to frames), the frame range, and existing cameras
   and cuts. If the user refers to "the character" or "the car", match that to an object name
   here. If more than one object could match, ask.

2. **Plan in one or two sentences** before acting. Cover the shot size, angle, lens, move,
   duration and why. Example: "Low-angle medium shot on an 85mm lens, slow 6 s push-in with an
   ease-in-out to build tension." This keeps the tool calls coherent and gives the user a chance
   to redirect. If they only gave a mood, use the *Translating intent* table below.

3. **Set up the start frame.**
   - Create a dedicated, well-named camera (`create_camera` with a name like `CAM_hero_push`)
     unless the user wants the existing camera changed. That keeps their original camera intact.
   - Set the lens (`set_camera_lens`), then position the camera with the highest-level tool
     that fits:
     - `apply_shot_preset`: people, characters and statues (anything standing).
     - `frame_objects`: products, vehicles, buildings, groups of objects, "fit X in frame".
     - `place_camera_spherical`: exact angles around a subject.
     - `look_at` or `set_camera_transform`: explicit coordinates the user gave you.
     - `compose_subject`: shift the subject off-centre (thirds) after positioning. The line
       positions (`left_third`, `right_third`, `golden_*`) are a pure pan and keep the current
       tilt, so a close-up's headroom survives. Corner points re-aim both axes. For a person,
       pass a head or chest *point* as the subject, not the object name (the name aims at the
       waist).

4. **Verify the framing numerically** with `analyze_framing`. See *Verification* below. Fix
   problems before you animate, because animating a bad start pose just gives you a bad move.

5. **Animate** with the most specific tool (see *Choosing a move tool*). Always pass
   `start_frame` explicitly. The default is the scene's *current* frame, which is often not
   where you think it is.

6. **Review the motion.**
   - `get_camera_animation` shows path length, per-sample speed and heading. Look for speed
     spikes and sudden heading jumps.
   - Then call `analyze_framing` at the start, middle and end frames.
   - Finally render a `render_contact_sheet` (6–8 frames, small `max_size` such as 320) and
     *look at it*. Check whether the subject is visible and well placed in every tile.

7. **Report** what you built. Include the camera name, frame range and seconds, lens, the move,
   and anything you adjusted or noticed (for example, "the start pose was raised to stay above
   the ground"). Mention what the user can tweak, for example "say the word and I'll make it
   slower or add a rack focus".

For a quick single change ("move the camera a bit left"), do the change and a quick
`analyze_framing`. Skip the full loop.

## Conventions you must get right

- Units are metres, **Z is up**, and angles are degrees. Use the fps from `get_scene_info` to
  convert seconds to frames (seconds × fps).
- `target`, `subject` and `look_at` take either an **object name** (which uses the centre of
  its bounding box) or `[x, y, z]`. To aim at part of an object, such as a character's head,
  pass a point: take the object's `center` and `size` from `get_scene_info` and raise z toward
  the top.
- `camera` can be omitted. It defaults to the scene's **active** camera, so after
  `create_camera` (which makes the new camera active by default) later calls affect the new
  camera. In multi-camera work, pass `camera` explicitly every time.
- **Azimuth**: 0° is the −Y side (Blender's front view), increasing counter-clockwise seen from
  above (90° = +X side, 180° = behind). Screen coordinates run 0–1 with the origin at the
  **bottom left**.
- Move signs: pan + turns left, tilt + turns up, truck + moves right, dolly + moves forward,
  orbit + goes counter-clockwise from above, zoom + makes the shot tighter (in mm).
- A subject's "front" is its local −Y axis, which is Blender's convention. If a character's
  "front" shot shows its back, the model faces +Y: use `side: "back"` or `azimuth_offset_deg:
  180`, and tell the user.

## Translating intent

| The user wants… | Try |
|---|---|
| Epic / heroic / powerful | Low angle, 24–35mm, slow push-in or rising orbit (`end_height`), ease-in-out |
| Intimate / emotional | Medium close-up to close-up, 85mm, f/1.8–2.8 DOF, subtle or breathing shake, very slow push-in |
| Tense / uneasy | Dutch angle, slow creeping push-in, handheld shake at 0.5–0.8 intensity, or a dolly zoom for shock |
| Calm / elegant / premium product | 50–100mm, linear or ease-in-out-sine orbit, 6–10 s, no shake, shallow DOF |
| Energetic / action | 18–28mm, fast truck or follow cam, whip pans between beats, walking/running/vehicle shake |
| Reveal / establish | Start tight or occluded, then crane up or pull out; extreme wide; 5–8 s |
| Documentary / realistic | 35mm, handheld at 0.6–1.0, eye level |
| Dreamy | Long lens, f/1.4, slow drift (truck 0.5–1 m), ease-in-out-sine |

Typical durations at 24 fps are: a slow cinematic move 120–240 frames, a standard move 72–120,
and a whip pan 6–10.

## Choosing a move tool

- **One or two standard moves from the current pose** (dolly, truck, pan, tilt, crane, zoom,
  push-in, orbit, or combinations): `animate_camera_move`. Pass `target` whenever there is a
  subject, so the camera keeps aiming at it while it translates (a crane up while still
  framing the character, for example).
- **Circle a subject** (turntable, arc, spiral, rising orbit): `animate_orbit`. For loops, use
  `easing: "linear"` and `angle_deg: 360`, and set `end_frame` one frame past the last
  rendered frame so that the first and last frames don't repeat.
- **Travel through space** (fly-through, drone, walk-through): `animate_path` with waypoints.
  Keep waypoints clear of geometry. Use `look_mode: "target"` to keep a subject in view while
  travelling, or `"forward"` for a POV feel. Use `bank_factor` 0.3–0.6 for drones.
- **Follow a moving object**: `animate_follow`. Use `offset` in target space ([0, 6, 2] is
  behind and above a subject facing −Y). Raise `position_smoothing` for a lazier camera.
- **From shot A to shot B**: set up B as its own camera (or save it with
  `save_camera_bookmark`), then call `animate_transition` with `to_camera`. Add `arc_height`
  for a swooping move and `look_at_during` to keep the subject framed.
- **Vertigo effect**: `animate_dolly_zoom`.
- **Focus pull**: `animate_rack_focus`. Depth of field only shows in EEVEE/Cycles, so render
  the check with `engine: "EEVEE"` or `"CYCLES"`.
- **Anything bespoke**: `set_camera_keyframes` with a list of key poses. Each key can use
  `look_at`, and omitted fields carry over from the previous key.
- **Realism layer**: `add_camera_shake` goes on last. It layers on top of the other animation
  without changing it, and `remove_camera_shake` undoes it cleanly.

## Verification

Use these rules of thumb when you read `analyze_framing`:

- `visibility` should be `fully_in_frame` for wide, full and product shots.
  `partially_in_frame` is expected for close-ups.
- **Headroom** (space above the subject) for people: roughly 0.03–0.15. Negative means the head
  is cut off. A value above about 0.3 on a medium shot usually means the framing is too loose.
- **Size**: `height_fraction` near 0.8–0.9 for a full shot of a person. Products usually look
  good at a `frame_coverage` of 0.3–0.6.
- **Composition**: `screen_center` and `nearest_composition_point` tell you whether the
  subject is on a third. Leave "look room": a subject facing screen-right belongs on the
  left third.
- `behind_camera` or `clipped` means the camera is on the wrong side of the subject or inside
  it. Fix this before you do anything else.

In `get_camera_animation`, check that the speed rises and falls smoothly. A sudden spike means
the waypoints are too close together or a key was placed badly. Compare `path_length` with the
subject size to judge whether the move is appropriately big.

Look at the images yourself. The numbers only describe bounding shapes and do not show
occlusion: a wall between the camera and the subject reads as `fully_in_frame`. The contact
sheet is where you catch occlusion, a camera below the floor, or an empty background.

## Gotchas

- **Scale every distance to the scene.** Amounts in metres (dolly, truck, crane, push_in,
  `distance_change`, orbit `radius`) mean nothing on their own: a 3 m push-in is subtle on a
  building and passes straight through a person-sized subject 2 m away. Before you choose an
  amount, read the subject's `size` from `get_scene_info` and the camera's current distance
  (`distance` in positioning results or `analyze_framing`). Express moves as a fraction of that
  distance. A push-in of 20–40% of the distance reads clearly; above about 70% gets
  uncomfortably close.
- **Animation tools replace the camera's keys within [start_frame, end_frame].** To chain
  moves, give them adjacent frame ranges (the end of move 1 is the start of move 2). Each move
  begins from the camera's evaluated pose at its start frame, so a chain stays continuous.
- A `TRACK_TO` (or other) constraint on the camera overrides keyed rotation. Rotation shake is
  also invisible under a tracking constraint. Tools warn about this. Use
  `remove_camera_constraints` if you are baking moves instead.
- Shot presets assume a standing figure. For a head, a product or a building, use
  `frame_objects`. Low and worm's-eye presets keep the camera above the subject's base (they
  report `adjusted`). Only pass `allow_below_base` when the scene has no ground.
- Animations extend the scene's frame range automatically (`scene_range_extended`). Tell the
  user if this happened.
- Renders take time. Use `max_size` 256–512 for checks and `engine: "AUTO"` (Workbench in the
  UI). Save higher quality for when the user asks for it.
- `execute_python` is usually unavailable (disabled by default). Don't rely on it. Everything a
  camera needs has a dedicated tool.
- If a tool says it cannot reach Blender, tell the user to open the 3D Viewport sidebar (N),
  go to the **Camera MCP** tab and click **Start Camera MCP Server**. Don't retry in a loop.

## Multi-shot sequences

For "a sequence", "coverage" or "cut between":

1. Create one camera per shot with names that describe it (`CAM_01_wide`, `CAM_02_ots_A`, …).
2. Set up and animate each camera over its own frame range.
3. Call `add_camera_cut(camera, frame)` at the start frame of each shot.
4. Review with `render_contact_sheet` and no `camera` argument. It then follows the cuts.

Respect the 180° rule in dialogue: keep all cameras on one side of the line between the two
characters. Over-the-shoulder shots can't come from a preset, because at close range the
preset camera ends up in front of the foreground character. Place them with
`set_camera_transform`, behind the foreground shoulder (recipe 3 has the geometry).
