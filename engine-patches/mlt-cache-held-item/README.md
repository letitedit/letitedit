# mlt-cache-held-item: a kept frame's decoder is freed after a cache eviction

**Where:** the MLT framework, `src/framework/mlt_cache.c` (`libmlt-7.dll`, in `app\`), MLT 7.41.0 at commit
`63218a28`. Upstream master has the same code.

## The problem

The avformat producer keeps each clip's decoder state (`producer_avformat`: codec contexts with their threads, a
hardware decoding device, packet queues, image and audio caches) in a global cache of a few entries
(`mlt_service_cache_*`, size `producer_avformat`; Shotcut sets it to its thread count plus two per track). Every frame
the clip makes holds a reference to that cache item (`avformat_cache` on the frame), so a frame keeps its decoder alive
until the frame is released.

When a clip's decoder is pushed out of the cache while a frame still holds it, and the clip then decodes again, the
clip gets a new decoder and `mlt_cache_put` stores it. In 7.41.0 it copied the held item to the garbage list and
updated the original item in place with the new decoder. But the frames hold the original item's address, so their
release later decremented the new decoder's count, and the copy in the garbage list (the old decoder) was never
released: one whole decoder kept for the rest of the process, every time.

In the editor this happens at every close after the bridge's snapshot (`letitedit_editor` with a picture): the
player keeps the frame it shows, the snapshot builds the project again from its XML (every clip it loads takes a
cache slot, so the timeline's decoders are pushed out), and closing seeks the player to 0, which decodes the shown
clips again. T312 measured it as +18 ffmpeg threads, +13 NVIDIA driver threads, ~2,700 handles and ~150 MB per round.
A timeline rebuild or anything else that opens many clips while a frame is shown does the same.

## The fix

`mlt_cache_put`: when the owner's item still has references, the item itself moves to the garbage list (by its data
address, as before) and the owner gets a new item. `cache_object_close`: a release carrying data that is no longer
the owner's current data releases its garbage item only, not the owner's new one. The frames' release then finds the
old decoder and frees it, and the new decoder's count is no longer decremented by someone else's frame.

## Proof

`check_cache_ref.py` (run by `check_engine.py` as `cache_ref`; `bridge/tests/core/test_engine_patches.py` runs it on
the installed app): five cycles of a kept frame outliving its decoder's eviction.

| engine | threads kept after 5 cycles | without the eviction |
|---|---|---|
| shipped `app\libmlt-7.dll` (stock 7.41.0) | 85 (FAIL) | 0 |
| T312/T314's engine (`mlt-chain-normalizer-ref` only) | 85 (FAIL) | 0 |
| both patches | 0 (PASS) | 0 |

A random stress run (`tests/t315/cache_stress.py`: 300 steps of opening, drawing, keeping, releasing and closing
clips with a 4-entry cache, three seeds) drew every frame on both engines; the stock engine kept 17-102 threads, the
patched one none. The window measurements are in `tests/t315/REPORT.md`.

## Building it

`build_libmlt.sh` builds `libmlt-7.dll` alone from `63218a28` with both framework patches in order
(`../mlt-chain-normalizer-ref/mlt-chain-normalizer-ref.patch`, then this one); `VARIANT=chain-ref` or `stock` for
comparisons. It is `release/source/mlt-patches/0005-mlt-cache-held-item.patch` in the source bundle.
