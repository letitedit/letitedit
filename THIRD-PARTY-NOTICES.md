# letitedit - third-party notices

## Learn's speed-change detector
- No new library, model, service or download. The detector uses existing NumPy arrays and OpenCV feature tracking;
  its offline synthetic-fixture script uses the existing `app/ffmpeg.exe`.
- Local package metadata: NumPy 2.5.2, `BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0`;
  opencv-contrib-python-headless 5.0.0.93, Apache-2.0 (NumPy/OpenCV contributors; existing notices below).
  Sources: https://github.com/numpy/numpy and https://github.com/opencv/opencv .
- Local FFmpeg n9.0.2-12-gc867e13549 reports `--enable-gpl --enable-version3`, already covered by this bundle's
  GPL-3.0 source obligations. No GPLv2-only component was added. The owner's synthetic footage is not shipped.

## Camera vocabulary reference
- **cinecode** by Sarp Y?ld?z (@sarpstar), Copyright (c) 2026, MIT.
  Source: https://github.com/sarpstar/cinecode, `references/camera-moves.md`.
  The motion skill's vocabulary is an independently worded adaptation, not its
  runtime. The upstream MIT notice is retained in
  `looks\themes\NOTICE-drawing-theme-sources.txt`.

## Drawing Theme recipes
- **lemo-opuscar** style recipes by LemoLab, Copyright (c) 2026 LemoLab, MIT. Source:
  https://github.com/lemomo-ai/lemo-opuscar at commit d33bdea74eeecde3922b0fbad227f0d3dc7afe75, as collected in
  **cinecode** by Sarp Yıldız (@sarpstar), Copyright (c) 2026, MIT (https://github.com/sarpstar/cinecode at commit
  67f9807112b97ae253d4a5f0eccaccc46c3b2633, `styles/`).
  The drawing Themes Art Deco, Stained glass, Paper lantern, Red paper-cut, Silkscreen poster, Swiss grid, Whiteboard,
  ASCII terminal and 80s cel anime (`looks\<id>\recipe.md`) are independently worded adaptations of those recipes, with
  letitedit's own drawing code and pictures; each Theme's `themes.json` entry names its source recipe. Both MIT notices
  are kept in `looks\themes\NOTICE-drawing-theme-sources.txt`.

Prepared 2026-10-20 (roadmap A6b) for a possible release; not legal advice. Lists every component letitedit ships
or downloads on first use: name, version, licence, copyright holder, source, and where it lives under
C:\LetItEdit. Exact hashes are in the SOURCE.md files and in release\source\app-binaries-manifest.tsv.
GPL source for the editor: release\source\README.md.

## Attribution that must appear in videos or credits
- **GeoNames** (place names from letitedit_places / footage "place:" lines, maps): CC BY 4.0 requires attribution
  wherever the data, or names derived from it, are shown: "Contains data from GeoNames (www.geonames.org), licensed
  under CC BY 4.0." (models\geo\SOURCE.md). A place name burned into a video counts.
- **Natural Earth** (maps drawn by letitedit_map): public domain, no attribution required; suggested credit
  "Made with Natural Earth." (maps\naturalearth\SOURCE.md).
- **Chatterbox voices**: every output carries Resemble AI's inaudible Perth watermark (not a credit line).
- **Noto animated emoji** (Elements emojis, asset library ids `noto/...`, refs `anim:...`): CC BY 4.0 requires a credit
  wherever one is shown, e.g. in the video's description: "Animated emoji: Noto Emoji Animation by Google, licensed under
  CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/)" (assets\licences\noto-emoji-animation-CC-BY-4.0.txt;
  `assets.credits(files)` lists what a video owes). The still Fluent emoji, Tabler icons, Lottie elements and CC0 sounds
  need no credit line.
- Fonts (OFL/Apache/UFL), music models and other voice models below require no credit line in the video.
- Learn's sound-effect finder uses the Demucs model, numpy, scipy and ffmpeg below, and names sounds against the CC0
  sound library (section 7), which needs no credit line. Its sound-device setting (off by default) also runs PANNs and
  DBS-TIGER-DnR (below), downloaded on first use; neither puts anything in a video.

