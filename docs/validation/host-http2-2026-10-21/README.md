# Cloudflare HTTP530, 2026-10-21

Owner output confirms signed discovery passed but tunnel health returned530
for300seconds. QUIC/UDP blockage is a hypothesis, not an observed root cause.
Host now explicitly uses HTTP/2 overTCP7844 and waits for registration before
publishing. Raw cloudflared logs remain private; only fixed error categories print.

9new synthetic scenarios; targeted86passed/3.40s. No live cloudflared/Windows
acceptance, paid calls or system firewall changes. Game/Setup runtime unchanged.
Previous full suite1388passed at8913908; not repeated for standalone host change.
