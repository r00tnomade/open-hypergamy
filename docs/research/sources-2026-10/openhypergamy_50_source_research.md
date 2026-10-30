# OpenHypergamy: 50 opportunity sources - research report

Generated 2026-10-30T01:17:45+01:00 (Europe/Berlin). Verification pass 2026-10-30T01:17:32+01:00 to 2026-10-30T01:17:45+01:00.
## 1. Executive summary
Exactly 50 distinct sources were researched. Status counts: **35 PROBE_PASSED**, **1 RESEARCH_VERIFIED**, **14 MANUAL_REVIEW**. **0 sources are activated, approved (stage F) or ingestion-validated (stage E).**
PROBE_PASSED here means one robots-checked GET of the exact endpoint returned HTTP 200 during the verification pass. It is not a policy approval: for most sources the terms of use were not read in full, so policy is `unclear` and each needs a human terms review before `terms_review_note` is recorded. The `ohg sources probe` command was not run against these candidates in this document's pass (see Limitations).
The P0 sources (S01, S02, S05, S07, S22) are the highest-value onboarding targets, conditional on that terms review. 12 sources need an adapter that does not exist yet.
## 2. Repository compatibility
- Implemented adapters: `rss_atom`, `html`, `sitemap`. `ical` and `playwright` are **not** implemented (such sources are skipped). There is no JSON/YAML data adapter and no authenticated-API support.
- `Crawl-delay` in robots.txt is not honoured by the fetcher (CTFtime asks for 10 s), so S10 needs a code change before activation.
- The strict date parser flags yearless and two-digit-year dates (MLH, GSoC, ELLIS), which will land as `needs_review`, not confirmed.
- A source activates only with both `robots_policy_checked_at` and a non-empty `terms_review_note`. The draft YAML omits both on purpose and sets `enabled: false`.
- Draft files use the existing `SourceConfig` schema (`extra=forbid`); they live under `draft_sources/`, outside `config/sources/`.
## 3. The 50 sources
| ID | Cat | Source | Endpoint | Method | Status | Policy | Score | Pri |
|---|---|---|---|---|---|---|---|---|
| S01 | B | euRobotics news & calls feed | https://eu-robotics.net/feed/ | rss_atom | PROBE_PASSED | unclear | 21 | P0 |
| S02 | B | Robotics Institute Germany news feed | https://robotics-institute-germany.de/feed/ | rss_atom | PROBE_PASSED | unclear | 22 | P0 |
| S03 | A | lablab.ai AI hackathons | https://lablab.ai/ai-hackathons | html | PROBE_PASSED | unclear | 19 | P1 |
| S04 | A | MLH season events | https://www.mlh.com/seasons/2027/events | html | PROBE_PASSED | unclear | 20 | P1 |
| S05 | C | CERN openlab summer student programme | https://openlab.cern/cern-openlab-summer-student-programme/ | html | PROBE_PASSED | unclear | 20 | P0 |
| S06 | C | DESY Summer Student Programme | https://summerstudents.desy.de/ | html | PROBE_PASSED | unclear | 17 | P2 |
| S07 | D | NLnet grants (calls + news Atom) | https://nlnet.nl/propose/ | html+rss_atom | PROBE_PASSED | unclear | 23 | P0 |
| S08 | E | CCF-Deadlines conference data (GitHub) | https://raw.githubusercontent.com/ccfddl/ccf-deadlines/main/conference/AI/nips.yml | yaml/json data adapter (missing) | PROBE_PASSED | no_restriction_observed | 20 | P1 |
| S09 | E | WikiCFP RSS (machine learning, robotics) | http://www.wikicfp.com/cfp/rss?cat=machine%20learning | rss_atom | PROBE_PASSED | unclear | 15 | P2 |
| S10 | F | CTFtime upcoming events (RSS + API) | https://ctftime.org/event/list/upcoming/rss/ | rss_atom | PROBE_PASSED | unclear | 20 | P1 |
| S11 | B | IEEE RAS events calendar (iCal) + news feed | https://www.ieee-ras.org/events/?ical=1 | ical (missing) | PROBE_PASSED | unclear | 21 | P1 |
| S12 | B | TUM MIRMI news & events RSS | https://www.mirmi.tum.de/mirmi/rss.xml | rss_atom | PROBE_PASSED | unclear | 20 | P1 |
| S13 | A | Kaggle competitions (official API) | https://github.com/Kaggle/kaggle-api | authenticated JSON API (missing) | RESEARCH_VERIFIED | unclear | 20 | P1 |
| S14 | A | European Hackathon League | https://ehl.gg/ | html | PROBE_PASSED | unclear | 17 | P2 |
| S15 | C | FZI Karlsruhe careers (internships, theses, student jobs) | https://www.fzi.de/en/career/ | html | MANUAL_REVIEW | unclear | 17 | P2 |
| S16 | D | Sovereign Tech Fellowship | https://www.sovereign.tech/programs/fellowship | html+rss_atom | PROBE_PASSED | unclear | 18 | P2 |
| S17 | D | Erasmus+ opportunities for students | https://erasmus-plus.ec.europa.eu/opportunities/individuals/students | html | PROBE_PASSED | no_restriction_observed | 15 | P2 |
| S18 | E | NeurIPS dates and deadlines | https://neurips.cc/Conferences/2026/Dates | html | PROBE_PASSED | unclear | 22 | P1 |
| S19 | F | Codeforces contests (official API) | https://codeforces.com/api/contest.list?gym=false | JSON API adapter (missing) | PROBE_PASSED | no_restriction_observed | 20 | P2 |
| S20 | F | Google Summer of Code timeline | https://developers.google.com/open-source/gsoc/timeline | html | PROBE_PASSED | unclear | 20 | P1 |
| S21 | B | euROBIN events and competitions | https://www.eurobin-project.eu/index.php/events | html | PROBE_PASSED | unclear | 18 | P1 |
| S22 | B | Cyber Valley careers | https://cyber-valley.de/career/ | html | PROBE_PASSED | unclear | 20 | P0 |
| S23 | A | TUM.ai events and hackathons | https://www.tum-ai.com/events | html | PROBE_PASSED | unclear | 17 | P1 |
| S24 | A | EvalAI challenges | https://eval.ai/api/challenges/challenge/present/approved/public | JSON API adapter (missing) | MANUAL_REVIEW | unclear | 16 | P2 |
| S25 | C | IAESTE Germany | https://www.iaeste.de/de/ | html | MANUAL_REVIEW | unclear | 13 | P2 |
| S26 | C | Max Planck Institute for Informatics job openings | https://www.mpi-inf.mpg.de/career/job-openings | html | MANUAL_REVIEW | unclear | 17 | P2 |
| S27 | D | Studienstiftung des deutschen Volkes | https://www.studienstiftung.de/ | html | PROBE_PASSED | unclear | 14 | P2 |
| S28 | E | ICLR 2027 | https://iclr.cc/ | html | PROBE_PASSED | unclear | 21 | P1 |
| S29 | E | CVPR 2027 | https://cvpr.thecvf.com/ | html | PROBE_PASSED | unclear | 21 | P1 |
| S30 | F | Outreachy internships | https://www.outreachy.org/ | html | PROBE_PASSED | unclear | 20 | P2 |
| S31 | B | ELLIS event calendar | https://ellis.eu/event-calendar | html | PROBE_PASSED | unclear | 20 | P1 |
| S32 | B | Helmholtz AI | https://www.helmholtz.ai/ | html | PROBE_PASSED | unclear | 19 | P2 |
| S33 | A | Codabench public competitions | https://www.codabench.org/competitions/public/ | JSON API / JS render (missing) | MANUAL_REVIEW | unclear | 13 | P2 |
| S34 | A | Junction hackathon | https://www.hackjunction.com/ | Playwright (missing) | MANUAL_REVIEW | unclear | 11 | Hold |
| S35 | C | TH Mannheim Career Center | https://www.career.hs-mannheim.de/ | html | MANUAL_REVIEW | unclear | 16 | P2 |
| S36 | D | DAAD scholarship database | https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/ | form/search (missing) | MANUAL_REVIEW | unclear | 16 | Hold |
| S37 | D | Deutschlandstipendium (BMFTR) | https://www.deutschlandstipendium.de/deutschlandstipendium/de/home/home_node.html | html | PROBE_PASSED | unclear | 14 | P2 |
| S38 | E | CoRL 2026 | https://www.corl.org/ | html | PROBE_PASSED | unclear | 19 | P1 |
| S39 | F | Cyber Security Challenge Germany (CSCG) | https://cscg.de/ | html | PROBE_PASSED | unclear | 17 | P2 |
| S40 | F | European Cybersecurity Challenge (ECSC) | https://ecsc.eu/ | html | PROBE_PASSED | unclear | 15 | P2 |
| S41 | B | Open Robotics Discourse – Jobs category | https://discourse.openrobotics.org/c/jobs/15 | html | PROBE_PASSED | restricted | 20 | P1 |
| S42 | B | RoboCup news and events | https://www.robocup.org/ | html | MANUAL_REVIEW | restricted | 16 | P2 |
| S43 | A | Devpost hackathons | https://devpost.com/hackathons | none until access is permitted | MANUAL_REVIEW | blocked | 15 | Hold |
| S44 | A | DrivenData competitions | https://www.drivendata.org/competitions/ | html | MANUAL_REVIEW | prohibited | 13 | Hold |
| S45 | C | ESA careers portal (students & graduates) | https://jobs.esa.int/ | Playwright (missing) | MANUAL_REVIEW | unclear | 12 | Hold |
| S46 | C | EURAXESS jobs | https://euraxess.ec.europa.eu/jobs/search | none while robots disallows | MANUAL_REVIEW | blocked | 18 | Hold |
| S47 | D | Fulbright Germany | https://www.fulbright.de/ | html | PROBE_PASSED | unclear | 17 | P2 |
| S48 | E | RSS: Robotics Science and Systems 2027 | https://roboticsconference.org/ | html | PROBE_PASSED | unclear | 22 | P1 |
| S49 | E | Eastern European Machine Learning (EEML) Summer School | https://www.eeml.eu/ | html | PROBE_PASSED | unclear | 17 | P2 |
| S50 | F | LFX Mentorship | https://mentorship.lfx.linuxfoundation.org/ | Playwright / JSON API (missing) | MANUAL_REVIEW | unclear | 13 | Hold |
## 4. Batches
- Batch 1: [batch_01.md](batch_01.md) - 10 sources
- Batch 2: [batch_02.md](batch_02.md) - 10 sources
- Batch 3: [batch_03.md](batch_03.md) - 10 sources
- Batch 4: [batch_04.md](batch_04.md) - 10 sources
- Batch 5: [batch_05.md](batch_05.md) - 10 sources

