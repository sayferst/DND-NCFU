# Public readiness, 2026-10-21

Owner start published the signed manifest but timed out with a generic document
message. A public GET from this environment returned HTTP200 (no endpoint printed).
The old catch covered both discovery verification and tunnel health; the actual
Windows failure phase is unknown. It is not evidence of a bad API key.

Host now waits up to300s with bounded progress and separate safe phase/errors.
No provider calls or manifest/health validation are bypassed. No actual tunnel
was started or Windows acceptance claimed here. Five fake-clock scenarios cover
GitHub propagation, tunnel delay, exact endpoint rejection, signature rejection
and phase-specific sanitized final errors. See target-final.txt.

Game runtime and Setup unchanged. Previous full suite1388passed at8913908.
