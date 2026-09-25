"""Pure camera math helpers (depend only on ``mathutils``).

Everything here is independent of scene state so it can be unit tested and
reused by the command handlers.
"""

import math

from mathutils import Matrix, Quaternion, Vector

WORLD_UP = Vector((0.0, 0.0, 1.0))


# ---------------------------------------------------------------------------
# Easing
# ---------------------------------------------------------------------------

def _ease_out_back(t):
    c1 = 1.70158
    c3 = c1 + 1.0
    return 1.0 + c3 * (t - 1.0) ** 3 + c1 * (t - 1.0) ** 2


def _ease_in_out_expo(t):
    if t <= 0.0:
        return 0.0
    if t >= 1.0:
        return 1.0
    if t < 0.5:
        return 2.0 ** (20.0 * t - 10.0) / 2.0
    return (2.0 - 2.0 ** (-20.0 * t + 10.0)) / 2.0


EASINGS = {
    "linear": lambda t: t,
    "ease_in": lambda t: t ** 3,
    "ease_out": lambda t: 1.0 - (1.0 - t) ** 3,
    "ease_in_out": lambda t: 4.0 * t ** 3 if t < 0.5 else 1.0 - (-2.0 * t + 2.0) ** 3 / 2.0,
    "ease_in_quad": lambda t: t * t,
    "ease_out_quad": lambda t: 1.0 - (1.0 - t) ** 2,
    "ease_in_out_quad": lambda t: 2.0 * t * t if t < 0.5 else 1.0 - (-2.0 * t + 2.0) ** 2 / 2.0,
    "ease_in_out_sine": lambda t: -(math.cos(math.pi * t) - 1.0) / 2.0,
    "ease_in_out_expo": _ease_in_out_expo,
    "smoothstep": lambda t: t * t * (3.0 - 2.0 * t),
    "smootherstep": lambda t: t * t * t * (t * (t * 6.0 - 15.0) + 10.0),
    "ease_out_back": _ease_out_back,
}


def ease(name, t):
    """Apply the easing curve ``name`` to ``t`` in [0, 1]."""
    try:
        fn = EASINGS[name or "linear"]
    except KeyError:
        raise ValueError(
            "Unknown easing '%s'. Valid: %s" % (name, ", ".join(sorted(EASINGS)))
        ) from None
    t = min(max(t, 0.0), 1.0)
    return fn(t)


def lerp(a, b, t):
    return a + (b - a) * t


# ---------------------------------------------------------------------------
# Orientation
# ---------------------------------------------------------------------------

def look_quat(eye, target, roll=0.0):
    """Quaternion that points a camera at ``target`` from ``eye``.

    Cameras look down their local -Z axis with +Y up. ``roll`` (radians)
    rotates about the view axis; positive rolls the camera counter-clockwise
    as seen from behind it.
    """
    direction = Vector(target) - Vector(eye)
    return direction_quat(direction, roll)


def direction_quat(direction, roll=0.0):
    direction = Vector(direction)
    if direction.length < 1e-9:
        raise ValueError("Camera position and look-at target are the same point")
    # Tracking -Z with a Y-up hint keeps the horizon level (world Z up).
    q = direction.normalized().to_track_quat("-Z", "Y")
    if roll:
        q = q @ Quaternion((0.0, 0.0, 1.0), roll)
    return q


def camera_axes(quat):
    """Return (forward, right, up) world vectors for a camera orientation."""
    q = Quaternion(quat)
    return q @ Vector((0.0, 0.0, -1.0)), q @ Vector((1.0, 0.0, 0.0)), q @ Vector((0.0, 1.0, 0.0))


def heading_pitch(direction):
    """(heading, pitch) in radians of a direction vector.

    Heading is measured counter-clockwise from +X in the XY plane, pitch is
    the angle above the horizon.
    """
    d = Vector(direction).normalized()
    heading = math.atan2(d.y, d.x)
    pitch = math.asin(max(-1.0, min(1.0, d.z)))
    return heading, pitch


def direction_from_heading_pitch(heading, pitch):
    cp = math.cos(pitch)
    return Vector((cp * math.cos(heading), cp * math.sin(heading), math.sin(pitch)))


def camera_roll(quat):
    """Roll (radians) of a camera orientation relative to a level horizon."""
    forward, _right, up = camera_axes(quat)
    level = direction_quat(forward)
    _f, _r, level_up = camera_axes(level)
    angle = level_up.angle(up, 0.0)
    sign = 1.0 if level_up.cross(up).dot(-forward) >= 0.0 else -1.0
    return angle * sign


