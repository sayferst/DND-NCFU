# RouterAI catalog alias, 2026-10-21

Owner's public catalog lists `~deepseek/deepseek-v4-flash-latest`,
`recraft/recraft-v4.1-flash`, and `black-forest-labs/flux-3-image-klein`.
The prior default omitted `~`, so gateway preflight rejected model availability.
No credential or authenticated provider response is included here.

Defaults now agree across server, client and Windows builder. Cloud model parsing,
persistence and narration records accept a single leading `~`; local Ollama model
filtering remains unchanged. Missing models are listed explicitly by preflight.
The existing preflight test was corrected to actually reach catalog validation:
its former empty fake key response failed at allowance validation first.

Targeted final run: `target-final.txt` (62 passed), and broader runtime/source smoke
run: `target-02.txt` (109 passed). These overlap; do not sum their counts.
`full-01.txt` was started before the complete alias support edits, so its results
are intermediate. `full-final-02.txt` is the final full suite.

Tests use local fake providers/loopback. No paid calls, real RouterAI success,
native Windows setup, DPAPI or Inno execution are claimed.
All 75 protected hashes and the original AGENTS prefix are preserved.

Owner verification: update source and run `scripts\tester_host.cmd start`.
A newly built personal Setup includes the corrected text model identifier.

Final full suite: **1388 passed in 212.46s**, exit 0. Ruff check and format
passed (213 files); pip check passed. No failures or skips in the final run.
