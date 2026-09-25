"""Keep the blender-camera-director skill honest.

* every tool/parameter mentioned in the skill's recipes exists in the MCP schemas;
* every recipe actually runs, in order, against a real scene.
"""

import asyncio
import json
import os
import re

import bpy
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "skills", "blender-camera-director")
CALL = re.compile(r"^([a-z_]+)\s*(\{.*)?$")


def _recipes():
    text = open(os.path.join(SKILL, "references", "shot-recipes.md")).read()
    recipes = []
    for section in re.split(r"^## (?=\d+\.)", text, flags=re.M)[1:]:
        title = section.splitlines()[0].strip()
        calls = []
        for block in re.findall(r"```\n(.*?)```", section, flags=re.S):
            current = None
            for raw in block.splitlines():
                line = re.sub(r"\s+#.*$", "", raw).rstrip()
                if not line:
                    continue
                m = CALL.match(line)
                if m and not raw.startswith(" "):
                    current = [m.group(1), m.group(2) or ""]
                    calls.append(current)
                else:
                    current[1] += " " + line.strip()
        recipes.append((title, [(name, json.loads(args) if args else {}) for name, args in calls]))
    return recipes


RECIPES = _recipes()


@pytest.fixture(scope="module")
def schemas():
    pytest.importorskip("mcp")
    from blender_cam_mcp_server.server import mcp

    tools = asyncio.run(mcp.list_tools())
    return {t.name: (getattr(t, "input_schema", None) or t.inputSchema) for t in tools}


def test_recipes_parsed():
    assert len(RECIPES) == 10
    assert all(calls for _title, calls in RECIPES)


def test_skill_mentions_only_real_tools(schemas):
    body = open(os.path.join(SKILL, "SKILL.md")).read()
    mentioned = set(re.findall(r"`([a-z]+_[a-z_]+)`", body))
    params = {p for s in schemas.values() for p in s.get("properties", {})}

    def enums(node):
        if isinstance(node, dict):
            for v in node.get("enum", []):
                yield v
            for v in node.values():
                yield from enums(v)
        elif isinstance(node, list):
            for v in node:
                yield from enums(v)

    params |= {v for v in enums(list(schemas.values())) if isinstance(v, str)}
    unknown = sorted(m.rstrip("*") for m in mentioned if m not in schemas and m not in params
                     and not m.endswith("_*") and m not in {"scene_bounds", "screen_center", "nearest_composition_point",
                                   "height_fraction", "frame_coverage", "behind_camera",
                                   "path_length", "scene_range_extended", "fully_in_frame",
                                   "partially_in_frame", "average_speed_m_per_s", "execute_python"})
    assert not unknown, unknown


@pytest.mark.parametrize("title,calls", RECIPES, ids=[t for t, _ in RECIPES])
def test_recipe_calls_match_schemas(schemas, title, calls):
    for name, args in calls:
        assert name in schemas, "%s: unknown tool %s" % (title, name)
        props = schemas[name].get("properties", {})
        assert set(args) <= set(props), "%s: %s has unknown params %s" % (title, name, set(args) - set(props))
        missing = set(schemas[name].get("required", [])) - set(args)
        assert not missing, "%s: %s missing %s" % (title, name, missing)


def _build_scene():
    bpy.ops.wm.read_factory_settings(use_empty=False)
    bpy.data.objects.remove(bpy.data.objects["Cube"])

    def box(name, loc, size):
        bpy.ops.mesh.primitive_cube_add(location=loc)
        o = bpy.context.object
        o.name = name
        o.scale = [s / 2 for s in size]
        return o

    bpy.ops.mesh.primitive_plane_add(size=200)
    box("Product", (0, 0, 0.25), (0.4, 0.4, 0.5))
    box("Hero", (0, 0, 0.9), (0.5, 0.3, 1.8))
    box("A", (-1, 0, 0.9), (0.5, 0.3, 1.8)).rotation_euler.z = 1.5708
    box("B", (1, 0, 0.9), (0.5, 0.3, 1.8)).rotation_euler.z = -1.5708
    box("Tower", (25, 25, 15), (6, 6, 30))
    box("Background_Object", (0, 8, 1), (1, 1, 2))
    car = box("Car", (0, 0, 0.7), (1.8, 4.2, 1.4))
    car.keyframe_insert("location", frame=1)
    car.location = (0, -80, 0.7)
    car.keyframe_insert("location", frame=240)
    bpy.context.view_layer.update()


@pytest.mark.parametrize("title,calls", RECIPES, ids=[t for t, _ in RECIPES])
def test_recipe_runs(title, calls):
    from blender_cam_mcp.commands import dispatch

    _build_scene()
    if any(a.get("camera") in {"CAM_A", "CAM_B"} for _n, a in calls):
        dispatch("create_camera", {"name": "CAM_B", "location": [6, -6, 1.6], "look_at": "Hero"})
        dispatch("create_camera", {"name": "CAM_A", "location": [-6, -6, 1.6], "look_at": "Hero"})
    results = []
    for name, args in calls:
        args = dict(args)
        if name.startswith("render_"):
            # Keep the check fast and GPU-free.
            args.update(engine="CYCLES", samples=1, max_size=64)
        results.append((name, dispatch(name, args)))

    for name, res in results:
        for f in (res.get("framing", []) if isinstance(res, dict) else []):
            assert f["visibility"] != "behind_camera", (title, name, f)
        if name == "analyze_framing":
            for f in res["objects"]:
                assert f["in_frame"], (title, f)
