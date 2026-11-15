#!/usr/bin/env bash
set -euo pipefail
root=/tmp/qgf-b9-1382-peer
scenario=$1
role=$2
image=$(podman image inspect qgf-b9-1382 --format '{{.Id}}')
image="sha256:${image#sha256:}"
mkdir -p "$root/results/$scenario"
container=
cleanup() {
  if test -n "$container"; then
    podman inspect "$container" > "$root/results/$scenario/$role-container.json"
    podman rm -f "$container" >/dev/null
  fi
}
trap cleanup EXIT
container=$(podman create --platform linux/amd64 --network none --cpuset-cpus=4-7 \
  -e QGF_IMAGE_ID="$image" -e PYTHONDONTWRITEBYTECODE=1 -e GOMAXPROCS=4 \
  -v "$root/results:/results" "$image" \
  --binary /usr/local/bin/qgf-r17-peer --test-binary /src/peer-matrix.test \
  --controller bbrv3 --matrix --scenario "$scenario" --role "$role" \
  --output "/results/$scenario/$role")
timeout 150s podman start --attach "$container" > "$root/results/$scenario/$role-container.log" 2>&1
test "$(podman inspect "$container" --format '{{.State.ExitCode}}')" = 0
