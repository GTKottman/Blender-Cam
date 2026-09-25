"""Preview rendering: single stills and tiled contact sheets as PNG."""

import base64
import os
import struct
import tempfile
import zlib

import bpy


class _RenderState:
    """Temporarily override render settings and restore them afterwards."""

    def __init__(self, scene, camera, engine, width, height, samples):
        self.scene = scene
        self.camera = camera
        self.engine = engine
        self.width = width
        self.height = height
        self.samples = samples

    def __enter__(self):
        s = self.scene
        r = s.render
        self.saved = {
            "camera": s.camera, "frame": s.frame_current, "engine": r.engine,
            "filepath": r.filepath, "res": (r.resolution_x, r.resolution_y, r.resolution_percentage),
            "format": (r.image_settings.file_format, r.image_settings.color_mode),
            "use_ext": r.use_file_extension,
        }
        self.saved_cycles = None
        self.saved_eevee = None
        if self.camera is not None:
            s.camera = self.camera
        r.engine = self.engine
        r.resolution_x, r.resolution_y, r.resolution_percentage = self.width, self.height, 100
        r.image_settings.file_format = "PNG"
        r.image_settings.color_mode = "RGB"
        r.use_file_extension = True
        if self.engine == "CYCLES" and hasattr(s, "cycles"):
            self.saved_cycles = (s.cycles.samples, getattr(s.cycles, "use_denoising", None))
            s.cycles.samples = self.samples
        elif self.engine.startswith("BLENDER_EEVEE") and hasattr(s, "eevee"):
            ee = s.eevee
            attr = "taa_render_samples"
            if hasattr(ee, attr):
                self.saved_eevee = getattr(ee, attr)
                setattr(ee, attr, self.samples)
        return self

    def __exit__(self, *exc):
        s = self.scene
        r = s.render
        sv = self.saved
        s.camera = sv["camera"]
        r.engine = sv["engine"]
        r.filepath = sv["filepath"]
        r.resolution_x, r.resolution_y, r.resolution_percentage = sv["res"]
        r.image_settings.file_format, r.image_settings.color_mode = sv["format"]
        r.use_file_extension = sv["use_ext"]
        if self.saved_cycles is not None:
            s.cycles.samples = self.saved_cycles[0]
        if self.saved_eevee is not None:
            s.eevee.taa_render_samples = self.saved_eevee
        if s.frame_current != sv["frame"]:
            s.frame_set(sv["frame"])
        return False


def _preview_size(scene, max_size):
    r = scene.render
    w = r.resolution_x * r.resolution_percentage / 100.0
    h = r.resolution_y * r.resolution_percentage / 100.0
    scale = min(1.0, max_size / float(max(w, h)))
    return max(4, int(round(w * scale))), max(4, int(round(h * scale)))


def _render_to(scene, frame, path):
    if frame is not None and scene.frame_current != int(frame):
        scene.frame_set(int(frame))
    scene.render.filepath = path
    bpy.ops.render.render(write_still=True)
    if not os.path.exists(path):
        raise RuntimeError("Render produced no file at %s" % path)


def render_still(scene, camera, frame, max_size, engine, samples, filepath=None):
    w, h = _preview_size(scene, max_size)
    tmp = None
    if not filepath:
        fd, tmp = tempfile.mkstemp(suffix=".png", prefix="cam_mcp_")
        os.close(fd)
        filepath = tmp
    filepath = bpy.path.abspath(filepath)
    if not filepath.lower().endswith(".png"):
        filepath += ".png"
    with _RenderState(scene, camera, engine, w, h, samples):
        _render_to(scene, frame, filepath)
        rendered_frame = scene.frame_current
    with open(filepath, "rb") as fh:
        data = fh.read()
    if tmp:
        os.remove(tmp)
    return {"camera": camera.name, "frame": rendered_frame, "width": w, "height": h, "engine": engine,
            "filepath": None if tmp else filepath, "png_base64": base64.b64encode(data).decode("ascii")}


