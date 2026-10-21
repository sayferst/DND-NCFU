# Tester build handoff, 2026-10-22

Latest owner steering: tunnel is solved; complete the remaining Setup work.
The attached diagnostic report is contextual evidence, not authorization to change
all networking described in it. No tunnel/DNS changes are included in this stage.
The Codex/ChatGPT usage limit is separate from RouterAI, as clarified by the owner.

Confirmed defect: both builders missed per-user Inno Setup installed under
LOCALAPPDATA/Programs/Inno Setup 6. Both now find it, and owner CLI passes the
absolute compiler path. The PowerShell builder checks Inno before expensive work.

Build preflight distinguishes missing/dead host, discovery signature/network and
HTTP530 before issuing a grant. Temporary stage JSON supplies only a fixed failure
category; bootstrap remains separate and is removed on failure/success. Handoff
uses only the newly written exact DND-NCFU-Setup.exe, not arbitrary glob results.

Targeted: 81 passed in 6.45s (tester build/delivery/release profiles/desktop release).
16 new cases use fake PowerShell, compiler and DPAPI. Loopback/fake providers only,
no real activation, paid generation, tunnel publication or system changes.
The complete Linux check is recorded in full-01.txt. Native Windows PowerShell,
Inno compilation and delivery to a tester must still be confirmed on Windows.

Final `scripts/check.py` exit0: **1437 passed in213.15s**, no skips/failures;
Ruff check and format passed (218 Python files). All75 protected hashes and the
original AGENTS prefix preserved. Native Windows/Inno compilation not run here.
