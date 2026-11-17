# Upstream advisories and Go compatibility

This runbook applies the independent maintenance policy settled in [#651](https://github.com/the-sarge/quic-go-fast/issues/651#issuecomment-6563772122) and recorded in [ADR 0015](../adr/0015-independent-maintenance.md). Joshua Sargent owns security triage, Go compatibility, disclosure, release timing and consumer notification unless he explicitly delegates them. Agents monitor sources, assess applicability and prepare fixes and evidence. Security response is best effort, with no fixed response-time commitment. This runbook adds no review panel, gate or budget, and authorizes no automatic merge, release, third-party notification or consumer cutover.

## Sources and cadence

Check these sources daily:

- [Upstream quic-go security advisories](https://github.com/quic-go/quic-go/security/advisories) and [releases](https://github.com/quic-go/quic-go/releases).
- [Go security announcements](https://go.dev/doc/security/policy#receiving-security-updates) and [Go release history](https://go.dev/doc/devel/release), including detection of the first release candidate of each new Go release.
- The existing daily [`govulncheck` workflow](../../.github/workflows/govulncheck.yml), as an additional signal; see [scanner identity limits](#scanner-identity-limits).

A daily check is a monitoring cadence, not a response deadline. Notify Josh when a new or changed item needs assessment, when monitoring fails, or when a supported Go toolchain leaves Go's security-support window. Do not send routine no-change notifications.

## Procedure

1. **Assess the actual code.** Record:
   - the source advisory or release;
   - the upstream commits that fix it, where available;
   - the project versions that may be affected;
   - evidence of applicability to this source;
   - remaining uncertainty.

   Do not infer safety from an upstream version range, a clean cherry-pick or a clean scanner result alone. Escalate potentially exploitable findings to Josh promptly.
2. **Handle privately where needed.** Unpublished vulnerability details, reproductions, investigation and patch preparation stay private: the applicability review is returned to Josh, not committed, posted or summarized with specifics in public issues. Public tracking holds only information that can be disclosed. Josh controls disclosure and consumer notification.
3. **Prepare an applicable fix.** Use a minimal cherry-pick or hand-port, record the adaptation rationale and upstream provenance, and add regression coverage. Use the existing review process and applicable validation.
4. **Validate Go releases.** Starting at the first release candidate, exercise the public QUIC/TLS integration and the private FIPS and test hooks on the candidate toolchain with the project's applicable tests and CI. Aim for readiness at the stable release without promising day-one support. The project targets the two Go release families that Go supports, and declares support only after validation. If a new release is incompatible, keep the last validated matrix, document the unsupported release, and alert Josh if an older toolchain leaves Go's security-support window.
5. **Make the release decision.** Josh weighs urgency, evidence, release timing and the facts consumers need. Agents prepare that material. A security fix that changes the documented contract is released as a minor version with migration guidance ([ADR 0016](../adr/0016-version-aware-compatibility.md)).
6. **Record the disposition.** Keep the applicability decision, its evidence, fix and release references, and the notification decision somewhere appropriate to their confidentiality. Entries Josh classifies as disclosable belong in the release record, as in the [v0.63.0 record](../releases/v0.63.0.md#upstream-advisory-applicability-record). An applicable unfixed finding stays out of the repository and public issues. Its fix is a separate security task under Josh's disposition.

## Reproduce an applicability review

Upstream advisories and their affected and patched ranges:

```sh
gh api 'repos/quic-go/quic-go/security-advisories?per_page=100' \
  --jq '.[] | [.ghsa_id, .cve_id, .published_at, (.vulnerabilities | map(.vulnerable_version_range + " => " + (.patched_versions // "")) | join("; ")), .summary] | @tsv'
```

Go vulnerability database entries for the upstream module path:

```sh
curl -fsS https://vuln.go.dev/index/modules.json |
  jq '.[] | select(.path == "github.com/quic-go/quic-go")'
curl -fsS https://vuln.go.dev/ID/<GO-ID>.json | jq '.aliases, .affected, .references'
```

Fix ancestry and later changes to the fixed code. Upstream commits after v0.62.0 are not in this repository's history; fetch one first with `git fetch https://github.com/quic-go/quic-go <commit>`.

```sh
git merge-base --is-ancestor <fix-commit> v0.62.0 && echo "in the v0.62.0 baseline"
git merge-base --is-ancestor v0.62.0 <candidate> && echo "baseline is an ancestor of the candidate"
git log --oneline v0.62.0..<candidate> -- <files touched by the fix>
```

Then read the fixed code at the candidate, find existing regression tests, and state a conclusion and its remaining uncertainty for each advisory.

## Scanner identity limits

- Go vulnerability records name affected module paths, and `govulncheck` looks up modules by path and version.
- For a replaced module, the lookup uses the replacement's path and version: see [`fetch.go`](https://github.com/golang/vuln/blob/e672cbe8fbc8c76e28fcb6db0efd9ce354e0dac5/internal/vulncheck/fetch.go#L13-L24) at the pinned revision.
- Records for code this project inherited from upstream name `github.com/quic-go/quic-go`. A clean scan of `github.com/GridCastIO/quicquic-go`, at any version, does not cover inherited upstream code. The applicability review above supplies that coverage.
- Never falsify a module path, for example by declaring or replacing the old path, to obtain scanner output.
- Re-read the scanner's lookup code at a pinned revision when its behavior matters to a decision. It can change between scanner releases.

## Monitoring runner

On 2026-11-17, Josh chose the runner that fulfills the policy's monitoring step ([#1109 decision receipt](https://github.com/the-sarge/quic-go-fast/issues/1109#issuecomment-6940490276)): a daily GitHub Actions scheduled workflow beside the existing `govulncheck` workflow. It does not exist yet. It is built and enabled at the final repository home as a follow-up after [#1111](https://github.com/the-sarge/quic-go-fast/issues/1111), under the ordinary review process. Its design:

- **Sources.** Upstream quic-go's published security advisories and release notes, Go security announcements, and the release history, to detect the first release candidate of each new Go release.
- **Durable watch state.** For each source, the identifiers last seen and their last-modified markers, persisted between runs. Only a new or changed item notifies. A missing or unreadable state is reported as a monitoring failure, not treated as "nothing new".
- **Notification.** A GitHub issue in this repository, assigned to Josh, carrying only public identifiers and links. No routine no-change issues.
- **Failure notification.** When a source cannot be read, the state cannot be loaded or saved, or the run fails, the workflow notifies Josh the same way.
- **Privacy.** Unpublished vulnerability details never enter the workflow, its state, its logs or its issues.

Enablement checks after the workflow is built:

1. the schedule is active;
2. a recent scheduled run succeeded;
3. the watch state advanced across runs;
4. a test notification reached Josh.

Record these checks where the follow-up is tracked.
