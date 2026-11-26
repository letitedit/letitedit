# mlt-chain-normalizer-ref: a clip's normalizer links are freed with the clip

**Status: built, checked and deployable, not deployed.** It patches the engine's framework DLL (`app\libmlt-7.dll`).
`deploy.ps1`, `modules\VERIFIED.txt` and `check_engine.py` (check `chain_ref`) cover it like the modules, and
`release\source\mlt-patches\0004-mlt-chain-normalizer-ref.patch` carries it in the source bundle. The installer
build doesn't take it from `modules\` yet: it ships `app\libmlt-7.dll` as it is.

## The problem

Every clip Shotcut and letitedit open is an MLT *chain* (`<chain>` in a project, `Mlt::Chain` in the editor). When a
chain is made, `mlt_chain_attach_normalizers` gives it the links listed in `share\mlt\chain_normalizers.ini` (colour,
deinterlace, field order, crop, scale, resize, pixel format, audio format, resample, channels: 10 links here). Each link
it makes has one reference from `mlt_factory_link`; `mlt_chain_attach` adds the chain's own; the function never drops
the first. When the chain closes it drops only its own, so all 10 links stay alive for the rest of the process.

Every MLT property owns a Windows event, so each kept link shows as about 40 handles: **377 handles kept per clip**,
measured with `check_chain_ref.py`. A project of 46 clips keeps about 17,500 handles each time it is opened and closed
(a test window went from 25,000 Events empty to 135,000 after two open, edit and close cycles; `tests/t312/REPORT.md`),
and every edit or check that rebuilds the timeline from its XML keeps another set. The links' memory (scalers,
resamplers) is kept too.

Every other caller of `mlt_chain_attach` (the XML loader's `<link>`, `producer_melt`, `Mlt::Chain::attach`) drops its
own reference after attaching. Upstream MLT master (as fetched here, 18 Oct 2026, `f0cafd23`) has the same code.

## The fix

`mlt-chain-normalizer-ref.patch`: after attaching and moving each normalizer link, `mlt_link_close(link)` releases the
factory's reference. The chain then holds the only one and frees the link when it closes. Nothing else changes: no
picture or sound differs: three real projects exported by letitedit's own export with each engine came out
byte-identical (every frame and the sound), and `compare_frames.py` drew 24 of 24 frames identical.

## Files

- `mlt-chain-normalizer-ref.patch`: the change, against MLT `63218a28` (the app's 7.41.0).
- `build_libmlt.sh`: builds `libmlt-7.dll` alone from that commit plus the patch (`STOCK=1`: without it), MSYS2
  MINGW64, 4 threads, under the PC lock. `MLT_SRC` must be a checkout of your own (the script resets it). The result
  imports the same DLLs as the shipped one (KERNEL32, libdl, libiconv-2, libwinpthread-1, msvcrt) and exports the same
  1,174 functions.
- `check_chain_ref.py`: the check. Exit 1 on the shipped engine (377 handles kept per clip), 0 on the patched one
  (1, the same as a clip with no links). About 5 seconds, no renders.

## To deploy (not done: the orchestrator's call)

Windows locks `libmlt-7.dll` in every running letitedit window and export, so it can only be replaced with none
running, like the modules. `app\libmlt-7.dll` is shared by the editor and `melt.exe` (exports). Put the built file
(SHA-256 in `..\modules\SHA256SUMS.txt`) in `..\modules\`, then run `..\deploy.ps1` with no letitedit window or
export open: it swaps the file in, keeps a backup, runs `check_engine.py` under the PC lock and puts the backup back if
a check fails; `deploy.ps1 -Undo <backup folder>` puts the stock one back. Once the file is in `modules\`, every
editor build (`build.ps1`, `deploy.ps1 -IfFree`) also swaps it in when nothing has it loaded.
