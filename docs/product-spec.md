# ZeroBacklog Product Specification

## Document status

This is the initial product specification for the hackathon direction. The current repository implements only the product preview and API foundation. Unless marked implemented, the behaviors below are planned.

## Product identity

- **Name:** ZeroBacklog
- **Tagline:** Stop Saving. Start Learning.
- **Promise:** Upload everything you have been postponing. Leave with one clear learning path.

## Target user

The primary user is a coding student or early-career developer preparing for interviews or building a new technical skill. They have accumulated a mixed backlog of videos, PDFs, screenshots, notes, roadmaps, and coding sheets. They care about learning but are overwhelmed by volume, repetition, and the fear of skipping something important.

Secondary users may include self-taught developers, bootcamp learners, and working engineers assembling a focused revision plan.

## Core user problem

The user's saved-resource queue is organized by source, not by learning value. It does not answer:

- Which concepts repeat across resources?
- What is genuinely unique?
- Where do trusted sources contradict one another?
- Which part of a long resource is worth the time?
- Which coding-sheet problems cover the same pattern?
- What can be skipped without creating a gap?
- What should the learner do next?

Conventional summarization can make the backlog shorter while still leaving these decisions unresolved. ZeroBacklog must reduce both content volume and decision burden.

## Product promise

ZeroBacklog will convert a mixed resource collection into an inspectable learning path and an approved set of study assets. It will be honest about unreadable, unsupported, irrelevant, incomplete, or low-confidence material. A learner should understand not just the recommendation, but why the system made it and which sources support it.

## In-scope hackathon MVP

The intended MVP vertical slice includes:

- one learner project with a stated learning goal;
- a constrained set of supported inputs across multiple resource types;
- per-resource validation and transparent status;
- extraction with source references;
- cross-resource concept grouping and repetition reduction;
- evidence-linked consume, skim, practice, and skip decisions;
- a prioritized learning sequence;
- generated concise text notes, one useful visual format, and a voice lesson;
- evaluation state for each generated asset;
- selective regeneration of one asset;
- storage of originals and derivatives in Backblaze B2;
- version/provenance display;
- a downloadable Action Pack; and
- failure and partial-processing behavior suitable for a live demo.

The MVP should be narrow enough to finish well. It does not need to accept every web source or file type.

## Explicitly out of scope

- a universal web crawler;
- automatic access to private paywalled content;
- bypassing DRM, platform controls, or creator permissions;
- arbitrary-length video processing with no limits;
- guaranteed factual correctness or a replacement for source review;
- real-time collaborative editing;
- social feeds, public profiles, or a creator marketplace;
- a browser extension;
- full learning-management-system functionality;
- automatic calendar scheduling;
- production billing;
- native mobile applications;
- enterprise tenancy and compliance certification;
- training a foundation model; and
- fully autonomous deletion or irreversible decisions based on model output.

## Planned result-page outputs

The result experience should lead with action, then evidence:

1. **Next best action** — what to do, estimated time, expected value, and reason.
2. **Learning path** — an ordered series of consume, skim, practice, and revision tasks.
3. **Backlog reduction summary** — resource count/time reduced and the basis for the estimate.
4. **Concept map** — repeated concepts, unique insights, dependencies, and contradiction flags.
5. **Skip list** — items or sections that add little value, with evidence and confidence.
6. **Practice plan** — de-duplicated coding problems grouped by pattern.
7. **Concise notes** — source-linked written synthesis.
8. **Visual asset** — a diagram, flowchart, or revision image selected for the topic.
9. **Voice lesson** — a short audio review for a bounded learning objective.
10. **Revision cards** — compact recall prompts tied to the learning path.
11. **Processing report** — supported, partial, failed, and excluded resources.
12. **Provenance/version panel** — source versions, generation attempts, evaluation state, and storage references appropriate for the learner.
13. **Action Pack download** — a manifest-backed bundle containing approved versions only.

The foundation UI contains illustrative preview values only; it computes none of these outputs.

## Transparency states

