# Issue tracker: GitHub

Issues and PRDs live in GitHub Issues in `GridCastIO/quicquic-go`. Use the `gh` CLI and explicitly pass `--repo GridCastIO/quicquic-go` for issue and PR commands because this checkout also has an upstream remote.

## Conventions

- Create: `gh issue create --repo GridCastIO/quicquic-go --title "..." --body-file <path>`.
- Read: `gh issue view <number> --repo GridCastIO/quicquic-go --json number,title,body,labels,comments` so the body and labels come through with the comments.
- List: `gh issue list --repo GridCastIO/quicquic-go --state open --json number,title,body,labels,comments`, adding appropriate filters.
- Comment: `gh issue comment <number> --repo GridCastIO/quicquic-go --body-file <path>`.
- Apply or remove labels: `gh issue edit <number> --repo GridCastIO/quicquic-go --add-label "..." --remove-label "..."`.
- Sub-issue: `gh issue create --repo GridCastIO/quicquic-go --parent <parent> ...`, or `gh issue edit <parent> --repo GridCastIO/quicquic-go --add-sub-issue <child>` afterwards. Without sub-issues, put `Part of #<parent>` at the top of the child body.
- Blocking: use native GitHub issue dependencies with `gh issue create --repo GridCastIO/quicquic-go --blocked-by <n>,<n> ...` or `gh issue edit <child> --repo GridCastIO/quicquic-go --add-blocked-by <blocker>`. If dependencies are unavailable, use a `Blocked by: #<number>` line at the top of the child body. A ticket is unblocked when every blocker is closed.
- Count open blockers: `gh api repos/GridCastIO/quicquic-go/issues/<n> --jq .issue_dependencies_summary.blocked_by` (open blockers only; 0 means startable). `gh issue view --json blockedBy` also lists closed blockers.
- Close: post the explanation with `gh issue comment <number> --repo GridCastIO/quicquic-go --body-file <path>`, then `gh issue close <number> --repo GridCastIO/quicquic-go`. On an already-closed issue, `gh issue close --comment` drops the comment and still exits 0.

For multiline bodies, write the exact Markdown to a file and use `--body-file`.

## Pull requests as a triage surface

**PRs as a request surface: no.**

External PRs do not enter the issue triage queue. Explicitly requested PR review remains a separate workflow.

GitHub shares issue and PR numbers. When a reference is ambiguous, resolve its type with `gh pr view <number> --repo GridCastIO/quicquic-go`, falling back to `gh issue view` when it is an issue.

## Skill instructions

When a skill says "publish to the issue tracker", create a GitHub issue in this repository. When it says "fetch the relevant ticket", read the issue and its comments.

## Wayfinding operations

- Map: one issue labelled `wayfinder:map`, containing Notes, Decisions-so-far, and Fog.
- Children: GitHub sub-issues (see **Sub-issue** under Conventions) labelled `wayfinder:research`, `wayfinder:prototype`, `wayfinder:grilling`, or `wayfinder:task`. If sub-issues are unavailable, use a task list in the map and a `Part of #<map>` line in each child.
- Blocking: see **Blocking** under Conventions.
- Frontier: list the map's open children, drop any with an open blocker (see **Count open blockers**) or an assignee, and select the first remaining child in map order.
- Claim: assign the ticket to the driving developer.
- Resolve: record the answer, close the ticket, and append a brief finding and link to the map's Decisions-so-far.

Create any missing wayfinding labels when that workflow is first used.