## 1. Editor (app\)
| Component | Version | Licence | Copyright | Source | Where |
|---|---|---|---|---|---|
| Shotcut (forked as "letitedit Assist") | 26.9.27, upstream commit 325c2cc6422d93567d4edb57f1fee401f73beea1 + local changes | GPL-3.0-or-later | Meltytech, LLC and contributors; changes: letitedit | https://github.com/mltframework/shotcut ; release\source | app\letitedit-*.exe, app\share\shotcut |
| Official Shotcut Windows bundle | 26.9.27 (shotcut-win64-26.9.27.zip) | GPL-3.0 as a whole | Meltytech, LLC | https://github.com/mltframework/shotcut/releases/tag/v26.9.27 | app\ |
| MLT | 7.41.0 (63218a28d21f1e64b5b9e6671b4ff9146023282c); letitedit rebuilds two modules with its patches: qt (font folders, weights) and plus (captions that run to the video's end) | LGPL-2.1-or-later (framework, plus); GPL modules (plusgpl, qt with GPL3=ON, rubberband, vid.stab...) | Meltytech, LLC and contributors; patches: letitedit | https://github.com/mltframework/mlt ; patches and build script in engine-patches, release\source\mlt-patches (0001-0003) | app\libmlt*.dll, app\lib\mlt (libmltqt6.dll and libmltplus.dll patched), app\melt.exe |
| FFmpeg | n9.0.2-12-gc867e13549, --enable-gpl --enable-version3 | GPL-3.0 as built | the FFmpeg developers | https://github.com/FFmpeg/FFmpeg ; shotcut-src-26.9.27.txz | app\av*.dll, sw*.dll, ffmpeg/ffprobe/ffplay.exe |
| Qt | 6.11.2 (MSYS2 qt6-* 6.11.2-1/-2) | LGPL-3.0 (some tools GPL-3.0) | The Qt Company Ltd. and contributors | https://download.qt.io/official_releases/qt/6.11/6.11.2/ ; MSYS2 source packages | app\Qt6*.dll, app\lib\qt6, app\lib\qml |
| libvterm | 0.3.3 | MIT | Paul Evans and contributors | https://github.com/neovim/libvterm/releases/tag/v0.3.3 ; src\third_party\libvterm\LICENSE | statically linked into app\letitedit-*.exe; licence at licences\libvterm-MIT.txt |
| Microsoft WebView2 SDK loader | 1.0.4314.35 | BSD-3-Clause, with bundled third-party notices | Microsoft Corporation and contributors | Microsoft's NuGet package Microsoft.Web.WebView2 1.0.4314.35; src\third_party\webview2\LICENSE.txt and NOTICE.txt | app\WebView2Loader.dll; licence and notice at licences\WebView2Loader-* |
| x264 | 0.165.3222 b35605a | GPL-2.0-or-later | x264 project | https://code.videolan.org/videolan/x264 | app\libx264-165.dll |
| x265 | 4.3+1 | GPL-2.0-or-later | MulticoreWare, Inc. | https://bitbucket.org/multicoreware/x265_git | app\libx265-217.dll |
| frei0r, movit, rubberband (GPL-2.0+), fftw (GPL-2.0+), sox (LGPL/GPL), vid.stab (GPL-2.0+), ladspa-swh (GPL-2.0+), bigsh0t (GPL), glaxnimate 0.5.4 (GPL-3.0) | per shotcut-src-26.9.27.txz | as listed | respective authors | shotcut-src-26.9.27.txz | app\, app\lib |
| libvpx, aom 3.13.1, dav1d, SVT-AV1, opus, vorbis, theora, webp (BSD); OpenCV 4.x + contrib 4.12.0 (Apache-2.0); vmaf 3.0.0 (BSD-2-Clause-Patent); OpenBLAS (BSD-3); SDL2 (zlib); ICU (ICU); zimg (WTFPL); cairo (LGPL-2.1/MPL-1.1); glib2 (LGPL-2.1+); freetype (FTL/GPL-2); harfbuzz (MIT); libxml2 (MIT); gcc runtime (GPL-3 with GCC exception) and ~50 more | see app-binaries-manifest.tsv / msys2-sources.tsv | as listed there | respective authors | MSYS2 sources / shotcut-src | app\ |
| whisper.cpp / ggml | 1.8.3 | MIT | the ggml authors | https://github.com/ggerganov/whisper.cpp | app\libwhisper.dll, ggml*.dll, whisper-cli.exe |
| Mesa llvmpipe (opengl32sw.dll) | per Shotcut 26.9.27 | MIT | Mesa contributors | https://mesa3d.org | app\opengl32sw.dll |
| Lottie elements (graphics, text, transitions) | Shotcut 26.9.27 | Lottie Simple License | LottieFiles | app\share\shotcut\elements\Lottie Simple License.txt | app\share\shotcut\elements |
| Noto animated emoji (elements\emojis, 1,196 .tgs) | Shotcut 26.9.27 | CC BY 4.0 per Google's Noto Emoji Animation site (the folder's "SIL Open Font License.txt" is the font's licence) | Google LLC | https://googlefonts.github.io/noto-emoji-animation/ ; assets\licences\noto-emoji-animation-CC-BY-4.0.txt | app\share\shotcut\elements\emojis |
| Elements sounds (letitedit's CC0 set, 57 FLAC) | 2026-10-29 (src 2eaf6df6) | CC0 1.0 / public domain | Kenney.nl, Freesound contributors, Wikimedia Commons contributors, letitedit (synthesised) | app\share\shotcut\elements\sounds\CC0 sounds - credits.txt | app\share\shotcut\elements\sounds |
| Kokoro voice previews | Shotcut 26.9.27 | Apache-2.0 | hexgrad | https://huggingface.co/hexgrad/Kokoro-82M | app\share\shotcut\voices |
| gopro2gpx | per Shotcut 26.9.27 | GPL-3.0 | Dan Dennedy et al. | https://github.com/ddennedy/gopro2gpx | app\gopro2gpx.exe |

`app\LICENSE` (Apache-2.0 text) is shipped by upstream Shotcut 26.9.27 without naming its component; `app\COPYING.txt` is GPL-3.0.

## 2. Tool server (bridge) Python environment - envs\bridge-clean (release\env\requirements-bridge*.txt)
Python 3.14 (PSF-2.0). Packages (full list with licences: envs\bridge-clean\licences.tsv, 78 packages):
mcp 2.3.0 (MIT), numpy 2.5.2 (BSD-3), scipy 1.18.1 (BSD-3), pillow 12.3.0 (MIT-CMU), pillow_heif 1.8.0 (BSD-3; bundles
libheif LGPL-3.0), opencv-contrib-python-headless 5.0.0.93 (Apache-2.0), onnxruntime-directml 1.24.4 (MIT),
fonttools 4.66.0 (MIT), PyYAML 6.0.3 (MIT), soundfile 0.14.0 (BSD-3; bundles libsndfile LGPL-2.1), faster-whisper
1.2.1 (MIT), ctranslate2 4.8.1 (MIT), av 18.0.0 (BSD-3; bundles FFmpeg with x264/x265, GPL), huggingface_hub 1.27.0
(Apache-2.0), tokenizers 0.23.1 (Apache-2.0), kokoro-onnx 0.4.7 (MIT), phonemizer-fork 3.3.1 (GPL-3.0),
espeakng-loader 0.2.4 (MIT; bundles espeak-ng GPL-3.0), praat-parselmouth 0.4.7 (GPL-3.0-or-later;
Yannick Jadoul and contributors, https://github.com/YannickJadoul/Parselmouth; bundles Praat by Paul Boersma and David
Weenink, GPL-3.0-or-later; the pitch tracker in timing.prosody, with a numpy fallback without it), tqdm (MPL-2.0 AND MIT), certifi (MPL-2.0), and their
permissive dependencies. No AGPL package.

## 3. Model environments (installed by setup scripts from PyPI / download.pytorch.org; not shipped)
| Env | Main packages | Licences |
|---|---|---|
| envs\models | torch 2.8 cu128, torchaudio, torchvision, transformers, demucs, open_clip, speechbrain, accelerate, bitsandbytes, timm, nara_wpe 0.0.11, lameenc | BSD / Apache-2.0 / MIT; lameenc LGPL-3.0+; NVIDIA CUDA runtime libs under NVIDIA's CUDA EULA |
| envs\voice | chatterbox-tts, torch 2.6 cu124, diffusers, gradio, librosa, pykakasi, soxr, resemble-perth | MIT / Apache / ISC; pykakasi GPL-3.0+; soxr LGPL-2.1+ |
| envs\voice_dots, voice_qwen3, voice_voxcpm (C5) | dots.tts 0.3.1, qwen-tts 0.1.1, voxcpm 2.0.3 + torch | Apache-2.0 (per models\*\SOURCE.md) |
| %APPDATA%\uv\tools\openai-whisper | openai-whisper, torch, tiktoken, numba | MIT / BSD |

## 4. Models and data (downloaded on first use from the origin listed; records in each SOURCE.md)
| Model / data | Version / revision | Licence | Copyright holder | Source | Where |
|---|---|---|---|---|---|
| Whisper large-v3-turbo, base(.en), small(.en) | sha256 in URL | MIT | OpenAI | https://openaipublic.azureedge.net/main/whisper/models/<sha256>/<name>.pt | %USERPROFILE%\.cache\whisper |
| faster-whisper medium.en, base.en, small | Systran HF revisions a29b04bd, 3d3d5dee, 536b0662 | MIT | OpenAI (weights), SYSTRAN (conversion) | https://huggingface.co/Systran | %USERPROFILE%\.cache\huggingface |
| whisper.cpp ggml-base.en.bin | sha256 a03779c8... | MIT | ggml authors / OpenAI | https://huggingface.co/ggerganov/whisper.cpp | models\ggml-base.en.bin (models\README.txt) |
| Qwen3.5-4B | 851bf6e8 | Apache-2.0 | Alibaba Cloud (Qwen) | https://huggingface.co/Qwen/Qwen3.5-4B | models\hf (SOURCE.md) |
| Chatterbox | 5bb1f6ee | MIT | Resemble AI | https://huggingface.co/ResembleAI/chatterbox | models\hf |
| Chatterbox Turbo | 749d1c1a | MIT | Resemble AI | https://huggingface.co/ResembleAI/chatterbox-turbo | models\chatterbox-turbo |
| CLIP ViT-B-32 laion2B-s34B-b79K | 1a25a446 | MIT | LAION | https://huggingface.co/laion/CLIP-ViT-B-32-laion2B-s34B-b79K | models\hf |
| CLAP htsat-unfused | 8fa0f1c6 | Apache-2.0 | LAION | https://huggingface.co/laion/clap-htsat-unfused | models\hf |
| PANNs Cnn14_DecisionLevelMax (AudioSet sound event detection; Learn's sound-device setting, off by default; 312 MB on first use) | Zenodo 3987831 v3, md5 70539c43c18b6a289b3199c503a82c5a | CC BY 4.0 (weights); MIT (network code, copied in `bridge/sfx_devices_worker.py`) | Qiuqiang Kong et al. ("PANNs", 2020) | https://zenodo.org/records/3987831 ; https://github.com/qiuqiangkong/audioset_tagging_cnn | models\panns (SOURCE.md) |
| DBS-TIGER-DnR (film-sound separation: dialogue, music, effects; Learn's sound-device setting, off by default; 4 MB on first use) | HF JusperLee/DBS-TIGER-DnR model.safetensors sha256 3d820574...; code github JusperLee/Dynamic-Band-Splitting ff526463 | Apache-2.0 (code and weights; parts of the code MIT: BS-RoFormer (Phil Wang), Music-Source-Separation-Training (Roman Solovyev, ZFTurbo), TIGER (Kai Li), see its THIRD_PARTY.md) | Zhang, Li, Hu (Tsinghua), 2026 | https://huggingface.co/JusperLee/DBS-TIGER-DnR ; https://github.com/JusperLee/Dynamic-Band-Splitting | models\dbs-tiger (SOURCE.md) |
| SpeechBrain spkrec-ecapa-voxceleb | 0f99f2d0 | Apache-2.0 | SpeechBrain | https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb | models\hf |
| CommonAccent ECAPA accent id | 14bebf44 | MIT | Juan Zuluaga-Gomez | https://huggingface.co/Jzuluaga/accent-id-commonaccent_ecapa | models\accent-id-commonaccent_ecapa |
| Demucs htdemucs | 955717e8-8726e21a | MIT | Meta Platforms, Inc. | https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/955717e8-8726e21a.th | models\torch (SOURCE.md) |
| BAAI bge-small-en-v1.5 | 5c38ec7c | MIT | BAAI | https://huggingface.co/BAAI/bge-small-en-v1.5 | models\bge-small-en-v1.5 |
| SCUNet (scunet_color_real_psnr) | KAIR release v1.0 | Apache-2.0 (SCUNet), MIT (KAIR) | Kai Zhang et al. | https://github.com/cszn/SCUNet | models\scunet |
| Real-ESRGAN x2plus, general-x4v3 | v0.2.1, v0.2.5.0 | BSD-3-Clause | Xintao Wang | https://github.com/xinntao/Real-ESRGAN | models\realesrgan |
| DeepFilterNet (deep-filter exe) | 0.5.6 | MIT OR Apache-2.0 | Hendrik Schroeter | https://github.com/Rikorose/DeepFilterNet | models\deepfilternet |
| FFmpeg 8.1 GPL build with vid.stab (BtbN) | n8.1 "latest" zip, sha256 d1ff977a... | GPL-3.0 (vid.stab GPL-2.0+; build scripts MIT) | the FFmpeg developers; Georg Martius; BtbN | https://github.com/BtbN/FFmpeg-Builds | models\ffmpeg-vidstab |
| ACE-Step 1.5 (music) + code ca1e85fe | 19671f40 | MIT (embedded Qwen3-Embedding-0.6B Apache-2.0) | ACE Studio / StepFun | https://huggingface.co/ACE-Step/Ace-Step1.5 | models\ace-step-1.5, ace-step-1.5-code |
| dots.tts-soar | 2f9b3e18 | Apache-2.0 | dots studio | https://huggingface.co/dots-studio/dots.tts-soar | models\dots-tts-soar |
| Qwen3-TTS 12Hz 1.7B Base | fd4b2543 | Apache-2.0 | Alibaba Cloud (Qwen) | https://huggingface.co/Qwen/Qwen3-TTS-12Hz-1.7B-Base | models\qwen3-tts-1.7b-base |
| VoxCPM2 | 32279eff | Apache-2.0 | OpenBMB | https://huggingface.co/openbmb/VoxCPM2 | models\voxcpm2 |
| Kokoro-82M ONNX + voices | release model-files-v1.0 | Apache-2.0 (weights), MIT (kokoro-onnx) | hexgrad; thewh1teagle | https://github.com/thewh1teagle/kokoro-onnx | vfx\models (SOURCE.md) |
| BiRefNet-lite ONNX | de15b22b | MIT | Peng Zheng et al. | https://huggingface.co/onnx-community/BiRefNet_lite-ONNX | vfx\models |
| SAM 2 Hiera Tiny (`model.safetensors`) | 7c218beaf0bb87874785f32b582f640134fc1c09, SHA-256 `1449035ba6ba2ed524c646da989e5cb3a9b93b97f1c1b2d474e598c3b748d99f` | Apache-2.0 (Meta model card and https://github.com/facebookresearch/sam2/blob/main/LICENSE) | Meta Platforms, Inc. | https://huggingface.co/facebook/sam2-hiera-tiny | vfx\models\sam2-hiera-tiny (locally downloaded candidate; not in installer) |
| BiRefNet lite official (`model.safetensors`) | aa62cd87eafb9cc43056d08ef3615a14628b831d, SHA-256 `4417d89795250e698c3cb0ae8df15743810065f646f48a694fdfa7ca052d0815` | MIT (author model card and https://github.com/ZhengPeng7/BiRefNet/blob/main/LICENSE) | Peng Zheng et al. | https://huggingface.co/ZhengPeng7/BiRefNet_lite | vfx\models\birefnet-lite-official (verified first-use download; checkpoint not bundled) |
| MODNet ONNX | fa2fa546 | Apache-2.0 | Zhanghan Ke et al. | https://huggingface.co/Xenova/modnet | vfx\models |
| Depth Anything V2 Small ONNX | 4472b736 | Apache-2.0 | Lihe Yang et al. (TikTok/HKU) | https://huggingface.co/onnx-community/depth-anything-v2-small | vfx\models |
| LaMa ONNX | c3c0c9e4 | Apache-2.0 | Samsung AI (advimman/lama); Carve | https://huggingface.co/Carve/LaMa-ONNX | vfx\models |
| Sky segmentation ONNX | 3ba8c6df | MIT (origin not fully confirmed, see SOURCE.md) | xiongzhu666 | https://huggingface.co/JianyuanWang/skyseg | vfx\models |
| YuNet / SFace / VitTrack | OpenCV Zoo f12e1279 / ba91a3b9 / fef72f8f | MIT / Apache-2.0 / Apache-2.0 | OpenCV Zoo contributors | https://github.com/opencv/opencv_zoo | vfx\models |
| GeoNames cities1000, admin1, countryInfo | 2026-10-20 dump | CC BY 4.0 (attribution above) | GeoNames | https://download.geonames.org/export/dump/ | models\geo |
| Natural Earth vector + SR_LR relief | 5.1.2 / 2.0.0 | public domain | Natural Earth (NACIS) | https://github.com/nvkelso/natural-earth-vector, https://naciscdn.org | maps\naturalearth |

## 5. Separate programs
| Program | Version | Licence | Source | Where |
|---|---|---|---|---|
| Blender | 4.5.14 (vfx), 5.2 (letitedit_3d) | GPL-3.0-or-later | https://download.blender.org/source/ | vfx\blender; Blender 5.2 install |
| HyperFrames CLI (motion clips, `letitedit_motion`) | 0.8.214 (npm `hyperframes`) | Apache-2.0, Copyright 2026 HeyGen, Inc. (licence text: motion\LICENSE-hyperframes.txt; the package ships no NOTICE file) | https://github.com/heygen-com/hyperframes | motion\engine (shipped since 30 Oct 2026) |
| HyperFrames' npm dependencies (76 packages, pinned by motion\engine\package-lock.json) | as locked | 54 MIT, 8 Apache-2.0, 6 ISC, 2 BSD-3-Clause, 1 0BSD, 1 CC0-1.0, sharp's libvips binaries Apache-2.0 AND LGPL-3.0-or-later (dynamic library, unmodified; LGPL text in licences\) | npm registry | motion\engine\node_modules (shipped without type definitions, source maps and readmes; each package's own licence file kept) |
| anidoodle's music engine (music written as a score, `letitedit_music_write`) | commit 6ae8827, most of its music folder, bundled and changed by letitedit on 4 Nov 2026 (the changed files say so; a new command line, and no sound pack, recorded rooms, sound effects, drawing code or Remotion) | Apache-2.0, Copyright 2026 Alex Greenshpun; based on anidoodle by Alex Greenshpun (licence and notice: written-music\LICENSE-anidoodle.txt, written-music\NOTICE-anidoodle.txt; the notice's sound pack and Van Gogh picture aren't in letitedit). Nothing is owed per video | https://github.com/alexgreensh/anidoodle | written-music\written-music.mjs (shipped), source in written-music\engine |
| anidoodle's drawing code (optional drawing kits for code scenes, `M.look.<name>`) | commit 9c20e77 (v0.10.1): `core.ts`, `gallery.ts`, `scrapbookKit.ts` copied whole with a header added, and marks taken from `flatVector.ts`, `paperCraft.ts`, `scrapbook.ts` and `koiDrawKit.ts`; for the pencil, ink and board kits also `colouredPencilKit.ts`, `charcoalErasureKit.ts`, `blueprintKit.ts` and `drafting.ts` copied whole (two small changes, named in their headers), and marks taken from `pocketWatch.ts`, `ranunculusDraw.ts`, `wren.ts`, `wrenDraw.ts`, `stipple.ts`, `mellan.ts`, `scratchboard.ts` and `moonPhases.ts`; for the paper, cartoon and pixel hands also `pixelArtKit.ts`, `toyBrickKit.ts`, `isometricKit.ts`, `embroideryKit.ts` and `rubberHoseKit.ts` copied whole, and marks taken from `fox.ts`, `balloon.ts`, `storybook.ts`, `koi.ts`, `lowPoly.ts`, `isometric.ts`, `toyBrick.ts` and `rubberHose.ts`; for the paint and print hands also `paintedOilKit.ts`, `brokenColourKit.ts`, `dreamGlazeKit.ts`, `sumiEKit.ts`, `folkTaleKit.ts`, `riso.ts`, `halftoneKit.ts` and `woodcutKit.ts` copied whole, and marks taken from `paintedOil.ts`, `brokenColour.ts`, `midCentury.ts`, `sumiE.ts`, `lighthouseDraw.ts`, `halftone.ts` and `woodcut.ts`, changed by letitedit on 4 Nov 2026 (the headers in `motion\runtime\looks-src` say how); its pictures, film runner, `three`, Remotion and sound pack are left out | Apache-2.0 | Copyright 2026 Alex Greenshpun | `motion\runtime\looks\`, with `LICENSE-anidoodle.txt` and `NOTICE-anidoodle.txt`; source `motion\runtime\looks-src\` |
| Node.js (runs the HyperFrames CLI and the music writer) | 22.15.1 (the build PC's official Windows release, signed by the OpenJS Foundation) | MIT, Copyright Node.js contributors; bundled libraries under their own licences (V8 BSD-3-Clause, libuv MIT, OpenSSL Apache-2.0, ICU Unicode-3.0, zlib, llhttp, c-ares, nghttp2, brotli, undici and others; motion\node\LICENSE.txt names them; full texts in the release's LICENSE file, https://github.com/nodejs/node/blob/v22.15.1/LICENSE) | https://nodejs.org/ | motion\node\node.exe (shipped) |
| chrome-headless-shell (renders motion clips on the build PC) | 152.0.7977.30 | BSD-3-Clause (Chromium) with bundled third-party licences (its own LICENSE/ABOUT files) | https://googlechromelabs.github.io/chrome-for-testing/ | motion\chrome (this PC only; not shipped) |
| Microsoft Edge / Google Chrome (draw motion clips in an install) | the person's own, 140 or newer | their own licences; not shipped, not modified: the engine starts the installed browser headless with a temporary profile | already on the PC | the browser's own folder |
| uv (installs the whisper tool env) | user install | MIT OR Apache-2.0 | https://github.com/astral-sh/uv | user PATH |
| Microsoft Visual C++ v14 Redistributable (x64) (the C++ runtime the tools' packages need; setup runs it only on a PC whose Windows lacks the runtime, with one admin prompt) | 14.52.37029 (vc_redist.x64.exe, as signed by Microsoft, from https://aka.ms/vc14/vc_redist.x64.exe) | Microsoft Software License Terms for the Visual C++ Redistributable; the redistributable is listed as distributable code in the Visual Studio licence (shown by its own installer; not modified) | https://learn.microsoft.com/cpp/windows/latest-supported-vc-redist | setupc_redist.x64.exe (shipped) |

## 6. Fonts (fonts\library)
316 Google Fonts families: 305 SIL OFL-1.1, 10 Apache-2.0, 1 Ubuntu Font Licence 1.0; each family folder holds its
licence text (OFL.txt / LICENSE.txt / UFL.txt), Tinos included since 2026-10-20 (googlefonts/tinos OFL.txt,
commit 5df023370055d3fe8f05aa288fe0ba9a6928068a). Copyright: each family's authors (see the licence file).
Fonts may be used in videos; OFL fonts may not be sold on their own and Reserved Font Names may not be used for
modified versions. Source: https://github.com/google/fonts.

**Font matching in Learn.** Learn compares the letters of a reference video's text with the
families above, drawn on this PC; it uses no other font data and downloads nothing.

**Fonts fetched on demand (since November 2026).** The installer ships an index of every Google Fonts family (fonts\google-fonts.json.gz and fonts\google-fonts-glyphs.bin: names, licences, measured shape and a small drawing of 74 characters per family, made by letitedit from the fonts at one pinned commit of https://github.com/google/fonts). A family the person or the AI chooses comes down from that commit, checked against the index, with its own licence file (OFL.txt, LICENSE.txt or UFL.txt) beside it in %LOCALAPPDATA%\Microsoft\Windows\Fonts\letitedit-on-demand\<Family>\, with a letitedit-font.json record (source, commit, licence, designers, date). The same licence terms apply as for the bundled families: free to use in videos; OFL fonts may not be sold on their own.

## 7. Asset library (assets\; bridge\assets.py, letitedit_assets)
Per-source details (version, download hash, when and where the licence was checked) are in each
assets\manifest\<source>.json header; licence texts in assets\licences. Media is made again by tools\assets.
| Component | Version | Licence | Copyright | Source | Where |
|---|---|---|---|---|---|
| Microsoft Fluent Emoji (3D PNG, Color and Flat SVG, default skin tone) | commit 1ffb34c7 (2026-08-24) | MIT | Microsoft Corporation | https://github.com/microsoft/fluentui-emoji | assets\emoji\fluent |
| Tabler Icons (outline and filled SVG) | 3.50.0 (npm @tabler/icons, sha256 4c2eb678...) | MIT | Pawel Kuna | https://github.com/tabler/tabler-icons | assets\icons\tabler |
| CC0 sound-effect library (565 files; copied from the local collection) | 2026-10-29 | CC0 1.0 / public domain, per file in license_log.csv | Kenney.nl; Freesound contributors (CC0 only); Wikimedia Commons contributors | assets\sfx\library\_Licenses\license_log.csv | assets\sfx\library |
| Kenney Sci-Fi Sounds, Digital SFX, UI SFX (151 files not already in the library) | Kenney's OpenGameArt uploads (sha256 in cache\downloads\kenney\*\source.json) | CC0 1.0 | Kenney Vleugels (kenney.nl) | https://opengameart.org/users/kenney ; https://kenney.nl/assets | assets\sfx\kenney |
| letitedit synthesised sounds (28) | 1 (tools\assets\synth_sfx.py) | CC0 1.0 (ours) | letitedit | tools\assets\synth_sfx.py | assets\sfx\synth |
| CC0 music library (785 songs; 32 of them shipped as the starter set in `starter-music\`, listed in `starter-music\starter-list.csv`; the rest indexed only where the library exists) | library.csv | CC0 1.0 / Public Domain Mark, per song | each song's artist (library.csv) | music-library\library.csv (Internet Archive album pages) | music-library |

## yt-dlp (the video downloader; fetched on first use, not in the installer)

letitedit_fetch uses yt-dlp (https://github.com/yt-dlp/yt-dlp), released into the public domain under the Unlicense (https://unlicense.org). The program is downloaded from its GitHub release on first use, pinned by version, size and SHA-256 (`bridge/ytdlp_pin.json`), and run as a separate program with no console window; letitedit links none of its code. The Windows executable bundles Python and libraries under their own licences (listed in the release's `THIRD_PARTY_LICENSES.txt`). It is used only to fetch a reference video from a link the person gives, kept in their own folders.

## Beat This! (the beat finder; in the installer)

The beat finder is Beat This! by Foscarin, Schlueter and Widmer, Johannes Kepler University Linz (https://github.com/CPJKU/beat_this), checkpoint final0, converted to ONNX with its large weights stored as 16-bit floats, in `models\beat-finder`. Its README: "The code and the published model weights are released under the MIT license. Note that some of the training files are fully copyrighted or under limited Creative Commons licenses, and it is up to the user to assess whether this may impact their use case."
It runs on ONNX Runtime (MIT), already part of the tools. Its spectrogram and chunking are reimplemented in `bridge\beat_finder.py` from its MIT code.

## Optional code-scene shaders

The following twelve ingredients are MIT-licensed. They are not scene defaults. Original sources, their SHA-256 checksums,
source and licence URLs, and settings are recorded in `motion/runtime/shaders/catalogue.json`; the original files and full
licence texts are in that directory. Each `.shader.js` registration embeds the full applicable MIT licence.

| Ingredient | Source file | Author / credit | Licence |
|---|---|---|---|
| simplex2D | stegu/webgl-noise `src/noise2D.glsl` | Ian McEwan / Ashima Arts | MIT |
| classic2D | stegu/webgl-noise `src/classicnoise2D.glsl` | Stefan Gustavson | MIT |
| simplex3D | stegu/webgl-noise `src/noise3D.glsl` | Ian McEwan / Ashima Arts; Stefan Gustavson | MIT |
| film | mrdoob/three.js `examples/jsm/shaders/FilmShader.js` | three.js authors | MIT |
| vignette | mrdoob/three.js `examples/jsm/shaders/VignetteShader.js` | three.js authors; Eskil Steenberg (formula) | MIT |
| rgbShift | mrdoob/three.js `examples/jsm/shaders/RGBShiftShader.js` | three.js authors; Tom Butterworth | MIT |
| horizontalBlur | mrdoob/three.js `examples/jsm/shaders/HorizontalBlurShader.js` | three.js authors | MIT |
| verticalBlur | mrdoob/three.js `examples/jsm/shaders/VerticalBlurShader.js` | three.js authors | MIT |
| crossWarp | gl-transitions/gl-transitions `transitions/CrossWarp.glsl` | Eke Peter | MIT |
| directionalWipe | gl-transitions/gl-transitions `transitions/DirectionalWipe.glsl` | gre | MIT |
| fade | gl-transitions/gl-transitions `transitions/Fade.glsl` | gre | MIT |
| filmBurn | gl-transitions/gl-transitions `transitions/FilmBurn.glsl` | Anastasia Dunbar | MIT |

Pinned sources and licence pages, checked before fetching shader source:
- webgl-noise: commit `22434e04d7753f7e949e8d724ab3da2864c17a0f`, https://github.com/stegu/webgl-noise/blob/22434e04d7753f7e949e8d724ab3da2864c17a0f/LICENSE ; local `LICENSE-noise.txt`. Each shader also declares MIT in its source header.
- three.js r180: commit `0af9729d0c143a86a1d725d6e2c3ad83301f3f34`, https://github.com/mrdoob/three.js/blob/0af9729d0c143a86a1d725d6e2c3ad83301f3f34/LICENSE ; local `LICENSE-three.txt`.
- gl-transitions: commit `bb4c58bfa842808cfb531a68af236f6481be66d1`, https://github.com/gl-transitions/gl-transitions/blob/bb4c58bfa842808cfb531a68af236f6481be66d1/LICENSE ; local `LICENSE-transitions.txt`. Each shader also declares MIT in its source header.

Adaptations: `tools/motion/vendor_shaders.py` extracts three.js fragments and replaces FilmShader's common include with local
rand/luminance functions. Noise sources gain palette/time uniforms and a main function; transitions gain canvas samplers and
a main function. `motion/runtime/shaders.js` supplies the WebGL-to-2D bridge and the plain 2D fallback. No upstream package,
new dependency, driver, browser or model is required or downloaded by this feature.
# Editorial sound effects

assets/sfx/editorial contains 15 BigSoundBank recordings by Joseph SARDIN (turned page by DavidGreck)
and two AI-generated public-library flash cues published by SFXMint. Each source page declares CC0 1.0
Universal: https://creativecommons.org/publicdomain/zero/1.0/. Processed copies are trimmed, faded,
mono and peak-normalised. Individual source URLs, authors and checked declarations are retained in
assets/licences/editorial-sfx-sources.json, with output measurements in assets/manifest/editorial-sfx.json.
No attribution is required; these credits preserve provenance. No account-only Studio assets are used.

# rea-video source taxonomy and analysis process

The shot-source vocabulary in `bridge/vendor/rea_video/sources.py` is adapted from
JuneYaooo/rea-video (`https://github.com/JuneYaooo/rea-video`), pinned at
`3522250b4d3e667610a175c0f188ac3d725b41cd`, under Apache-2.0. The file identifies
the modifications: taxonomy only, explicit unknowns, no forensic classifier or downloads.
Its film/generate/code planning split, separate base/overlay inventory and per-shot evidence
page also informed letitedit's reviewed-source workflow. Original `LICENSE` and `NOTICE`
are retained alongside the adaptation and included by the installer. No upstream model
weights, OCR, voice/stem model or reference analysis output is bundled with this adaptation.
