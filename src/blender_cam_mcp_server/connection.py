"""Socket client for the Camera MCP Blender add-on."""

import itertools
import json
import os
import socket

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9877


class BlenderError(RuntimeError):
    """Blender rejected or failed a command."""


class BlenderConnectionError(BlenderError):
    """Could not reach Blender."""


class BlenderConnection:
    def __init__(self, host=None, port=None, timeout=None):
        self.host = host or os.environ.get("BLENDER_CAM_HOST", DEFAULT_HOST)
        self.port = int(port or os.environ.get("BLENDER_CAM_PORT", DEFAULT_PORT))
        self.timeout = float(timeout or os.environ.get("BLENDER_CAM_TIMEOUT", 300))
        self._ids = itertools.count(1)

    def send(self, command, params=None):
        """Send one command and return its result (raises BlenderError on failure).

        A fresh connection per call keeps things robust across Blender restarts.
        """
        request = {"id": next(self._ids), "command": command,
                   "params": {k: v for k, v in (params or {}).items() if v is not None}}
        try:
            sock = socket.create_connection((self.host, self.port), timeout=5.0)
        except OSError as exc:
            raise BlenderConnectionError(
                "Cannot reach Blender at %s:%d (%s). In Blender open the 3D Viewport sidebar (N) > "
                "'Camera MCP' tab and press 'Start Camera MCP Server', or run Blender headless with "
                "scripts/run_headless.py." % (self.host, self.port, exc)) from exc
        try:
            sock.settimeout(self.timeout)
            sock.sendall(json.dumps(request).encode("utf-8") + b"\n")
            buf = b""
            while b"\n" not in buf:
                chunk = sock.recv(1 << 20)
                if not chunk:
                    break
                buf += chunk
        except socket.timeout as exc:
            raise BlenderError("Blender did not answer '%s' within %.0fs" % (command, self.timeout)) from exc
        finally:
            sock.close()
        if not buf:
            raise BlenderError("Blender closed the connection without answering '%s'" % command)
        response = json.loads(buf.split(b"\n", 1)[0].decode("utf-8"))
        if response.get("status") != "ok":
            raise BlenderError(response.get("message", "unknown error"))
        return response.get("result")
