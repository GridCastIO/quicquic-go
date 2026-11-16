# Handshake stream release evaluation (#1411)

## Decision

Adopt the bounded ownership change for [issue #1411](https://github.com/the-sarge/quic-go-fast/issues/1411), subject to completion of review and exact-head certification. Five paired local trials show about 4.20 MB less retained server heap for 1,000 idle connections (about 4.20 KB/connection, 10.7% of baseline connection-attributed heap). No steady-state delivery-classification or packet-packing slowdown stands out from the observed ranges, and their allocation counts are unchanged. Complete handshake timing is slightly slower in all five candidate runs; treat this as a possible connection-setup cost, not a proven neutral result.

The approved [contract](../../agents/crypto-stream-release-1411.md) and [ownership argument](ownership.md) bound the change. The memory reduction persists for the connection's idle lifetime; the measured setup difference is approximately 8 microseconds at the median. For the motivating persistent idle-server workload, that tradeoff supports adoption. Connection-churn-heavy deployments may value this tradeoff differently. This experiment is not a throughput/SLO qualification and cannot establish CPU neutrality on other platforms.

## Revisions and conditions

Production baseline: `f11a20cf56d7dcf682e5e02e7969ccd7bcd7811a`. Baseline with measurement-only fixtures: `483d647554dc690b660ace0abf61fd145c7466af`. Candidate: `70924089d427bc6cf94eb8f1220585ee15326d32`. Measurement source files are identical between instrumented baseline and candidate. [The baseline fixture patch](baseline-fixture.patch) adapts the existing test-packer fixture to the same benchmarks without modifying production behavior.

Measured November 15, 2026 on Darwin/arm64, Apple M4 Max, Go 1.27.4, with `GOMAXPROCS=4`. Baseline and candidate ran sequentially, alternating pair order, without simultaneous test/compile workloads from this task. The host was not reserved or pinned to a CPU cluster; there is no assertion that unrelated efficiency-core work constituted interference, nor a claim of isolated performance-core timing.

[Heap fixture](heap/main.go): separate client/server processes; 1,000 live loopback QUIC v1 connections; repository certificate/key and CA, TLS 1.3 with verified `localhost` identity, fixed ALPN; no session resumption; normal session tickets; one `ping`/`pong` exchange per connection; keepalives disabled; PMTU discovery disabled consistently; two-minute idle timeout; five seconds idle after the last exchange; two explicit GCs for both empty-server and loaded snapshots. The server keeps every connection alive and checks that no connection has closed before measuring. The empty control is the same listener and waiting client-process setup before dialing. The metric is Go `HeapAlloc`, not RSS, and excludes the separate client process.

The CPU comparison uses identical compiled benchmark source. The complete-handshake benchmark is the existing integration benchmark, which includes both endpoints and closing each connection. It generates its TLS certificate once per process. Packing uses the real packet packer with transparent test protection and mocked packet-number/ACK sources, and reinitializes stream values so every client iteration scrambles a new ClientHello. Its result includes those fixture costs, not real AEAD cost. Delivery classification exercises the real method after handshake discard; the pending case contains 1-RTT CRYPTO retransmission work. Each CPU sample is a one-second Go benchmark; five samples per build were collected.

## Retained heap

All figures below are bytes, after subtracting each run's empty-server control. Full snapshot values and object counts are in `results/*-heap.json`.

| Pair | Baseline | Candidate | Reduction | Bytes saved / connection |
| --- | ---: | ---: | ---: | ---: |
| 1 | 39,432,632 | 35,224,944 | 4,207,688 | 4,207.688 |
| 2 | 39,430,984 | 35,234,752 | 4,196,232 | 4,196.232 |
| 3 | 39,427,952 | 35,223,152 | 4,204,800 | 4,204.800 |
| 4 | 39,424,936 | 35,219,624 | 4,205,312 | 4,205.312 |
| 5 | 39,428,384 | 35,233,608 | 4,194,776 | 4,194.776 |

Baseline median: 39,428,384 bytes, range 39,424,936–39,432,632. Candidate median: 35,224,944 bytes, range 35,219,624–35,234,752. Paired savings range: 4,194.776–4,207.688 bytes/connection; median paired saving: 4,204.800 bytes/connection. The difference of the two heap medians is 10.66% of the baseline median.

Sampled heap profiles attribute baseline retention to `baseCryptoStream.Write`, `initialCryptoStream.Write`, and stream/sorter construction; these handshake ownership sites disappear from the candidate's first sampled profile. Profiles remain statistical samples, not exact per-site accounting. Remaining retention includes TLS crypto output/transcript allocations, AEAD state, the connection, recovery, receive ring buffers, and send queues. Surviving 1-RTT crypto and legitimately outstanding frame owners remain allowed. The exact heap metric and focused weak-reference tests, rather than subtraction of sampled profile estimates, establish the reported savings and release behavior.

## CPU and allocations

| Benchmark | Baseline median (range), ns/op | Candidate median (range), ns/op | Median allocs/op, baseline → candidate |
| --- | ---: | ---: | ---: |
| Delivery classification, empty | 13.23 (12.96–13.35) | 13.10 (13.05–13.32) | 0 → 0 |
| Delivery classification, application pending | 1.906 (1.877–1.918) | 1.897 (1.883–1.914) | 0 → 0 |
| Server Initial/Handshake packing | 5,576 (5,460–5,659) | 5,580 (5,512–5,648) | 49 → 49 |
| Client packing with scrambling | 6,536 (6,324–6,636) | 6,548 (6,452–6,595) | 56 → 56 |
| Complete handshake | 564,380 (561,107–595,584) | 572,256 (562,132–603,237) | 2,196 → 2,196 |

Complete handshake median increased 7,876 ns/op (1.40%). Every paired sample was slower, with paired changes approximately +0.16% to +6.42%. Five local samples do not establish the population effect or its cause; this directional result is retained in the adoption tradeoff rather than dismissed because the ranges overlap. Median handshake allocation bytes decreased from 252,055 to 251,558 B/op, with unchanged median allocation count. Packet-packing B/op varies with per-process generated ClientHello details; allocation counts are stable. Raw benchmark output is retained for every pair.

Compiler inspection shows `cryptoStreamManager.HasData` inlined at delivery-sampling and packet-packing callers. `Write`, `PopCryptoFrame` and `Drop` are not inlined. The hot availability query adds no allocation or interface dispatch. This supports the narrow steady-state result without explaining away the complete-handshake timing difference. See `results/inlining.txt`.

## Reproduction and validation

From separate worktrees at the revisions above, build each heap fixture with `go build -o <heap-binary> ./docs/audits/crypto-stream-release-1411/heap/main.go`, the root benchmarks with `go test -c -o <bench-binary> .`, and handshake benchmarks with `go test -c -o <handshake-binary> ./integrationtests/self`. To reconstruct the baseline fixtures from production baseline, copy the candidate's heap and benchmark source and apply `baseline-fixture.patch` with `git apply --unidiff-zero` (zero context avoids interpreting patch context as repository whitespace).

[The executed driver](run_measurements.py) records the exact local binary paths, alternating order, commands, environment and result filenames. Each pair runs `GOMAXPROCS=4 <heap-binary> -connections 1000 -profile <output>`, then the root binary with `-test.run '^$' -test.bench '^BenchmarkCrypto' -test.benchtime 1s -test.count 1`, then the integration binary with the same flags and `-test.bench '^BenchmarkHandshake$'`. Inspect a profile with `go tool pprof -top -sample_index=inuse_space <heap-binary> <profile>`.

The source baseline failed the write-storage retention regression at both levels. Before queue integration, the connection-level obsolete-retransmission regression failed at both levels. Both now pass. Root, recovery and handshake package tests passed; focused race tests passed for the new lifetime regressions and existing crypto, handshake, Retry, version-negotiation, 0-RTT, coalesced/close and native ordinary/software paths. Real-loopback handshake, explicit versions, Retry, HelloRetryRequest, 0.5-RTT, version negotiation during MTU fallback, session resumption, and immediate-close integration tests passed with the race detector. `go vet .`, `go mod tidy -diff`, root `golangci-lint run .`, and `git diff --check` passed. Final certification and hosted check receipts are recorded separately after review.

The initial fixture smoke run exposed an incorrect certificate hostname; the fixture was corrected to the certificate's `localhost` identity before either measured binary was built. That failed smoke run produced no measurement result and is not one of the five trials. No production code changed after the measured candidate to obtain these results.
