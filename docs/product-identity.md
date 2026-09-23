# LecturAL Product Identity

> Status: Draft\
> Purpose: Define what LecturAL is, what makes it distinctive, and how to decide whether a new feature belongs in the project.

---

## 1. One-line definition

**LecturAL turns media into complete, deterministic, timestamp-addressable evidence that agents can verify and reuse.**

A more product-oriented version:

> **LecturAL compiles video and audio into the smallest trustworthy evidence context an agent needs.**

---

## 2. What LecturAL is

LecturAL is not primarily a note-taking app, a video chatbot, or an editor.

It is an **evidence compiler for media-based work**.

Its job is to take video/audio sources and produce machine-readable evidence with explicit provenance, timestamps, completeness, and resource-aware extraction.

Typical pipeline:

```text
video / audio / YouTube
        ↓
      LecturAL
        ↓
deterministic evidence
        ↓
query + budget
        ↓
agent-ready context
        ↓
downstream agent/workflow
```

The downstream agent may summarize, answer questions, edit video, write code, study a lecture, perform research, or create another artifact.

LecturAL should not need to know which of those jobs will happen next.

---

## 3. Core personality

LecturAL should feel:

### Reliable before clever

Prefer a boring result that is traceable and complete over a clever result that cannot explain where it came from.

### Evidence-first

The main output is not an answer.

The main output is the evidence required to produce an answer.

### Deterministic where possible

Speech acquisition, OCR, timestamps, frame extraction, coverage, path handling, contracts, and validation should be deterministic whenever practical.

LLMs may consume LecturAL output, but they should not be required to make the raw evidence trustworthy.

### Cheap by default

Do not run expensive stages merely because they exist.

If captions are sufficient, skip ASR.

If visual evidence is unnecessary, skip frame extraction and OCR.

If a small context satisfies the request, do not send the full source downstream.

### Agent-native, not agent-dependent

LecturAL should be easy for Claude, Codex, or another agent to call, but its core must remain independently testable as a CLI/library.

### Fail-closed on trust boundaries

If a contract cannot prove that required evidence is complete or valid, it should report that uncertainty explicitly rather than silently pretending the extraction succeeded.

### Composable

LecturAL should expose stable primitives that downstream systems can combine:

- transcript segments
- visual evidence
- intervals
- OCR
- provenance
- context selection
- resource metrics

It should avoid owning higher-level workflows unnecessarily.

---

## 4. Product boundary

### LecturAL owns

- media acquisition
- caption/STT selection
- timestamped transcript evidence
- visual evidence extraction
- OCR annotations
- interval-level evidence
- completeness validation
- timestamp integrity
- provenance
- context selection under a token/resource budget
- resource/cost observability
- stable versioned contracts
- thin agent-facing CLI/Skill interfaces

### LecturAL may provide

- translation as a derived artifact while preserving the original transcript
- multiple execution profiles
- optional backend adapters
- cross-video indexing/retrieval
- source-clip materialization
- lightweight query-oriented evidence retrieval

### LecturAL should not own by default

- final question answering
- summarization quality
- quiz generation
- domain-specific semantic interpretation
- object/entity tracking
- automatic editing
- creative storyboarding
- recommendation engines
- channel/workflow-specific orchestration
- generated commentary or opinion

Those belong in downstream agents, skills, or products built on top of LecturAL.

---

## 5. The key abstraction: Evidence, not Notes

The original use case was lecture notes.

That remains useful, but notes should now be treated as one consumer of the evidence layer.

The canonical architecture is:

```text
                     ┌───────────────┐
                     │   LecturAL    │
                     │ evidence core │
                     └───────┬───────┘
                             │
              ┌──────────────┼──────────────┐
              ▼              ▼              ▼
            notes          research       media work
            agent           agent           agent
```

`notes.md` is useful.

`evidence.json` is foundational.

---

## 6. The key abstraction: Query returns Context

A downstream agent rarely needs the full evidence bundle.

The intended public interaction is:

```text
query → evidence context
query ≠ answer
```

Conceptually:

```console
lectural query evidence.json \
  "Where is the attention mechanism explained?" \
  --budget 6000
```

Possible output:

```json
{
  "query": "Where is the attention mechanism explained?",
  "context": {
    "estimated_tokens": 4820,
    "intervals": [...],
    "transcript_segments": [...],
    "frames": [...],
    "ocr": [...]
  }
}
```

