# Synthetic WeChat fixture

This directory contains invented schema metadata only. Tests create disposable
SQLite files with invented identifiers and message text at runtime. No file in
this directory comes from WeChat or a user account.

The non-atomic snapshot provider is test-only and assumes a trusted synthetic
fixture. It does not prove production safety against hostile same-UID path
replacement. Production WeChat source access remains disabled until an atomic
path-walk and open capability is available.
