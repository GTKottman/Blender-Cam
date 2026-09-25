"""MCP tool -> socket -> add-on server -> bpy, with the queue pumped on the main thread."""

import asyncio
import json
import socket
import threading
import time

import bpy
import pytest

from blender_cam_mcp.server import CameraMCPServer


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_server(scene):
    server = CameraMCPServer("127.0.0.1", _free_port())
    server.start()
    yield server
    server.stop()


def _pump_until(server, thread, timeout=60):
    deadline = time.monotonic() + timeout
    while thread.is_alive() and time.monotonic() < deadline:
        if not server.process_queue():
            time.sleep(0.002)
    assert not thread.is_alive(), "client did not finish"


def _in_thread(fn):
    box = {}

    def runner():
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001
            box["error"] = exc

    t = threading.Thread(target=runner)
    t.start()
    return t, box


def test_socket_protocol(live_server):
    from blender_cam_mcp_server.connection import BlenderConnection, BlenderError

    conn = BlenderConnection("127.0.0.1", live_server.port, timeout=30)

    def client():
        out = [conn.send("ping"), conn.send("look_at", {"target": "Cube", "camera": None})]
        try:
            conn.send("look_at", {"target": "Missing"})
        except BlenderError as exc:
            out.append(str(exc))
        # Raw, newline-less JSON (compatible with other Blender MCP clients).
        with socket.create_connection(("127.0.0.1", live_server.port)) as s:
            s.sendall(json.dumps({"type": "list_cameras", "params": {}}).encode())
            out.append(json.loads(s.makefile().readline()))
        return out

    t, box = _in_thread(client)
    _pump_until(live_server, t)
    assert "error" not in box, box.get("error")
    ping, look, err, raw = box["value"]
    assert ping["pong"] is True
    assert look["name"] == "Camera"
    assert "No object named 'Missing'" in err
    assert raw["status"] == "ok" and raw["result"][0]["name"] == "Camera"


def test_connection_refused_message():
    from blender_cam_mcp_server.connection import BlenderConnection, BlenderConnectionError

    with pytest.raises(BlenderConnectionError, match="Start Camera MCP Server"):
        BlenderConnection("127.0.0.1", _free_port()).send("ping")


def test_mcp_tools_end_to_end(live_server):
    pytest.importorskip("mcp")
    from blender_cam_mcp_server import server as mcp_server

    mcp_server._blender.port = live_server.port

    async def session():
        tools = {t.name for t in await mcp_server.mcp.list_tools()}
        created = await mcp_server.mcp.call_tool(
            "create_camera", {"name": "Hero", "location": [4, -8, 2], "look_at": "Cube"})
        orbit = await mcp_server.mcp.call_tool(
            "animate_orbit", {"target": "Cube", "start_frame": 1, "end_frame": 48, "angle_deg": 180})
        framing = await mcp_server.mcp.call_tool("analyze_framing", {"objects": ["Cube"], "frame": 24})
        image = await mcp_server.mcp.call_tool(
            "render_preview", {"max_size": 64, "engine": "CYCLES", "samples": 1})
        return tools, created, orbit, framing, image

    t, box = _in_thread(lambda: asyncio.run(session()))
    _pump_until(live_server, t)
    assert "error" not in box, box.get("error")
    tools, created, orbit, framing, image = box["value"]

    assert {"apply_shot_preset", "animate_path", "render_contact_sheet", "add_camera_shake"} <= tools
    assert "execute_python" not in tools

    def text(result):
        blocks = result[0] if isinstance(result, tuple) else getattr(result, "content", result)
        return next(b.text for b in blocks if getattr(b, "type", "") == "text")

    def blocks(result):
        return result[0] if isinstance(result, tuple) else getattr(result, "content", result)

    assert json.loads(text(created))["name"] == "Hero"
    assert json.loads(text(orbit))["keyframes"] == 48
    cube = json.loads(text(framing))["objects"][0]
    assert cube["visibility"] == "fully_in_frame"
    assert cube["screen_center"] == pytest.approx([0.5, 0.5], abs=1e-3)
    kinds = [b.type for b in blocks(image)]
    assert "image" in kinds and "text" in kinds
    assert bpy.data.objects["Hero"].animation_data is not None


def test_blender_errors_reach_the_model(live_server):
    pytest.importorskip("mcp")
    from blender_cam_mcp_server import server as mcp_server

    mcp_server._blender.port = live_server.port

    async def call():
        try:
            await mcp_server.mcp.call_tool("look_at", {"target": "Cubee"})
        except Exception as exc:  # noqa: BLE001 - SDKs differ in how they surface tool errors
            return str(exc)
        return "no error"

    t, box = _in_thread(lambda: asyncio.run(call()))
    _pump_until(live_server, t)
    assert "No object named 'Cubee'" in box["value"] and "Cube" in box["value"]


def test_addon_register_and_server_lifecycle(scene):
    import blender_cam_mcp

    blender_cam_mcp.register()
    try:
        assert hasattr(bpy.types, "CAMMCP_PT_panel")
        assert blender_cam_mcp.start_server(port=_free_port())
        assert blender_cam_mcp._state["server"].running
        blender_cam_mcp.stop_server()
        assert blender_cam_mcp._state["server"] is None
    finally:
        blender_cam_mcp.unregister()