def spherical_offset(azimuth, elevation, distance):
    """Offset from a target to a camera in spherical coordinates.

    ``azimuth`` (radians) is counter-clockwise from -Y (Blender's "front"
    view, i.e. the camera sits on the -Y side looking toward +Y at 0);
    ``elevation`` is above the horizon.
    """
    ce = math.cos(elevation)
    return Vector((
        math.sin(azimuth) * ce * distance,
        -math.cos(azimuth) * ce * distance,
        math.sin(elevation) * distance,
    ))


def spherical_from_offset(offset):
    """Inverse of :func:`spherical_offset` -> (azimuth, elevation, distance)."""
    offset = Vector(offset)
    distance = offset.length
    if distance < 1e-9:
        return 0.0, 0.0, 0.0
    azimuth = math.atan2(offset.x, -offset.y)
    elevation = math.asin(max(-1.0, min(1.0, offset.z / distance)))
    return azimuth, elevation, distance


def compat_euler(quat, mode, previous=None):
    """Convert ``quat`` to an Euler compatible with ``previous`` (no flips)."""
    m = Quaternion(quat).to_matrix()
    if previous is not None:
        return m.to_euler(mode, previous)
    return m.to_euler(mode)


def compat_quat(quat, previous=None):
    q = Quaternion(quat)
    if previous is not None and q.dot(Quaternion(previous)) < 0.0:
        q.negate()
    return q


# ---------------------------------------------------------------------------
# Lens / field of view
# ---------------------------------------------------------------------------

SENSOR_PRESETS = {
    # name: (width_mm, height_mm)
    "full_frame": (36.0, 24.0),
    "super35": (24.89, 18.66),
    "aps_c": (23.6, 15.6),
    "aps_c_canon": (22.3, 14.9),
    "micro_four_thirds": (17.3, 13.0),
    "super16": (12.52, 7.41),
    "imax": (70.41, 52.63),
    "alexa_lf": (36.7, 25.54),
    "red_monstro": (40.96, 21.60),
    "one_inch": (13.2, 8.8),
    "smartphone": (7.6, 5.7),
}


def render_aspect(scene):
    r = scene.render
    return (r.resolution_x * r.pixel_aspect_x) / max(1e-9, (r.resolution_y * r.pixel_aspect_y))


def camera_fov(cam_data, scene):
    """Horizontal and vertical field of view (radians) as rendered.

    Accounts for render aspect ratio and ``sensor_fit`` exactly like Blender
    does, so the values match what the rendered frame shows.
    """
    aspect = render_aspect(scene)
    fit = cam_data.sensor_fit
    if fit == "AUTO":
        fit = "HORIZONTAL" if aspect >= 1.0 else "VERTICAL"
        sensor = cam_data.sensor_width
    elif fit == "HORIZONTAL":
        sensor = cam_data.sensor_width
    else:
        sensor = cam_data.sensor_height

    if cam_data.type == "ORTHO":
        # Report the ortho extents (in scene units) as a pseudo "fov".
        size = cam_data.ortho_scale
        if fit == "HORIZONTAL":
            return size, size / aspect
        return size * aspect, size

    half = math.atan(sensor / (2.0 * cam_data.lens))
    if fit == "HORIZONTAL":
        hfov = 2.0 * half
        vfov = 2.0 * math.atan(math.tan(half) / aspect)
    else:
        vfov = 2.0 * half
        hfov = 2.0 * math.atan(math.tan(half) * aspect)
    return hfov, vfov


def lens_for_fov(cam_data, scene, fov, axis="horizontal"):
    """Focal length (mm) that yields ``fov`` (radians) along ``axis``."""
    aspect = render_aspect(scene)
    fit = cam_data.sensor_fit
    if fit == "AUTO":
        fit = "HORIZONTAL" if aspect >= 1.0 else "VERTICAL"
        sensor = cam_data.sensor_width
    elif fit == "HORIZONTAL":
        sensor = cam_data.sensor_width
    else:
        sensor = cam_data.sensor_height

    tan_half = math.tan(fov / 2.0)
    # Convert the requested axis to the sensor-fit axis.
    if axis == "horizontal" and fit == "VERTICAL":
        tan_half /= aspect
    elif axis == "vertical" and fit == "HORIZONTAL":
        tan_half *= aspect
    return sensor / (2.0 * tan_half)


# ---------------------------------------------------------------------------
# Framing
# ---------------------------------------------------------------------------

