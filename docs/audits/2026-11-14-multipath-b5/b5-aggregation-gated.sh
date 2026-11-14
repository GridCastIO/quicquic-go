#!/usr/bin/env bash
# B5 #1044: the aggregation campaign on the gated candidate, after the uncounted
# diagnosis ruled the fixture out and the driver's admission gate was fixed. It
# builds the aggregation binary from the exact candidate archive, waits for the
# shared host's named CI processes and VMs to stay absent for five minutes, then
# runs the driver once against the remaining ledger. Nothing on the host is paused.
set -euo pipefail
[ $# -eq 5 ] || { echo "usage: $0 CANDIDATE_SHA ARCHIVE OUTPUT_DIR REMAINING_INSTANCES REMAINING_HOST_SECONDS" >&2; exit 2; }
candidate=$1 archive=$2 out=$3 remaining_instances=$4 remaining_host_seconds=$5
[[ $candidate =~ ^[0-9a-f]{40}$ ]] || { echo "candidate must be a full SHA" >&2; exit 2; }
[ ! -e "$out" ] || { echo "output $out exists" >&2; exit 2; }
mkdir -p "$out/src"
exec >> "$out/host.log" 2>&1
tar -xzf "$archive" -C "$out/src"
sha256sum "$archive" > "$out/source-archive.sha256"
setup_begun=$(date +%s.%N)
(cd "$out/src" && CGO_ENABLED=0 GOAMD64=v1 go test -c -tags aggregation -o "$out/aggregation.test" .)
setup_seconds=$(echo "$(date +%s.%N) - $setup_begun" | bc)
sha256sum "$out/aggregation.test"
echo "setup_seconds $setup_seconds"
pattern='[R]unner.Worker|[t]ransfer.test|qemu.*guest=[i]nfra-garm|[n]ativerig'
quiet=0
while [ "$quiet" -lt 300 ]; do
	if pgrep -f "$pattern" > /dev/null; then quiet=0; else quiet=$((quiet + 15)); fi
	sleep 15
done
echo "$(date -u +%FT%TZ) host quiet for 300 s; starting"
left_seconds=$(echo "$remaining_host_seconds - $setup_seconds" | bc)
status=0
python3 -B "$out/src/interop/multipath/aggregation.py" \
	--candidate "$candidate" --binary "$out/aggregation.test" \
	--output "$out/aggregation" --remaining-instances "$remaining_instances" \
	--remaining-host-seconds "$left_seconds" --timeout-seconds 120 || status=$?
echo "$(date -u +%FT%TZ) aggregation exit $status"