## 5. Category counts

| Cat | Name | Target | Actual |
|---|---|---|---|
| A | AI/ML hackathons and competitions | 10 | 10 |
| B | Robotics and research opportunities | 10 | 10 |
| C | Research internships and student technical opportunities | 8 | 8 |
| D | Scholarships, fellowships and grants | 7 | 7 |
| E | AI/ML conferences, workshops and summer schools | 8 | 8 |
| F | Open-source programmes, technical challenges and cybersecurity | 7 | 7 |
| | **Total** | 50 | 50 |

## 6. Detailed profiles

Full profiles with evidence and score rationales are in the batch files (same content as in the JSON).

## 7. Rejected and substituted candidates (not counted)

| Candidate | Reason | Replaced by |
|---|---|---|
| AIcrowd challenges | Terms prohibit automated access ('monitor (e.g. spider, scrape) the Platform'); the list is JavaScript-loaded ('Loading Challenges'). | Codabench / EvalAI / lablab.ai |
| ARC Prize | Terms prohibit bots/scrapers; competitions run on Kaggle, which is already covered (S13). | Kaggle (S13) |
| Hack Club hackathons | Page is titled 'High School Hackathons in 2026'; the target profile is a university student. | MLH (S04) |
| HackZurich | Site states 'HackZurich is currently on hiatus'. | European Hackathon League (S14) |
| DoraHacks hackathons | HTTP 405 to our agent for the page and robots.txt; no usable endpoint. | lablab.ai (S03) |
| DFKI career pages | Bot challenge ('Just a moment...', HTTP 403); not circumvented. | FZI (S15), Cyber Valley (S22) |
| Max Planck Institute for Intelligent Systems jobs | Redirects to a bot-detection challenge page. | Cyber Valley (S22) |
| Prototype Fund | Security interstitial ('Establishing a secure connection', HTTP 403) for our agent. | NLnet (S07), Sovereign Tech (S16) |
| DLR careers | TLS certificate chain cannot be verified ('unable to get local issuer certificate'); not bypassed. | Helmholtz AI (S32) |
| RoboCup German Open (robocup.de) | TLS certificate verification fails. | RoboCup (S42) |
| Stipendienlotse | TLS certificate verification fails. | DAAD (S36), Studienstiftung (S27) |
| MLSS (mlss.cc) | TLS certificate verification fails; MLSS 2027 Okinawa is covered by a single event page only. | ELLIS (S31), EEML (S49) |
| NASA Space Apps | TLS certificate verification fails. | MLH (S04) |
| DAAD RISE Germany | Eligibility excludes the target profile (a bachelor student at a German university): 'You are enrolled as Master or Ph.D. student or a Bachelor who is a RISE Germany-Alumni at a North American, British or Irish university'. The programme feed is also stale (newest item 2016). | FZI (S15) |
| AI Deadlines (aideadlin.es) | Underlying repository last pushed 2024-09-15 (stale); overlaps with CCF-Deadlines (S08). | CCF-Deadlines (S08) |
| HackHPI | Single annual event page whose visible edition is 10-11 April 2026; narrow value. | TUM.ai (S23) |
| ETH Zurich RSL student projects | URL returned 404 and no replacement listing was found. | Cyber Valley (S22) |
| CERN openlab (guessed URL) | Guessed path returned 404; correct page found from the homepage and used instead (S05). | S05 |
| Google Student Researcher / Microsoft Research academic pages | Guessed URLs returned 404; no official listing endpoint verified. | CERN openlab (S05) |
| Fraunhofer IPA jobs / HPI careers / ZIB jobs | Guessed URLs returned 404; not verified. | FZI (S15) |
| picoCTF | Site now redirects visitors to the CMU CyLab Security Academy; no event list on the fetched page. | CTFtime (S10) |
| MLH Fellowship (spare) | Same publisher as S04; static page has no dated cycles. Kept as a spare rather than counted. | Outreachy (S30) |

