# Engine fixes ready to offer to MLT upstream

The owner's OK (21 Nov 2026): T312's chain-normalizer fix may be offered to the MLT project, with no private paths or
details. These files hold only the change and a neutral description; the orchestrator sends them (as a pull request
to https://github.com/mltframework/mlt or a mailing-list patch), with an author identity chosen then.

| File | What | Applies on |
|---|---|---|
| `0001-chain-normalizer-links-release-factory-ref.patch` | `mlt_chain_attach_normalizers` releases the factory's reference to each link (T312) | MLT master `f0cafd23` (the last local fetch) and `63218a28` |

Two more fixes could follow the same way if he wants (not prepared, not approved for upstream yet):
`mlt-cache-held-item` (a frame's decoder freed after a cache eviction) and `mlt-resample-close` (the resample
filter's close frees its properties).
