---
status: accepted
---

# Maintain independently, adopting validated upstream changes selectively

quicquic-go develops independently of upstream quic-go. It does not wholesale merge or rebase onto upstream releases; returning to release tracking would need a new explicit decision. quic-go v0.62.0 remains identifiable as the historical baseline: it is provenance, not a promise of continued tracking or upstream parity. This supersedes [ADR 0003](0003-follow-stable-upstream-releases.md) under the maintenance decision in [#651](https://github.com/the-sarge/quic-go-fast/issues/651#issuecomment-6563772122) and the evidence decision in [#1067](https://github.com/the-sarge/quic-go-fast/issues/1067#issuecomment-6564931617).

Individual upstream changes remain eligible when they meet a demonstrated need here: security, correctness, performance or Go compatibility. Each adopted change records:

- its upstream provenance;
- its applicability to this project's code;
- its adaptation rationale;
- validation evidence.

A change may be cherry-picked or hand-ported where the code has diverged. Upstream acceptance and a clean cherry-pick do not substitute for validation here. Upstream tests, CI, interoperability history and review remain historical evidence for the upstream revisions they examined. They do not validate this project's later changes, and this project's results support only the revision and configuration tested.

Joshua Sargent owns security triage, Go compatibility, CI, interoperability evidence and release readiness, unless he explicitly delegates. Agents monitor sources, assess applicability and prepare fixes and evidence. Security response is best effort, with no fixed response-time commitment. Vulnerabilities in this project are reported privately through this repository's vulnerability-reporting channel, and unpublished details stay private. Upstream advisories are assessed against the actual source rather than inferred from version ranges or scanner results. The [upstream-advisory runbook](../runbooks/upstream-advisories.md) owns the procedure, scanner limits and monitoring runner.

The project targets the two Go release families that Go supports. Compatibility work starts at the first release candidate, and support is declared only after validation. An incompatible new release leaves the last validated matrix in place and is documented. Missing external interoperability results do not by themselves block a release; a confirmed defect affecting promised behavior gets an explicit disposition from Josh.

ADR 0003 based releases on validated stable upstream releases and kept fork patches separately reviewable so they could be retired when upstream provided an equivalent remedy. That rationale fit a fork that intended to track upstream. Under independent maintenance it is replaced by recorded provenance for each adopted change. The existing review and release obligations are unchanged; this decision adds no gate, review budget or narrower review panel.
