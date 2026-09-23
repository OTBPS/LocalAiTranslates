# Test fixtures sampled from real systems

Files here are recorded from a real machine rather than written by hand. A
hand-written fixture can only confirm what its author already believed; that is
exactly how `parse_peer_route` shipped with the `Relay` and `CurAddr` checks in
the wrong order while its test passed.

## Desensitisation rules

Field **names, types and shapes are never altered** — that is the whole value of
a sampled fixture. Only identifying *values* are replaced, with stable fakes:

| Kind | Replaced with |
|---|---|
| Node public keys | `nodekey:` + repeated digit |
| Host names | `workstation` / `laptop` / `tablet` / `desktop` |
| MagicDNS suffix | `tailnet-example.ts.net` |
| Tailnet addresses | `100.64.0.x` and `fd7a:115c:a1e0::100x` |
| LAN and public addresses | `192.168.1.50`, or removed |
| Derived address echoes (`AllowedIPs`, `PeerAPIURL`) | recomputed from the fake addresses |
| Login and display names | `user@example.com` / `Example User` |
| `CapMap`, `Capabilities` | emptied — they carry the tailnet display name and no parser reads them |

DERP region codes (`iad`, `sfo`, `ord`) are public Tailscale infrastructure
names and are kept as-is.

The generator asserts that none of the original values survive in the output.
Two real leaks were caught that way while writing this file: `AllowedIPs` /
`PeerAPIURL` echoing the real addresses, and an email address buried in
`Self.CapMap["tailnet-display-name"]`.

## `tailscale_status.json`

Recorded from `tailscale status --json` (Tailscale 1.80, Windows 11).

Four nodes, chosen to cover every branch of the route classifier:

| Node | `CurAddr` | `Relay` | `Online` | Expected route |
|---|---|---|---|---|
| `workstation` (Self) | empty | empty | true | — |
| `laptop` | `192.168.1.50:41641` | `iad` | true | **direct** |
| `tablet` | empty | `sfo` | true | relay |
| `desktop` | empty | `ord` | false | relay (offline) |

`laptop` is the important one. **A directly connected peer still reports a home
DERP region in `Relay`** — that field is where the node would relay *if it had
to*, not where traffic is going now. Only a non-empty `CurAddr` means direct.
Any classifier that checks `Relay` first gets this backwards.

## Regenerating

Requires a logged-in Tailscale with at least one peer. Re-record only when the
schema changes, and re-read the rules above before committing the result.
