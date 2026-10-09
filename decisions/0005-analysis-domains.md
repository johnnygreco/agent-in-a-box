# 0005. Analysis domains: a schema request environment, optionally narrowed by one stated condition

Date: 2026-10-09
Status: accepted

## Context

Every "proved for domain D" result must state its domain (PLAN.md, Formal verification; formal-methods review F4). SymCC's native domain is one request environment of the schema (principal type, action, resource type) with every entity and context value the schema allows. For HttpRequest, that includes methods no client sends. On 2026-10-09 the solver answered the P0 → P2 check over the schema-wide domain with method `""`, which is a correct witness that no learner would recognize. The P2 lesson (CURRICULUM.md, chapter 5) expects a recognizable method such as PUT. The review warns against "emulating arbitrary assumptions with ad hoc policy rewriting".

## Decision

A `Domain` (contracts.py) is one schema request environment plus at most one Cedar condition on the request, with a name and a plain description. A condition is encoded exactly, not approximately. Both policy sets in the query get one added policy:

```cedar
@id("domain:D_http")
forbid (principal is Sandbox::Process, action == Sandbox::Action::"HttpRequest", resource is Sandbox::NetworkEndpoint)
unless { ["GET", "HEAD", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"].contains(context.method) };
```

Because `Allow(P + forbid-outside-D, x) = Allow(P, x) ∧ D(x)`, the SymCC query `implies(new + D, old + D)` searches exactly for `D(x) ∧ Allow(new, x) ∧ ¬Allow(old, x)`, and `equivalent(A + D, B + D)` checks equivalence on D. Witnesses are replayed against the original policy sets, without the domain policy, and must also satisfy the condition; otherwise the result is "no conclusion".

The lesson domain `D_http` is the set of HttpRequest requests the proxy can construct. Its method list is the proxy's own supported set (`policy/requests.py`, `SUPPORTED_METHODS`); the proxy refuses any other method before Cedar is asked. The domain is therefore stated by the component that builds requests, not chosen to make a result look good. Domain ids beginning `domain:` are reserved, and the compiler rejects authored policies that use them.

## Alternatives rejected

- **Schema-wide domains only.** Honest, but the P2 witness becomes `""`, and the lesson's point (a method the learner did not think of) is lost in a string no client sends. Kept available, and shown by a test, as a teaching contrast.
- **SymCC's custom symbolic environments (`compile_with_custom_symenv`).** SymCC marks them "use at your own risk", with undocumented invariants and no Lean counterpart.
- **A schema enum for HTTP methods.** It would change the schema's vocabulary (method is a String) and every policy's text.
- **Several conditions or arbitrary rewriting.** One stated condition is enough for the lessons and easy to show in the domain inventory.

## Consequences

- The domain's condition and its forbid appear in the disclosed solver input (`emit_smtlib`) and in every analysis result's domain record, so learners can see exactly what was assumed.
- The domain describes request construction. It says nothing about the kernel profile or the proxy's correctness (invariant 5).
- If the proxy's supported methods change, D_http changes with them, and earlier results stay tied to the old policy hashes and domain record.

## Plan sections affected

PLAN.md: Formal verification as a core learning feature (Properties: domains). CURRICULUM.md: chapter 5 expected observation 2 is unchanged and now depends on D_http, which this ADR records.
