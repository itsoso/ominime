# Source-owned investigation fixtures

This directory is reserved for invented, local-only protocol fixtures used by
the source-owned interface feasibility tests. Fixtures must never contain live
application data, account values, message text, paths, URLs, ports, process
identifiers, credentials, tokens, cookies, hashes, or copied diagnostic output.

The evidence contract tests construct synthetic objects in memory. Candidate
discovery is not proof of chat-history access, so block reports keep all seven
required capabilities false and expose an empty field-mappings object.

The WeChat listener-inventory tests also construct invented `pgrep`, `ps`,
`codesign`, and `lsof` machine output in memory and inject a fake command
runner. They must never execute those tools, read a live process, or persist a
discovered process identifier, executable path, signature diagnostic, address,
or port. Synthetic loopback endpoints exist only to test strict parsing and are
not feasibility evidence.

The passive inventory's claim is deliberately narrow: before and after listener
enumeration it checks the exact current UID, a stable `ps` process-start value,
the canonical executable path inside `WeChat.app`, and the expected signature
of that on-disk bundle. This does not prove the cryptographic identity of the
already loaded process image. Proving that stronger claim would require a
separately approved native interface and is outside this source-owned probe.

An `lsof` exit status of 1 means “no listeners” only when both captured output
channels are exactly empty. The tests preserve that exit status only inside the
injected runner result and still perform all post-enumeration identity checks;
no status, diagnostics, path, process identity, address, or port is evidence.
