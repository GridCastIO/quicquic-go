#!/usr/bin/env bash
# Local bundle preparation only; no build, remote job or operational execution.
set -euo pipefail
repo=${1:?read-only repository path required}
qroot=${2:?new absolute output directory required}
product_sha=a1c9442f110cca36cb4752b39ce24ae998d76f05
here=$(cd -- "$(dirname -- "$0")" && pwd)
mkdir "$qroot"
mkdir "$qroot/apparatus"
git -C "$repo" archive "$product_sha" docs/audits/2026-11-14-bbr-ordinary-cost-1368/qualification \
  | tar -xf - -C "$qroot/apparatus"
apparatus="$qroot/apparatus/docs/audits/2026-11-14-bbr-ordinary-cost-1368/qualification"
python3 -B "$apparatus/prepare.py" --repo "$repo" --product-sha "$product_sha" --output "$qroot/ordinary-bundle"
# Interop bundle generation is local only; its image/build must wait until ordinary timing ends.
python3 -B "$apparatus/interop/prepare.py" --repo "$repo" --product-sha "$product_sha" --output "$qroot/interop-bundle"
cp "$here/commands.sh" "$here/receipt.py" "$here/interop-case.sh" "$qroot/"
