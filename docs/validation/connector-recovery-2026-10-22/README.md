# Connector recovery, 2026-10-22

Owner diagnosis: signed discovery OK, owner PID alive, system HTTP proxy not
configured;3system and3direct health requests all return530/Cloudflare1033 with
cf-ray present. This establishes Cloudflare cannot find a healthy connector for
the URL. The reason its connection was lost remains unknown. No Windows remote
tool exists in this chat despite the owner's authorization to use their PC.

Confirmed lifecycle defect: after a single successful health, the owner script
watched only child process survival. New code requires3consecutive initial HTTPS
checks, probes every15s, removes readiness on the first error, restores after3good
checks, and recreates the connector after3bad checks or child exit. Gateway,
Store, async jobs, grants and accounting survive connector replacement. A new
sequence/signed endpoint is published. HTTP2/QUIC alternate;3restarts/hour max,
with5/15/30second backoff. Ctrl+C cancels and cleans up instead of restarting.

Targeted:73passed in3.45s before3additional fixed log messages. Seven new fake
clock/process scenarios cover readiness withdrawal, recovery, backoff, child
exit, actual session cleanup, Gateway/Store identity, and Ctrl+C. No live tunnel,
paid provider call, grant activation or Windows system change occurs in tests.
Full check is recorded separately in full-01.txt. This is not evidence that
Cloudflare or the owner's underlying network has been repaired.

Final full `scripts/check.py` exit0: **1459 passed in216.02s**, no failures/skips.
Ruff check/format passed (222files).75protected hashes and original AGENTS prefix
unchanged. Native Windows and real Cloudflare stability still require owner testing.
