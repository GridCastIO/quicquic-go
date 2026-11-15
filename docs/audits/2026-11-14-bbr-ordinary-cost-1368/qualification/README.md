# BBR ordinary-cost qualification apparatus for issue #1368

This apparatus reproduces the two-cell ordinary-cost comparison required by [BBR ordinary-flow cost (#1368)](https://github.com/the-sarge/quic-go-fast/issues/1368), using an explicit measurement-only Go overlay. It does not enable public BBR multipath. Unoverlaid source and its refusal tests remain authoritative for public support. No measurements were run while preparing these helpers.

## Source and overlay identity

`prepare.py` reads the full product commit supplied by `--product-sha` from Git, independently of the checkout's working files. It requires exact original SHA-256 values for both overlaid files and exactly one occurrence of each replacement snippet. These file identities are from diagnostic-fixture commit `c1a6ffea2a52e2b9c820b4632f22e547560fa5c2`; a product candidate may change other files. A change to either overlaid file requires explicit inspection and revision of this apparatus, rather than approximate matching.

| Overlaid file | Exact measurement-only changes |
| --- | --- |
| `multipath_api.go` | Admit either Reno or BBR at the controller check. Preserve the platform, QUIC version, path-count, policy, connection-ID, socket, grant and conflicting-I/O checks. No public configuration selector is added. |
| `ordinary_cost_test.go` | Permit BBR in the existing `mixed-bulk` cell in addition to `stateless-pressure`; advertise multipath on a granted server as the historical B5 fixture did; add each server connection's and client flow's actual `Conn.CongestionControlV1()` result for the historical driver's validation. |

The overlay changes no packet emission, recovery, scheduling, timing, rate, payload, useful-delivery boundary or cleanup implementation. It makes the candidate's existing BBR primary/backup implementation reachable only in the separately built measurement binary. The fixture's ordinary public-refusal/controller-scope tests describe unoverlaid behavior and must be run without this overlay; the qualification driver runs only `TestOrdinaryCostRole` in the overlaid binary.

The generated bundle contains the exact source archive, a manifest of every archived file, the original and replacement hashes, both replacement files, the unified `overlay.patch`, the build helper and the historical driver. `build.py` requires a fresh extraction with exactly the recorded file inventory, verifies all source and helper hashes, binds absolute paths into `overlay.json`, and records the exact command, environment, exit code, Go build information and resulting binary SHA-256 in `build-receipt.json`. A pre-existing binary or receipt is preserved by refusing a second build in that bundle.

## Preserved B5 driver and applicability

`ordinary_cost_b5.py` is byte-for-byte `interop/multipath/ordinary_cost.py` from B5 candidate `4e80d3cf4fa7454ffc3e2a46655afd5f81f86313`, SHA-256 `37433087ea2b921bc47ed5603d52d7d55939347fbcab7208e62de3a6885f3d03`. Its fixed BBR inventory is two cells × two endpoint profiles × three observations = 12 observations. Its seeds, alternating profile order, 10-second warmup, 60-second measurement window, server cores 8–11, client cores 12–15, sibling-aware contamination accounting, bounded replacements, pre-launch charges and cleanup are unchanged. The original B5 receipt and raw data remain frozen at [B5 ordinary cost (#1044)](../../2026-11-14-multipath-b5-receipt.md#bbr-primarybackup-revalidation).

Goodput is receiver-counted ordinary application bytes over the window. CPU per useful byte is the server's window CPU divided by all useful application bytes received, including the mixed cell's background; it is not combined server-plus-client CPU. The independent limits remain goodput ratio ≥ 0.95 and CPU per useful byte ratio ≤ 1.10. Existing echo/send-call latency, memory, close, write, loss and progress checks retain their original interpretation. Every connection uses BBR in both profiles. The mixed cell compares one ordinary connection plus a two-path primary/backup BBR background against the ordinary connection plus two independent BBR backgrounds with the same total offered load. The stateless-pressure cell has no multipath connection.

These two BBR ordinary-cost cells remain the affected cost inventory for retained E02 + E06 + E08 + E09, audited at `96b57b83ad33473f194d2d39969a8f5ab41fe5f5` and measured as native source `76f64bd9418bcf403c6b0eaecdffc69ca611073c`. Selected source `59ca2a3a3d6dc9419f9bd09ae4b1e6197153e103` adds only the deterministic successor-skip fixture fix. After rejecting E11, integrated revert `05b23cddcce1acc3dc9305f05ab8c5fe3de5fa16` and evidence commit `9325fb70107d5698b7a1a33208f93a2344cb2fd6` have byte-identical Go source/tests and module files to that selected source. This documentation worktree is based on historical E11 integration `e89a22c0889fc87a65b93be4327514aea997c0c1`; it does not select that rejected runtime. The [combined candidate applicability record](../candidate-applicability.md) binds the actual guards, shared success bookkeeping, protected-buffer extension, accepted-member completion and case-by-case evidence carry. The earlier [E06 source assessment](../e06-applicability.md) remains a historical record of its own pin.

E02 retains the guarded BBR no-loss completion path. E06 uses one larger ordinary native BBR member; E05's two-buffer grouping is absent. E08 admits a whole-packet portion [M,N] under the existing credit lock, uses the actual grant for construction/storage selection and rearms M on true refusal. Q pacing, 2Q pending credit, generation debt, isolation and the original native lifetime remain. Current M ≤ 1,452 is the size guard, so a jumbo-configured connection still sending standard packets can qualify; active jumbo, Reno, unregistered BBR, negotiated multipath and routed work retain exact reservation. GSO-disabled eligible sends have N = M. These are scoped exceptions to earlier exact-request/batch examples, not changes to their frozen receipts or evidence of a performance gain.

E09 extends the existing fully accepted 2–64-packet native-member completion boundary to matching concrete BBR handlers. All current owner/epoch/history, prior-positive-PTO and live current-generation rich identities are checked before mutation; unsafe members retain ordered scalar completion. Per-packet authority, ECN and empty recovery-feedback transitions remain, with one ordered qualification traversal and final alarm derivation. Its call-local delivery-record borrows do not create a persistent owner or cache. Unlike E06/E08 admission, E09 has no ordinary-only or current-packet-size gate. Reno shares the factored authority loop and retains accepted-span semantics under existing equivalence/native tests; that is not a claim of identical machine code or measured CPU cost. Reno geometry, endpoint ownership and native timing boundaries remain unchanged, so the scoped Reno and E6/R21 carry still applies. E11's BBR-only prior-witness relaxation is rejected and absent from the selected source.

The combined candidate also revalidates the six existing BBR interop cases using the separate [measurement-only interop apparatus](interop/README.md). E02 and E09 reach BBR protocol-path handlers even though E06/E08 exclude negotiated multipath. The rejected E11 eligibility expansion adds no retained case. Neither apparatus replaces the final ready-head hosted checks, including the independent-peer job's 16 Reno cases and separate zero evidence, and neither enables public BBR multipath. The unoverlaid Reno-only admission/refusal tests remain authoritative.

**Final operational qualification: NOT RUN; overall acceptance: NOT MET; E11: VALID DIAGNOSTIC MISS, REJECTED.** The [valid E09 second-window pair](../e09-window2-timing/summary.json) and [independent raw audit](../e09-window2-independent-audit.json) record retained E09's goodput ratio `0.9693330897326472` passing and CPU/useful-byte ratio `1.1569072171177908` as the only failed check. E09 remains provisionally retained alongside E06+E08. The [completed E10 attribution pair](../e10-observed/summary.json) was contaminated; its [coverage audit](../e10-coverage-audit.json) verifies grouped PTO counts but cannot isolate the failing conjunct or establish quiet-case prevalence. All E10 timing is excluded, and its observer runtime is absent from the product.

The [valid E11 pair](https://github.com/the-sarge/quic-go-fast/blob/9325fb70107d5698b7a1a33208f93a2344cb2fd6/docs/audits/2026-11-14-bbr-ordinary-cost-1368/e11-timing/summary.json) and [independent audit](https://github.com/the-sarge/quic-go-fast/blob/9325fb70107d5698b7a1a33208f93a2344cb2fd6/docs/audits/2026-11-14-bbr-ordinary-cost-1368/e11-independent-audit.json) record goodput ratio `0.9585355015010547` passing and CPU/useful-byte ratio `1.1521072012417604` still failing. Against valid E09, granted useful output fell 2.1626% and absolute CPU/useful byte worsened 1.1208%; the slightly smaller paired CPU ratio did not establish a useful benefit. These are descriptive single-pair comparisons, not repeatability or isolated causal proof. E11 is rejected under its [predeclared retention criterion and committed disposition](https://github.com/the-sarge/quic-go-fast/blob/9325fb70107d5698b7a1a33208f93a2344cb2fd6/docs/audits/2026-11-14-bbr-ordinary-cost-1368-experiments.md#e11--let-a-validated-bbr-member-provide-its-initial-pto-witness), despite passing correctness/native checks. Its production/test change is reverted, its raw evidence remains frozen, and final qualification remains unlaunched. Mechanism checks, contaminated attribution and individual diagnostic pairs do not replace the existing final inventory.

The apparatus source, exact overlay files/snippets, historical drivers and scenario/build pins are unchanged and remain applicable to the audited/native source. This documentation update runs no workload and changes no source, command, inventory, threshold or allowance. Fresh bundles, build receipts and execution results must identify the actual final committed candidate after feasibility; no earlier binary, observer build or historical native timing is promoted to final qualification.

## Preparation and build

Choose the exact committed candidate after correctness checks. Generate a new bundle outside the repository; the generator reads Git objects and does not modify the product checkout:

```sh
python3 docs/audits/2026-11-14-bbr-ordinary-cost-1368/qualification/prepare.py \
  --repo /absolute/path/to/quic-go-fast \
  --product-sha FULL_40_CHARACTER_PRODUCT_SHA \
  --output /absolute/path/to/new-qualification-bundle
```

Transfer the complete bundle to the measured host, preserving `manifest.json`, `source.tar`, `overlay.patch` and the helpers. Extract `source.tar` into an empty directory outside the bundle, then run the build helper under native Go 1.27.4 on Linux amd64:

```sh
mkdir /absolute/path/to/fresh-source
tar -xf /absolute/path/to/qualification-bundle/source.tar -C /absolute/path/to/fresh-source
python3 /absolute/path/to/qualification-bundle/build.py \
  --bundle /absolute/path/to/qualification-bundle \
  --source /absolute/path/to/fresh-source
```

The recorded build command is `go test -overlay=/absolute/path/to/qualification-bundle/overlay.json -tags ordinarycost -c -o /absolute/path/to/qualification-bundle/ordinarycost.test .`, executed in the verified source directory with `GOOS=linux`, `GOARCH=amd64`, `GOAMD64=v1`, `CGO_ENABLED=0`, empty `GOFLAGS` and `GOEXPERIMENT`, `GOWORK=off`, `GOENV=off` and `GOTOOLCHAIN=local`. This compiles the test binary without running tests. The build receipt supplies its actual binary hash; the historical driver independently records that hash again in the run identity. Do not substitute an unoverlaid binary or one built from another candidate.

## Fixed requalification

Reconcile the live cumulative [program ledger (#646)](https://github.com/the-sarge/quic-go-fast/issues/646) before launch and supply its actual remaining instances and host-seconds. Preserve prior attempts, failures and charges. The existing cumulative ceilings are 420 run instances and 28,800 host-seconds; this apparatus adds no allowance. The issue's working experiment record owns the finite execution scope. Use the uninstrumented binary and run the archived driver once for the fixed BBR inventory:

```sh
python3 /absolute/path/to/qualification-bundle/ordinary_cost_b5.py \
  --candidate FULL_40_CHARACTER_PRODUCT_SHA \
  --binary /absolute/path/to/qualification-bundle/ordinarycost.test \
  --output /absolute/path/to/new-qualification-results \
  --remaining-instances ACTUAL_REMAINING_INSTANCES \
  --remaining-host-seconds ACTUAL_REMAINING_HOST_SECONDS \
  --timeout-seconds 135 \
  --controller bbrv3
```

Keep the generated bundle, build receipt/log, role outputs, identity, ledger, observations and summary together. Report absolute goodput and CPU values as well as paired ratios. A valid failed threshold remains a failed result; do not repeat until passing. Reconcile actual charges and any approved contamination replacements with program #646 and the OmniFocus task. Public BBR primary/backup remains disabled regardless of this measurement result until the separate owner decision enables it.
