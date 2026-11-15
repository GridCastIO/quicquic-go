# RAS Review Synthesis

PR #1377 — Reduce ordinary BBR overhead on granted endpoints. Reviewed scope: base `62247738352d9f645935518fa9259fe4e2f48dc8`, candidate `734a8190810eed2b9230a274386459aa67e2cae3`. The supplied findings and adjudications support two bounded documentation corrections and no demonstrated runtime defect. The owner's exact measured exceptions for issue #1368 remain distinct from the unchanged thresholds and raw failed verdicts; ready-head hosted checks remain unverified in the supplied evidence.

## Fix First

1. <!-- ras:cluster C-001 --> **[low; high confidence] Correct E09's documented production reach.** Source agent: `claude-fable`; all supplied adjudications agree. `native_ordinary.go:129–135` initializes recovery from the connection's root handler, and `native_ordinary_completion.go:24` is the sole production caller of `TryCompleteLocalAcceptedPackets`. The owner/epoch checks in `internal/ackhandler/local_completion_span.go:55` reject nonzero-path registrations, whose handlers have separate owners (`sent_path.go:94`). Ordered scalar completion delegates to those owners (`local_completion.go:254–266`), allowing E02 to reach them safely. Update `docs/designs/bbrv3.md:67` and the maintained E09 reach statements in `docs/audits/2026-11-14-bbr-ordinary-cost-1368/candidate-applicability.md`: current production member completion handles root-owned members, including eligible path-zero members; nonzero-path members fall back to scalar completion. Distinguish production wiring from helper capability: an explicitly supplied matching path handler could satisfy the helper. Do not expand runtime reach or rewrite historical experiment plans. Keep the six-case interoperability inventory; its existence does not prove the E09 member branch executed on a root with rich paths attached.

2. <!-- ras:cluster C-003 --> **[low; high confidence for stale wording] Reconcile current deferred-cost descriptions.** Source agent: `claude-fable`, originally medium confidence. `CHANGELOG.md:9`, `docs/adr/2026-10-24-multipath-bbr-plan.md:3` and `docs/adr/2026-10-24-multipath-program.md:16` still describe issue #1368 as deferred, while PR #1377 delivers retained E09 under exact-result exceptions and updates the corresponding usage documentation. Update those current-status phrases and link the final acceptance/results. Preserve the historical B5 failure and deferral decision, the work's placement outside the earlier track/program, experimental and unqualified BBR status, and public Reno-only multipath support. Adjudications differ on whether the historical changelog context and ADR wording require maintenance, but the present-tense deferred characterization warrants this narrow reconciliation. They do not establish a mandatory separate Unreleased entry: release preparation has its own changelog workflow. A concise amendment suffices; do not require a duplicated measurement table or present accepted exceptions as passing thresholds.

## Follow Up

No finding clusters require follow-up.

## Do Not Act On

1. <!-- ras:cluster C-002 --> **[low/nit; high confidence in disposition] Retain the tested profiled-diagnostic success behavior.** Source agent: `claude-opus`, medium confidence. `interop/multipath/ordinary_cost.py:619–621` can report `passed=true` and exit zero alongside `timing_eligible=false`; the observation is supported. Adjudications range from agreement to disagreement, with partial agreements narrowing the concern to ambiguous naming. The summary also declares diagnostic/smoke mode and `campaign_complete=false`, and campaign accounting rejects profiled records. The existing `test_profiling_requires_both_profiles_and_is_not_timing_evidence` intentionally expects successful collection to exit zero. Supplied adjudications report passing focused profiling and inventory tests; archived profiled summaries retain failed verdicts, and final qualification was unprofiled. No qualification bypass is demonstrated. Do not AND success with `not cpu_profile`, which would conflate successful attribution collection with failure. Optional naming cleanup has insufficient benefit to add work to this delivery queue.

## Verification

For C-001, trace the sole production caller, root-handler initialization, per-path registration ownership and scalar delegation against every amended E09 reach statement. Confirm documentation distinguishes actual production reach from hypothetical direct helper use and makes no unsupported branch-coverage claim.

For C-003, inspect all three current-status passages alongside `docs/usage.md` and the latest recorded owner acceptance for issue #1368. Preserve the original 0.95 goodput floor, 1.10 CPU ceiling and raw failures: mixed-bulk paired ratios `0.944295141271208 / 1.2081314772756437`, stateless-pressure `0.9590708299335772 / 1.1593702973325581`. Acceptance covers only the recorded exceptions.

Verify the resulting patch changes maintained prose only, preserves frozen evidence and introduces no paragraph-rewrapping churn. Use existing documentation checks and scoped finding verification at the exact updated head. These corrections do not justify replaying native workloads or adding platform coverage. Existing ready-head checks and the bounded review workflow remain required; this synthesis claims no new test execution.

## Resolution Reply

| Cluster | Disposition | Resolution evidence |
| --- | --- | --- |
| C-001 | Fix first; pending | Cite corrected maintained reach statements and the production caller/owner trace. |
| C-002 | Do not act; low value | Retain explicit timing ineligibility, campaign exclusion and tested successful profile collection. |
| C-003 | Fix first; pending | Cite the three reconciled status passages and preserved exact-result acceptance boundaries. |

Recommendation: apply the two documentation corrections, verify them within the existing bounded workflow, and complete the required ready-head checks before proceeding with the authorized merge of PR #1377.