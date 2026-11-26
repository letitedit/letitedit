"""letitedit VFX (beta): agent-driven 3D/procedural effects composited into Shotcut timelines.

Off by default. Nothing here runs unless the user explicitly asks for effects and an agent
enables the feature (see config.enable). Rendering uses portable Blender; shot analysis uses
small ONNX models (person matte + depth); ffmpeg/melt move frames in and out.
"""

__version__ = "0.1.0-beta"
