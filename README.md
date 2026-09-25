# Blender Camera MCP

Let an AI assistant work as your camera operator in Blender. This project connects any
[Model Context Protocol](https://modelcontextprotocol.io) client (Claude Desktop, Claude Code,
Cursor, …) to Blender through a set of camera tools. The assistant can place and aim cameras,
frame subjects, compose shots, animate camera moves, and render previews to check its work.

```
 MCP client  ──stdio──▶  blender-cam-mcp (MCP server)  ──TCP 127.0.0.1:9877──▶  Camera MCP add-on (inside Blender)
 (Claude …)              src/blender_cam_mcp_server                             addon/blender_cam_mcp
```

* **Blender add-on** (`addon/blender_cam_mcp`): runs a small local socket server inside Blender
  and does all of the camera work on Blender's main thread.
* **MCP server** (`src/blender_cam_mcp_server`): exposes the typed, documented tools to the AI
  and forwards each call to the add-on.

Supports Blender **4.2 LTS through 5.x**, including the slotted-action animation system.
The test suite runs against real `bpy` 4.5 LTS and 5.0.

---

## What the AI can do

| Area | Tools |
|---|---|
| **Inspect** | `get_scene_info`, `list_cameras`, `get_camera_info`, `analyze_framing`, `get_camera_animation` |
| **Camera setup** | `create_camera`, `duplicate_camera`, `delete_camera`, `set_active_camera`, `set_camera_lens` (focal length or FOV, sensor presets, ortho/pano, clipping, lens shift), `set_depth_of_field` |
| **Position & compose** | `set_camera_transform`, `look_at`, `move_camera` (dolly · truck · pedestal · crane · pan · tilt · roll · zoom · orbit · push in / pull out, combinable), `place_camera_spherical`, `frame_objects` (fit objects exactly), `apply_shot_preset` (extreme wide → extreme close-up × eye-level/high/low/bird's-eye/worm's-eye/dutch × front/¾/profile/back/over-the-shoulder), `compose_subject` (rule of thirds / golden ratio / any screen point, horizon kept level) |
| **Animate** | `animate_camera_move`, `animate_orbit` (turntable, arc, spiral, rising orbit), `animate_path` (smooth spline fly-through with look-ahead, target, or fixed aim, plus banking), `animate_follow` (damped chase cam), `animate_dolly_zoom` (Vertigo effect), `animate_transition` (move to another camera or pose, optionally in an arc), `animate_rack_focus`, `animate_whip_pan`, `set_camera_keyframes` (write many keys in one call), `insert_camera_keyframe`, `set_keyframe_interpolation`, `clear_camera_animation` |
| **Realism** | `add_camera_shake` / `remove_camera_shake`: presets handheld, subtle, breathing, walking, running, vehicle, helicopter, earthquake, explosion. The shake is layered on delta transforms, so existing keys stay untouched. |
| **Constraints** | `add_track_constraint`, `remove_camera_constraints` |
| **Editing** | `add_camera_cut`, `list_camera_cuts`, `clear_camera_cuts` (switch between cameras over time), `set_frame_range`, `set_render_settings` (aspect presets such as 2.39:1 and 9:16, motion blur, engine) |
| **Bookmarks** | `save_camera_bookmark`, `apply_camera_bookmark`, `list_camera_bookmarks` |
| **Visual review** | `render_preview` (returns the image to the AI), `render_contact_sheet` (several frames tiled into one image) |
| **Guidance** | the `camera://guide` resource (a cinematography cheat sheet) and the `plan_camera_shot` prompt |

Design choices that help an AI:

* **`target` accepts an object name or a point.** When you pass an object name, the tool uses the
  centre of the object's evaluated bounding box. When you leave `camera` out, the tool uses the
  scene's active camera.
* **The motion tools compute a keyframe for every frame** (see `key_step`). The results stay exact
  and editable, and they have no hidden constraints or rig. Euler rotations stay continuous, so the
  camera never makes a 360° flip.
* **Tools report numbers the AI can check.** `analyze_framing` gives each object's screen bounding
  box, frame coverage, headroom and nearest thirds point. `get_camera_animation` samples speed,
  heading, pitch and roll over time. `frame_objects` and `apply_shot_preset` return the framing
  they produced.
* **Error messages suggest a fix.** Examples include "did you mean …", listings of valid options,
  and a warning when a tracking constraint will override keyed rotation.