LecturAL returns the evidence required to answer the question.

The host agent decides what that evidence means and produces the final answer.

### Query design is intentionally open

`query` is expected to become one of LecturAL's most important interfaces, but its internal retrieval and packing strategy is **not yet fixed**.

Open design questions include:

- lexical retrieval vs semantic retrieval vs hybrid retrieval
- whether transcript and OCR should be indexed separately or jointly
- how point hits should expand into coherent evidence intervals
- how nearby hits should merge
- how visual evidence should be attached to speech evidence
- how relevance, evidence quality, novelty, redundancy, and cost should interact
- how a token budget should be estimated and enforced
- whether frame count and interval count should become first-class budget dimensions
- how deterministic or reproducible ranking must be
- how query behavior should degrade when optional embedding/model backends are unavailable

These decisions should be driven by benchmarks and dogfooding rather than frozen prematurely.

The stable product contract should be defined before the ranking algorithm is considered stable.

---

## 7. Adaptive compute philosophy

LecturAL should satisfy the requested evidence quality through the cheapest valid pipeline.

Conceptually:

```text
request
  ↓
evidence requirements
  ↓
execution planner
  ├─ captions enough?       → skip ASR
  ├─ visual evidence needed?→ extract frames
  ├─ text on screen needed? → OCR
  ├─ exact timing needed?   → stronger alignment
  └─ high quality required? → expensive backend if justified
```

Possible profiles may include:

- `captions-only`
- `cpu-friendly`
- `no-ocr`
- `balanced`
- `full-quality`

Profiles are conveniences.

The long-term principle is **requirement-driven execution**, not simply a collection of presets.

---

## 8. Query and retrieval philosophy

LecturAL may support requests such as:

> "Find the part where this concept is explained."

The intended responsibility is:

```text
query
  ↓
relevant evidence candidates
  ↓
coherent evidence intervals
  ↓
budget-aware context
  ↓
timestamp + transcript + frame/OCR
```

Not:

```text
query
  ↓
authoritative final answer
```

Retrieval belongs in LecturAL when it helps locate evidence.

Interpretation belongs to the consumer.

The existence of a `query` command does **not** imply that LecturAL must own a vector database, RAG framework, chat UI, or a specific embedding model. Those are implementation choices to evaluate separately.

---

## 9. Multi-video philosophy

A source should ideally be extracted once and reused many times.

Long-term:

```text
source A ─┐
source B ─┼→ evidence library → context/search
source C ─┘
```

Useful capabilities:

- extraction cache
- stable source identity
- playlist/series ingestion
- cross-video search
- context assembly across sources

The library layer should still preserve source-level provenance and contracts.

---

## 10. Observability is a product feature

LecturAL should make the cost of evidence visible.

Useful metrics include:

- total runtime
- per-stage runtime
- peak RAM
- CPU/GPU use
- artifact size
- frames retained/discarded
- OCR workload
- ASR workload
- resulting context token count
- token reduction versus naive/raw input

This allows users and agents to reason about quality/resource trade-offs instead of treating the pipeline as a black box.

---

## 11. Benchmark philosophy

LecturAL should be evaluated on downstream usefulness, not only extraction accuracy.

Useful comparisons:

```text
raw multimodal input
vs transcript-only
vs LecturAL evidence
```

Possible downstream tasks:

- summarization
- targeted retrieval
- research
- study
- question answering
- task execution

Questions to measure:

- Did the required evidence survive?
- Can the agent find the right timestamp?
- Is the context smaller?
- Is the result equally or more accurate?
- What compute was required?

Benchmarking should guide new features rather than feature count.

---

## 12. CLI vocabulary

The current preferred command vocabulary is:

```text
lectural extract
lectural inspect
lectural verify
lectural query
lectural export
```

### `extract`

Convert a source into a versioned evidence bundle.

```text
source → evidence
```

### `inspect`

Show a human-readable summary of what an evidence bundle contains.

Typical information includes source, duration, transcript source, frame count, OCR state, coverage, schema/contract version, and artifact sizes.

```text
evidence → readable inventory
```

### `verify`

Validate whether an evidence bundle satisfies its structural and completeness contracts.

```text
evidence → trust/integrity result
```

