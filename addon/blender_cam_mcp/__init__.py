"""Camera MCP — lets AI assistants direct Blender cameras over the Model Context Protocol.

The add-on runs a small local TCP server inside Blender. The companion MCP
server (``blender-cam-mcp``) forwards tool calls from an MCP client (Claude
Desktop, Claude Code, Cursor, ...) to it.
"""

bl_info = {
    "name": "Camera MCP",
    "author": "Blender-Cam contributors",
    "version": (1, 0, 0),
    "blender": (4, 2, 0),
    "location": "3D Viewport > Sidebar > Camera MCP",
    "description": "MCP bridge for AI-driven camera placement, framing and animation",
    "category": "Camera",
}

import time

import bpy
from bpy.props import BoolProperty, IntProperty, StringProperty

from . import commands
from .server import DEFAULT_HOST, DEFAULT_PORT, CameraMCPServer

_state = {"server": None, "error": None}
UNDO_SKIP = {"ping", "list_commands", "get_scene_info", "list_cameras", "get_camera_info",
             "analyze_framing", "get_camera_animation", "list_camera_cuts", "list_camera_bookmarks",
             "render_preview", "render_contact_sheet"}


def _addon_prefs():
    addon = bpy.context.preferences.addons.get(__package__)
    return addon.preferences if addon else None


def _push_undo(name):
    if name in UNDO_SKIP:
        return
    try:
        bpy.ops.ed.undo_push(message="Camera MCP: %s" % name)
    except RuntimeError:
        pass


def _timer():
    server = _state["server"]
    if server is None or not server.running:
        return None
    try:
        server.process_queue()
    except Exception as exc:  # pragma: no cover
        print("Camera MCP: error processing queue:", exc)
    return 0.02


def start_server(host=None, port=None):
    stop_server()
    prefs = _addon_prefs()
    host = host or (prefs.host if prefs else DEFAULT_HOST)
    port = port or (prefs.port if prefs else DEFAULT_PORT)
    commands.PYTHON_ALLOWED["value"] = bool(prefs.allow_python) if prefs else False
    server = CameraMCPServer(host, port, on_command=_push_undo)
    try:
        server.start()
    except OSError as exc:
        _state["error"] = "Could not listen on %s:%d (%s)" % (host, port, exc)
        print("Camera MCP:", _state["error"])
        return False
    _state["server"] = server
    _state["error"] = None
    if not bpy.app.timers.is_registered(_timer):
        bpy.app.timers.register(_timer, first_interval=0.05, persistent=True)
    print("Camera MCP: listening on %s:%d" % (host, port))
    return True


def stop_server():
    server = _state["server"]
    if server is not None:
        server.stop()
        _state["server"] = None
    if bpy.app.timers.is_registered(_timer):
        bpy.app.timers.unregister(_timer)


def run_headless(host=DEFAULT_HOST, port=DEFAULT_PORT, allow_python=False):
    """Serve forever from a background Blender (``blender -b --python ...``).

    Timers do not fire in background mode, so this pumps the queue itself.
    """
    commands.PYTHON_ALLOWED["value"] = bool(allow_python)
    server = CameraMCPServer(host, port)
    server.start()
    print("Camera MCP (headless): listening on %s:%d — Ctrl+C to stop" % (host, port), flush=True)
    try:
        while server.running:
            if not server.process_queue():
                time.sleep(0.01)
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------

def _on_allow_python(self, _context):
    commands.PYTHON_ALLOWED["value"] = bool(self.allow_python)


class CAMMCP_Preferences(bpy.types.AddonPreferences):
    bl_idname = __package__

    host: StringProperty(name="Host", default=DEFAULT_HOST,
                         description="Interface to listen on. Keep 127.0.0.1 unless you know you need otherwise")
    port: IntProperty(name="Port", default=DEFAULT_PORT, min=1024, max=65535)
    autostart: BoolProperty(name="Start server automatically", default=False,
                            description="Start listening when Blender starts / the add-on is enabled")
    allow_python: BoolProperty(
        name="Allow arbitrary Python (execute_python tool)", default=False, update=_on_allow_python,
        description="Lets the connected AI run any Python code inside Blender. Only enable if you trust it")

    def draw(self, _context):
        layout = self.layout
        row = layout.row()
        row.prop(self, "host")
        row.prop(self, "port")
        layout.prop(self, "autostart")
        layout.prop(self, "allow_python")


class CAMMCP_OT_start(bpy.types.Operator):
    bl_idname = "camera_mcp.start"
    bl_label = "Start Camera MCP Server"
    bl_description = "Listen for camera commands from the MCP server"

    def execute(self, _context):
        if start_server():
            self.report({"INFO"}, "Camera MCP listening")
            return {"FINISHED"}
        self.report({"ERROR"}, _state["error"] or "Failed to start")
        return {"CANCELLED"}


class CAMMCP_OT_stop(bpy.types.Operator):
    bl_idname = "camera_mcp.stop"
    bl_label = "Stop Camera MCP Server"

    def execute(self, _context):
        stop_server()
        return {"FINISHED"}


class CAMMCP_PT_panel(bpy.types.Panel):
    bl_label = "Camera MCP"
    bl_idname = "CAMMCP_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Camera MCP"

    def draw(self, context):
        layout = self.layout
        server = _state["server"]
        prefs = _addon_prefs()
        if server and server.running:
            layout.label(text="Listening on %s:%d" % (server.host, server.port), icon="CHECKMARK")
            layout.label(text="Commands run: %d" % server.commands_run)
            if server.last_command:
                layout.label(text="Last: %s" % server.last_command)
            layout.operator(CAMMCP_OT_stop.bl_idname, icon="PAUSE")
        else:
            layout.label(text="Server stopped", icon="X")
            if _state["error"]:
                layout.label(text=_state["error"], icon="ERROR")
            layout.operator(CAMMCP_OT_start.bl_idname, icon="PLAY")
        if prefs:
            col = layout.column(align=True)
            col.prop(prefs, "port")
            col.prop(prefs, "allow_python", text="Allow arbitrary Python")
        scene = context.scene
        box = layout.box()
        box.label(text="Active camera: %s" % (scene.camera.name if scene.camera else "none"),
                  icon="OUTLINER_OB_CAMERA")


CLASSES = (CAMMCP_Preferences, CAMMCP_OT_start, CAMMCP_OT_stop, CAMMCP_PT_panel)


def _autostart():
    prefs = _addon_prefs()
    if prefs and prefs.autostart and not bpy.app.background:
        start_server()
    return None


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.app.timers.register(_autostart, first_interval=0.5)


def unregister():
    if bpy.app.timers.is_registered(_autostart):
        bpy.app.timers.unregister(_autostart)
    stop_server()
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