* **Each command is one undo step** in the Blender UI (*Camera MCP: animate_orbit*, …).

## Installation

### 1. Install the Blender add-on

```bash
python scripts/build_addon.py        # -> dist/blender_cam_mcp.zip
```

In Blender, go to **Edit → Preferences → Add-ons → ⌄ → Install from Disk…** and choose
`dist/blender_cam_mcp.zip`, then enable **Camera MCP**. The zip is both a legacy add-on and a
Blender 4.2+ extension.

Open the 3D Viewport sidebar (**N**), go to the **Camera MCP** tab, and click **Start Camera MCP
Server**. If you want the server to start every time Blender does, enable *Start server
automatically* in the add-on preferences.

### 2. Configure your MCP client

The MCP server needs Python 3.10+ and the `mcp` package. The simplest way to run it is with
[`uv`](https://docs.astral.sh/uv/):

**Claude Desktop** (`claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "blender-camera": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/gtkottman/blender-cam", "blender-cam-mcp"]
    }
  }
}
```

**Claude Code**:

```bash
claude mcp add blender-camera -- uvx --from git+https://github.com/gtkottman/blender-cam blender-cam-mcp
```

To run it from a local checkout instead: `pip install -e .`, then use `blender-cam-mcp` as the
command, or run `python -m blender_cam_mcp_server`.

| Option | Env var | Default |
|---|---|---|
| `--host` | `BLENDER_CAM_HOST` | `127.0.0.1` |
| `--port` | `BLENDER_CAM_PORT` | `9877` |
| — | `BLENDER_CAM_TIMEOUT` | `300` seconds per command (long renders) |
| `--transport` | — | `stdio` (also `sse`, `streamable-http`) |

The default port is 9877, so it doesn't clash with other Blender MCP add-ons that use 9876, and
both can run at once.

### Headless / automation

```bash
blender -b scene.blend --python scripts/run_headless.py -- --port 9877
```

Blender timers don't run in background mode, so this script processes the command queue itself.
When Blender runs headless, `engine="AUTO"` renders previews with Cycles at low sample counts,
because Workbench needs a GPU context.

## Example requests

* *"Give me a slow 8-second push-in on the Statue from a low angle with an 85mm lens, and add
  subtle handheld shake."*
* *"Make a 360° product turntable of the Sneaker, 5 seconds, that loops seamlessly, then show me a
  contact sheet."*
* *"Set up three cameras on the two characters (a wide establishing shot and two over-the-shoulder
  shots) and cut between them every 3 seconds."*
* *"Do a drone fly-through that enters the courtyard, rises over the fountain and ends looking at
  the tower. Bank into the turns."*
* *"Chase the Car from behind and above with a lazy follow cam, then rack focus to the sign at
  frame 120."*
* *"Put the Hero on the left third with look room to the right and check the headroom."*

## Coordinate & angle conventions

* World units are metres, **Z is up**, and angles are in **degrees**.
* Screen coordinates run from 0 to 1 with the origin at the bottom left (as in Blender's
  `world_to_camera_view`).
* **Azimuth**: 0° places the camera on the target's −Y side (Blender's front view), and it
  increases counter-clockwise seen from above: 90° is the +X side and 180° is behind.
* **Subject facing** (`apply_shot_preset`): a subject's front is its local −Y axis, and the
  subject's rotation is taken into account.
* **Moves**: pan + turns left, tilt + turns up, roll + turns counter-clockwise, truck + moves right,
  dolly + moves forward.

## Security

The add-on listens on `127.0.0.1` only by default. The `execute_python` escape hatch is **off**
by default. To enable it, you need both:

1. *Allow arbitrary Python* turned on in the add-on preferences, and
2. `BLENDER_CAM_ENABLE_PYTHON_TOOL=1` set in the MCP server's environment.

## Development

```bash
uv venv --python 3.11 && uv pip install -e ".[dev]"   # installs bpy (Blender as a Python module)
pytest
```

The tests run the real add-on inside `bpy`. They cover framing accuracy, composition, orbit
continuity, dolly-zoom size constancy, path waypoints, follow cam, shake, rack focus, cuts,
bookmarks, rendering, the socket protocol, and a full MCP tool call through the socket.

The wire protocol is newline-delimited JSON:
`{"id": 1, "command": "look_at", "params": {"target": "Cube"}}` →
`{"id": 1, "status": "ok", "result": {…}}`. You can call the add-on from any language this way.
