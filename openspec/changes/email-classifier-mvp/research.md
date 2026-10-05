# Research: JEV API (pre-proposal evidence)

> Orchestrator-owned research note (SDD research lane is unselected in this
> runtime; this is layered pre-proposal evidence collected 2026-10-05 from
> <https://opencode.ai/docs/zen/> and <https://docs.typesafe.ai/>).

## What JEV is

Jev (`jev-1.13`, TypeSafe AI) is a "System One" model: it does not generate
text. It evaluates a `state` against typed questions and returns structured,
probability-bearing answers designed for direct programmatic use. This matches
PROD.md §9/§20 exactly.

## Access via OpenCode Zen

- Endpoint: `https://opencode.ai/zen/v1/systemone`
- Auth: `Authorization: Bearer $OPENCODE_API_KEY`
- Models: `jev-1.13` (paid: $0.042 per 1M input tokens, output free) and
  `jev-1.13-free` (limited-time free). Pricing is per-call on the full state,
  so one email = one request regardless of question count.
- Models listing: `GET https://opencode.ai/zen/v1/models`
- TypeSafe also offers a direct API (`https://api.typesafe.ai/v1/systemone`)
  and a Python SDK; the Zen gateway is the user-preferred access path.

## Request schema

```json
{
  "model": "jev-1.13",
  "state": "<full email text: subject, body, sender, attachment names>",
  "questions": {
    "claim_new": {
      "type": "noul",
      "instructions": "Does this email report a new insurance claim?",
      "criteria": { "true": "...", "false": "..." }
    }
  }
}
```

Question types: `noul` (yes/no -> single probability 0..1), `choice`
(options -> choice + `probabilities` + `confidence`), `score` (rubric levels ->
score + `probabilities` + `confidence`). All types can be mixed in ONE request;
every question is evaluated in parallel and in isolation against the same
state (no context-rot from adding questions; response time barely changes).

## Response schema (noul)

`answers.<question_id>.noul` = probability that the answer is yes (0..1).
Noul carries NO separate `confidence` field: the probability IS the certainty
(0.5 = unsure). Distance-from-0.5 (`|2p-1|`) is the documented way to get a
confidence-style number when gating nouls and choices with the same code.

## Design implications for the classifier

1. One API call per email with the entire MVP question set (~28 noul
   questions: 16 primary categories + 6 sensitivity + 6 actions). Batching is
   native; no client-side parallelization needed.
2. `state` is a single string: the normalization layer composes subject,
   sender, body, attachment filenames into it. Attachment *content* extraction
   is our responsibility before calling JEV.
3. Noul semantics confirm the PROD.md model: threshold per question in OUR
   code; values near 0.5 should route to human review rather than a code path.
   This directly supports the paired review-floor fix for the 0.95
   auto-tier gap found in exploration.
4. `criteria` (true/false descriptions) is the documented mechanism for
   encoding taxonomy boundary definitions (e.g. COMPLAINT vs LEGAL
   disambiguation) at the question level, versioned with the question set.
5. Privacy: Zen routes JEV prompts to TypeSafe ("Prompts and other inputs are
   not used for training"). With synthetic-only data (user decision), sending
   email text is acceptable for the PoC. Still, the JEV port must be a
   seam: a deterministic fake scorer for tests, real HTTP client in prod.
6. Open questions for design: exact response envelope field names (verify
   against TypeSafe API docs / Python SDK), retry/timeout/error behavior,
   `choice` vs noul-only strategy for primary_category selection (PROD.md
   says binary questions; primary category can be derived as argmax over
   category nouls with a dominance rule + review floor).
