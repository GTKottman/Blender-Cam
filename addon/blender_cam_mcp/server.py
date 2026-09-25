"""TCP JSON server that forwards MCP requests onto Blender's main thread.

Protocol: one JSON object per line.
    request:  {"id": 1, "command": "look_at", "params": {"target": "Cube"}}
    response: {"id": 1, "status": "ok", "result": {...}}
              {"id": 1, "status": "error", "message": "..."}

Networking happens on background threads; commands are queued and executed
by :meth:`CameraMCPServer.process_queue`, which the add-on calls from a
``bpy.app.timers`` callback (or a headless loop) on the main thread, because
``bpy`` is not thread-safe.
"""

import json
import queue
import socket
import threading
import time
import traceback

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9877
MAX_LINE = 16 * 1024 * 1024


class _Job:
    __slots__ = ("request", "response", "done")

    def __init__(self, request):
        self.request = request
        self.response = None
        self.done = threading.Event()


class CameraMCPServer:
    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT, handler=None, timeout=600.0,
                 on_command=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._handler = handler
        self._on_command = on_command
        self._queue = queue.Queue()
        self._sock = None
        self._thread = None
        self._running = False
        self.last_command = None
        self.commands_run = 0

    # -- lifecycle ---------------------------------------------------------

    @property
    def running(self):
        return self._running

    def start(self):
        if self._running:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((self.host, self.port))
        sock.listen(8)
        sock.settimeout(0.5)
        self._sock = sock
        self._running = True
        self._thread = threading.Thread(target=self._accept_loop, name="camera-mcp-accept", daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        # Fail anything still waiting.
        while True:
            try:
                job = self._queue.get_nowait()
            except queue.Empty:
                break
            job.response = {"id": job.request.get("id"), "status": "error", "message": "server stopped"}
            job.done.set()

    # -- networking (background threads) -----------------------------------

    def _accept_loop(self):
        while self._running:
            try:
                conn, _addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(target=self._client_loop, args=(conn,), name="camera-mcp-client",
                             daemon=True).start()

    def _client_loop(self, conn):
        conn.settimeout(None)
        buf = b""
        try:
            while self._running:
                chunk = conn.recv(65536)
                if not chunk:
                    break
                buf += chunk
                if len(buf) > MAX_LINE:
                    self._send(conn, {"status": "error", "message": "request too large"})
                    break
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if line.strip():
                        self._send(conn, self._handle_line(line))
                # Tolerate clients that send a bare JSON object without newline.
                if buf.strip():
                    try:
                        json.loads(buf.decode("utf-8"))
                    except (ValueError, UnicodeDecodeError):
                        continue
                    line, buf = buf, b""
                    self._send(conn, self._handle_line(line))
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass

    @staticmethod
    def _send(conn, obj):
        conn.sendall(json.dumps(obj).encode("utf-8") + b"\n")

    def _handle_line(self, line):
        try:
            request = json.loads(line.decode("utf-8"))
            if not isinstance(request, dict):
                raise ValueError("request must be a JSON object")
        except (ValueError, UnicodeDecodeError) as exc:
            return {"status": "error", "message": "invalid JSON: %s" % exc}
        # Accept both {"command": ..., "params": ...} and {"type": ..., "params": ...}.
        if "command" not in request and "type" in request:
            request["command"] = request["type"]
        job = _Job(request)
        self._queue.put(job)
        if not job.done.wait(self.timeout):
            return {"id": request.get("id"), "status": "error",
                    "message": "timed out waiting for Blender (is the UI blocked?)"}
        return job.response

    # -- execution (main thread) --------------------------------------------

    def process_queue(self, budget_seconds=0.25):
        """Run queued commands. Must be called from Blender's main thread."""
        deadline = time.monotonic() + budget_seconds
        ran = 0
        while True:
            try:
                job = self._queue.get_nowait()
            except queue.Empty:
                break
            job.response = self._execute(job.request)
            job.done.set()
            ran += 1
            if time.monotonic() > deadline:
                break
        return ran

    def _execute(self, request):
        from .commands import CommandError, dispatch

        rid = request.get("id")
        name = request.get("command")
        params = request.get("params") or {}
        self.last_command = name
        try:
            handler = self._handler or dispatch
            result = handler(name, params)
            self.commands_run += 1
            if self._on_command:
                try:
                    self._on_command(name)
                except Exception:  # pragma: no cover - UI hooks must never break commands
                    pass
            return {"id": rid, "status": "ok", "result": result}
        except CommandError as exc:
            return {"id": rid, "status": "error", "message": str(exc)}
        except Exception as exc:  # noqa: BLE001 - report everything back to the client
            traceback.print_exc()
            return {"id": rid, "status": "error", "message": "%s: %s" % (type(exc).__name__, exc),
                    "traceback": traceback.format_exc(limit=6)}
