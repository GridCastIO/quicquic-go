#!/usr/bin/env bash
set -euo pipefail
qroot=$1; scenario=$2; role=$3
bundle="$qroot/interop-bundle"; source="$qroot/interop-source"; results="$qroot/interop-results"
image_id=$(cat "$bundle/image-id.txt")
mkdir -p "$results/$scenario"
test ! -e "$results/$scenario/$role"
container=
cleanup() {
    local status=$?
    trap - EXIT
    if [[ -n "$container" ]]; then
        podman inspect "$container" > "$results/$scenario/$role.container-inspect.json" || status=1
        podman rm -f "$container" >> "$results/$scenario/$role.container-cleanup.log" 2>&1 || status=1
    fi
    exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT TERM
container=$(podman create --platform linux/amd64 --network none --userns=keep-id \
  -e QGF_IMAGE_ID="$image_id" -e PYTHONDONTWRITEBYTECODE=1 \
  -e HOME=/tmp -e GOCACHE=/tmp/go-build -e GOPATH=/tmp/go \
  -v "$source:/product:ro" -v "$bundle:/bundle:ro" -v "$results:/results" \
  --entrypoint python3 "$image_id" /bundle/run_b5.py \
  --binary /usr/local/bin/qgf-r17-peer --test-binary /bundle/peer-matrix.test \
  --controller bbrv3 --matrix --scenario "$scenario" --role "$role" \
  --output "/results/$scenario/$role")
printf '%s\n' "$container" > "$results/$scenario/$role.container-id.txt"
status=0
timeout 150s podman start --attach "$container" > "$results/$scenario/$role.container.log" 2>&1 || status=$?
container_status=$(podman inspect "$container" --format '{{.State.ExitCode}}')
test "$status" = 0
test "$container_status" = 0
