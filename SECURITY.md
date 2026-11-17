# Security policy

quicquic-go is an independently maintained QUIC and HTTP/3 implementation in Go. Joshua Sargent owns security triage, disclosure, release timing and consumer notification for this project. Security response is best effort, with no fixed response-time commitment.

## Reporting a vulnerability

Report a suspected vulnerability privately through this repository's [private vulnerability reporting](https://github.com/GridCastIO/quicquic-go/security/advisories/new). Please **do not** file a public issue, pull request or discussion for it. Unpublished vulnerability details, reproductions and fixes stay private until Josh decides on disclosure.

If you are unsure whether an issue is a vulnerability, report it privately; it can be moved to a public issue once Josh decides it can be disclosed.

## Reporting a non-security bug

For bugs, feature requests and other non-security concerns, open an [issue](https://github.com/GridCastIO/quicquic-go/issues/new) in this repository.

## Fixes and versions

Fixes ship as new versions under the [compatibility promise](docs/adr/0016-version-aware-compatibility.md). A fix that changes the documented API, error, ownership or wire contract ships as a minor release with migration guidance. There is no backport window.

## Upstream advisories and scanner coverage

quicquic-go derives from quic-go, so upstream quic-go advisories can apply to inherited code. They are monitored and assessed against this project's actual source under the [upstream-advisory runbook](docs/runbooks/upstream-advisories.md), and each release record carries its applicability review.

Go vulnerability scanners match records by module path. Records for inherited code name `github.com/quic-go/quic-go`, so a clean `govulncheck` result for `github.com/GridCastIO/quicquic-go` does not show that inherited upstream code is unaffected.