Every resource and generated asset must have an explicit user-visible state.

| State | Meaning | Required product behavior |
| --- | --- | --- |
| Fully processed | The supported resource completed the required stages | Include it in analysis and show completion/provenance |
| Partial | Only part of the resource was usable or a later stage failed | State what was included, what was missed, and how conclusions may be affected |
| Low confidence | Processing completed but evidence or model confidence is weak | Avoid definitive skip decisions; highlight review needs |
| Unreadable | The system could not recover usable content | Exclude it from conclusions and suggest a corrective action |
| Irrelevant | The resource does not materially address the stated goal | Explain the mismatch and let the learner override |
| Unsupported | The format, source, size, or access mode is outside MVP capability | Do not pretend to process it; list supported alternatives |

These labels must not collapse into a generic “failed” state. The Action Pack must state whether it represents the whole submitted backlog or only the successfully processed subset.

## Core decision language

Recommendations should use a small, understandable vocabulary:

- **Consume:** the source or section contains high-value material not sufficiently covered elsewhere.
- **Skim:** useful context exists, but full attention is unnecessary.
- **Practice:** active recall or problem solving is the next valuable step.
- **Skip:** the content is redundant or irrelevant with adequate evidence and confidence.
- **Review manually:** uncertainty, conflict, or unsupported content prevents a safe automated decision.

A skip recommendation carries the highest trust burden and should always expose evidence and confidence.

## Student value

The MVP succeeds for a student when it:

- turns an intimidating collection into one achievable next task;
- saves time without creating anxiety about hidden omissions;
- reveals useful overlap across formats;
- turns passive saved material into active practice and revision;
- accommodates reading, visual, and audio learning modes; and
- makes regeneration precise rather than wasteful.

## Judge value

The project should demonstrate:

- a recognizable problem with a specific user and credible utility;
- a product decision layer beyond generic summarization;
- clear planned-versus-working boundaries;
- real multi-stage orchestration with visible state and failure handling;
- B2 usage that is essential to provenance, versioning, and delivery;
- Genblaze usage that creates useful, evaluated media rather than decorative output;
- security and privacy awareness; and
- a foundation another engineer can run, test, and extend.

## Success metrics

These are proposed MVP/demo targets, not current measurements.

### User-outcome metrics

- **Time to first clear action:** under 60 seconds after processing completes.
- **Backlog reduction:** at least 40% fewer full resources recommended for consumption in the curated demo set.
- **Decision coverage:** every successfully processed resource receives an evidence-linked action.
- **Transparency coverage:** 100% of submitted resources show one of the defined processing states.
- **Source traceability:** 100% of learner-facing claims in the demo synthesis link to at least one source span.
- **Action Pack utility:** a test learner can identify the next task and explain why without opening every source.

### System-quality metrics

- **Object provenance:** every generated demo asset links to source versions, brief, attempt, and evaluation state.
- **Selective retry:** one failed or rejected asset can regenerate without rerunning successful assets.
- **Workflow reliability:** duplicate client requests do not create duplicate logical jobs.
- **Failure honesty:** unsupported and partial inputs never appear as fully processed.
- **Download integrity:** the Action Pack manifest checksums match delivered assets.
- **Foundation quality:** lint, tests, build, secret scan, and setup steps pass in a clean environment.

### Guardrail metrics

- no secrets in client bundles, logs, tracked files, or public health responses;
- no final skip decision from a low-confidence or partial-only evidence set without a visible warning;
- bounded generation retry count; and
- explicit deletion/retention state for every project before using real user data.

## Open product questions

- Which exact input types make the strongest feasible vertical slice?
- How should learners express goal, time budget, and prior knowledge without a long form?
- What evidence threshold is required for a safe skip recommendation?
- Which visual output is most useful for the demo topic: concept map, flowchart, or comparison diagram?
- When should the learner approve generation to control latency and cost?
- What should remain in a downloadable pack when a source is partial or low confidence?
- How should retention and project deletion be explained in plain language?
