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

These two BBR ordinary-cost cells remain the affected cost inventory for retained E02 rich-feedback completion and the planned E05 ordinary-native grouping. The source assessment at `7721bd07dcce00e2734fa6b4ef3b0a3fb402ed2b` is conditional on the E05 plan; no completed E05 diff was reviewed when this apparatus was prepared. Final applicability must establish that E05 is unreachable for Reno, unregistered BBR and negotiated multipath, and that its same-call two-buffer request geometry preserves existing native ownership, absolute deadlines, result settlement and shutdown. Under those demonstrated boundaries, the applicable Reno and E6/R21 native receipts can carry forward by an explicit source record. A change to shared completion behavior, native ownership or a common send path widens the affected-case analysis; this helper does not pre-approve that scope.

The combined candidate also revalidates the six existing BBR interop cases using the separate [measurement-only interop apparatus](interop/README.md). E02's BBR rich-completion helper reaches multipath path handlers even though E05 is planned to exclude negotiated multipath. Neither apparatus replaces the exact-head hosted checks or required independent-peer job, and neither enables public BBR multipath.

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
