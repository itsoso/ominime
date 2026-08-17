# Synthetic Kim fixture

This directory documents an invented structured-store header used only by
tests. The header contains a magic value, a format version, a bounded metadata
length, an invented app version, and field names. Metadata is accepted only
when its bytes exactly equal the documented canonical JSON encoding; alternate
whitespace, key order, duplicate keys, and invalid UTF-8 fail closed. Tests
append invented private values after the header to prove that the reader does
not inspect message data.

No file in this directory comes from Kim or a user account. The non-atomic
snapshot provider and synthetic adapter are test-only. Production Kim access
remains disabled until Node can perform an atomic, no-symlink path walk and
open on macOS.
