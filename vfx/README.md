# letitedit — VFX beta

Experimental, **off by default**. Agent-driven 3D/procedural effects composited into Shotcut
timelines through the `letitedit_vfx_*` MCP tools. The agent guide is the VFX section of
`C:\LetItEdit\AGENTS.md`.

## What is installed (all inside this folder; nothing system-wide)

| Component | Version | Size | License | Purpose |
|---|---|---|---|---|
| Blender (portable) | 4.5.14 LTS, official Windows x64 zip, SHA-256 `b9533d23…c8b9` verified | 399 MB download, 0.87 GB unpacked | GPL-3.0-or-later (run as a separate program) | 3D, materials, animation, rendering (EEVEE GPU, Cycles CPU fallback) |
| MODNet (`models/modnet.onnx`, from Xenova/modnet) | ONNX | 26 MB | Apache-2.0 | person cut-out / matting |
| BiRefNet lite (`models/birefnet-lite-official/`, from ZhengPeng7) | PyTorch safetensors | 169.4 MiB | MIT | default GPU person matte; fetched on first use |
| Depth Anything V2 Small (`models/depth_anything_v2_small.onnx`, from onnx-community) | ONNX | 99 MB | Apache-2.0 | relative depth |
| onnxruntime-directml (Python package) | 1.24.4 | — | MIT | runs the models on the GPU (DirectML) or CPU |

## Portrait cut-out comparison (31 Oct 2026)

The normal `cutout`, `backdrop`, `text_behind` and `clone` made items and the
VFX analysis path share `letitedit_vfx/portrait_matte.py`. On an NVIDIA GPU it
uses the author's BiRefNet-lite checkpoint in a separate CUDA worker. A narrow
blend with MODNet restores soft hair and some finger detail, while BiRefNet's
stable body remains the base. If the GPU, checkpoint or worker is unavailable,
the stream falls back to cleaned MODNet: enclosed holes and stable one-frame
dropouts are repaired without holding a moving edge. Each shot has its own
history. Made-item masks are cached by source size/mtime, range, frame rate,
frame size and matte version, so a background or text change reuses the cut-out.
`backdrop` has gentle colour, brightness and edge light matching by default;
`light_match: false` turns those off. `sky` uses its own sky mask; it does not
remove the person from the frame.

Check moving hair and limbs for halos and missing regions. Temporal-stability measurements are not segmentation-accuracy measurements.

The files below come
from the model authors' own Hugging Face repositories, at pinned revisions.
Their model cards identify the weights' licences and their code repositories
carry the matching licence texts, copied into each local model folder. The
weight hashes match the authors' LFS hashes from the Hugging Face API.

| Candidate | Official weight file | Revision | Bytes | SHA-256 | Licence |
|---|---|---|---:|---|---|
| SAM 2 Hiera Tiny | `facebook/sam2-hiera-tiny/model.safetensors` | `7c218beaf0bb87874785f32b582f640134fc1c09` | 155,841,672 | `1449035ba6ba2ed524c646da989e5cb3a9b93b97f1c1b2d474e598c3b748d99f` | Apache-2.0 |
| BiRefNet lite | `ZhengPeng7/BiRefNet_lite/model.safetensors` | `aa62cd87eafb9cc43056d08ef3615a14628b831d` | 177,634,392 | `4417d89795250e698c3cb0ae8df15743810065f646f48a694fdfa7ca052d0815` | MIT |

The files live under git-ignored `vfx/models/sam2-hiera-tiny/` and
`vfx/models/birefnet-lite-official/`. `vfx/tests/download_cutout_models.py`
repeats the pinned download and verification without installing packages.
The older `birefnet_lite.onnx` in the same folder is a verified community
conversion, not the author-hosted checkpoint used for this comparison. The author-hosted checkpoint needs CUDA torchvision for deformable convolutions. CPU inference is too slow for the default path.

Use the CUDA model environment for the official checkpoint, with the author's 1024 px input. Keep GPU work separate from renders.

The official checkpoint is listed for verified first-use fetch. It can have a harder fine-hair edge; inspect moving masks. Cleaned MODNet is the fallback, and the older ONNX conversion remains for still-image callouts.

macOS (Apple silicon): `setup_vfx.py` installs the `macos-arm64` Blender 4.5.14 build
(SHA-256 `65134d9b…a170`) and plain `onnxruntime` (CoreML/CPU). Not yet tested on a Mac.

## Layout

| Path | What |
|---|---|
| `letitedit_vfx/config.py` | Paths, the feature flag (`settings.json`), Originals guard |
| `letitedit_vfx/hardware.py` | GPU/CPU tier detection (high / medium / low) → preview size and samples |
| `letitedit_vfx/media.py` | Timeline/file segments to frames (melt / ffmpeg), ProRes 4444 / H.264 encoders |
| `letitedit_vfx/analyze.py` | Person matte, depth, camera-motion check, light estimate, analysis sheet |
| `letitedit_vfx/blender/` | `runner.py` (Blender entry), `vfxlib.py` (helpers), `effects/*.py` (templates) |
| `letitedit_vfx/composite.py` | Overlay or full composite (occlusion, glow, flicker, shake), filmstrips |
| `letitedit_vfx/pipeline.py`, `jobs.py`, `worker.py` | Background analysis/render jobs |
| `letitedit_vfx/library.py` | Reusable presets in `library/` |
| `letitedit_vfx/api.py` | Entry points used by `C:\LetItEdit\bridge\vfx_tools.py` (MCP tools) |
| `letitedit_filter_ui/ai_vfx_layer/` | Shotcut filter panel 'AI Effect (VFX beta)' (MLT `watermark` overlay); installed into Shotcut by `setup_vfx.py` |
| `setup_vfx.py` | Install / verify on Windows or Apple-silicon Mac |
| `tests/test_unit.py` | Unit tests; `C:\LetItEdit\bridge\test_vfx_mcp.py` is the end-to-end MCP test |

Working files: `work/` (analysis frames), `jobs/` (renders and logs). Both can be deleted any time.

## New machine (Mac / HP laptop)
1. Copy `C:\LetItEdit\vfx` (or the whole letitedit folder) to the machine.
2. `python setup_vfx.py` → downloads Blender + models, verifies checksums, prints the hardware tier.
3. Register the `shotcut` MCP server for Claude Code / Codex as on this PC.
Weak machines get smaller previews and fewer samples automatically; if EEVEE cannot start
(old OpenGL), renders fall back to Cycles on the CPU.

## Adding an effect template
Create `letitedit_vfx/blender/effects/<name>.py` with `build(ctx)` (see `tool_popup.py`), add it to
`EFFECTS` in `pipeline.py`, document its params in AGENTS.md, and add a render to `tests/test_unit.py`.
