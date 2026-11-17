# Library releases

quicquic-go releases module `github.com/GridCastIO/quicquic-go` as an annotated Git tag plus a GitHub Release. Versions follow the [version-aware compatibility promise](../adr/0016-version-aware-compatibility.md). Releases follow [independent maintenance](../adr/0015-independent-maintenance.md) and the [independent module identity](../adr/0014-independent-module-identity.md).

There is no publishing workflow. An audit for the identity transition found no prerelease or publication automation. The only prerelease assumptions were the earlier versions of this runbook and the README, which described the fork's draft GitHub prereleases. Push and tag workflows validate tags, and the interop workflow builds an image without publishing it.

## Version selection

Choose the version deliberately and record it in [CHANGELOG.md](../../CHANGELOG.md) or a release issue before tagging:

- **First independent version.** Independent versions start at `v0.63.0`.
- **Patch, minor and v1.** A patch release preserves the public contract within its minor series. A minor release may change it, with migration instructions, and raising the consumer's minimum Go version needs a minor release. `v1.0.0` is reserved for a deliberate long-term stability commitment.
- **Release type.** Publish `v0.63.0` as a stable GitHub Release, not a prerelease. Choose the type of each later release deliberately.
- **Release candidates.** Optional `-rc.N` candidates need an explicit decision. Consumers must select them explicitly, and they never stand in for `@latest`.
- **Module path.** The canonical path is exactly `github.com/GridCastIO/quicquic-go`. Path case is significant: `github.com/gridcastio/quicquic-go` is a different module path and fails with a path mismatch.

Never move or reuse an existing tag, or replace an existing published release in place. A correction gets a new version.

The `v0.62.1-fast.N` series ended at fast.10. Inherited tags, including upstream quic-go releases and the fast-series prereleases, are history, not releases of the new module. Tags with a `go.mod` file declare `github.com/quic-go/quic-go` or `github.com/lucas-clemente/quic-go`, so Go rejects them for the new path when it loads the requirement. The few pre-module tags without one, such as `v0.10.1`, resolve under any requested path because Go synthesizes their declaration; they rank below every independent release and are not supported versions.

## Prepare and validate

1. Prepare the changelog, release record and any adoption changes in a dedicated feature worktree. Merge their PR through the repository's existing checks. Keep archived evidence unchanged.
2. Select a full commit SHA on `main`. Verify it is an ancestor of the current remote default branch and that the worktree used for tagging is clean.
3. Require successful unit, integration, lint, cross-compilation and interop-image workflows at that exact commit. Inspect individual jobs and relevant steps. Document existing limitations; do not count an unexplained failed check as green or rerun it until it passes.
4. Run a fresh `govulncheck ./...` and record the scanner and Go versions. Inspect reachable findings before release, and record the target platform and any uncalled module advisories. To scan for another `GOOS`/`GOARCH`, build the scanner for the host first, then set the target environment when invoking that executable. A clean scan of this module path does not cover inherited upstream code. Refresh the upstream-advisory applicability record at the candidate commit under the [advisory runbook](upstream-advisories.md), with Josh's disposition, and include only what he classifies as disclosable.
5. Verify that a separate consumer builds QUIC and HTTP/3 from a fresh environment without replacements:
   - Use a new module and an empty module cache.
   - Before tagging, require the candidate commit with `go get github.com/GridCastIO/quicquic-go@<full-sha>`, which Go resolves as a pseudo-version.
   - After tagging, repeat with the real tag before publishing the GitHub Release, and verify the downloaded module version, commit and archive boundary.
   - Record the resolved version, `go.sum` lines and a versioned `govulncheck` of the consumer.
6. Write release notes covering:
   - the v0.62.0 ancestry and the provenance of adopted upstream changes;
   - the changes and the Go minimum;
   - migration instructions for any incompatible change;
   - the advisory applicability record and the scanner coverage limit;
   - known limitations, and tested versus build-only platforms.

   Link the exact commit's workflow results. This library release has no binary assets; adding binary distribution is a separate scope decision.

## Publish and verify

Check that both the proposed remote tag and the GitHub Release are absent. Create an annotated tag at the selected SHA and push only that tag. Never force-push tags. The existing push workflows also validate tag pushes; no additional release workflow is required.

Create a draft GitHub Release from the verified tag and the prepared notes, marked as a prerelease only for an explicitly selected `-rc.N` candidate. Inspect the draft, verify the public Go module download and the consumer build from step 5 against the tag, and wait for the tag-triggered workflows to succeed before publishing it. If a published tag's validation fails, keep the failure on record and stop publication. Repair through a new commit and a new version rather than moving the tag.

After publication, verify the following:

- `GOPROXY=https://proxy.golang.org GOFLAGS=-mod=mod go list -m -json github.com/GridCastIO/quicquic-go@<version>` returns the expected version, commit and origin. Downloading the module verifies it against the checksum database.
- `go list -m -versions github.com/GridCastIO/quicquic-go` lists the release.
- For a stable release, `go list -m github.com/GridCastIO/quicquic-go@latest` resolves to it, unless a later stable release exists. A `-rc.N` candidate resolves only when requested explicitly, and `@latest` continues to select the latest stable release.
- In a disposable module with an empty module cache and no replacements, `go get github.com/GridCastIO/quicquic-go@v0.62.0` and `go get github.com/GridCastIO/quicquic-go@v0.62.1-fast.10` fail with the specific error that the module declares its path as `github.com/quic-go/quic-go`. A metadata lookup such as `go list -m` can succeed for these tags and is not evidence of rejection.
- The release URL, tag object and peeled commit, the prerelease flag matches the selected release type, the notes are as prepared, and the release has no unexpected assets.

Record the tag-run URLs and the verification results in the release notes or the release issue.

For later releases, use the same flow: changelog PR, validated default-branch commit, fresh vulnerability scan and advisory refresh, immutable annotated tag, consumer verification and GitHub Release. Update the README's installation example only to a real released tag or a Go-generated pseudo-version. Never present a planned tag as an already available dependency.

## Recorded maintenance exception

[Fast.9](https://github.com/the-sarge/quic-go-fast/releases/tag/v0.62.1-fast.9), published October 25, 2026, used the owner's one-time source-selection exception in [#1049](https://github.com/the-sarge/quic-go-fast/issues/1049): fast.8 plus the idle path-MTU timer fix from PR #1047, at `0f717339f767df5d2e4091b2515266d61f66e2ac`. Its version and release record were kept in the issue so a changelog-only commit did not alter the approved source. Validation, immutable-tag and publication gates remained in force. This exception does not authorize future maintenance-branch releases or replace the default-branch flow above.

When reconciling maintained documentation after this exception, distinguish the published maintenance source from `main`, retain the historical fast.8 preparation and measurement records, and point installation examples to the latest real fork release. Adaptive application-loss thresholds (#971) were absent from fast.9 despite landing on `main` before its publication; they first shipped in [fast.10](https://github.com/the-sarge/quic-go-fast/releases/tag/v0.62.1-fast.10). Consumer certification and BBR qualification remain separate from release publication.