This is not fact-checking. It verifies the bundle, timestamps, references, artifacts, and declared completeness semantics.

### `query`

Retrieve and package evidence relevant to a request.

```text
evidence + query + optional budget → context
```

This is expected to be a core product surface. Its internal retrieval, interval-building, and budget-packing design remains intentionally open until benchmarked.

### `export`

Materialize concrete media artifacts from timestamp-addressable evidence.

```text
evidence interval → clip / frame / audio artifact
```

`export` is useful but comparatively deterministic and lower risk. It is not a near-term design priority compared with `query`.

---

## 13. Integration philosophy

### In the LecturAL repository

Keep a thin Agent Skill / adapter that allows natural requests such as:

```text
"Extract evidence from this video."
"Find where X is explained."
"Give me context for this question within 4k tokens."
```

The Skill should mostly translate user intent into stable LecturAL CLI/contracts.

### In `agent-skills`

Keep higher-level workflows that compose multiple tools or engines.

Example:

```text
LecturAL
 + browser research
 + codebase
 + document generation
```

LecturAL should not absorb workflow orchestration merely because an agent can call it.

---

## 14. Hosted compute philosophy

Hosted execution is an infrastructure concern, not the product core.

The preferred architecture is:

```text
same LecturAL engine
same contracts
same evidence
        │
        ├─ local CPU
        ├─ local GPU
        └─ remote worker
```

Remote compute may arrive later for users without sufficient hardware.

The engine and public contract should not depend on the hosting model.

---

## 15. Build-vs-borrow rule

LecturAL should not reimplement mature lower-level tools merely to own the entire stack.

Examples of capabilities that should generally be benchmarked or adapted before reimplementation:

- scene detection
- speech alignment
- diarization
- OCR engines
- media decoding
- vector search
- clip extraction

LecturAL's value is in **normalizing these capabilities into reliable evidence**, not necessarily inventing every detector.

A useful rule:

> If a mature tool solves a primitive well, integrate or adapt it.\
> Build where LecturAL's evidence contract, completeness, or resource-aware behavior requires something distinct.

---

## 16. Feature admission test

Before adding a feature, ask:

### A. Does it improve evidence?

Does it make evidence more complete, precise, reusable, traceable, or cheaper?

If yes, it probably belongs.

### B. Does it improve context delivery?

Does it help select the right evidence for an agent under a budget?

If yes, it may belong.

### C. Is it semantic interpretation?

If it primarily decides what the media *means*, it probably belongs downstream.

### D. Is it workflow-specific?

If it exists mainly for one product/workflow, put it in that consumer or `agent-skills`.

### E. Is there already a mature primitive?

Benchmark or integrate before reimplementing it.

---

## 17. Current priority direction

Recommended direction:

1. **Interval evidence**
2. **`query` contract and benchmark design**
3. **Adaptive compute**
4. **Resource observability and downstream benchmark**
5. **Thin agent integration**
6. **Multi-video library**
7. **Translation artifacts**
8. **`export` / media materialization**
9. **Hosted compute**

The exact retrieval algorithm, interval-building strategy, and budget-packing policy for `query` remain open.

The order may change through dogfooding and benchmarks.

---

## 18. Non-goal: Feature accumulation

LecturAL should not become successful by accumulating every possible video capability.

A smaller tool with strong contracts is preferable to a broad tool with unclear ownership.

The target is not:

> "LecturAL can do everything with video."

The target is:

> **"When an agent needs evidence from media, LecturAL is the trustworthy layer underneath."**

---

## 19. Current design status

### Relatively stable

- evidence-first product boundary
- deterministic extraction and verification
- versioned public contracts
- adaptive/cheap-by-default execution philosophy
- thin agent integration
- `extract`, `inspect`, and `verify` vocabulary

### Directionally agreed, design still open

- `query` public contract
- evidence interval representation
- context budget semantics
- retrieval/ranking strategy
- interval expansion/merging
- multimodal context packing
- cross-video retrieval

### Lower priority / comparatively straightforward

- `export` and media materialization
- hosted compute

This distinction is intentional: product identity should stabilize before implementation details do.

---

## 20. Product mantra

Three phrases should guide the project:

> **Evidence before answers.**

> **Use the cheapest pipeline that preserves the required evidence.**

> **Extract once, verify it, reuse everywhere.**
