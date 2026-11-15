# Measurement-only BBR interoperability revalidation (#1368)

This apparatus restores the six existing B5 cases for the combined candidate of [BBR ordinary-flow cost (#1368)](https://github.com/the-sarge/quic-go-fast/issues/1368). It changes no product source in the checkout and adds no public BBR multipath selector. Unoverlaid refusal tests remain authoritative. The [B5 receipt (#1044)](../../../2026-11-14-multipath-b5-receipt.md#bbr-primarybackup-revalidation) and [program applicability rule](../../../../adr/2026-10-24-multipath-bbr-plan.md#program-budget-and-prior-evidence-validity) own the inventory; this apparatus adds no cases, thresholds or allowance.

The inventory is `useful-transfer`, `abandon-reopen-late-feedback` and `same-id-migration-rebinding`, each with quic-go-fast as client and server, on BBR primary/backup: six observations. The separate required hosted independent-peer job still runs its 16 Reno cases and zero evidence on the final ready PR head. These six cases do not replace that job or qualify public BBR support.

## Frozen driver, scenario timeline and overlay

`run_b5.py` is byte-for-byte `interop/multipath/run.py` at `4e80d3cf4fa7454ffc3e2a46655afd5f81f86313`, SHA-256 `7de31bd73bfb026c7aa24989139fd38032c5caac730498f4967c3b5dde4c1990`. Its controller, exact-case, failure/skip, identity and aggregate checks are unchanged. The original 30-second role context, 90-second Go timeout, 120-second driver timeout and 150-second outer container timeout remain. It requires `peer.c` beside itself to hash the adapter; the generator supplies the exact historical bytes.

`prepare.py` reads the supplied full product commit through Git, checks exact source hashes and unique replacement snippets, and emits a source archive, complete file inventory, original/replacement hashes, overlay diff and build/driver identities. The matrix source is pinned at SHA-256 `d81d1e4fc5b574bd4f0fcd5de03c916168fa2e02b53602a8268f411cd90f971b` before overlay. The generated matrix must equal historical B5 matrix SHA-256 `270dbdd71a42e5622217b9fa33fc12c4a32d467a19e05b8f9e0a38bf8a227ccb` after removing only the retired private evidence assignment and its two comment lines. Thus scenario actions, timing, payloads, role order, lifecycle and oracles retain their historical bytes. Trace/oracle/peer helpers and the Dockerfile are separately pinned and must equal B5. A mismatch stops generation for explicit applicability review.

| Overlaid source | Exact measurement-only footprint |
| --- | --- |
| `multipath_api.go` | Allow Reno or BBR at the controller admission check; preserve all other platform, version, path-count, policy, CID, socket, grant and I/O gates. |
| `multipath_picoquic_matrix_test.go` | Restore the historical environment controller helper, select that controller on the fixture Config and assert the established connection's actual identity. Do not restore `multipathEvidence` or its Config assignment. |

No emission, feedback, scheduler, endpoint owner or support-document source is overlaid. The image is built from the unmodified product archive using the unchanged Dockerfile; only the separately compiled measurement test binary uses the Go overlay. `build.py` checks the complete extracted source inventory and bundle hashes, requires the pinned native Linux amd64 Go version and matching image source identity, then records the exact command, overlay, image, peer and resulting test-binary hashes. Failed builds keep their logs and receipts; preserve an interrupted build's log and use a fresh bundle. This is preparation, not evidence that a case ran.

## Preparation and build

Run the apparatus-only tests without launching a peer:

```sh
python3 -B -m unittest discover -s docs/audits/2026-11-14-bbr-ordinary-cost-1368/qualification/interop -p 'test_*.py'
```

After the final source applicability review, generate a fresh bundle from the exact committed candidate. Here `product_sha`, `bundle`, `source` and `results` are explicit caller-selected values; source and results must be new directories outside the repository.

```sh
python3 docs/audits/2026-11-14-bbr-ordinary-cost-1368/qualification/interop/prepare.py \
  --repo /absolute/path/to/quic-go-fast --product-sha "$product_sha" --output "$bundle"
mkdir "$source"
tar -xf "$bundle/source.tar" -C "$source"
```

Minimax's native Linux amd64 venue uses rootless Podman 5.7.0, as recorded by the frozen [B5 host command (#1044)](../../../2026-11-14-multipath-b5/b5-host.sh) and [venue receipt (#1044)](../../../2026-11-14-multipath-b5/venue.txt). Retain setup attempts and charge occupied host time under the existing [program ledger (#646)](https://github.com/the-sarge/quic-go-fast/issues/646). Build the unchanged pinned Dockerfile from the exact extraction, recording the source tree from the manifest. The build retains the original 1200-second bound. Do not substitute an unverified cached image or an earlier product candidate.

```sh
set -euo pipefail
product_tree=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["product_tree"])' "$bundle/manifest.json")
timeout 1200s podman build --platform linux/amd64 -f "$source/interop/multipath/Dockerfile" \
  --build-arg QGF_SOURCE_COMMIT="$product_sha" --build-arg QGF_SOURCE_TREE="$product_tree" \
  -t qgf-bbr-interop-1368 "$source" 2>&1 | tee "$bundle/image-build.log"
podman image inspect qgf-bbr-interop-1368 > "$bundle/image-inspect.json"
image_digest=$(podman image inspect qgf-bbr-interop-1368 --format '{{.Id}}')
image_id="sha256:${image_digest#sha256:}"
test "$(podman image inspect "$image_id" --format '{{.Architecture}}')" = amd64
printf '%s\n' "$image_id" > "$bundle/image-id.txt"
container=$(podman create "$image_id")
podman cp --archive=false "$container:/src/build-packages.txt" "$bundle/build-packages.txt"
podman rm "$container"
timeout 1200s podman run --rm --platform linux/amd64 --network none \
  -e QGF_IMAGE_ID="$image_id" -e PYTHONDONTWRITEBYTECODE=1 \
  -v "$source:/product:ro" -v "$bundle:/bundle" \
  --entrypoint python3 "$image_id" /bundle/build.py --bundle /bundle --source /product
```

Podman reports a bare image digest on this venue; the normalization supplies exactly one `sha256:` prefix to `QGF_IMAGE_ID`, matching the unchanged build helper and driver's identity checks. The package receipt copy uses the invoking host user's ownership. The overlay build runs as root inside the default rootless user namespace, which maps to the invoking host user and can write the bundle. It retains the image's populated `/go` module cache and build environment for the network-disabled build. The case containers below instead retain B5's `--userns=keep-id` so their output files belong to the invoking host user.

The recorded test build is `go test -overlay=/bundle/overlay.json -tags picoquic -c -o /bundle/peer-matrix.test .`, in `/product`. It compiles but does not run peer scenarios. The unchanged image build performs its existing fixture unit checks and compiles the public unoverlaid binaries. The mounted source stays byte-exact. Keep `build-receipt.json`, `build.log`, `manifest.json`, `overlay.patch`, image inspection, package identities and the image ID together.

## Six existing observations

The root executor owns pre-launch reconciliation and charging for every attempt; the historical driver does not maintain the cumulative program ledger. Use the existing finite six-case inventory and the live remaining allowance. No duplicate manual Reno matrix, new semantic cell, pass-seeking retry or uncharged setup is authorized here. Stop at the first unexplained prerequisite or case failure, retaining all attempts.

For each scenario in the listed order and each role in `client server`, create a fresh child container and output directory. The following is one explicit case template, not an automatic rerun loop. Set `scenario` and `role` to the scheduled case; use the same immutable image and measurement binary for all six. The source/bundle mount paths match the build. Record each container inspection even when its command fails, remove the container after inspection, and charge actual duration before continuing.

```sh
mkdir -p "$results/$scenario"
container=$(podman create --platform linux/amd64 --network none --userns=keep-id \
  -e QGF_IMAGE_ID="$image_id" -e PYTHONDONTWRITEBYTECODE=1 \
  -e HOME=/tmp -e GOCACHE=/tmp/go-build -e GOPATH=/tmp/go \
  -v "$source:/product:ro" -v "$bundle:/bundle:ro" -v "$results:/results" \
  --entrypoint python3 "$image_id" /bundle/run_b5.py \
  --binary /usr/local/bin/qgf-r17-peer --test-binary /bundle/peer-matrix.test \
  --controller bbrv3 --matrix --scenario "$scenario" --role "$role" \
  --output "/results/$scenario/$role")
status=0
timeout 150s podman start --attach "$container" > "$results/$scenario/$role.container.log" 2>&1 || status=$?
podman inspect "$container" > "$results/$scenario/$role.container-inspect.json"
container_status=$(podman inspect "$container" --format '{{.State.ExitCode}}')
podman rm -f "$container"
test "$status" = 0
test "$container_status" = 0
```

After all six charged observations pass, aggregate the receipts without running another peer:

```sh
python3 -B "$bundle/run_b5.py" --controller bbrv3 --validate-matrix --output "$results"
```

The aggregate must report exactly six successful BBR cases with one candidate/tree/image/toolchain/kernel/peer/test/driver identity. Compare its `test_binary_sha256`, `peer_binary_sha256`, candidate, tree and image to the build receipt before claiming qualification. Preserve the raw Go JSON, peer logs, attempts and per-case results alongside the aggregate. Performance qualification remains the separate fixed 12-observation ordinary-cost comparison.

## Applicability for the combined candidate

The [combined candidate applicability record](../../candidate-applicability.md) pins E02 + E06 + E08 + E09 at audited source `96b57b83ad33473f194d2d39969a8f5ab41fe5f5` and integrated native source `76f64bd9418bcf403c6b0eaecdffc69ca611073c`; documentation base `872af89701460a94fcde7861fb156321bb2d9afa` has identical Go source/tests and module files. E05's two-buffer grouping is absent. E06/E08 select only ordinary native BBR with current M ≤ 1,452, the local sender as queue, no multipath registry and no selected route. E08's whole-packet [M,N] admission and minimum-M rearming therefore do not change multipath path-view readiness or its exact reservation. The shared successful-reservation bookkeeping is extracted unchanged; the exact-operation oracle remains applicable to excluded paths.

E02 and E09 both reach eligible concrete BBR path handlers, so the combined candidate still revalidates these six existing BBR cases. E09's accepted-member helper has no ordinary-only or current-packet-size gate; it checks every owner/epoch/history and live current-generation rich identity before mutation, preserves per-packet authority/ECN/empty-feedback transitions and declines unsafe members to ordered scalar completion. Late feedback after abandonment/reopen and same-ID migration/rebinding therefore remain directly applicable. Public admission, native owners, packet geometry and credit retirement are unchanged. Reno retains the factored helper's semantics under existing scalar/native equivalence tests, without a claim of identical machine code or measured CPU cost; the scoped Reno/E6/R21 carry remains separate from final ready-head checks.

This apparatus's source, exact overlay snippets, scenario timeline, peer/build pins and frozen driver are unchanged and remain applicable to the audited/native source. No native execution follows from that source check. The earlier [E06 source assessment](../../e06-applicability.md) remains frozen at its own source pin, including its geometry limits. The existing six-case inventory, commands, timeouts and accounting are unchanged.

**Final six-case BBR interoperability qualification: NOT RUN; combined acceptance: NOT MET; E10 attribution: PENDING.** The [valid E09 second-window diagnostic](../../e09-window2-timing/summary.json) and [independent raw audit](../../e09-window2-independent-audit.json) record goodput ratio `0.9693330897326472` passing and CPU/useful-byte ratio `1.1569072171177908` as the only failed check. E09 is provisionally retained alongside E06+E08; the contaminated attempts remain excluded. The [E10 plan](../../../2026-11-14-bbr-ordinary-cost-1368-experiments.md#e10--measure-current-accepted-member-coverage-and-cpu-attribution) now calls for current-source coverage/profile attribution, with all instrumented timing excluded from acceptance. Local/native mechanism tests, that attribution and a single valid diagnostic pair do not replace final qualification.

The final receipt must identify the actual final runtime/test source, fresh build and six executions, alongside the separate 12-observation cost comparison and mandatory exact-head hosted checks. The hosted independent-peer job still supplies its 16 Reno cases and separate zero evidence. Applicable Reno and E6/R21 observations are carried only within their original tested domain; they do not establish fresh timing for larger protected members. Public BBR primary/backup stays refused. No new case, gate or budget is introduced.
