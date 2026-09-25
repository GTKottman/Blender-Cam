"""Build an installable add-on zip: ``python scripts/build_addon.py`` -> dist/blender_cam_mcp.zip"""

import os
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "addon", "blender_cam_mcp")
OUT = os.path.join(ROOT, "dist", "blender_cam_mcp.zip")


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in sorted(os.listdir(SRC)):
            if name.endswith((".py", ".toml")):
                zf.write(os.path.join(SRC, name), os.path.join("blender_cam_mcp", name))
    print(OUT)


if __name__ == "__main__":
    main()
