# quicquic-go Identity Transition Preparation Plan

**Date:** 2026-11-17
**Status:** Revised after the [delegated `revise` decision](https://github.com/the-sarge/quic-go-fast/issues/1109#issuecomment-6940490276) on revision `fb14a6d7`; awaiting delegated approval of this revision. No product code is written before that approval.
**Issue:** [Prepare the quicquic-go module, documentation and release transition (#1109)](https://github.com/the-sarge/quic-go-fast/issues/1109), part of [Execute quicquic-go independence and consumer cutovers (#1108)](https://github.com/the-sarge/quic-go-fast/issues/1108)
**Decision sources:** [Sequence detach, transfer, rename and consumer cutover (#655)](https://github.com/the-sarge/quic-go-fast/issues/655#issuecomment-6584616162); approved policies [#650](https://github.com/the-sarge/quic-go-fast/issues/650#issuecomment-6564455591), [#651](https://github.com/the-sarge/quic-go-fast/issues/651#issuecomment-6563772122), [#653](https://github.com/the-sarge/quic-go-fast/issues/653#issuecomment-6564715434), [#654](https://github.com/the-sarge/quic-go-fast/issues/654#issuecomment-6564813895) and [#1067](https://github.com/the-sarge/quic-go-fast/issues/1067#issuecomment-6564931617)
**Downstream:** [Human move (#1110)](https://github.com/the-sarge/quic-go-fast/issues/1110), then [Merge the identity transition and publish quicquic-go v0.63.0 at its final home (#1111)](https://github.com/the-sarge/quic-go-fast/issues/1111)
**Base:** `f05a8a4a1e6c766936d154759171e7a98955fdb6` (`origin/main`, after the fast.10 publication record)
**Normative scope:** Current outcome, boundaries, invariants, acceptance evidence, blockers and stop conditions. Review chronology and receipts belong in the PRs and linked comments, not here.

## Goal

Prepare two reviewed, locally certified, **unmerged** draft PRs that move this library to module `github.com/GridCastIO/quicquic-go` (root `package quic`) and adapt its public declaration, documentation, ADRs, release runbook and security instructions to independent maintenance. Hand #1111 exact commit identities, validation receipts, destination-dependent revalidation commands and a consumer migration packet.

## Completion boundary

#1109 ends at a handoff, not a merge. It replaces `planit` workflow steps 4–7 (mark ready, merge, journal, deferred-finding filing and OmniFocus closure) as follows:

- Both PRs stay draft. Run the code-review preparation pass, the bounded RAS loop and local exact-head certification, push, and observe the hosted checks that run on drafts (unit, integration, lint, cross-compilation and interop image build) on the exact pushed heads. Then stop.
- Do not mark either PR ready, merge, journal, or file deferred findings. #1111 owns refresh, ready, the required multipath peer job, merge, journal, deferred-finding revalidation against the merged head and closure. Deferred findings are listed in the handoff packet with the head they were observed on.
- PR bodies say `Part of #1109`. No closing keyword names #1109, #1110 or #1111.
- The coordinator owns the #1108 tracker comment and the OmniFocus mirror. This worker writes neither.

## Current shape (verified at the base)

- **Module identity.** Root `go.mod` declares `github.com/quic-go/quic-go`. 725 maintained `.go` files outside `docs/` and root `testdata/` contain 2,136 lines naming that path: imports, `go:generate` mockgen directives and their 23 generated outputs, `-self_package` arguments, goroutine stack-frame strings in `sys_conn_closure_test.go`, `ringbuffer` panic messages, and the `qlogwriter` build-info match. 15 lines are upstream issue, PR or wiki URLs and must stay upstream.
- **Runtime identity dependency.** [`qlogwriter/trace.go`](../../qlogwriter/trace.go) matches `debug.ReadBuildInfo` dependencies against the literal module path to fill qlog `code_version`; its comment and [`interop/Dockerfile`](../../interop/Dockerfile) set `-X github.com/quic-go/quic-go/qlogwriter.quicGoVersion`. A stale `-X` path is silently ignored by the linker. [`qlogwriter/version_test.go`](../../qlogwriter/version_test.go) builds real consumers through a fake module proxy keyed by unescaped module paths.
- **Nested modules.** `integrationtests/fips` (module `…/integrationtests/fips`, replace `../../`), `integrationtests/gomodvendor` (module `test`, replace `../../`), the inert packaging marker `docs/audits/go.mod` (module `…/docs/audits`, classified shipped packaging behavior by the [module payload plan](2026-09-08-module-payload-plan.md)), and five campaign-only modules under `docs/audits/*/` that are frozen evidence.
- **Tool configuration.** [`.golangci.yml`](../../.golangci.yml) depguard rules `http3-internal` (package pattern) and `quicvarint` (file glob containing the module path); [`unit.yml`](../../.github/workflows/unit.yml) `-package-name`; [`interop/multipath/run.py`](../../interop/multipath/run.py) `PACKAGE` and `SMOKE_PACKAGE`, consumed by the required independent multipath peer job; dormant fuzz scripts `.clusterfuzzlite/build.sh` and `oss-fuzz.sh`.
- **Module graph.** No dependency requires `github.com/quic-go/quic-go`; `qpack` and `go-ossfuzz-seeds` are separate upstream modules that stay. After the rename the graph contains no upstream quic-go node.
- **Protocol and diagnostic strings** that contain `quic-go` but are not module identity: session-ticket prefix `quic-go1`, token HKDF info `quic-go token source`, HTTP/3 0-RTT settings prefix `quic-go h3 settings v1`, default User-Agent `quic-go HTTP/3`, qlog title `quic-go qlog`, integration ALPN, `QUIC_GO_*` environment variables, build tag `quic_go_no_private_syscalls`, container directories and image names.
- **Documentation.** README presents a fork with replacement adoption; [ADR 0001](0001-upstream-compatibility.md), [ADR 0002](0002-adopt-through-module-replacement.md) and [ADR 0003](0003-follow-stable-upstream-releases.md) are accepted and conflict with the approved policies; [SECURITY.md](../../SECURITY.md) routes reports and bugs upstream; the [release runbook](../runbooks/release.md) describes `-fast.N` prereleases, replacement consumer checks and draft prereleases; [usage](../usage.md) has "Use the fork" and "Return to upstream"; [conventions](../agents/conventions.md) require preserving the old module identity; `AGENTS.md` and [issue tracker](../agents/issue-tracker.md) name `the-sarge/quic-go-fast`; `http3/README.md` has an old-path pkg.go.dev badge; `FUZZING.md` shows upstream coverage badges.
- **Publication automation.** No publishing workflow exists. Prerelease assumptions live only in the runbook (draft GitHub prerelease) and README wording. Push/tag workflows validate tags; the interop image is build-only.
- **Repository state.** Tags reach `v0.62.1-fast.10`; `v0.63.0` is absent. Private vulnerability reporting is disabled. The repository description contains criticism of upstream and stale BBR wording.
- **Upstream advisories.** The upstream repository lists eight published advisories, all with patched versions at or below v0.59.1. Applicability to this source has not been reviewed.
- **Frozen evidence.** `docs/audits/**` (except the packaging marker's module line), `docs/DEV-JOURNAL.md`, existing `docs/releases/*.md`, root `testdata/congestioncontrol` and `testdata/externalpacketio` (closed compatibility fixtures that copy one consumer into upstream and fork modules under the old shared path), historical CHANGELOG entries, and dated plan documents under `docs/adr/`.

A disposable probe on an exported copy of the base confirmed the shape: the rewrite below builds, vets on darwin, linux, windows, freebsd and openbsd, regenerates mocks with no drift, keeps the root and FIPS modules tidy, vendors the vendor fixture, leaves no upstream quic-go node in the module graph, and passes the `qlogwriter` and closure tests after the two fixes named in PR A. The probe was discarded; it is not evidence for any PR.

## Approach

**Decision.** One atomic mechanical identity PR (A), then a stacked declaration and documentation PR (B). A's rewrite is a recorded, rerunnable procedure so #1111 can regenerate it on a moved `main` rather than hand-merge 700 files.

**Owner's design.** Go's own tooling owns identity: `go mod edit -module` owns module declarations; the compiler and `go/parser` own import validity; `go generate` owns generated mocks; the module proxy protocol owns path escaping. The plan uses those owners for every universal claim and confines handwritten checks to enumerated non-Go configuration.

**Rejected alternatives.**

- One PR containing both identity and documentation. Buries the prose review in a 730-file mechanical diff. `none: rejected on merit`.
- Splitting the Go rewrite across PRs. Imports and the module declaration must change atomically to compile. `none: rejected on merit`.
- Compatibility aliases or a shim module at `github.com/quic-go/quic-go`. Prohibited by #1109; defined types from different module paths are distinct. `none: rejected by contract`.
- Renaming protocol, crypto-domain or diagnostic strings, environment variables or build tags. Changes behavior, session/token compatibility or operator interfaces without an approved need. Revisit if Josh requests a distinct User-Agent or qlog title in a later minor release.
- Rewriting historical links to the new repository. Transfer redirects preserve them, and rewriting historical records is prohibited. Revisit if #1110 reports a redirect failure.
- Adapting the frozen `testdata` compatibility fixtures. They are closed experiment helpers whose method depends on the old shared path. Revisit only under a new compatibility-evidence scope.
- Activating the inert `quicvarint` depguard rule. Its file glob appears to depend on a GOPATH-style checkout path, so it does not match this repository's CI checkouts; changing its meaning is an enforcement change outside identity. Revisit as a separate follow-up after PR A's probe confirms inertness.

## PR A — module identity

**Branch and worktree:** `claude/quicquic-identity-1109` in `/Volumes/worktrees/quicquic-identity-1109/quic-go-fast`, based on the base above. This plan document is the branch's first commit; PR A's diff therefore contains it as process metadata.

### Contract

- **Outcome:** every maintained Go package, nested maintained module, generated file and identity-bearing tool configuration names `github.com/GridCastIO/quicquic-go`, with root `package quic` and no change in behavior other than identity.
- **Acceptance criteria:**
  1. Root `go.mod` declares `module github.com/GridCastIO/quicquic-go`; `go`, `toolchain`, `require` and `tool` lines are unchanged; `go.sum` is unchanged.
  2. No maintained `.go` file, under any build constraint, imports a path equal to or under `github.com/quic-go/quic-go`.
  3. Package-path strings change only where they name this module: mockgen directives and regenerated headers, `-self_package`, stack-frame expectations, `ringbuffer` panic text, the `qlogwriter` build-info match and `-X` comment.
  4. `integrationtests/fips` and `integrationtests/gomodvendor` require and replace the new path; `docs/audits/go.mod` declares `github.com/GridCastIO/quicquic-go/docs/audits` with its comment unchanged.
  5. `.golangci.yml`, `unit.yml`, `interop/Dockerfile`, `interop/multipath/run.py`, `.clusterfuzzlite/build.sh` and `oss-fuzz.sh` name the new package paths.
  6. `TestTraceCodeVersion` builds real consumers of the new module path and reports the expected `code_version` for ordinary, versioned-replacement, local-replacement, linker-revision and linker-over-replacement cases. Its fake proxy escapes uppercase path elements as the module proxy protocol requires.
  7. Upstream URLs and `quic-go/quic-go#N` references are unchanged, and PR A introduces no link to `github.com/GridCastIO/quicquic-go`.
  8. Protocol, crypto-domain and diagnostic strings, environment variables, build tags, container paths and image names are unchanged.
  9. Frozen evidence is byte-identical.
  10. `go mod graph` contains no `github.com/quic-go/quic-go` node.
- **Preserved behavior:** all runtime behavior, wire format, public API shape (names, signatures, documented contracts), experimental qualifications, defaults, test inventory and CI job structure. The only intended caller-visible change is the import path.
- **Non-goals:** documentation prose (PR B); type aliases or shim modules; activating the `quicvarint` rule; restoring dormant fuzzing or performance infrastructure; renaming OSS-Fuzz project names or storage repositories; interop runner registration (#1112); upstream URL rewriting.
- **Blast radius:** public import path of every package (intended, total consumer cutover); generated mocks; lint enforcement inputs; required multipath job package matching; qlog `code_version` detection; interop image version stamping; nested module identities. No new dependency, go.mod requirement, goroutine, lock or API.
- **Artifact classes:** shipped behavior: module declaration, imports, qlog build-info match, panic text. Required safety enforcement: none newly added; the existing `http3-internal` depguard rule must stay effective. Verification aids: `TestTraceCodeVersion`, stack-frame test expectations, `run.py`, the residual scans and probes below (throwaway; none becomes a maintained deliverable). Process metadata: this plan, PR body.
- **Representation domain and owner:** maintained Go source = every tracked `.go` file outside `docs/` and root `testdata/`, owned by `go/parser` (imports, regardless of build constraints) and the Go compiler (resolution); module files owned by `go mod edit`; generated files owned by `.github/workflows/go-generate.sh`; non-Go configuration = the enumerated six files.
- **Guarantee level:** universal over maintained Go import specs (parser-owned scan plus compiler across the lint and cross-compile GOOS matrix); canonical-subset over the enumerated configuration files; example-level for runtime string behavior (`TestTraceCodeVersion`, closure tests).
- **Review-round budget:** one code-review preparation pass; one initial fully briefed RAS review with the configured panel and default timeouts; verification of accepted `fix-now` findings; at most one replacement review. No panel narrowing and no `--timeout-seconds`.

### Changes

Run from the worktree root. The procedure is the reproducible source of PR A; #1111 reruns it if `main` moves.

```sh
OLD=github.com/quic-go/quic-go
NEW=github.com/GridCastIO/quicquic-go
go mod edit -module "$NEW"
go mod edit -module "$NEW/docs/audits" docs/audits/go.mod
git grep -lz "$OLD" -- ':!docs/' ':!testdata/' ':!*.md' |
  xargs -0 perl -pi -e 's{(?<!://)\bgithub\.com/quic-go/quic-go(?![\w-])}{github.com/GridCastIO/quicquic-go}g'
(cd integrationtests/fips && go mod tidy)
git add -A && .github/workflows/go-generate.sh
```

The negative lookbehind keeps `https://github.com/quic-go/quic-go/...` URLs upstream; the lookahead permits `.` so stack-frame symbols such as `github.com/quic-go/quic-go.(*closureReader)` are rewritten. Then two hand edits:

- `qlogwriter/version_test.go`: the module constant becomes the new path, the replacement constant becomes a synthetic `example.com/quicquic-go-replacement`, and a local helper escapes each uppercase letter as `!` plus its lowercase form for the fake proxy keys. No new dependency.
- Review the `perl` result for `oss-fuzz.sh`'s GOPATH `cd` line and accept it: the script is dormant upstream OSS-Fuzz integration, and only its Go package paths are identity.

### Evidence and test seams

| Seam | Catches | Misses |
| --- | --- | --- |
| `go build ./...`, `go vet ./...` for darwin, linux, windows, freebsd and openbsd; golangci-lint matrix; hosted cross-compile | Unresolved or stale imports in compiled files for those targets | Files excluded by every built tag combination |
| Throwaway `go/parser` `ImportsOnly` scan of every maintained `.go` file, ignoring build constraints | Any remaining old import in any file, including tag-gated and test files | Non-import strings |
| Residual `git grep` for the old path outside `docs/`, `testdata/` and `*.md`, each hit classified as upstream URL or frozen | Leftover package-path strings in Go, YAML, shell, Python, Dockerfile | Semantic misuse of a correctly spelled path |
| Normalized-tree equality: candidate tree with `NEW` mapped back to `OLD` must equal the base tree except this plan and `qlogwriter/version_test.go` | Any accidental non-identity edit, including changed protocol strings | URL rewrites that normalize back; covered by the next row |
| `git grep 'https://github.com/GridCastIO/quicquic-go'` empty in PR A | Upstream URLs rewritten to the new home | Nothing in scope |
| `TestTraceCodeVersion` (updated) | Stale build-info match, stale `-X` package path, proxy case escaping | Interop Dockerfile string, covered by residual scan |
| Existing closure tests in `sys_conn_closure_test.go` | Stale stack-frame expectations | None in scope |
| `go mod tidy -diff` (root and FIPS), `go mod vendor` in `gomodvendor`, FIPS integration test, `go mod graph` grep | Nested-module and graph identity | Proxy download, deferred to #1111 |
| `.github/workflows/go-generate.sh` | Generated files out of date with directives | Generator behavior changes (none) |
| One temporary depguard probe: an `http3` file importing `NEW/internal/protocol` must fail lint; revert | `http3-internal` rule silently disabled by a stale pattern | Other depguard rules |
| One temporary `quicvarint` probe: record whether the rule fires; expected inert; do not fix | Confirms the pre-existing inertness claim | — |
| `python3 interop/multipath/test_run.py` plus `go test -json -run '^$' ./integrationtests/self` Package field equals `run.PACKAGE` | Required peer job package mismatch | Full peer matrix, which runs only on ready and is deferred to #1111 |
| `git diff --stat <base>...HEAD -- docs/audits ':!docs/audits/go.mod' testdata docs/DEV-JOURNAL.md docs/releases CHANGELOG.md` empty | Frozen-evidence edits | — |
| Full local `go test ./...` and integration packages on macOS; hosted unit, integration, lint, cross-compile and interop-image on the draft head | Behavior regressions on Linux, macOS, Windows, race lane | Destination-dependent checks |

**Contract closure:** triggered for acceptance criterion 2. Failure is a public compatibility break, and tag- and GOOS-gated files are independently reachable states. Invariant: no maintained Go file imports the old module path. Single enforcement owner: the `go/parser` scan, with the compiler matrix as corroboration. Matrix:

| Semantic class | Disposition | Owner | Evidence | Status |
| --- | --- | --- | --- | --- |
| Untagged production and test files | Rewritten | Parser scan, compiler | Scan, local build/vet/test | Covered |
| GOOS/GOARCH-suffixed and tag-gated files (`root`, `gomock`, `quic_go_no_private_syscalls`, `race`) | Rewritten | Parser scan | Scan; vet matrix; hosted lint and cross-compile | Covered |
| Nested maintained modules | Rewritten | go command | Tidy, vendor, FIPS test | Covered |
| Generated mocks | Regenerated | go-generate.sh | Generation check | Covered |
| Frozen fixtures and campaign modules | Preserved; not compiled | Path exclusion | Frozen diff check | Non-goal |

No other closure is triggered. No fuzz, repetition, timing or extra platform scope.

**Terminating evidence:** every row above observed once on the final candidate, plus hosted draft checks green on the exact pushed head, plus the review budget satisfied.

## PR B — declaration, documentation, release and security instructions

**Branch and worktree:** `claude/quicquic-docs-1109` in `/Volumes/worktrees/quicquic-docs-1109/quic-go-fast`, branched from PR A's head and opened with PR A's branch as its base, so its diff is documentation only and its CI runs on the combined final tree. Review fixes in PR A are carried into B by rebasing B onto A before B's certification.

### Contract

- **Outcome:** maintained documentation, ADRs, release runbook, security instructions and package descriptions match the approved identity, independent maintenance, versioning, declaration and evidence policies, with history preserved.
- **Acceptance criteria:**
  1. README opens with the approved sentence verbatim, titles the project quicquic-go, removes upstream criticism and stale BBR wording, keeps maturity qualifications beside the claims they qualify, states v0.63.0 as the planned first independent release without presenting it as available, and adds an "Origins and license" section: derives from quic-go, v0.62.0 historical baseline, MIT notice and author credits unchanged, upstream documentation (quic-go.net, inherited `FIPS140.md`, `FUZZING.md`, `http3/README.md`) distinguished from this project's supported behavior, brand-asset policy retained.
  2. CHANGELOG adds a `v0.63.0 — unreleased` entry marking the first independent release and explaining the name and module-path transition, ancestry and version policy. Every earlier line is byte-identical.
  3. New ADRs: 0014 independent module identity and adoption (supersedes 0002, including its wiremux dual-path section, pointing to GridSwarm/wiremux#2175); 0015 independent maintenance with selective validated upstream adoption (supersedes 0003); 0016 version-aware compatibility promise (supersedes 0001 and carries forward its protection against silently imposed ownership obligations; cites ADR 0009's keyed-`Config` exception). ADRs 0001–0003 change only their front-matter status to superseded and gain one leading line naming the successor; their bodies are byte-identical.
  4. SECURITY.md routes vulnerabilities to this repository's private vulnerability reporting at the final home and ordinary bugs to its issues, states Josh's security ownership, keeps unpublished details private, and states the scanner coverage limit. Its merge in #1111 requires the private channel to be enabled and verified first, as #651 already requires.
  5. Release runbook: independent versions starting at v0.63.0 under the #653 meaning; canonical module path; stable GitHub Release (not prerelease) for v0.63.0; optional `-rc.N` candidates need explicit selection and never stand in for `@latest`; existing exact-commit unit, integration, lint, cross-compile and interop-image evidence; fresh `govulncheck` with recorded scanner and Go versions plus the upstream-advisory applicability record; a separate downloaded consumer that builds QUIC and HTTP/3 from a fresh environment without replacements; explicit-version and `@latest` checks after publication; inherited old-path tags are history, not releases of the new module; corrections get new versions. The fast.9 exception stays as history. The prerelease-automation audit finding (none exists) is recorded.
  6. New runbook `docs/runbooks/upstream-advisories.md`: the #651 procedure (sources, cadence, notify-on-action, applicability assessment, private handling, fix preparation, Go-release validation, Josh's disposition, record keeping), scanner identity limits (vulnerability records match module paths; replacements and versions affect lookup; a clean independent-path scan does not cover inherited upstream code; never falsify the module path), and the reproducible review commands. It selects and documents the monitoring runner Josh chose on 2026-11-17, satisfying #651 step 8: a daily GitHub Actions scheduled workflow beside the existing `govulncheck` job. The design covers its sources (upstream quic-go's published advisories and release notes, Go security announcements, and detection of the first Go release candidate); a durable watch state (the last-seen identifiers per source, kept so that only new or changed items notify and a lost state is detectable); notification through a GitHub issue assigned to Josh that carries only public identifiers and links; a notification when monitoring itself fails; and enablement checks that confirm, once enabled, that the schedule is active, a recent run succeeded, the watch state advanced and a test notification reached Josh. Unpublished vulnerability details never enter the workflow, its state or its issues. #1109 creates no workflow file and schedules nothing; building and enabling the workflow is a follow-up after #1111 at the final home.
  7. `docs/usage.md` replaces "Use the fork" and "Return to upstream" with the migration packet: root and subpackage import changes with exact path case; `go get github.com/GridCastIO/quicquic-go@v0.63.0` once published; dropping the old replacement after `go mod why -m` and `go mod graph` show no remaining requirement; keyed `Config` literals; HTTP/3 error handling; Go 1.26.0 minimum; mixed old/new type exposure at dependency boundaries (wiremux first); other actual public differences from upstream v0.62.0 and from fast.10.
  8. `docs/releases/v0.63.0.md` preparation record: scope, migration summary, scanner coverage note, the advisory applicability record with Josh's disposition, destination-dependent checks and expected metadata changes.
  9. Package doc comments for root `quic` and `http3` describe the approved identity. No other package gains or changes a doc comment.
  10. `docs/agents/conventions.md` points to ADR 0014 and the new identity; `AGENTS.md` and `docs/agents/issue-tracker.md` name `GridCastIO/quicquic-go`; `http3/README.md` badge uses the new path; `FUZZING.md` replaces upstream coverage badges with a note that ClusterFuzzLite workflows are disabled and CodSpeed is manual-only.
  11. Links into the old repository's issues, PRs, releases and pinned blobs stay as written. New-home links appear only for the repository, issues, security reporting, pkg.go.dev and the planned release.
- **Preserved behavior:** historical records, tags, evidence, qualifications, MIT license and copyright, author credits, brand-asset policy, existing review and release obligations.
- **Non-goals:** a wholesale "fork" wording sweep beyond the files above; rewriting inherited upstream documents; editing the development journal; scheduling monitoring; enabling private reporting or other settings; publishing any advisory or vulnerability report; changing repository metadata (specified for #1110 below); README installation pointing at an unpublished tag; topics decision.
- **Blast radius:** documentation and two doc comments. Agent instructions change repository slug, which takes effect only after merge at the final home.
- **Artifact classes:** process metadata and documentation, except the two doc comments (shipped package documentation).
- **Representation domain and owner:** the enumerated files; Markdown rendering by GitHub; relative links owned by the repository tree.
- **Guarantee level:** example-level for prose; exact byte preservation for historical CHANGELOG lines and ADR bodies.
- **Review-round budget:** as PR A. PR B's code-review preparation pass and RAS review start only after the disclosable advisory record and Josh's disposition are in PR B's candidate (see the advisory section). The docs-only polish exemption does not apply to that security content.

### Evidence and test seams

| Seam | Catches | Misses |
| --- | --- | --- |
| CHANGELOG suffix comparison against base | Rewritten history | Accuracy of the new entry (review) |
| ADR body comparison below the new header | Silent ADR rewrites | Successor ADR quality (review) |
| Changed-path allowlist against the enumerated files | Frozen evidence or out-of-scope edits | — |
| `git diff --check`; throwaway relative-link check over changed Markdown | Whitespace errors, broken relative links | External and new-home links, deferred to #1111 |
| Approved-text check: README opening equals the #654 sentence | Drift from approved declaration | — |
| `go vet ./... && go doc . && go doc ./http3` | Doc comment placement and syntax | pkg.go.dev rendering, deferred |
| Optional `apidiff` (pinned `golang.org/x/exp/cmd/apidiff`) of upstream v0.62.0 and fast.10 against the base, same old module path, for the supported packages | Unlisted incompatible public differences for the migration packet | Behavioral differences without signature change (taken from the changelog) |

Contract closure: not triggered. Terminating evidence: the disclosable advisory record and Josh's disposition present in the candidate before review begins, every row once on the final candidate, hosted draft checks green on the exact head, review budget satisfied.

## Upstream-advisory applicability review

- **Preparation.** During PR B, record retrieval time and sources (upstream security advisories API, the Go vulnerability database entries for `github.com/quic-go/quic-go`). For each advisory record GHSA, CVE and GO identifiers, affected and patched ranges, upstream fix commits, whether each fix is an ancestor of `v0.62.0` (`git merge-base --is-ancestor`), fork changes since `v0.62.0` touching the fixed code (`git log v0.62.0..<head> -- <files>`), existing regression tests, and an applicability conclusion with remaining uncertainty. Read the scanner's module-lookup and replacement code at a pinned current `golang/vuln` revision and record its actual behavior.
- **Privacy.** The analysis is prepared privately and returned to the coordinator for Josh, not committed or posted first. Entries Josh classifies as disclosable are committed to the release record; any applicable and unfixed finding stays out of the repository and public issues. A fix for such a finding is a separate security task under Josh's disposition, not part of #1109.
- **Disposition.** Josh's disposition is a reserved human decision, requested through the coordinator once the review is ready.
- **Sequence.** (1) Prepare the private applicability review. (2) Return it to the coordinator for Josh; it is not committed, posted or summarized with specifics on GitHub. (3) Add only the disclosable record and Josh's disposition to PR B's candidate. (4) Only then start PR B's code-review preparation pass and RAS review. PR A proceeds independently and does not wait for this sequence.

## Local certification and hosted checks

There is no `task preflight`. For each PR, at the exact pushed head with a clean worktree, record: head and base SHAs, `go version`, the PR's evidence rows above, `go test ./...` and `go test ./integrationtests/...` (PR A), `go test -count=1 ./.githooks`, `go tool gcassert ./...`, `go fix -diff` as configured, golangci-lint v2.14.0 for the six configured GOOS values, `python3 .github/scripts/test_unit_capture.py`, and `git diff --check`. Then observe `gh pr checks <pr> --repo the-sarge/quic-go-fast` on that head with one background watcher per head. Expected on drafts: unit, integration, lint, cross-compile and interop image. The multipath peer job skips drafts.

CI at the old home is not expected to fail because of the new path: every workflow builds from the checkout, `govulncheck` scans the local module, and no step downloads this module by path. A failure is diagnosed before any rerun. A green `govulncheck` here says nothing about inherited upstream advisories.

## Destination-dependent checks deferred to #1111

1. Refresh both PRs on the final home's `main`; if `main` moved, rerun PR A's procedure and its evidence; review changed work under the existing rules.
2. Hosted CI at the final home on the exact head, including the required multipath peer job when marked ready; Actions variables, runners and `CODECOV_TOKEN` reconciled by #1110.
3. Private vulnerability reporting enabled and verified before SECURITY.md merges.
4. New-home links: repository, issues, security reporting, release, pkg.go.dev badge.
5. `v0.63.0` tag and release absent; inherited tags unchanged.
6. After tagging: `GOPROXY=https://proxy.golang.org GOFLAGS=-mod=mod go list -m -json github.com/GridCastIO/quicquic-go@v0.63.0`, checksum-database verification, `go list -m -versions` and `@latest` resolving to v0.63.0, and inherited old-path tags not selectable for the new path.
7. A fresh external consumer without replacements builds QUIC and HTTP/3; record resolved versions and sums; run a versioned consumer `govulncheck`; refresh the advisory review at the release commit.
8. pkg.go.dev rendering of README and package docs (observational).
9. Repository description and topics applied during #1110.
10. Post-publication docs update pointing installation at the real tag and recording publication.
11. Follow-up after #1111, not filed by #1109: build and enable the daily upstream-advisory monitoring workflow at the final home as designed in `docs/runbooks/upstream-advisories.md`, then run its enablement checks.

## Handoff packet

PR numbers and URLs; final heads and the base they were certified against; normalized-equality and scan receipts; local certification receipts; hosted check URLs per head; deferred findings with observing heads; the rerunnable PR A procedure; the deferred check list above with commands; the consumer migration packet (pointer to `docs/usage.md` plus a short summary); expected metadata changes:

- Description: "An independently maintained QUIC and HTTP/3 implementation in Go, focused on transport performance and practical application integration."
- Topics, proposed for Josh to confirm in #1110: `quic`, `http3`, `go`, `golang`, `rfc9000`, `rfc9001`, `rfc9114`, `rfc9221`, `rfc9297`, `quic-datagram`. The BBR topics are dropped because BBR is experimental and unqualified.

## Untraced effects

- Go proxy and checksum-database treatment of inherited tags that declare the old path when queried under the new path; observable only after publication.
- Exact-case requirement: `github.com/gridcastio/quicquic-go` is a different module path and fails with a path mismatch; cache paths use `!`-escaping. Documented, not tested beyond `TestTraceCodeVersion`.
- Current `govulncheck` replacement semantics; to be read at a pinned revision during PR B.
- RAS behavior on a 730-file mechanical diff; reported if it fails, never handled by narrowing the panel or timeouts.
- Codecov project mapping, Actions variables and secrets after transfer.
- Other work merging into `main` before #1111 will need the rewrite; open PR #1295 will conflict.
- Consumers that expose QUIC types (wiremux) create mixed old/new type sets until their own cutovers.

## Decisions requested

- **Josh — upstream-advisory disposition (reserved).** Requested through the coordinator when the private review is ready, before PR B's review begins. Recommendation: commit only entries Josh marks disclosable; keep any applicable unfixed finding in a private location he chooses (for example a draft repository security advisory once private reporting is enabled at the final home).

## Settled decisions

- **Monitoring runner (Josh, 2026-11-17):** a daily GitHub Actions scheduled workflow beside the existing `govulncheck` job, documented by PR B and built after #1111. Recorded in the [decision receipt](https://github.com/the-sarge/quic-go-fast/issues/1109#issuecomment-6940490276).
- **Scope readings (confirmed by the coordinator):** package descriptions are the root `quic` and `http3` doc comments only; the default User-Agent and other protocol, crypto-domain and diagnostic strings stay unchanged; `main` is not frozen, and #1111 reruns PR A's procedure if it moved.

## Stop conditions

Stop and return to the coordinator if: a non-identity behavior change is needed to make PR A pass; a finding is `stop-for-decision` under the shared review loop; the advisory review finds an applicable unfixed vulnerability; approved policies contradict each other in a way the plan cannot satisfy; or certification requires a new gate, budget or platform scope.
