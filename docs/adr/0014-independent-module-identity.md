---
status: accepted
---

# Adopt quicquic-go through its own module path

This project is quicquic-go, hosted at `GridCastIO/quicquic-go` and declaring module `github.com/GridCastIO/quicquic-go`. The root package keeps the name `quic`, so callers keep identifiers such as `quic.Config` after changing their imports. Applications and libraries depend on it directly through that path. No `replace` directive is needed, and none can make the old path select this project. This supersedes [ADR 0002](0002-adopt-through-module-replacement.md) under the identity decision in [#650](https://github.com/the-sarge/quic-go-fast/issues/650#issuecomment-6564455591) and the sequence decision in [#655](https://github.com/the-sarge/quic-go-fast/issues/655#issuecomment-6584616162).

Keeping `github.com/quic-go/quic-go` made adoption a per-application maintenance obligation that did not propagate through dependencies. It also let inherited upstream tags win `@latest`. Both costs were accepted while the fork's value was being established, and that is now settled. The new path removes both costs and needs one coordinated import migration. Choosing the lasting organization and name before that migration avoids a second consumer cutover. A later change of module path would repeat the whole migration. A `/v2` suffix is not implied: v0 and v1 versions of this path need none.

No type aliases, shim module or compatibility package is published at the old path. Keeping the package name preserves source-level qualifiers, not type identity: defined types from the old and new paths are distinct ([Go type identity](https://go.dev/ref/spec#Type_identity)). A dependency that exposes QUIC types in its API therefore moves to the new path before or together with its consumers.

ADR 0002's wiremux socket-integration section required wiremux to stay buildable with upstream quic-go and to keep fork-only capabilities optional. That requirement is superseded too. wiremux's maintained QUIC transport moves to this module in [GridSwarm/wiremux#2175](https://github.com/GridSwarm/wiremux/issues/2175), and no dual backend is kept solely to retain the old identity. GridCast and tapmux then follow the published wiremux version. The structural registration and ownership design of [ADR 0006](0006-explicit-external-packet-io.md) is unchanged.

Inherited tags, including upstream quic-go releases and the `v0.62.1-fast.N` prereleases, remain immutable history. They declare the old module path and are not releases of this module. Rollback to an old source or dependency state uses those ordinary references; it does not restore the fork relationship. The [migration guide](../usage.md#migrate-to-quicquic-go) owns consumer steps. Protocol, crypto-domain and diagnostic strings, environment variables and build tags that contain `quic-go` are behavior, not module identity, and are unchanged by this decision.
