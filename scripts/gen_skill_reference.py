"""Regenerate skills/blender-camera-director/references/tools.md from the MCP tool schemas.

    python scripts/gen_skill_reference.py
"""

import asyncio
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from blender_cam_mcp_server.server import mcp  # noqa: E402

OUT = os.path.join(ROOT, "skills", "blender-camera-director", "references", "tools.md")


def _type(schema):
    if "enum" in schema:
        return " | ".join(repr(v) for v in schema["enum"])
    if "anyOf" in schema:
        parts = [_type(s) for s in schema["anyOf"] if s.get("type") != "null"]
        return " or ".join(parts)
    t = schema.get("type", "any")
    if t == "array":
        return "list[%s]" % _type(schema.get("items", {}))
    return t


async def main():
    tools = sorted(await mcp.list_tools(), key=lambda t: t.name)
    lines = [
        "# Tool reference (generated)",
        "",
        "Generated from the MCP server's schemas by `scripts/gen_skill_reference.py`; do not edit by hand.",
        "Parameters marked **required** have no default. Everything else can be omitted.",
        "",
        "## Contents",
        "",
    ]
    lines += ["- `%s`" % t.name for t in tools]
    for t in tools:
        desc = " ".join((t.description or "").split())
        lines += ["", "## `%s`" % t.name, "", desc, ""]
        schema_all = getattr(t, "input_schema", None) or t.inputSchema  # MCP SDK 2.x / 1.x
        props = schema_all.get("properties", {})
        required = set(schema_all.get("required", []))
        if not props:
            lines.append("_No parameters._")
            continue
        for name, schema in props.items():
            default = "" if name in required else " = `%r`" % (schema.get("default"),)
            req = " **required**" if name in required else ""
            text = schema.get("description", "")
            lines.append("- `%s` (%s)%s%s — %s" % (name, _type(schema), req, default, text))
    with open(OUT, "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print("%s (%d tools)" % (OUT, len(tools)))


asyncio.run(main())
