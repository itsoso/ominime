# Source-owned investigation fixtures

This directory is reserved for invented, local-only protocol fixtures used by
the source-owned interface feasibility tests. Fixtures must never contain live
application data, account values, message text, paths, URLs, ports, process
identifiers, credentials, tokens, cookies, hashes, or copied diagnostic output.

The evidence contract tests construct synthetic objects in memory. Candidate
discovery is not proof of chat-history access, so block reports keep all seven
required capabilities false and expose an empty field-mappings object.
