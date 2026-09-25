"""Run the Camera MCP server from a background Blender.

    blender -b my_scene.blend --python scripts/run_headless.py -- --port 9877

Useful for automation/CI or render nodes. Save your work with the
``execute_python`` tool (``bpy.ops.wm.save_mainfile()``) when enabled, or
open the .blend in the UI afterwards.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "addon"))

import blender_cam_mcp  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
parser = argparse.ArgumentParser()
parser.add_argument("--host", default="127.0.0.1")
parser.add_argument("--port", type=int, default=9877)
parser.add_argument("--allow-python", action="store_true")
args = parser.parse_args(argv)

blender_cam_mcp.run_headless(args.host, args.port, args.allow_python)
