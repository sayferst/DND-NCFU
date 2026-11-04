# QLoRA data readiness, 04.11.2026

The two reports cover complete corpora, not samples:1100 baseline rows and1196
HP-augmented rows. The baseline rows are shared, so this is1196 unique rows.
Both independently match AutoTokenizer input IDs, target IDs and loss masks.
No weights, CUDA, paid services or training were used. Human row review remains0.
The HP extension has no real external holdout; full native FIREBALL is not admitted
as Russian narrator SFT. See ../../intelligent_gm/QLORA_DATA_READY.md.

targeted-02.txt is the actual138-test run after fixing the old incomplete-report
fixture and enabling local loopback sockets. Full game tests were not repeated.
The logs' PyTorch-not-found message is expected in the tokenizer-only environment.