def _load_rgb(path):
    """Load a PNG through Blender and return rows top-to-bottom of RGB bytes."""
    img = bpy.data.images.load(path, check_existing=False)
    try:
        w, h = img.size
        px = [0.0] * (w * h * 4)
        img.pixels.foreach_get(px)
    finally:
        bpy.data.images.remove(img)
    rows = []
    for y in range(h - 1, -1, -1):
        base = y * w * 4
        row = bytearray(w * 3)
        for x in range(w):
            i = base + x * 4
            j = x * 3
            row[j] = int(max(0.0, min(1.0, px[i])) * 255 + 0.5)
            row[j + 1] = int(max(0.0, min(1.0, px[i + 1])) * 255 + 0.5)
            row[j + 2] = int(max(0.0, min(1.0, px[i + 2])) * 255 + 0.5)
        rows.append(bytes(row))
    return w, h, rows


def _load_rgb_fast(path):
    try:
        import numpy as np
    except ImportError:
        return _load_rgb(path)
    img = bpy.data.images.load(path, check_existing=False)
    try:
        w, h = img.size
        px = np.empty(w * h * 4, dtype=np.float32)
        img.pixels.foreach_get(px)
    finally:
        bpy.data.images.remove(img)
    arr = (np.clip(px.reshape(h, w, 4)[::-1, :, :3], 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    return w, h, [arr[y].tobytes() for y in range(h)]


def write_png(path, width, height, rows):
    """Minimal RGB8 PNG writer (rows top-to-bottom)."""
    raw = b"".join(b"\x00" + r for r in rows)

    def chunk(tag, data):
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 6))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(png)


def contact_sheet(scene, camera, frames, columns, max_size, engine, samples, filepath=None):
    """Render ``frames`` and tile them (left-to-right, top-to-bottom)."""
    w, h = _preview_size(scene, max_size)
    columns = max(1, min(columns, len(frames)))
    rows_n = (len(frames) + columns - 1) // columns
    gap = 4
    sheet_w = columns * w + (columns + 1) * gap
    sheet_h = rows_n * h + (rows_n + 1) * gap
    bg = bytes((24, 24, 24))
    sheet = [bytearray(bg * sheet_w) for _ in range(sheet_h)]
    tmpdir = tempfile.mkdtemp(prefix="cam_mcp_sheet_")
    cams = []
    try:
        with _RenderState(scene, camera, engine, w, h, samples):
            for i, f in enumerate(frames):
                p = os.path.join(tmpdir, "f%04d.png" % i)
                _render_to(scene, f, p)
                cams.append(scene.camera.name if scene.camera else None)
                tw, th, tile = _load_rgb_fast(p)
                ox = gap + (i % columns) * (w + gap)
                oy = gap + (i // columns) * (h + gap)
                for y in range(min(th, h)):
                    sheet[oy + y][ox * 3:(ox + min(tw, w)) * 3] = tile[y][:min(tw, w) * 3]
        out = filepath and bpy.path.abspath(filepath)
        target = out or os.path.join(tmpdir, "sheet.png")
        if not target.lower().endswith(".png"):
            target += ".png"
        write_png(target, sheet_w, sheet_h, [bytes(r) for r in sheet])
        with open(target, "rb") as fh:
            data = fh.read()
    finally:
        for name in os.listdir(tmpdir):
            try:
                os.remove(os.path.join(tmpdir, name))
            except OSError:
                pass
        try:
            os.rmdir(tmpdir)
        except OSError:
            pass
    return {
        "frames": frames,
        "cameras": cams,
        "layout": {"columns": columns, "rows": rows_n, "tile_size": [w, h],
                   "order": "left-to-right, top-to-bottom"},
        "engine": engine,
        "filepath": out or None,
        "png_base64": base64.b64encode(data).decode("ascii"),
    }
