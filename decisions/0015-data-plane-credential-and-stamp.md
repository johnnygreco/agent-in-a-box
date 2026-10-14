# 0015. The data plane carries a run credential and a forward stamp

Date: 2026-10-14
Status: accepted

## Context

The per-run proxy listened on 127.0.0.1 with no credential, and so did the fixture. Both were reachable by any process on the host, under any user. A request from such a process would have been decided, recorded as the run's decision, and, if allowed, forwarded to the fixture, which would have written a receipt. The run's evidence could therefore be shaped by something that was never in the sandbox. PLAN.md requires identity to come from the supervisor's run and channel, and the gateway already had a session token; the data plane did not.

A second, smaller matter: Cedar sees the request path exactly as the client spelled it. Every shipped policy matches the path exactly, so an unusual spelling (`/reference/../collect`) was denied, but a learner's own policy using `like` would not have denied it, and an upstream could resolve it to another path.

## Decision

**Credential.** `dataplane.start_proxy` makes a credential for each run and gives the proxy mitmproxy's own proxy authentication with it (`proxyauth`). The credential goes into the workload's `HTTP_PROXY` and `HTTPS_PROXY` URLs as `http://run:<credential>@127.0.0.1:<port>`. A request without it is answered 407 before our decision path runs, so it is neither decided nor recorded. An https request therefore reaches the proxy as a CONNECT and is refused there with a recorded protocol decision, instead of being attempted directly and failing at the resolver or the kernel; inspected HTTPS arrives in Milestone 3.

**Stamp.** The scenario makes a second secret, the stamp, and hands it to the fixture in its environment (which other users' processes cannot read; a command-line argument could be) and to the proxy through a new `Lab` record in `RunRequest` that holds the routes and the stamp. The proxy adds the stamp as a header to every request it forwards; the fixture answers 403 and writes no receipt without it. The natively contained workload never holds the stamp, so the fixture trusts the proxy, not the workload. Both secrets live in the run's private directory and in processes of the developer's own uid, which could also edit the evidence files directly; under the test double the workload is such a process, so there the guarantee is against other users only. Neither secret is written to an event or a bundle; `Route` stays nonsecret and recorded.

**Spelling.** The proxy refuses a request target it would not describe truthfully: a dot segment, an empty segment before the end, or a percent-encoded slash or dot (`protocol.target_problem`). A trailing slash is an ordinary spelling and reaches Cedar as itself. The protocol check's detail records the target as sent beside the path Cedar saw.

## Alternatives rejected

- **A Unix socket listener instead of a TCP port.** mitmproxy's regular mode takes a TCP listener, and the fixture would still need to tell the proxy's connections from anyone else's.
- **Checking the connecting process's uid through `/proc/net/tcp`.** Linux-only, and the proxy and fixture are platform-independent.
- **One secret for both.** The fixture would then trust whatever the workload knows.
- **Normalizing unusual spellings instead of refusing them.** The proxy would then construct a request the client did not send, and the lesson is that the request Cedar sees is the one the proxy constructs from what was sent.

## Consequences

- The one secret the workload holds opens nothing but its own run's proxy, and the proxy ends with the run, so the credential is worthless afterwards. A bash probe that prints its environment shows it in the observation; that is a fact about the run, not a leak. Chapter 1 can show it as a fact the supervisor supplied, next to the facts the agent supplied.
- Attribution of a decision to a tool call could later ride in the same username field, labelled agent-claimed; mitmproxy's fixed username and password check would need a validator of our own for that.
- Every test that starts a fixture or a proxy passes a stamp; the fixture refuses to start without one.
- The fixture writes a receipt only for a request it accepted for reading. Besides the unstamped request (403), it refuses before reading a body whose length is undeclared or not a number (411, 400) and one over its 1 MiB limit (413), and closes the connection so unread bytes cannot pass for the next request. The proxy refuses a chunked request body before Cedar is asked, as it refuses upgrades, so a receipt's body fields describe the body that was sent. The proxy itself reads request bodies before forwarding, so its own limit is set to the same 1 MiB; mitmproxy applies it to response bodies too (502), which no fixture variant approaches. A decision record's `forwarded` is the decision to forward: mitmproxy may still answer a request whose body it rejects after that decision with its own 413, or close the connection with no answer when the body is shorter than declared, which leaves an allowed decision with no receipt; the same 413 replaces the proxy's own 403 when a refused request declared an oversize body, so the agent sees 413 without the refusal header while the decision record says refused.
- A direct request that is not stopped by the kernel now reaches the fixture and is answered 403 without a receipt, instead of being served and logged. The connection itself is the evidence that nothing stood in the way, and the `probe` command reports it that way. The shared conformance verdict for the direct probe therefore checks for a connection failure (curl exit 7), not merely for failure. The planned uncontained contrast recording (PLAN.md, chapter 4) can no longer show the direct request being served; its design should let the fixture record unstamped requests to a separate log that counts as evidence only in that recording. That design is a follow-up in STATUS.md.
- `curl` resolves dot segments itself before sending; `curl --path-as-is` is needed to send one and see the proxy refuse it before Cedar.
- macOS impact: none. The change is in the platform-independent data plane and in the workload environment both backends receive.

## Plan sections affected

PLAN.md: Network mediation.
