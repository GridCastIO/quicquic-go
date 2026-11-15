# Initial review disposition for PR #1377

Initial full-panel RAS run `20261115T044010-73516bc125a2bca0aee2c78e` reviewed base `62247738352d9f645935518fa9259fe4e2f48dc8` and head `734a8190810eed2b9230a274386459aa67e2cae3`. All four configured reviewers participated: codex-astra, codex-sol, claude-fable and claude-opus. The [complete synthesis](initial-synthesis.md) reports no demonstrated runtime defect and two narrow documentation corrections.

| Finding | Independent disposition and bounded evidence |
| --- | --- |
| C-001 | **fix-now**, maintained documentation accuracy. The sole production member-completion caller supplies the native sender's root recovery handler. The common epoch/owner check rejects nonzero-path registrations, whose scalar completion delegates to the actual owner. Correct current reach descriptions to distinguish root-owned members, including eligible path-zero members, from hypothetical helper calls with an explicitly matching path handler. Keep six-case interop evidence without inferring rich-root member-branch coverage. No runtime expansion or frozen-plan rewrite. |
| C-002 | **reject** as a required change. Successful profiled diagnostic collection may return success while explicitly declaring timing ineligibility and an incomplete campaign. Campaign accounting excludes profiling. The existing focused test intentionally covers that behavior, and final qualification was unprofiled. No demonstrated qualification bypass; adding failure for successful attribution collection is not required. No follow-up busywork. |
| C-003 | **fix-now**, current documentation status. Reconcile the three present-tense deferred-cost passages with the exact-result owner acceptance. Preserve historical B5 failure/deferral, placement outside the earlier program, experimental and unqualified BBR status, and public Reno-only multipath. No new release entry or duplicate metric table is required. |

These are maintained-prose obligations, not a material-risk enforcement seam. No representation change, repeated semantic counterexample or boundary expansion is involved. The cheap documentation-only policy permits local source/link/diff verification without a separate RAS verification cycle for these findings.

## Diagnosed hosted failure and test-only fix

Draft-head lint run `43677743317` failed both Go versions only on staticcheck QF1003 in three test branches. [Original failed logs](draft-lint-failure.log) are retained. Commit `853d6b8056d2289e3a4f749a45e093e63f58aa89` changes the outcome and payload-selection chains in `bbr_native_large_test.go` and the recovery-kind chain in `internal/ackhandler/local_bbr_span_test.go` to tagged switches. The independent read-only audit inspected that exact working diff before its commit: selectors are stable local strings; the mutually exclusive branch bodies, order, no-op defaults and absence of fallthrough preserve behavior. It found no production or qualification-apparatus change.

At this source, `go test -count=1 . ./internal/ackhandler` passed (27.862 /23.632 seconds); `go vet . ./internal/ackhandler` and `go mod tidy -diff` passed; installed golangci-lint 2.14.0 with Go 1.27.4 ran `golangci-lint run --timeout=3m ./...` with zero issues. All commands returned zero. These are source-specific local results; hosted checks on the final head remain authoritative.

Native qualification keeps its original `a1c9442f110cca36cb4752b39ce24ae998d76f05` source and binary identities. Whole-Go-file equality no longer holds because two test files changed; unchanged production and qualification apparatus plus the semantic audit support applicability. No new native experiment or operational charge is justified. A final exact-head local certificate and the one allowed full-panel replacement review cover the updated candidate before ready-head checks.

## Review-tool placement

The initial run inherited `/Volumes/worktrees/quic-go-fast/silent-drop-plan/.ras/config.yaml`, placing disposable reviewer worktrees one directory level below the intended root. All reviewers still used the correct pinned commit. RAS retained ownership of those active worktrees; none was moved or reset. Subsequent runs use an explicit task-local config with `worktree_root: /Volumes/worktrees` and this task's `.ras/data`, preserving the full global panel and the existing isolated compatibility binary. The initial history remains in its original RAS data directory.
