#!/usr/bin/env bash
# Prepared only. Each explicit phase runs sequentially when the root executes it.
set -euo pipefail
product_sha=a1c9442f110cca36cb4752b39ce24ae998d76f05
phase=${1:?phase required}
qroot=${2:?absolute fresh qualification root required}
remaining_instances=${3:?current remaining instances required}
remaining_seconds=${4:?current remaining host-seconds required}
here=$(cd -- "$(dirname -- "$0")" && pwd)
ordinary_bundle="$qroot/ordinary-bundle"
ordinary_source="$qroot/ordinary-source"
interop_bundle="$qroot/interop-bundle"
interop_source="$qroot/interop-source"
record() {
    local name=$1 instances=$2 reserve=$3
    shift 3
    python3 "$here/receipt.py" --receipt "$qroot/receipts/$name.json" \
      --instances "$instances" --remaining-instances "$remaining_instances" \
      --remaining-host-seconds "$remaining_seconds" --reserve-host-seconds "$reserve" -- "$@"
}
case "$phase" in
ordinary-setup)
    record ordinary-setup 0 0 bash -eu -c '
      bundle=$1; source=$2
      mkdir "$source"
      tar -xf "$bundle/source.tar" -C "$source"
      env CGO_ENABLED=0 GOOS=linux GOARCH=amd64 GOAMD64=v1 GOEXPERIMENT= GOFLAGS= GOENV=off GOWORK=off GOTOOLCHAIN=local \
        python3 "$bundle/build.py" --bundle "$bundle" --source "$source"
    ' bash "$ordinary_bundle" "$ordinary_source"
    ;;
ordinary-run)
    # This ledger alone owns observations and occupied time; do not also charge wall time including quiet waits.
    python3 "$ordinary_bundle/ordinary_cost_b5.py" --candidate "$product_sha" \
      --binary "$ordinary_bundle/ordinarycost.test" --output "$qroot/ordinary-results" \
      --remaining-instances "$remaining_instances" --remaining-host-seconds "$remaining_seconds" \
      --timeout-seconds 135 --controller bbrv3
    ;;
interop-image)
    record interop-image 0 1200 bash -eu -c '
      bundle=$1; source=$2; sha=$3
      mkdir "$source"
      tar -xf "$bundle/source.tar" -C "$source"
      tree=$(python3 -c '\''import json,sys;print(json.load(open(sys.argv[1]))["product_tree"])'\'' "$bundle/manifest.json")
      timeout 1200s podman build --platform linux/amd64 -f "$source/interop/multipath/Dockerfile" \
        --build-arg QGF_SOURCE_COMMIT="$sha" --build-arg QGF_SOURCE_TREE="$tree" -t qgf-bbr-interop-1368 "$source" > "$bundle/image-build.log" 2>&1
      podman image inspect qgf-bbr-interop-1368 > "$bundle/image-inspect.json"
      digest=$(podman image inspect qgf-bbr-interop-1368 --format "{{.Id}}")
      image_id="sha256:${digest#sha256:}"
      test "$(podman image inspect "$image_id" --format "{{.Architecture}}")" = amd64
      printf "%s\n" "$image_id" > "$bundle/image-id.txt"
      container=$(podman create "$image_id")
      trap '\''podman rm -f "$container" >/dev/null'\'' EXIT
      podman cp --archive=false "$container:/src/build-packages.txt" "$bundle/build-packages.txt"
    ' bash "$interop_bundle" "$interop_source" "$product_sha"
    ;;
interop-build)
    image_id=$(cat "$interop_bundle/image-id.txt")
    record interop-build 0 1200 timeout 1200s podman run --rm --platform linux/amd64 --network none \
      -e QGF_IMAGE_ID="$image_id" -e PYTHONDONTWRITEBYTECODE=1 \
      -v "$interop_source:/product:ro" -v "$interop_bundle:/bundle" \
      --entrypoint python3 "$image_id" /bundle/build.py --bundle /bundle --source /product
    ;;
interop-case)
    scenario=${5:?scenario required}; role=${6:?role required}
    case "$scenario" in useful-transfer|abandon-reopen-late-feedback|same-id-migration-rebinding) ;; *) exit 2;; esac
    case "$role" in client|server) ;; *) exit 2;; esac
    record "interop-$scenario-$role" 1 150 bash "$here/interop-case.sh" "$qroot" "$scenario" "$role"
    ;;
interop-aggregate)
    record interop-aggregate 0 0 python3 -B "$interop_bundle/run_b5.py" --controller bbrv3 --validate-matrix --output "$qroot/interop-results"
    ;;
*) printf 'Unknown phase: %s\n' "$phase" >&2; exit 2;;
esac
