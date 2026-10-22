# Health530 after start success, 2026-10-22

Owner reports successful start health followed by HTTP530 during build.
This does not identify connector loss versus route/proxy behavior. External curl
from agent environment received exit56/HTTP000; no Cloudflare body obtained.
No claim of actual live cause or network repair is supported by that attempt.

New diagnose-tunnel reads only the existing public readiness document, verifies
signed discovery and compares3samples each with system HTTP proxy and explicit
no-HTTP-proxy routing. TUN VPN remains in effect. It never reads DPAPI/API key,
opens grant Store, activates a tester or starts/publishes a new tunnel.
Health errors retain only allowlisted CF codes1033/1016/1000 and a boolean cf-ray
presence; response body, URL, ray value and proxy credentials are never printed.

Target-final:108passed in3.50s;15new fake-network cases. Ruffcheck/format220files.
Previous full1437passed at5ce14ff, not repeated for this owner-only diagnostic.
Real Windows output and successful Setup compilation remain unverified here.