def fit_distance(points, center, forward, right, up, tan_h, tan_v, near=0.0):
    """Distance from ``center`` (along -forward) that keeps all points in view.

    Solves, per point, ``|x| <= depth * tan`` with ``depth = D + r.forward``.
    """
    best = 0.0
    for p in points:
        r = Vector(p) - center
        x = abs(r.dot(right))
        y = abs(r.dot(up))
        along = r.dot(forward)
        need = max(x / tan_h, y / tan_v) - along
        need = max(need, near - along)
        best = max(best, need)
    return best


def bbox_corners(min_v, max_v):
    return [
        Vector((x, y, z))
        for x in (min_v[0], max_v[0])
        for y in (min_v[1], max_v[1])
        for z in (min_v[2], max_v[2])
    ]


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

def _catmull_rom_point(p0, p1, p2, p3, t, alpha=0.5):
    """Centripetal Catmull-Rom (no cusps/self intersections)."""

    def tj(ti, pi, pj):
        d = (pj - pi).length
        return ti + max(d, 1e-6) ** alpha

    t0 = 0.0
    t1 = tj(t0, p0, p1)
    t2 = tj(t1, p1, p2)
    t3 = tj(t2, p2, p3)
    tt = lerp(t1, t2, t)
    a1 = p0 * ((t1 - tt) / (t1 - t0)) + p1 * ((tt - t0) / (t1 - t0))
    a2 = p1 * ((t2 - tt) / (t2 - t1)) + p2 * ((tt - t1) / (t2 - t1))
    a3 = p2 * ((t3 - tt) / (t3 - t2)) + p3 * ((tt - t2) / (t3 - t2))
    b1 = a1 * ((t2 - tt) / (t2 - t0)) + a2 * ((tt - t0) / (t2 - t0))
    b2 = a2 * ((t3 - tt) / (t3 - t1)) + a3 * ((tt - t1) / (t3 - t1))
    return b1 * ((t2 - tt) / (t2 - t1)) + b2 * ((tt - t1) / (t2 - t1))


def smooth_path(points, closed=False, samples_per_segment=48):
    """Dense polyline through ``points`` using a centripetal Catmull-Rom spline."""
    pts = [Vector(p) for p in points]
    if len(pts) < 2:
        raise ValueError("A path needs at least 2 points")
    if len(pts) == 2:
        return [pts[0].lerp(pts[1], i / samples_per_segment) for i in range(samples_per_segment + 1)]

    if closed:
        ext = [pts[-1]] + pts + [pts[0], pts[1]]
        segments = len(pts)
    else:
        ext = [pts[0] * 2.0 - pts[1]] + pts + [pts[-1] * 2.0 - pts[-2]]
        segments = len(pts) - 1

    dense = []
    for s in range(segments):
        p0, p1, p2, p3 = ext[s], ext[s + 1], ext[s + 2], ext[s + 3]
        for i in range(samples_per_segment):
            dense.append(_catmull_rom_point(p0, p1, p2, p3, i / samples_per_segment))
    dense.append(pts[0].copy() if closed else pts[-1].copy())
    return dense


def linear_path(points):
    return [Vector(p) for p in points]


class Polyline:
    """Arc-length parameterised polyline."""

    def __init__(self, points):
        self.points = [Vector(p) for p in points]
        self.cumulative = [0.0]
        for a, b in zip(self.points, self.points[1:]):
            self.cumulative.append(self.cumulative[-1] + (b - a).length)
        self.length = self.cumulative[-1]

    def at_distance(self, s):
        if self.length <= 0.0:
            return self.points[0].copy()
        s = min(max(s, 0.0), self.length)
        lo, hi = 0, len(self.cumulative) - 1
        while hi - lo > 1:
            mid = (lo + hi) // 2
            if self.cumulative[mid] <= s:
                lo = mid
            else:
                hi = mid
        seg = self.cumulative[hi] - self.cumulative[lo]
        t = 0.0 if seg <= 0.0 else (s - self.cumulative[lo]) / seg
        return self.points[lo].lerp(self.points[hi], t)

    def at_fraction(self, f):
        return self.at_distance(f * self.length)

    def at_index_fraction(self, f):
        """Position by sample index (non-constant speed) for f in [0, 1]."""
        n = len(self.points) - 1
        x = min(max(f, 0.0), 1.0) * n
        i = min(int(x), n - 1) if n > 0 else 0
        if n == 0:
            return self.points[0].copy()
        return self.points[i].lerp(self.points[i + 1], x - i)


def to_matrix(loc, quat, scale=(1.0, 1.0, 1.0)):
    return Matrix.LocRotScale(Vector(loc), Quaternion(quat), Vector(scale))
