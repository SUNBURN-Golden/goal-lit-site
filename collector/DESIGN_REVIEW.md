# Design review: Goal Lit collector

**Verdict: APPROVED WITH CONDITIONS**

[DESIGN.md](/workspace/lit-hub/collector/DESIGN.md) addresses all seven requirements explicitly, but several enforcement details remain underspecified. The main gaps concern durable pre-storage sanitization, verification semantics, deduplication boundaries, shared rate limits, and the required status report.

This is a design audit only; implementation behavior and the stated migration counts have not been verified.

## Requirements checklist

| # | Requirement | Assessment | Evidence and remaining conditions |
|---|---|---|---|
| 1 | Three collection paths and a separate local worker | **Pass** | §1 defines automatic, browser, and manual-extension paths, with `local_worker.py` and `storage.py` handling processing. Specify a common ingestion contract so every path necessarily passes through the same validation gates. |
| 2 | Non-official sources admitted as discovered; strict discovered/verified separation; conflict preservation | **Conditional** | Principles and §3.1 explicitly admit non-official leads and distinguish discovery from source checking. Both conflicting claims are preserved with flags. However, confirming that an article contains a statement does not establish the statement’s truth. Define claim-level verification criteria, conflict linkage, and whether unresolved conflicts block promotion. |
| 3 | Pre-storage PII filtering and prompt-injection isolation | **Conditional** | §2 explicitly requires filtering before DB storage and AI delivery. Extension queue persistence follows only “first-pass” masking, leaving uncertainty about full filtering before **all** durable storage. Injection defense specifies pattern detection and replacement but needs an architectural trust boundary independent of detection. |
| 4 | Six Goal Lit fields; five access levels kept separate; three unverified categories | **Conditional** | §3.2 lists all six fields and all five exact access levels; §3.3 lists all three categories. Clarify ambiguous source classification, field-level provenance, and unavailable values. “Review opening” under `paper_abstract` is too broad, and “multiple verified evidence” must never imply `full_text_read`. |
| 5 | Semantic and URL deduplication clustering | **Conditional** | §4 covers normalized URLs, identifiers, textual similarity, and edition grouping. Lexical similarity is a useful baseline but does not establish robust semantic matching across paraphrases or translations. Shared ISBNs and related editions must not collapse distinct source documents or erase contradictions. |
| 6 | Limits of 500/200/1/5 seconds/depth 2; no bypass, proxies, or spoofing | **Conditional** | §5 contains every required value and explicitly prohibits evasion. Define persistent, atomic enforcement across collectors and restarts. In-memory locks alone cannot enforce domain concurrency across separate processes. |
| 7 | Chrome MV3 `activeTab` + `scripting`; persistent queue; five-stage status report; no automatic publishing | **Partial** | §1.3 explicitly specifies MV3 permissions and persistent queues; §3.1 defines five statuses and editorial publication approval. However, a **five-stage status report is not specified**. Queue acknowledgment, idempotency, recovery triggers, and the local endpoint’s access controls also need definition. |

## Conditions for approval

### 1. Make sanitization a prerequisite for every durable write

Apply the full PII and untrusted-text policy before writing to `chrome.storage.local`, SQLite queues, logs, retry payloads, caches, or diagnostic artifacts—not just final records. Include URLs, titles, metadata, and evidence locators.

Define failure behavior: extraction or filtering failures must not cause raw content to be persisted as a fallback.

### 2. Separate evidence checking from truth verification

Record claims with their own provenance, evidence location, access level, and verification decision. Specify the checks required for `source_checked → verified_ready`.

Preserve conflicting claims independently, link them explicitly, and state how unresolved conflicts affect bundle readiness and publication review. A cluster’s representative record must not suppress conflicting evidence.

### 3. Enforce prompt-injection isolation structurally

Treat **all** collected content as untrusted, including content that matches no known injection pattern. Keep it outside privileged instruction channels and prevent it from authorizing tools, changing policy, or initiating publication.

Pattern detection should provide flags and additional handling; it must not be the trust boundary. Preserve sanitized quotations where possible so defensive processing does not silently distort evidence.

### 4. Clarify schema and deduplication boundaries

Distinguish source documents, extracted claims, works, editions, and bundles. ISBN matching establishes an edition relationship; it does not prove two articles are duplicate documents.

Define:

- Classification rules for mixed pages, interviews embedded in articles, and missing abstracts.
- Explicit unknown or pending handling without inventing evidence or defaulting to `press_article`.
- Provenance and access level per supporting source, including bundles with several source types.
- A semantic matching strategy, confidence thresholds, and reversible cluster decisions.
- Separate verification progress and duplicate membership, while retaining the five required reporting categories.

The current `deduped` status is a branch for excluded duplicates, not an obvious sequential stage that every valid record should traverse.

### 5. Centralize collection budgets and recovery

Use a shared persistent scheduler for daily counters, domain locks, minimum intervals, and backoff. Specify the day boundary, domain grouping, retry accounting, rechecks, and coverage of redirects and browser-generated requests.

For extension delivery, define stable clip IDs, acknowledgment after durable acceptance, idempotent retries, and restart/resume triggers. Specify how the extension may access the loopback endpoint and how that endpoint rejects unauthorized submissions.

### 6. Specify the five-stage status report and publication gate

Add a report contract covering:

`discovered`, `source_checked`, `deduped`, `verified_ready`, `publish_pending`.

Define current-state counts versus transition totals, unique-document versus claim counts, reporting period, last update, backlog, failures, and conflicts. Avoid counting one document’s derived claims as multiple independent sources.

Make editorial approval explicit and bound to the reviewed content version. Automated collectors and workers must have no execution path that publishes pending content.

## Implementation edge cases

| Edge case | Expected behavior |
|---|---|
| Worker commits a clip but the extension loses the acknowledgment | Retry returns the existing result; no duplicate record or repeated budget charge. |
| Extension shuts down between extraction and queue persistence | Recovery has a defined outcome; no raw-content fallback or false success notification. |
| Two collectors start requests to the same domain simultaneously | Shared coordination enforces one request at a time and the minimum interval. |
| Restart, midnight rollover, or clock changes occur during backoff | Counters and backoff survive; no accidental budget reset or burst. |
| An approved URL redirects to a restricted domain or private address | Revalidate the destination and access policy before fetching it. |
| A browser page loads background requests or follows links after rendering | Scheduler coverage and request accounting are explicit; rendering does not bypass limits. |
| Two articles cite the same ISBN but make different claims | Preserve both documents and claims; link the edition without falsely deduplicating the articles. |
| Near-identical reports contain different sales figures | Preserve the difference and flag the conflict despite high textual similarity. |
| A URL changes content, or query parameters select distinct editions | Preserve source versions and meaningful parameters; normalization must not merge distinct evidence. |
| An interview quotes an abstract and a book passage | Track provenance for each extracted claim; do not infer full-work reading. |
| PII appears in URL parameters, metadata, or error messages | Sanitize before persistence, including queues and logs. |
| Injection is multilingual, encoded, or phrased as literary dialogue | Untrusted-content isolation holds regardless of detector results; legitimate quotations remain traceable. |
| One legacy item contains bibliography, speech, and interpretation claims | Split or classify constituent claims while preserving the original migration linkage. |
| Pending content changes after editorial approval | Require approval for the changed version before publication. |

## Final verdict

**APPROVED WITH CONDITIONS.** The architecture covers the requested scope and states the correct collection and publication principles. Before implementation is accepted, resolve the six conditions above—especially pre-storage filtering across queues, enforceable verification boundaries, shared politeness controls, and the missing five-stage status-report specification.
