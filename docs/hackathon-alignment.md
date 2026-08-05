# Hackathon Alignment

## Purpose

This document maps ZeroBacklog to the Backblaze Generative Media Hackathon judging themes supplied to the project team. It is an implementation and demo evidence checklist—not a claim that the current foundation already satisfies final judging requirements.

## 1. Real-world Utility

### ZeroBacklog's case

Learners already experience the problem: valuable material is distributed across watch-later queues, downloads, screenshots, notes, and coding sheets. The cost is not simply storage clutter. It is repeated study, missed contradictions, decision fatigue, and failure to start.

ZeroBacklog's useful unit of output is a justified next action, not another generic summary. Knowledge reduction, safe skip guidance, and multi-format revision assets directly support the learner's goal.

### Final demo evidence

- Start with a believable mixed backlog rather than synthetic text alone.
- State a concrete learner goal and time constraint.
- Show the initial resource count or estimated duration.
- Show repeated material collapsed and unique material retained.
- Show at least one consume, skim, practice, and skip decision with source evidence.
- Make a partial, unsupported, or low-confidence resource visible.
- End with a substantially smaller, ordered plan and a useful next task.
- Quantify reduction using defensible demo-set numbers; do not present illustrative UI values as computed results.

### Product bar

A learner who did not build the product should be able to look at the result and answer: “What do I do next, why is it next, and what did the system leave out?”

## 2. Production Readiness

### ZeroBacklog's case

Production readiness is treated as observable behavior and maintainable boundaries: explicit configuration, safe logs, stable API contracts, tests, honest partial states, idempotency, bounded retry, access controls, provenance, and reproducible setup.

The foundation already implements:

- centralized environment-backed settings;
- secret-safe field types and log redaction;
- configured-origin CORS;
- centralized exception responses;
- versioned and unversioned health routes;
- frontend loading/success/failure/retry states; and
- backend contract tests.

This is a foundation, not complete production hardening.

### Final demo evidence

- Deploy frontend and backend with a real health response.
- Show a clean setup path and automated checks.
- Demonstrate an unsupported or partial input without failing the whole project.
- Show durable job state, a correlation ID, and bounded retry behavior.
- Demonstrate duplicate-request protection for a generation or pack operation.
- Show authentication/authorization for project objects and downloads.
- Explain secrets management, least-privilege B2 access, and retention/deletion.
- Show that client and logs do not disclose credentials or raw provider errors.
- Include a concise limitation/security statement in the final README and demo.

### Engineering bar

A reviewer should be able to clone the repository, configure placeholders locally, run checks, understand the boundaries, and identify what happens when a dependency fails.

## 3. B2 Storage + Data Orchestration

### ZeroBacklog's case

B2 is planned as the durable artifact graph:

`original → extraction → analysis evidence → generation brief → generated attempt → evaluation → approved version → Action Pack`

This creates meaningful storage needs: mixed media, durable originals, multiple generated formats, selective regeneration, provenance, and authorized downloads. PostgreSQL will index workflow state and relationships; B2 will store the object bytes and object-level metadata.

### Required implementation

- store original demo resources in B2 with server-generated keys;
- store normalized derivatives separately from originals;
- store generated text, image, and voice objects;
- record checksum, content type, size, logical version, attempt, and source-version references;
- preserve prior outputs during selective regeneration;
- assemble an Action Pack from approved versions through a manifest;
- enforce scoped access for upload and download; and
- define cleanup behavior for temporary, failed, and deleted-project objects.

### Final demo evidence

- Show the upload creating real B2 source objects.
- Show the source object's identifier reappearing in provenance.
- Show more than one derivative media type in B2.
- Trigger selective regeneration and show a new object/version without overwriting the approved prior version.
- Show an evaluation or manifest object associated with the derivative.
- Download the final Action Pack from a controlled B2-backed flow.
- Briefly show bucket/key structure and non-sensitive metadata.
- Explain why the flow needs object storage and why a database alone is not appropriate.

### Storage bar

Removing B2 from the architecture should break source durability, derivative versioning, and pack delivery—not merely remove a backup copy.

## 4. Use of Genblaze

### ZeroBacklog's case

Genblaze is planned to turn an evidence-linked learning decision into selected media. It is not meant to generate every possible asset automatically. The decision layer supplies an asset-specific brief; Genblaze orchestrates the appropriate text, image, or voice work; evaluation determines acceptance; and selective retry produces a new version when necessary.

### Required implementation

- create a structured brief tied to approved source evidence;
- orchestrate at least text, image/diagram, and voice outputs;
- expose job and attempt status to the backend;
- evaluate format, completeness, grounding, and output-specific quality;
- retry only the rejected asset within a fixed budget;
- record model/workflow identity and timestamps in provenance; and
- persist every approved demo output to B2.

### Final demo evidence

- Show one analysis decision becoming a generation brief.
- Show Genblaze orchestrating genuinely different media types.
- Display generated text, an interactive Learning Workflow, and playable voice output.
- Show an evaluation status for each asset.
- Reject or flag one asset, selectively regenerate it, and keep the other outputs unchanged.
- Show the regenerated version stored in B2 and selected into the Action Pack.
- Explain how the generated asset reduces learning friction for the target student.

### Orchestration bar

Genblaze should visibly coordinate multi-format, stateful, evaluated work. A single unobserved generation call or decorative image is insufficient evidence.

## Cross-criterion demo matrix

| Demo moment | Utility | Readiness | B2 orchestration | Genblaze |
| --- | :---: | :---: | :---: | :---: |
| Mixed backlog upload | ✓ | ✓ | ✓ |  |
| Validation and partial state | ✓ | ✓ |  |  |
| Evidence-linked reduction | ✓ | ✓ |  |  |
| Multi-format generation | ✓ |  | ✓ | ✓ |
| Evaluation and selective retry | ✓ | ✓ | ✓ | ✓ |
| Provenance/version panel |  | ✓ | ✓ | ✓ |
| Controlled Action Pack download | ✓ | ✓ | ✓ |  |

## Final submission evidence checklist

- [ ] The deployed product completes one honest vertical slice.
- [ ] All illustrative data is clearly separated from measured demo results.
- [ ] The learner's before/after backlog is measurable.
- [ ] At least one imperfect input produces a transparent non-success state.
- [ ] Every demo recommendation links to evidence.
- [ ] Health, tests, and failure handling are visible.
- [ ] Real B2 objects include originals, derivatives, versions, and final pack data.
- [ ] Genblaze orchestrates multiple useful media types.
- [ ] One selective retry is shown end to end.
- [ ] Approved outputs preserve provenance.
- [ ] Security, privacy, cost, and limitations are acknowledged.
- [ ] The final README contains reproducible setup and architecture.

## Current gap summary

The repository currently establishes the engineering and documentation baseline only. It does not yet provide judging evidence for real B2 operations or Genblaze orchestration. Those integrations must be implemented, recorded, and demonstrated before final submission.
