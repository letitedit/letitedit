"""One-step installer for the letitedit VFX beta on Windows (x64) or macOS (Apple silicon).

    python setup_vfx.py            # install/verify everything, print a report
    python setup_vfx.py --check    # verify only

Installs into this folder (no system-wide changes): portable Blender 4.5.14 LTS (official build,
SHA-256 verified), two small Apache-2.0 ONNX models, and the onnxruntime Python package.
The feature stays OFF until a user explicitly asks for effects.
"""

import hashlib
import json
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BLENDER_VERSION = "4.5.14"
BLENDER = {
    "win32": ("blender-4.5.14-windows-x64.zip",
              "b9533d2397ac1984db4466fb23a7a4649391cca93f6e84209f9bcc60d071c8b9"),
    "darwin": ("blender-4.5.14-macos-arm64.dmg",
               "65134d9b07b20e2fa8d3c9e44f6f44ffb5c9774dd521b95f50387310241ca170"),
}
BLENDER_URL = "https://download.blender.org/release/Blender4.5/"
MODELS = {
    "modnet.onnx": {"url": "https://huggingface.co/Xenova/modnet/resolve/main/onnx/model.onnx",
                    "license": "Apache-2.0", "purpose": "person cut-out (matting)", "bytes": 25888640},
    "depth_anything_v2_small.onnx": {
        "url": "https://huggingface.co/onnx-community/depth-anything-v2-small/resolve/main/onnx/model.onnx",
        "license": "Apache-2.0", "purpose": "relative depth", "bytes": 99060839},
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    print(f"downloading {url}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as r, open(tmp, "wb") as fh:
        shutil.copyfileobj(r, fh, 1 << 20)
    tmp.replace(dest)


def blender_installed():
    base = ROOT / "blender"
    if sys.platform == "win32":
        return next(iter(base.glob("blender-*/blender.exe")), None)
    exe = base / "Blender.app" / "Contents" / "MacOS" / "Blender"
    return exe if exe.exists() else None


def install_blender(check_only):
    exe = blender_installed()
    if exe or check_only:
        return exe
    if sys.platform not in BLENDER:
        raise SystemExit("Only Windows x64 and Apple-silicon macOS are supported by this installer.")
    if sys.platform == "darwin" and platform.machine() != "arm64":
        raise SystemExit("This Mac is Intel; download the macos-x64 Blender 4.5.14 build manually.")
    name, digest = BLENDER[sys.platform]
    archive = ROOT / "downloads" / name
    if not archive.exists() or sha256(archive) != digest:
        download(BLENDER_URL + name, archive)
    if sha256(archive) != digest:
        raise SystemExit(f"Checksum mismatch for {name}; refusing to install.")
    target = ROOT / "blender"
    target.mkdir(exist_ok=True)
    if sys.platform == "win32":
        with zipfile.ZipFile(archive) as z:
            z.extractall(target)
    else:
        mount = Path("/Volumes/ShotcutVFXBlender")
        subprocess.run(["hdiutil", "attach", "-nobrowse", "-mountpoint", str(mount), str(archive)], check=True)
        try:
            shutil.copytree(mount / "Blender.app", target / "Blender.app", symlinks=True)
        finally:
            subprocess.run(["hdiutil", "detach", str(mount)], check=False)
    return blender_installed()


def install_models(check_only):
    status = {}
    for name, meta in MODELS.items():
        path = ROOT / "models" / name
        if not path.exists() and not check_only:
            download(meta["url"], path)
        status[name] = {"present": path.exists(), "license": meta["license"], "purpose": meta["purpose"],
                        "bytes": path.stat().st_size if path.exists() else None}
    return status


def install_python_deps(check_only):
    try:
        import onnxruntime  # noqa: F401
        return {"onnxruntime": onnxruntime.__version__}
    except ImportError:
        if check_only:
            return {"onnxruntime": None}
    pkg = "onnxruntime-directml" if sys.platform == "win32" else "onnxruntime"
    subprocess.run([sys.executable, "-m", "pip", "install", pkg, "numpy", "pillow"], check=True)
    import onnxruntime
    return {"onnxruntime": onnxruntime.__version__}


def install_filter_ui(check_only):
    """Copy the 'AI Effect (VFX beta)' filter panel into letitedit so effects can live on a clip
    like a text filter. Shotcut must be restarted to pick it up."""
    src = ROOT / "letitedit_filter_ui" / "ai_vfx_layer"
    if sys.platform == "win32":
        filters = ROOT.parent / "app" / "share" / "shotcut" / "qml" / "filters"
    else:
        filters = Path("/Applications/Shotcut.app/Contents/Resources/shotcut/qml/filters")
    dst = filters / "ai_vfx_layer"
    if not filters.exists():
        return {"installed": False, "note": f"Shotcut filters folder not found: {filters}"}
    if not check_only:
        dst.mkdir(exist_ok=True)
        for f in src.iterdir():
            shutil.copy2(f, dst / f.name)
    return {"installed": (dst / "meta.qml").exists(), "path": str(dst)}


def main():
    check_only = "--check" in sys.argv
    exe = install_blender(check_only)
    report = {"blender": {"version": BLENDER_VERSION, "path": str(exe) if exe else None,
                          "license": "GPL-3.0-or-later (separate program)"},
              "models": install_models(check_only), "python": install_python_deps(check_only),
              "letitedit_filter_ui": install_filter_ui(check_only)}
    if exe:
        out = subprocess.run([str(exe), "-b", "--factory-startup", "--python-expr",
                              "import bpy; print('BLENDER_OK', bpy.app.version_string)"],
                             capture_output=True, text=True).stdout
        report["blender"]["runs"] = "BLENDER_OK" in out
    sys.path.insert(0, str(ROOT))
    from letitedit_vfx import hardware
    report["hardware"] = hardware.detect()
    (ROOT / "INSTALLED.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    ok = report["blender"].get("runs") and all(m["present"] for m in report["models"].values()) \
        and report["python"]["onnxruntime"]
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
