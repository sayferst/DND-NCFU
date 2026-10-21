# Tunnel DNS bypass, 2026-10-21

Owner could not resolve Cloudflare SRV through system DNS or direct public DNS.
The diagnostic script did NOT change Windows DNS. Exact network policy unknown.

New owner bootstrap:
- Fixed HTTPS DNS A lookups for region1.v2.argotunnel.com / region2.v2.argotunnel.com.
- Bounded HTTPS responses, no redirects/auth, global IPv4 only, fixed port7844.
- Fallback IPs from Cloudflare published firewall/dig examples if DoH fails.
- Bounded numeric TCP probes; fail separately if edge TCP7844 is unreachable.
- Pass numeric --edge flags; Cloudflare TLS server-name checking remains enabled.

Sources inspected (read-only public upstream code/documentation):
https://raw.githubusercontent.com/cloudflare/cloudflare-docs/production/src/content/docs/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/tunnel-with-firewall.mdx
https://raw.githubusercontent.com/cloudflare/cloudflared/master/supervisor/supervisor.go
https://raw.githubusercontent.com/cloudflare/cloudflared/master/edgediscovery/allregions/regions.go
https://raw.githubusercontent.com/cloudflare/cloudflared/master/cmd/cloudflared/tunnel/configuration.go
https://raw.githubusercontent.com/cloudflare/cloudflared/master/cmd/cloudflared/tunnel/cmd.go

The hidden --edge option is implemented by the supervisor static-edge path. We do
not disable TLS verification or alter system DNS/firewall. These source snapshots
support implementation, not a claim of Windows binary/live tunnel acceptance.

Actual DoH probes from agent environment returned HTTP403; no success claimed.
Tests use fake DoH/TCP/cloudflared logs. target-final.txt:105passed in3.98s,
19new scenarios, Ruffcheck/format217files. Previous full suite1388passed at8913908.
No paid generation, actual tunnel startup or Windows system configuration changes.
Owner must verify start in their network. Bootstrap IPs may need updating if
Cloudflare changes its published destinations. A TCP7844 block requires network
access or a different transport/provider; a DNS change cannot remove that block.
