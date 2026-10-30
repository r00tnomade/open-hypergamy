# Controlled onboarding milestone 1: S22 Cyber Valley and S07 NLnet

Run on 2026-10-30 (Europe/Berlin), 15:05 to 15:15, in throwaway `OHG_HOME` directories with the LLM and Telegram disabled. Nothing here activates a source, and `config/sources/*.yaml` is unchanged.

**Operator decision:** S22 and S07 may enter a *restricted pilot*. This is an operational decision, **not legal clearance and not a content-reuse licence**. No explicit reuse or automated-access terms were located for either publisher; that absence is not permission. S01 (euRobotics) and S05 (CERN openlab) stay on HOLD. S02 (RIG) stays conditional, with deterministic extraction only and external LLM processing disabled. None of those three appears in the reviewed file.

Reviewed configuration: [`s22-s07.reviewed.yaml`](s22-s07.reviewed.yaml). Both entries are `enabled: false`.

## Policy review records

| | S22 Cyber Valley | S07 NLnet |
|---|---|---|
| Publisher | Cyber Valley GmbH | NLnet Foundation |
| Endpoint | `https://cyber-valley.de/career/` plus `/job/<slug>/` pages at depth 1 | `https://nlnet.nl/propose/`, no link following |
| Reviewed at | 2026-10-30T15:05:58+01:00 | 2026-10-30T15:05:58+01:00 |
| Terms found | Imprint and privacy policy only | Privacy statement only (its own text is CC0, which does not cover site content) |
| robots.txt (informational, ADR-008) | Only ClaudeBot named, with an empty Disallow; no Crawl-delay | Disallow `/cgi-bin/`, `/help*`, `/*?*`; no Crawl-delay. The config avoids those paths voluntarily |
| Limits | `allow_paths: /job/`, 24 h polling, 20-page cap, minimal factual metadata, no copying of descriptions | One page, 24 h polling, no query strings, minimal factual metadata, the Atom feed is not used |
| Residual uncertainty | Reuse terms unknown | Reuse terms unknown |

## Technical validation

| Step | S22 | S07 |
|---|---|---|
| Probe (`ohg sources probe`) | ok: 200, 70 links | ok: 200, 52 links |
| Import | created, disabled | created, disabled |
| Audit | counted in `europe_research`, 0 enabled | counted in `funding_fellowships`, 0 enabled |
| Ingestion (one-shot, isolated DB; sources enabled only there) | success, 18 pages, all HTTP 200 | success, 1 page, HTTP 200 |
| Repeat fetch | not repeated (to avoid extra load) | `not_modified`; no new rows |

Requests to the publishers: 2 probes, 1 link inspection, then 2 ingestion runs (19 pages each) and 1 repeat fetch of NLnet. No retries, no non-200 responses.

## Data quality

**S22: 17 job pages listed, 17 fetched and persisted, 0 duplicates.**
- 7 pages became candidates. 10 did not. All 7 were held as `edition_key_unknown`.
- Missing deadlines: 17 of 17. The pages carry no dates.
- Invalid or incomplete URLs: 0.
- **False positives (2):** "Fremdsprachensekretär:in" (a secretary role) and "Founding team wanted for a new biotech company". Neither is a research or education opportunity.
- **False negatives (2 student roles, 8 others):** "Computer Vision Engineer – Working Student" and "Student Assistant CELLnROLL" are not candidates because the wording rules know "internship" but not "working student", "student assistant" or "HiWi". These are the roles most relevant to a bachelor student.
- PhD and postdoc roles (4 of the 7 candidates) are correctly extracted but unlikely to suit a bachelor student; eligibility scoring marks them `possibly_eligible`, which is the honest answer when the page has no eligibility statement.
- Useful opportunities after manual review: about 1 of 7 candidates ("Research internship for PhD students", whose title says PhD students).

**S07: 1 page, 1 candidate, 0 duplicates.**
- The first run (with the draft's invalid `source_type: listing_page`) produced no candidate. This was my configuration error. The corrected type is `official_call_page`.
- Deadline extracted: `November 3rd 2026`, verified by rule from an official page, shown as **confirmed**.
- **The stated time is lost:** the page says "12:00 CET (noon)", the stored deadline is date-only and the timezone is empty. The excerpt keeps the full sentence, but reminders and the digest count the whole day. The deadline actually closes at noon.
- Title is stored as "NLnet; Apply for a grant" (site-name suffix not stripped).
- Not modelled: NLnet's call is rolling. When the page moves to the next deadline the system will see a changed deadline, not a new edition.

## Pipeline results

- Candidates: 8 (7 + 1), all `edition_key_unknown`. The design never infers a year, so none were promoted automatically.
- Manual promotion with an explicit edition key (isolated DB, 3 candidates): 3 editions, 1 deadline. NLnet is `confirmed_official` (date-only). Both Cyber Valley editions are `unverified` with an unknown closing date.
- Scoring with the repo's example profile (not a real profile): fit 52.8, 42.8 and 40.2. NLnet urgency 90 with reasons `APPLICATION_OPEN`, `DEADLINE_WITHIN_14_DAYS`, `ELIGIBILITY_UNCLEAR`.
- Weekly report: generated, lists the 3 opportunities and the NLnet deadline in the 7-day table.
- Telegram digest: generated with `ohg run digest --dry-run`; `notification_log` holds 0 rows. Nothing was sent.
- Stale review items: the 3 manually promoted candidates still have `pending` rows in `review_queue`, so the report says 8 pending instead of 5.

## Verdict

| Criterion | S22 | S07 |
|---|---|---|
| Policy review recorded | yes | yes |
| Config validates, probe, real ingestion | yes | yes |
| Dedup and persistence | yes | yes |
| Report and digest generation | yes | yes |
| Data-quality checks pass | **no** | **no** (time dropped, rolling call) |

Neither source is technically validated yet. Activation is a separate decision and was not made.

## Remaining blockers

1. **Working-student and student-assistant roles are not recognised** (S22, the main false negative). Needs a wording-rule change and tests; it affects every source.
2. **Stated deadline times are dropped** (S07). A `12:00 CET` should be stored with its timezone, not as date-only.
3. **Rolling postings and calls have no edition key**, so everything needs manual `--edition-key` promotion. Needs a decision on how to model rolling calls.
4. **Stale review-queue rows** after manual promotion.
5. Two false positives in S22 (non-research roles); cosmetic title cleanup for S07.

The same `source_type` mistake (`listing_page`, `feed`) was in all 32 draft configs under `draft_sources/`; they now use `official_programme_index`.
