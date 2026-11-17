---
status: accepted
---

# Promise compatibility by version, starting at v0.63.0

quicquic-go numbers its own releases, starting at `v0.63.0` under `github.com/GridCastIO/quicquic-go`; the `-fast.N` series ends. Versions advance with this project's changes, independently of upstream. The first independent release sets the project's own compatibility baseline. It is not a retroactive promise of exact compatibility with upstream or the fast series, nor of permanent interchangeability with future upstream releases. This supersedes [ADR 0001](0001-upstream-compatibility.md) under the versioning decision in [#653](https://github.com/the-sarge/quic-go-fast/issues/653#issuecomment-6564715434).

A restart at `v0.1.0` was rejected: Go selects by version order, and higher inherited tags that declare the old module path could win selection.

## Meaning of version changes

- **Patch updates** (`v0.63.0` → `v0.63.1`) contain compatible fixes or optimizations and preserve the public contract throughout the minor series. This is stronger than Go's default v0 guarantee.
- **Minor updates** (`v0.63.x` → `v0.64.0`) introduce features and may deliberately change the public contract. Every incompatible change needs clear migration instructions. Prefer compatible evolution where practical: permission to break is not a reason to break. An optional feature, multipath included, need not break existing callers, but it arrives in a minor release, and so does any incompatible revision of its API.
- **`v1.0.0`** is reserved for a deliberate future commitment to long-term API stability. After it, standard semantic versioning applies.

## Public contract

The contract covers the supported application-facing libraries: the root `quic` package, `http3`, and the public utility and tracing libraries. It includes callable APIs, supported error contracts, documented behavior, resource ownership and lifetime obligations. Compiling is not enough. A new requirement to retain a buffer, or a changed documented error, can be a breaking change.

This carries forward ADR 0001's protection: a change must not silently impose new buffer-lifetime or ownership obligations on existing callers. Optional APIs with different ownership contracts remain welcome. The exception that [ADR 0009](0009-opt-in-bbrv3.md) recorded for `Config` carries forward, generalized to every exported struct from this module: the patch-compatibility promise does not cover positional (unkeyed) composite literals, and keyed literals are the supported source form. This matches Go's own compatibility convention and the `go vet` composites check.

Experimental exported APIs follow the same patch rule. Experimental status describes maturity, performance or suitability, not permission for surprise patch-level breaks. Algorithm internals and performance results are not frozen merely because an API is compatible.

Outside the contract:

- internal packages;
- repository test helpers, including the explicitly unstable `testutils`;
- examples, interop programs and integration fixtures;
- experimental diagnostic schemas, a narrow exclusion that does not cover the public qlog Go APIs.

## Corrections, security and Go requirements

A patch may fix behavior that violates the documented contract; compatibility does not preserve every observable bug. A deliberate change to the documented API, error, ownership or supported wire contract needs a minor release, including when security motivates it. A necessary breaking security fix ships as a minor version with migration guidance. Raising the consumer's minimum Go version needs a minor release and migration notes, and dependency updates respect the minimum within a minor series. Maintainer tooling and CI updates that do not raise that minimum need no minor release.

## Wire interoperability

The project keeps standard QUIC and HTTP/3 interoperability with upstream quic-go and other conforming implementations of the supported standards. Optional wire extensions negotiate support. Ordinary operation remains available with a peer that lacks one, unless the application explicitly requires it; then the lack of support is surfaced rather than silently dropping the requirement. Local choices such as batching or congestion-control selection need no negotiation. The local ACK-threshold control is not the unimplemented negotiated ACK Frequency extension. This commitment is separate from Go API compatibility, performance claims and evidence that particular implementation combinations were tested.

A version without a prerelease suffix is not a blanket certification of experimental features or of any consumer workload.
