# Task-local RAS compatibility build for quic-go-fast #1368

This executable is an isolated tooling accommodation for the task’s later full-panel RAS review. Its source is commit `d66c51d35e0f295345316e843c7bb40e18ca1e3b` on `codex/bbr-review-tool-1368`, based on `de615a0d2175b0187e5e1d8db8a9dfdc492d91a4`. The owned source worktree is `/Volumes/worktrees/bbr-review-tool-1368/ras`. The installed `/Users/josh/.local/bin/ras` and global configuration were not changed. No push, RAS issue, or RAS pull request was created.

New configured-root `review` and `verify` allocations use `<root>/<task-slug>/<repository-basename>`. With the existing root, a quic-go-fast reviewer receives `/Volumes/worktrees/ras-review-<reviewer-label>-<identity-hash>/quic-go-fast`. The bounded task component retains repository identity, operation kind, execution ID, and full reviewer slot in its hash. Owner ID remains separate authority and cannot evade a reservation collision. Recorded locations and empty-root legacy locations return before this path selection; other operation kinds keep their previous layout.

The production change is confined to `internal/worktreeplacement/placement.go`. The durable registry, ownership markers, setup release, removal and missing-worktree reconciliation logic remain unchanged. Cleanup removes the exact owned worktree and reservation, then only its empty immediate task directory. The configured root and any unowned siblings survive. Tests cover those cases, linked-checkout identity, cross-store collisions, retained old layouts, invalid repository leaves, and other workflow layouts.

All four affected test suites passed: worktree placement, cleanup, review rounds, and runner. Vet passed for the same packages. The exact commands, source archive hash, binary hash, and clean embedded VCS identity are in `build-receipt.json`; `build-info.txt` records Go’s embedded binary metadata.

After independent review of the pinned source, invoke the executable by its absolute path from the intended review checkout, preserving the existing full-panel configuration:

```sh
/Volumes/worktrees/bbr-review-tool-1368/artifacts/ras review <PR-URL> --prompt-file <absolute-review-brief>
```

No agent, profile, context, timeout, or budget override is needed. The build was not installed globally, and the builder has not launched a RAS review or verification.
