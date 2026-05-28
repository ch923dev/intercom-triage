# Dependency Graph & Wave Schedule

Derived strictly from the roadmap. Edges are either **stated** ("Depends on X")
or **implied** (consumes a field/signal another item produces). Gates are hard:
a downstream item may not be dispatched until every upstream item is *merged*.

## Edge list (upstream → downstream)

| Edge | Type | Source in roadmap |
|------|------|-------------------|
| 0.2 → 1.2 | stated | "Consumes 0.2's score" |
| 0.2 → 1.1 | implied | saved views filter on urgency from 0.2 |
| 1.4 → 1.3 | stated | "feeds 1.3" (cost meter → dashboard) |
| 2.1 → 2.2 | stated | "do before/with 2.2" |
| 2.2 → 2.3 | stated | "pairs with 2.2's escalation trigger" |
| 2.4 → 2.5 | stated | "Depends on 2.4" |
| 2.4 → 2.6 | stated | "Depends on 2.4" |
| 2.4 → 3.1 | stated | "Reuses 2.4's embeddings" |
| 2.4 → 3.3 | stated | "Depends on 2.4" |
| 3.1 → 3.2 | stated | "Rank clusters (3.1)" |
| 0.1 → (Phase 2+) | soft | doc-sync prevents scope misread; finish before AI work |

## Critical path

The longest chain governs total wall-clock time no matter how many agents run:

```
2.1 → 2.2 → 2.3            (reliability chain, ~S+M+M)
2.4 → 2.6                  (keystone → RAG, L→L)   ← dominant
2.4 → 3.1 → 3.2           (keystone → cluster → gap, L→M→M)
```

**2.4 is the chokepoint.** It alone gates 2.5, 2.6, 3.1, 3.3 (and 3.2 via 3.1).
Front-load it. Nothing in Phase 2/3 AI-insight work compresses until it merges.

## Hard anti-parallelism constraints

1. **Cross-package single-PR rule** (`CLAUDE.md`): any item touching the
   `HydratedTicket` contract or shared schema ships as ONE atomic agent task
   across backend+webapp+extension. Affected: **4.2** (`non_actionable_kind`),
   and **0.2** (categorization schema change — backend + webapp consume it).
   These may NOT be split into per-package subagents.

2. **Shared-file collisions:** 0.5 (debt) touches `pipeline.py`, `tickets.py`,
   `.env`. 0.2 also touches the categorization schema in the pipeline. Run 0.5
   and 0.2 in the SAME wave only if they touch disjoint files; otherwise
   sequence 0.5 first (it's pure deletion) then 0.2. Scheduler treats them as
   file-conflicting → different sub-waves.

## Wave schedule (each wave = max safe parallel batch; gate between waves)

- **Wave A** (Phase 0 fan-out, no deps): 0.1, 0.3, 0.4, 0.5
  - then **0.2** (after 0.5 clears shared pipeline files) — cross-package, solo agent
- **Wave B** (Phase 1, after 0.2): 1.1, 1.2, 1.4, 1.5, 1.6 in parallel; **1.3 after 1.4**
- **Wave C** (Phase 2 reliability, independent of embeddings): 2.1 → 2.2 → 2.3 (serial chain)
  - **2.4 starts in parallel with Wave C** (no dep on 2.1–2.3) — kick it off ASAP
- **Wave D** (after 2.4 merges): 2.5, 2.6, 3.1, 3.3 in parallel
- **Wave E** (after 3.1): 3.2
- **Phase 4**: pull individual items on demand; 4.2 is cross-package solo
- **Robustness R.1–R.4**: continuous side-channel, 1 agent slot reserved throughout

## Concurrency cap

Recommend **3–4 concurrent subagents**. Worktree isolation prevents file
clobbering, but merge/review is serial and the operator (you) is the integration
bottleneck. More than ~4 in-flight PRs against a single-operator codebase
creates a review backlog that erases the parallelism gain.
