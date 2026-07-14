# Reference

Tested BOMs and **measured** data. Not datasheet claims — things we have actually run.

- [`drives-tested.md`](drives-tested.md) — verified CiA 402 servo drives
- [`measurements/`](measurements/) — frame modal tests, DC sync jitter, achieved accuracy

Two BOM tiers, because the manifest doesn't care ([ADR-0009](../docs/decisions/0009-spec-the-profile-not-the-part.md)):

- **Commercial** — buy the Beckhoff/Leadshine. It works. ~$400/module for I/O.
- **Frugal** — open LAN9252 board, ~$40 in parts. For the maker who wants a cheap cell.

Same manifest, same generated code, same behavior. **That optionality is what the abstraction
was for.**