## 8. Top 10 to onboard first

Ranked by total score among P0/P1 sources with PROBE_PASSED; each still needs a terms review.

| # | ID | Source | Score | Priority |
|---|---|---|---|---|
| 1 | S07 | NLnet grants (calls + news Atom) | 23 | P0 |
| 2 | S02 | Robotics Institute Germany news feed | 22 | P0 |
| 3 | S18 | NeurIPS dates and deadlines | 22 | P1 |
| 4 | S48 | RSS: Robotics Science and Systems 2027 | 22 | P1 |
| 5 | S01 | euRobotics news & calls feed | 21 | P0 |
| 6 | S11 | IEEE RAS events calendar (iCal) + news feed | 21 | P1 |
| 7 | S28 | ICLR 2027 | 21 | P1 |
| 8 | S29 | CVPR 2027 | 21 | P1 |
| 9 | S04 | MLH season events | 20 | P1 |
| 10 | S05 | CERN openlab summer student programme | 20 | P0 |

## 9. Suggested sequence

1. Terms review plus `robots_policy_checked_at` for the top 10 (one source at a time).
2. `ohg sources probe` on the draft batch, then `ohg sources import` once the review note is written.
3. Run discovery once, inspect candidates and the review queue, only then widen.
4. Build the missing adapters in the order of unlocked sources (below).

