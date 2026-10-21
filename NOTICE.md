# Attribution

New integration code, inbox UI, business-account guards, event delivery, draft
storage and tests were developed with OpenAI Codex. This is a community project,
not an official Kakao or OpenAI product.

## kakaocli (MIT)

- Source: https://github.com/silver-flight-group/kakaocli
- Reference commit: `8b6ffcfdaebc592a735dc1a8bd5e50037e626406`
- Copyright (c) 2026 Silver Flight Group, LLC
- Retained license: `LICENSE.kakaocli`
- The key-derivation and database-schema approach was ported into
  `src/kakao_db.py`; the account verification and read-only wrapper are local
  adaptations. `scripts/recover_uid.c` follows the upstream DeviceInfo method.

## kmsg (MIT), modified source included

- Source: https://github.com/channprj/kmsg
- Reference commit: `54cbff790b409214735ef365a621d791034fe500`
- Copyright (c) 2026 Park Hee Chan
- Retained licenses: `LICENSE.kmsg` and `vendor/kmsg/LICENSE`
- Modified build inputs are included in `vendor/kmsg` without its Git history,
  assets, caches or binaries. The fork pins the work app, separates account
  caches, checks exact window/input state, and limits the sending path.
- Swift Argument Parser is resolved from its upstream package; its own license
  applies. It is not vendored here.

## External infrastructure

Dots, MCP Events and Secure MCP Tunnel are existing OpenAI capabilities; this
repository implements an adapter for them. The official `tunnel-client` binary
and `terminal-notifier` are not redistributed. They retain their own licenses.
`integrations/dots/tunnel-release.json` records the official tunnel client asset
used during the prototype; use the official release channel for installation.
