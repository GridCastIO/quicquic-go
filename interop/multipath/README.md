# Independent peer control

This maintained fixture implements [R1 (#1021)](https://github.com/the-sarge/quic-go-fast/issues/1021): ordinary QUIC v1 transfer with quic-go-fast in each endpoint role. It does not advertise multipath or stand in for the later interoperability matrix. The transport integration suite owns the fixture; retire it only with equivalent independent coverage or feature removal.

The image pins picoquic `fbd46d9a1f54ebf9397f2ee6355b5019ab379fb7`, its default non-AEGIS PicoTLS `e446233b4100ebcdec60901c05bfb7f4cd369c5d`, Go 1.27.4, the base image digest, and a Debian package snapshot. The build verifies both source revisions and retains installed package identities in `/src/build-packages.txt`. Record the resulting image ID and execution environment with every receipt. This follows the endpoint/build structure in [qoke's MIT-licensed reference](https://github.com/qoke/mp-quic-go/tree/084c13ea3834fbe58cedb63db9208951d714f839/interop/multipath); the ordinary driver and strict accounting are local implementations.

R17 (#1037) recovery updates the independent peer to the merged [upstream scheduling correction (PR #2313)](https://github.com/private-octopus/picoquic/pull/2313). Its selector preserves a paced stream path’s wake deadline when another ready path has no matching stream work. An isolated comparison of the original and corrected selector demonstrates that deadline difference; it does not establish the historical matrix failure’s cause. PicoTLS is updated alongside it to satisfy the peer’s build requirement for disabling Brotli. Earlier peer receipts remain historical, and qualification requires the complete fixed matrix on this new pinned pair.

Run accounting regressions without starting a peer:

```sh
python3 -m unittest discover -s interop/multipath -p 'test_*.py'
```

Before operational execution, reserve the exact candidate, two smoke cases, build/setup cost, timeout and remaining capacity in the [program ledger](../../docs/adr/2026-10-24-multipath-reno-plan.md#candidate-and-run-ledger). Every failed attempt counts. Stop at the first unresolved prerequisite or budget failure; do not repeat until passing. The following commands are a single explicit invocation, not an automatic per-push campaign:

```sh
docker build --platform linux/amd64 -f interop/multipath/Dockerfile -t quic-go-fast-r1 .
docker create --platform linux/amd64 --network none --name quic-go-fast-r1-control quic-go-fast-r1 --output /results
docker start --attach quic-go-fast-r1-control
docker inspect quic-go-fast-r1-control --format '{{.State.ExitCode}}'
docker cp quic-go-fast-r1-control:/results ./r1-results
docker rm quic-go-fast-r1-control
```

Both `TestPicoquicOrdinaryControl/client` and `TestPicoquicOrdinaryControl/server` must execute and pass exactly once. The runner fails for unavailable prerequisites, a nonzero test exit, missing/duplicate cases, or skips. It retains Go JSON and each peer's output. Each role has a 20-second context, Go has a 90-second test timeout, and the outer runner has a 120-second timeout. Processes are canceled and joined before test cleanup finishes. TLS authentication uses a fresh local CA; workload bytes are fixed and compared in full at the receiver. The picoquic process receives no `-M` option. Ordinary public constructors remain unchanged.

The result is example-level evidence over this fixed scenario and toolchain, not universal protocol coverage or native endpoint qualification. Linux amd64 execution under emulation must be recorded as such. The negotiated-zero oracle gap remains for later normative vectors and a controlled peer; no multipath scenario is stubbed or reported as executed here. R14 and R17 own their later scenarios and any dedicated qualification workflow.

## Two-path smoke

[R14 (#1034)](https://github.com/the-sarge/quic-go-fast/issues/1034) adds one fixed two-path STREAM run per role: useful data on both paths, a stream abort and a close, in a `picoquic`-tagged root package test. It grants its sockets with `Transport.ConfigureMultipathIOV1` on Linux amd64 and still drives a few steps through internal helpers. Pass `--smoke` to the runner to select it. Both `TestPicoquicMultipathSmoke/client` and `TestPicoquicMultipathSmoke/server` must execute and pass exactly once. It is example-level evidence, charged to the program ledger, and [R17 (#1037)](https://github.com/the-sarge/quic-go-fast/issues/1037) owns the full matrix.

## Independent interoperability matrix

[R17 (#1037)](https://github.com/the-sarge/quic-go-fast/issues/1037) adds the fixed draft-21 QUIC v1 matrix on Linux amd64 and Go 1.27.4. `peer.c` is an application callback and UDP adapter linked to the same pinned picoquic library. Its commands call that library's APIs; picoquic owns its protocol parsing, protection, recovery and path state. The adapter can hold and replay one opaque UDP packet, map a client's existing path to a replacement socket, blackhole path zero, and impose a 1280-byte UDP payload ceiling on path one. It has no second QUIC implementation. The Go cases use the public V1 config, transport, path and lifecycle APIs on Linux amd64, where [R19 (#1039)](https://github.com/the-sarge/quic-go-fast/issues/1039) enables the profile.

Each row runs once with quic-go-fast as client and once as server. Missing, duplicate, failed or skipped cases fail the aggregate claim. An unsupported peer operation stops qualification; changing the peer pin or substituting a self-to-self exchange requires disposition under the accepted contract.

| Scenario | Observed behavior |
| --- | --- |
| `useful-transfer` | Exact STREAM and DATAGRAM round trips, with useful sent and received payload recorded on paths zero and one. |
| `absent-negotiation` | A locally enabled V1 constructor falls back to an ordinary peer, reports no negotiated paths, refuses `OpenPathV1`, and transfers the fixed workload. |
| `path-zero-ack` | Literal ACK and PATH_ACK vectors both acknowledge packet zero; decoded 1-RTT events identify both forms and useful transfer continues. |
| `key-update-silent-path` | The independent peer applies a public key-rotation request, returns its protected same-stream response, and transfers useful data on path zero while observed path-one packet counts stay unchanged; useful data then resumes on path one. |
| `status-backup-failover` | Backup/available status crosses the wire; useful traffic initially stays off the backup, then survives the original client's endpoint failure or path-zero packet loss through path one. |
| `abandon-reopen-late-feedback` | Path one retires and a new wire ID replaces it. The old encrypted packet is replayed, with decoded, duplicate or retired routing/key-reclamation disposition observed at existing owners; an explicit late PATH_ACK(1) arrives on a live carrier and useful replacement transfer continues. |
| `same-id-migration-rebinding` | A client calls `MigrateV1`, or the independent client undergoes NAT rebinding; wire ID and packet-number continuity survive a changed tuple without adding a third protocol path. |
| `unequal-mtu-invalid-frame` | Path-specific PMTU discovery converges across unequal UDP payload limits; a literal PATH_STATUS_BACKUP for a never-granted ID causes the expected protocol violation. |

The negotiated-zero gap is explicit: the pinned picoquic negotiator requires positive `initial_max_path_id` values and cannot act as the zero oracle. `TestMultipathNegotiatedZeroVectors` checks literal absent, zero and positive transport-parameter vectors in both roles, plus ACK/PATH_ACK(0) vectors through the existing wire parser. `TestMultipathNegotiatedZeroControlledPeer` checks a real self-to-self V1 exchange with both caps set to one, which advertises zero. These are separate normative and controlled evidence; they do not supply any of the 16 independent instances.

Freeze a clean candidate before building. Pass its commit and tree to Docker as `QGF_SOURCE_COMMIT` and `QGF_SOURCE_TREE`, and pass the resulting immutable image ID as `QGF_IMAGE_ID` to every container. The runner records those identities, the primary toolchain, kernel, both peer pins, driver and binary hashes, command, start time and duration. `/src/build-packages.txt` retains installed packages. Preserve the build log, image inspection and all per-case logs, including failed attempts. The scoped owner waiver changes cumulative ceilings, while the finite inventory, venues, accounting and per-invocation timeouts remain binding.

Run one case per invocation, with a fresh output directory. For example, this selects only the path-zero ACK case with quic-go-fast as server:

```sh
python3 -B interop/multipath/run.py --matrix --scenario path-zero-ack --role server --binary /usr/local/bin/qgf-r17-peer --test-binary /src/peer-matrix.test --output /results/path-zero-ack/server
```

After all 16 cases, run the separate zero evidence once, then validate the retained logs and receipts together:

```sh
python3 -B interop/multipath/run.py --zero-vectors --binary /usr/local/bin/qgf-r17-peer --test-binary /src/peer-matrix.test --output /results/negotiated-zero
python3 -B interop/multipath/run.py --validate-matrix --output /results
```

Each role context and the C adapter are bounded at 30 seconds; the Go test timeout remains 90 seconds, the runner remains 120 seconds, and each outer container remains 150 seconds. Build/setup has the inherited 1200-second bound. There is no longer monolithic matrix timeout. A failed operation, unavailable prerequisite or unresolved identity mismatch stops the invocation and retains its evidence; do not repeat until passing. Cancellation kills and joins the runner's process group, and Go cleanup cancels and joins its peer before returning the granted sockets.

Case containers run as the artifact owner's UID/GID with writable temporary HOME and Go cache locations, so retained 0700 peer directories remain readable after success or failure. The unequal-MTU case observes completion on the existing connection-owned finder, because a final lost probe can finish discovery without emitting a qlog Done update; all construction and path/lifecycle operations still use V1 APIs. Useful-traffic assertions wait for asynchronous trace consumption. Replay observations correlate the controlled packet's size with the existing connection/transport reception or drop events in this isolated single-peer case; they make no universal packet-correlation or retention-order claim. ACK(0), PATH_ACK(0), late PATH_ACK(1) and the invalid-path frame are literal controlled vectors protected and packetized by the pinned peer library.

While the unequal-MTU case waits for each selected path's finder, it supplies a fixed 256-byte public E request/response on 100-millisecond ticks, up to 300 exchanges per path under the same shared 30-second role context. Later packet/ACK progress lets the existing recovery owner resolve an in-flight dropped probe; the fixture still reads completion only on the connection owner. Trace notifications recheck completion without emitting traffic, and a timer recheck does not require a particular final qlog event. The serial caller stops its ticker on return; synchronous I/O retains its existing stream deadline. Missing/wrong responses, owner errors, cancellation or the cap fail the case. This fixed-example prerequisite changes no probe/loss/idle timer, PMTU comparison or invalid-frame assertion and does not attribute historical timeouts.

The abandon/reopen case in the Go-client role conditions delivery of the replacement tuple on a positive CID2 processing receipt. The existing typed recorder joins a path-zero 1-RTT CID2-carrying transmission with an authenticated ACK targeting that packet-number space and number, including reordered recorder callbacks and retransmissions. A separate 64-datagram opaque driver gate releases only after that witness, with delivery deferred until the application callback returns; overflow, missing evidence and API errors fail the case. This fixes the example's CID-before-replacement-delivery ordering. It does not query current peer CID inventory, guarantee indefinite CID availability or claim arbitrary packet-reordering interoperability. The Go-server role and the existing held path-one replay/late-feedback oracle retain their original behavior.

The key-update witness combines the pinned public K API completing successfully, its causally later protected OK on that request's fresh stream, authenticated path-zero useful transfer, the existing observed path-one silence window and authenticated path-one resumption. The peer copies OK into its stream queue only after fresh encryption keys are applied, and subsequent packet protection uses the then-current 1-RTT context. Normal automatic updates can advance generations without exposing every intermediate phase bit, so no parity-counter increment is required. This source-dependent example does not enumerate generations or prove complete recorder delivery/in-flight quiescence; the existing packet-count limits remain.

This is example-level evidence for these fixed scenarios, pins and venue. It does not claim universal draft conformance, arbitrary peer support, all key-update directions, Internet failure timing or other platforms. The early ordinary and smoke receipts remain historical evidence. The transport integration suite owns this maintained fixture; retire it only with equivalent independent coverage or feature removal.

The required [independent peer workflow](../../.github/workflows/multipath-interop.yml) executes this fixed inventory on a GitHub-hosted Linux amd64 runner for a ready source PR, checking out its exact head. Draft pushes and documentation-only changes do not start the matrix. It records the actual hosted runner, kernel, native architecture, image and packages and rejects an unexpected self-hosted venue before peer launch. For R17 qualification, this job supplies the original 16 instances; do not run a duplicate manual matrix first. The workflow retains failed setup/case attempts and raw peer/Go JSON as an artifact and stops at the first failure.

## Native Darwin peer profile

[MP-MAC-P1 (#1488)](https://github.com/GridCastIO/quicquic-go/issues/1488) adds an explicit `darwin-native` execution profile for the same picoquic and PicoTLS pins on Darwin arm64. It builds the peer natively, runs the ordinary control in both roles and compiles and lists the root multipath matrix. It executes no multipath case: Darwin public admission stays closed until its qualification slice. The Linux Docker profile remains the default, with unchanged image, toolchain, addresses and peer arguments. The [implementation plan](../../docs/adr/2026-11-19-macos-multipath-implementation-plan.md#p1--native-pinned-peer-build-and-ordinary-control) owns this contract; the transport integration suite owns the fixture.

Build inputs come from explicit caller-owned prefixes. CMake and pkg-config (PicoTLS's CMake requires it to probe Brotli, which picoquic disables) are not system packages here; OpenSSL is read from a prefix with static libraries, so the peer binaries do not load it at run time. A missing tool fails before any fetch. Nothing is installed or changed on the host:

```sh
python3 -B interop/multipath/native_build.py --cmake "$TOOLS/cmake" --pkg-config "$TOOLS/pkg-config" \
  --openssl-root "$OPENSSL_PREFIX" --work "$BUILD"
```

The recipe verifies both source revisions, links both binaries, rejects dynamic OpenSSL linkage, requires both to be exactly arm64, and runs the C adapter's fixed self-test: three explicit loopback tuples bind, and an oversized datagram is reported as truncated through `recvmsg` flags, which Darwin and Linux both provide. It passes the selected SDK to CMake explicitly and requires every compile command to use it. It then writes `build-identity.json` with the platform, compiler, that SDK, CMake, pkg-config and OpenSSL identities, the `peer.c` digest and both binary digests. The runner reads that record back and rejects unknown fields, other pins, another platform, another `peer.c` or an unrecorded binary.

Darwin configures only `127.0.0.1` on loopback without a privileged alias, so its tuples use that address with distinct ephemeral ports, including replacement and migration targets. The Go fixture owns this plan: on Darwin it reserves the adapter's three bind tuples together and passes each exact address and port, plus the replacement address, and the adapter binds exactly those or fails. Linux keeps `127.0.0.1`–`127.0.0.3` and the original seven arguments. On Linux the abandon/reopen tuple gate's address check also proves that the armed tuple is the replacement, because `127.0.0.3` belongs to no other tuple. On Darwin that check cannot separate tuples by address; the gate still matches only the exact armed address and port. The qualification protocol records this difference when it binds native multipath commands. Darwin has no GNU `stdbuf`: the C adapter's output is already unbuffered, and the ordinary demo's readiness is a successful Dial within the role context. Both child processes are still canceled and joined, and both exit statuses are checked.

Compile both test binaries for the candidate and pass its exact commit and tree. Each invocation uses a fresh output directory:

```sh
go test -c -tags=picoquic -o "$BIN/peer-control.test" ./integrationtests/self
go test -c -tags=picoquic -o "$BIN/peer-matrix.test" .
export QGF_SOURCE_COMMIT=$(git rev-parse HEAD) QGF_SOURCE_TREE=$(git rev-parse 'HEAD^{tree}')
python3 -B interop/multipath/run.py --profile darwin-native --binary "$BUILD/picoquic/build/picoquicdemo" \
  --test-binary "$BIN/peer-control.test" --build-identity "$BUILD/build-identity.json" --output "$OUT/ordinary-control"
python3 -B interop/multipath/run.py --profile darwin-native --discover-matrix \
  --test-binary "$BIN/peer-matrix.test" --build-identity "$BUILD/build-identity.json" --output "$OUT/matrix-discovery"
python3 -B interop/multipath/run.py --profile darwin-native --validate-native --output "$OUT"
```

The ordinary control must pass `TestPicoquicOrdinaryControl/client` and `/server` exactly once from the compiled `integrationtests/self` binary. Discovery requires the tagged `darwin/arm64` binary to list exactly `TestPicoquicMultipathMatrix`. Validation reads both receipts back and requires one shared candidate, toolchain and build identity; neither receipt substitutes for the other. The profile refuses `--smoke`, `--matrix`, `--zero-vectors` and `--validate-matrix`. These receipts are example-level development evidence for one host and toolchain, not qualification; the qualification slices select toolchains, venues and executions.

## Native deadline qualification

[E6 (#1020)](https://github.com/the-sarge/quic-go-fast/issues/1020) runs six native classes on real UDP sockets, once each on Go 1.26.11 and 1.27.4: 12 instances. `native_qualification_test.go` in the root package is the fixture, under `//go:build nativequal && linux && amd64`, and `native_qualification.py` is its driver. The transport test suite owns both, and retirement requires equivalent replacement or feature removal.

Run accounting regressions with the discovery command above. Execution needs Linux amd64 with `strace`, `nft`, `ip`, `unshare` and passwordless `sudo`, and it charges the [program ledger](../../docs/adr/2026-10-24-multipath-reno-plan.md#program-qualification-ledger-and-sequencing). This command is one explicit invocation, not a per-push campaign, and it stops at the first failure:

```sh
python3 interop/multipath/native_qualification.py --candidate "$(git rev-parse HEAD)" --output /path/to/new/results
```

`EAGAIN-to-deadline`, `retry-fallback` and `queued-expiry` run under strace. Their timing is attributed separately and never compared to the 20 ms tolerance. The other three classes are uninstrumented and are compared to it. The GSO `EIO` in `retry-fallback` is simulated by a test wrapper, because this kernel gave no real trigger. Everything after it is native. See the [re-audit](../../docs/audits/2026-11-03-e6-native-qualification-reaudit.md) for the method and the receipt for the executed identities.

## Native Darwin granted scalar fixture

[MP-MAC E1 (#1485)](https://github.com/GridCastIO/quicquic-go/issues/1485) adds `TestNativeDarwinScalar` in the root package (`native_darwin_fixture_test.go`, `//go:build darwin`) and its case runner `native_darwin.py`. The fixture reaches the real private write grant on loopback sockets. For IPv4-only, IPv6-only and a dual-stack socket's mapped IPv4 and native IPv6 delivery, it reads a CE-marked datagram on the granted socket with its source, packet-info destination and interface, then sends an ECT(0) reply through the granted writer, passing that packet info as control data, checks that the peer sees the granted address and port, and joins. It also checks repeated, held-socket, connected-socket and send-thread-QoS grant refusals, and that write and deadline authority return to the caller after the join. Without `NATIVE_DARWIN_RECORD` the cases are ordinary Darwin development tests and write nothing.

The runner requires native Darwin arm64 (Rosetta is refused). It builds one test binary for the requested `--toolchain` (default `local`) with `CGO_ENABLED=0`, `GOARCH=arm64` and `-buildvcs=false`, records the source commit, the built working tree's hash (taken before any output exists) and whether it equals HEAD's tree, and refuses a build that reads a main-module file, as `go list` reports the test build's inputs, that the recorded tree omits. It also records the toolchain, build mode, binary hash and native identity, and runs each case once in its own process group under a timeout, killing and reaping the group on timeout. A missing, duplicate, unknown, skipped, failed, unrecorded or mismatched case, or a case record whose socket tuples contradict its family, fails the run; it stops at the first failure and writes a status only for a complete passing run, then reads its `results.json` back against one declared results shape. `--validate RESULTS` repeats that readback.

```sh
python3 interop/multipath/native_darwin.py --output /path/to/new/results
```

A passing run is ordinary local smoke evidence for the endpoint method (`support_receipt: false`), not qualification or a support receipt. Native timing, pressure and exact-candidate family/metadata/ECN receipts are bound by later MP-MAC slices. The transport test suite owns the fixture and runner; retire them with equivalent replacement or removal of the Darwin support profile, preserving accepted receipts.

### Scalar contention and socket-pressure observation

[MP-MAC E3 (#1487)](https://github.com/GridCastIO/quicquic-go/issues/1487) adds the `scalar-contention` case to `TestNativeDarwinScalar` and the bounded socket-pressure observation `TestNativeDarwinPressure` (`native_darwin_contention_test.go`, `native_darwin_pressure_test.go`). Both start the endpoint's real writer on a real unconnected loopback socket through an observer that delegates every write and deadline call and keeps bounded aggregates, so it never blocks the writer. One producer per participant offers scalar requests on its two path lanes and its control lane. The record keeps each lane's offers, admissions, capacity refusals, closures, results, withdrawals, accepted/uncertain/unsubmitted datagrams, failed results, publication diagnostics, peak occupancy and longest time from a natively attempted member's return to the producer taking its result (an upper bound on the time to publication; a native size error counts as attempted, and work that ended locally adds no sample); each participant's peak occupancy and whether every participant finished inside the window; the writer's native writes, longest write, writes over the endpoint tolerance, errors by class (`enobufs`, `eagain`, `emsgsize`, `deadline`, `other`) and pressure waits; dropped diagnostics; and any endpoint fault. Every producer is joined, then the writer, before the sockets close; the diagnostic sink runs outside the writer's fence, so the fixture then waits up to the endpoint tolerance for its backlog, which touches only the fixture's counts. The endpoint's admission, fairness and result classification still own the behavior.

A pressure wait is a native write entered before its write deadline that returned a timeout; a deadline that passes between entry and the socket's own check also counts, so an observed wait is example-level evidence. A complete observation without one reports `pressure_wait: not-observed`, a valid negative. A dropped or undelivered diagnostic makes the observation `incomplete-coverage`, and a load that some participant didn't finish within its window, or whose endpoint closed or faulted, is `interrupted`, even if its last results were drained during cleanup; both report `unknown` instead of a negative. Immediate local errors such as ENOBUFS are counted as errors, not waits. The runner recomputes status and pressure result from the recorded facts and rejects a record whose lane, datagram or writer counts don't add up, or whose observed pressure wait has no uncertain member in a failed result while nothing was withdrawn. The `scalar-contention` development case must be complete and fault-free with progress on every lane; it asserts nothing about native pressure.

The pressure observation builds only with the `native_pressure` tag, so default development tests never launch it. `--profile pressure` builds with that tag and runs its one case once with no retry; its results (schema `native-darwin-run/v2`, which added the profile and the contention case) record the profile and build mode:

```sh
python3 interop/multipath/native_darwin.py --profile pressure --output /path/to/new/results
```

Synthetic development tests over a gated native side (`TestNativeDarwinContentionAccounting`, `TestNativeDarwinContentionObservations`) show real progress, refused lanes, immediate ENOBUFS, a pressure wait, missing observer coverage, a valid negative result, cleanup of an interrupted load, a faulted endpoint, a load finished outside its window and native-return timing. Whether a native pressure wait occurs is unknown until the protocol that Q1 binds runs its attempts; this observation is not E2's induced blocked-writer traversal.

## Aggregation comparison and BBR revalidation (retired)

[B5 (#1044)](https://github.com/the-sarge/quic-go-fast/issues/1044) measured the [controller-matched aggregation arms](../../docs/adr/2026-10-24-multipath-bbr-plan.md#controller-matched-aggregation-arms) and revalidated BBR primary/backup; its [receipt](../../docs/audits/2026-11-14-multipath-b5-receipt.md) records the results. [B6 (#1045)](https://github.com/the-sarge/quic-go-fast/issues/1045) published the outcome in the [support record](../../docs/audits/2026-11-14-multipath-b6-support.md) and retired these fixtures with the private evidence selection they ran through. The aggregation workload and driver (`aggregation_test.go`, `aggregation.py`) and the `--controller bbrv3` options of `run.py` and `ordinary_cost.py` remain at [`e048181a6`](https://github.com/the-sarge/quic-go-fast/tree/e048181a680f07dc7560f7df1667d8c065513583/interop/multipath). A later qualification adds its own fixture under its accepted plan.

`ordinary_cost.py --revalidate-cell CELL --cause TEXT` still reruns only the named Reno cells, for an existing cell that a later source change affects. The run records the cause in its identity and charges the reserve of the [program ledger](../../docs/adr/2026-10-24-multipath-reno-plan.md#program-qualification-ledger-and-sequencing).

## Experimental BBR primary/backup

[B9 (#1382)](https://github.com/the-sarge/quic-go-fast/issues/1382) restores `run.py --controller bbrv3` for exactly `useful-transfer`, `abandon-reopen-late-feedback` and `same-id-migration-rebinding`, each client/server. Pass the option to each `--matrix` invocation and to `--validate-matrix`; use a fresh results root. The fixture selects BBR with the public Config setter and reaches the ordinary public admission gate, with no product overlay. Per-case receipts bind the selected controller and exact candidate/build/kernel identity; the aggregate rejects missing, duplicate or mismatched cases. Timeouts and peer pins are unchanged.

The default remains Reno with the existing 16-case matrix and separate negotiated-zero evidence, including the required hosted job. BBR's six cases are a bounded primary/backup witness, not aggregate or full BBRv3 qualification. The [B9 support record](../../docs/audits/2026-11-15-bbr-b9-support.md) distinguishes the exact accepted ordinary-cost exceptions from raw failed verdicts. Historical B5 apparatus and receipts remain frozen.

## Experimental BBR aggregate

[B12 (#1385)](https://github.com/the-sarge/quic-go-fast/issues/1385) adds explicit public aggregate execution to the same six BBR cases. Pass `--controller bbrv3 --policy aggregate` to each `--matrix --scenario SCENARIO --role ROLE` invocation and to `--validate-matrix`, using a fresh results root. Aggregate requires BBR and the fixed matrix; receipt validation rejects mismatched policies. The default policy remains primary/backup, preserving B9 (#1382)'s historical primary/backup witness and the default hosted Reno inventory.

The aggregate useful-transfer case adds one bounded phase that activates both live paths, snapshots sent STREAM traffic after activation and requires new useful traffic on both while both remain active. DATAGRAM checks remain; lifecycle cases keep their deliberate per-path preference. The [B12 support record (#1385)](../../docs/audits/2026-11-15-bbr-b12-support.md) owns this finite aggregate witness, which is not full BBR qualification or a universal performance promise.

[B11 (#1384)](https://github.com/the-sarge/quic-go-fast/issues/1384) reintroduced a finite comparison runner for the replacement policy; [its positive receipt](../../docs/audits/2026-11-15-bbr-b11/README.md) preserves all raw evidence and limitations. B12 (#1385) retires that executable runner and private activation after publication. The measured fixture/driver remain in Git history at [`8c34fbac8`](https://github.com/the-sarge/quic-go-fast/tree/8c34fbac874adf55f096b6c67d51244160169422/interop/multipath); they are not maintained execution dependencies. Historical B5 evidence remains unchanged.
