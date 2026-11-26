# Local Review speech models (T210 notes 6 and 7)

The English short-note model is a CTranslate2 conversion of OpenAI Whisper tiny.en.
No recorded audio is uploaded. Model files alone are downloaded under the existing first-use policy.
Revision and MIT licence checked against the upstream model API on 13 November 2026.
Hashes below were calculated from the downloaded pinned revision on this PC.
Silero VAD v6 ships inside the already-required faster-whisper package (MIT); no separate VAD download.

| Repo | Licence |
|---|---|
| Systran/faster-whisper-tiny.en | MIT |

### Systran/faster-whisper-tiny.en (revision 0d3d19a32d3338f10357c0889762bd8d64bbdeba)

| File | Bytes | SHA-256 (local) |
|---|---|---|
| config.json | 2317 | 14b1b421a90349bc551b881461426b561a874049cb9e4c4864f2ca384f6a7cc5 |
| model.bin | 75537502 | 1a5afae06a4db91c975c9a9d78be5cc110ee4ea022ad57d55492e4550e936b2a |
| tokenizer.json | 2128466 | 929c5252409436dce1b38a75d1abbcb5e132d170d8e324e4e04ed915fa2d22df |
| vocabulary.txt | 422309 | ff77588746d3a2595d32ab5b69ffd7b95ce2441ac57533cb66fc3eb575a115cf |

Sources: https://huggingface.co/Systran/faster-whisper-tiny.en ; https://github.com/openai/whisper/blob/main/LICENSE ; https://github.com/snakers4/silero-vad
