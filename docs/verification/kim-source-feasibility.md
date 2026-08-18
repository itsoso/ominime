# Kim Source Feasibility

- Gate result: `BLOCK` for the production connector
- On-demand Skill gate: `PASS`
- Adapter version class: `chatkimv2-mcp-v1`
- Durable incremental synchronization: `NOT PROVEN / BLOCK`
- Legacy structured-snapshot adapter: `BLOCK` with `KIM_ATOMIC_OPEN_UNAVAILABLE`

The user-authorized local reader was built from the reviewed fixed source
revision in a clean temporary checkout. OmniMe verified the executable by exact
SHA-256 at runtime and accessed it only through the bounded MCP client. The live
proof emitted no account value, conversation value, message value, path, key,
binary hash, or source location.

| Required capability | Available | Field mapping names |
|---|---:|---|
| Source account identity | `true` | `current_user.user_id` |
| Conversation and participant identity | `true` | `conversation_id`, `conversation_type` |
| Stable message identity | `true` | `id`, `msg_id` |
| Final message text | `true` | `content` |
| Authoritative direction or sender | `true` | `sender_id`, `current_user.user_id`, `content_type` |
| Timestamp or ordering key | `true` | `timestamp_ms`, ascending query order |
| Incremental change detection | `false` | `null` |

The first six capabilities are sufficient for explicit, bounded, on-demand
Skill queries. They do not prove that cursors survive process restarts, late
arrivals, edits, retractions, or source mutations. Therefore the production
connector, scheduler, persistence, and automatic knowledge ingestion remain
disabled.

The earlier `kim-macos-structured-v1` snapshot probe remains a valid negative
result for that implementation: it cannot safely open the live source
atomically and continues to fail closed with
`KIM_ATOMIC_OPEN_UNAVAILABLE`. The on-demand reader is a separately approved
evidence path; it does not silently convert the legacy probe into a PASS.