## 10. Adapter gaps

- **JSON API / JS render (missing)**: S33
- **JSON API adapter (missing)**: S19, S24
- **Playwright (missing)**: S34, S45
- **Playwright / JSON API (missing)**: S50
- **authenticated JSON API (missing)**: S13
- **form/search (missing)**: S36
- **ical (missing)**: S11
- **none until access is permitted**: S43
- **none while robots disallows**: S46
- **yaml/json data adapter (missing)**: S08

## 11. Risks before private beta

- Policy: 42 of 50 sources have `unclear` policy; one is `prohibited` (S44), two `blocked` (S43, S46), two `restricted` (S41, S42).
- Yield: many landing pages carry news but no deadlines; expect low yield until sub-pages (dates, calls) are added per source.
- Staleness: yearly conference sites change URL/structure; feeds for S39 and S48 are stale.
- Date handling: yearless/two-digit dates will be flagged for review, not auto-confirmed.
- Undocumented endpoint: S24 (EvalAI) works but its documentation status is unverified.
- Eligibility: Outreachy, Fulbright, Studienstiftung eligibility for the target profile is unverified.
- Coverage: no industry-programme sources were accessible; the portfolio is research-heavy.

## 12. Limitations

- One robots-checked GET per endpoint at the verification time; no repeated sampling, so freshness and stability judgements are single observations.
- Terms of use were read for a subset only (see each profile's Terms line); `Not reviewed` means exactly that.
- Content fetched from sites was treated as untrusted data and used only for factual extraction.
- S13's endpoint field points at the official client repository, not a probed API call; no authenticated request was made.
- `ohg sources probe` is a separate check and was not recorded for the drafts here.
- Values marked `estimate` are the researcher's proposals, not source-published guidance.

## 13. `ohg sources probe` results (existing html/rss_atom adapters)

Run with a throwaway `OHG_HOME`; the command writes nothing and imports nothing. Only entries whose adapter exists, whose policy is not prohibited/blocked and whose endpoint passed the harness were drafted: 32 of 50. All returned `ok`. Notes: S07 was drafted with the `html` adapter, so NLnet's 2.8 MB Atom feed was not exercised through `rss_atom`; `0 entries` is expected for HTML pages (entries only count for feeds). `ok` means fetch+parse worked, not that useful deadlines were extracted.

| ID | Result | Detail | Time (Europe/Berlin) |
|---|---|---|---|
| S01 | ok | 200, 5009 chars, 10 links, 10 entries | 2026-10-30T01:18:56+0100 |
| S02 | ok | 200, 7833 chars, 10 links, 10 entries | 2026-10-30T01:18:56+0100 |
| S03 | ok | 200, 326 chars, 38 links, 0 entries | 2026-10-30T01:18:56+0100 |
| S04 | ok | 200, 7772 chars, 111 links, 0 entries | 2026-10-30T01:18:56+0100 |
| S05 | ok | 200, 4888 chars, 42 links, 0 entries | 2026-10-30T01:18:56+0100 |
| S06 | ok | 200, 2084 chars, 30 links, 0 entries | 2026-10-30T01:18:56+0100 |
| S07 | ok | 200, 1011 chars, 52 links, 0 entries | 2026-10-30T01:18:56+0100 |
| S09 | ok | 200, 6084 chars, 20 links, 20 entries | 2026-10-30T01:18:56+0100 |
| S10 | ok | 200, 20529 chars, 38 links, 38 entries | 2026-10-30T01:18:56+0100 |
| S12 | ok | 200, 7882 chars, 15 links, 15 entries | 2026-10-30T01:19:28+0100 |
| S14 | ok | 200, 697 chars, 42 links, 0 entries | 2026-10-30T01:19:28+0100 |
| S16 | ok | 200, 7662 chars, 27 links, 0 entries | 2026-10-30T01:19:28+0100 |
| S17 | ok | 200, 1495 chars, 57 links, 0 entries | 2026-10-30T01:19:28+0100 |
| S18 | ok | 200, 6087 chars, 71 links, 0 entries | 2026-10-30T01:19:28+0100 |
| S20 | ok | 200, 3981 chars, 41 links, 0 entries | 2026-10-30T01:19:28+0100 |
| S21 | ok | 200, 244 chars, 55 links, 0 entries | 2026-10-30T01:19:53+0100 |
| S22 | ok | 200, 592 chars, 70 links, 0 entries | 2026-10-30T01:19:53+0100 |
| S23 | ok | 200, 1716 chars, 17 links, 0 entries | 2026-10-30T01:19:53+0100 |
| S27 | ok | 200, 2969 chars, 128 links, 0 entries | 2026-10-30T01:19:53+0100 |
| S28 | ok | 200, 3080 chars, 54 links, 0 entries | 2026-10-30T01:19:53+0100 |
| S29 | ok | 200, 519 chars, 33 links, 0 entries | 2026-10-30T01:19:53+0100 |
| S30 | ok | 200, 3633 chars, 34 links, 0 entries | 2026-10-30T01:19:53+0100 |
| S31 | ok | 200, 8709 chars, 51 links, 0 entries | 2026-10-30T01:20:18+0100 |
| S32 | ok | 200, 1171 chars, 64 links, 0 entries | 2026-10-30T01:20:18+0100 |
| S37 | ok | 200, 1893 chars, 88 links, 0 entries | 2026-10-30T01:20:18+0100 |
| S38 | ok | 200, 1891 chars, 101 links, 0 entries | 2026-10-30T01:20:18+0100 |
| S39 | ok | 200, 314 chars, 17 links, 0 entries | 2026-10-30T01:20:18+0100 |
| S40 | ok | 200, 2035 chars, 18 links, 0 entries | 2026-10-30T01:20:18+0100 |
| S41 | ok | 200, 3510 chars, 129 links, 0 entries | 2026-10-30T01:20:46+0100 |
| S47 | ok | 200, 1558 chars, 51 links, 0 entries | 2026-10-30T01:20:46+0100 |
| S48 | ok | 200, 1325 chars, 9 links, 0 entries | 2026-10-30T01:20:46+0100 |
| S49 | ok | 200, 1446 chars, 195 links, 0 entries | 2026-10-30T01:20:46+0100 |
