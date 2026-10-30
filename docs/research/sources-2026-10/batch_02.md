# Batch 2 (10 sources)

Verification pass: 2026-10-30T01:17:32+01:00 (Europe/Berlin). Nothing here is activated.

| ID | Cat | Source | Endpoint | Method | Status | Policy | Score | Pri |
|---|---|---|---|---|---|---|---|---|
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

## Profiles

### S11 - IEEE RAS events calendar (iCal) + news feed  
**Status:** PROBE_PASSED | **Priority:** P1 | **Score:** 21/25 | **Confidence:** high

- **Publisher:** IEEE Robotics and Automation Society (first-party society)
- **Category:** B - Robotics and research opportunities | **Batch:** 2
- **Canonical URL:** https://www.ieee-ras.org/
- **Endpoint:** https://www.ieee-ras.org/events/?ical=1
- **Discovery:** iCalendar feed (30 VEVENTs observed); RSS at https://www.ieee-ras.org/feed/
- **Opportunity types:** robotics conferences and workshops; calls; competitions (via news)
- **Audience/eligibility:** Robotics researchers and students.
- **Geography / remote:** Global / Some virtual events
- **Value:** Society calendar with structured dates for 30 upcoming events; strongest robotics conference lead source found.
- **Auth / registration:** none / none
- **Adapter fit:** ical (missing) (gap) | stable IDs: iCal UID per event | dates: Yes (DTSTART) | difficulty: Medium: needs the iCal adapter (not implemented); RSS works today.
- **Policy:** unclear - robots.txt allows /events/ and /feed/; terms not reviewed.
- **Terms:** https://www.ieee-ras.org/ - Terms not located in this run.
- **Rate limits:** None published | **Polling guidance:** estimate 24 h with conditional GET | **Proposed interval:** 24 h | **Stability:** Medium: WordPress events plugin export.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://www.ieee-ras.org/events/?ical=1 - robots allowed=True (robots HTTP 200), HTTP 200, text/calendar, 32774 bytes
- **Evidence:**
  - iCal export returns 30 VEVENTs, first 'International Conference on Control, Automation and Systems' 2026-10-27 - <https://www.ieee-ras.org/events/?ical=1>
  - RSS feed valid, newest 29 Oct 2026 - <https://www.ieee-ras.org/feed/>
  - Homepage advertises both feeds via <link rel=alternate> - <https://www.ieee-ras.org/conferences-workshops>
- **Scores:** relevance 4 (Core robotics venues and workshops.) | authority 5 (Society is the publisher.) | signal quality 4 (Structured start dates; deadlines need linking.) | freshness 5 (Events from the current week.) | integration 3 (iCal adapter missing; RSS fallback works.)
- **Uncertainties:** Event deadline fields (CFPs) not in iCal
- **Next action:** Onboard the RSS feed now; implement the iCal adapter for the calendar.
- **Stages:** A=yes, B=no, C=no, D=yes, E=no, F=no

### S12 - TUM MIRMI news & events RSS  
**Status:** PROBE_PASSED | **Priority:** P1 | **Score:** 20/25 | **Confidence:** medium

- **Publisher:** Munich Institute of Robotics and Machine Intelligence (TUM) (first-party)
- **Category:** B - Robotics and research opportunities | **Batch:** 2
- **Canonical URL:** https://www.mirmi.tum.de/mirmi/startseite/
- **Endpoint:** https://www.mirmi.tum.de/mirmi/rss.xml
- **Discovery:** Atom/RSS feed (news; events on homepage)
- **Opportunity types:** news; events; research group announcements
- **Audience/eligibility:** Robotics/AI community at TUM and visitors.
- **Geography / remote:** Germany (Munich) / n/a
- **Value:** Top German robotics institute; feed updated 28 Oct 2026; local events and groups.
- **Auth / registration:** none / none
- **Adapter fit:** rss_atom (existing) | stable IDs: Atom entry id (news-NNNN.atom) | dates: Publication dates yes; event dates in text | difficulty: Low: existing adapter; mixed German/English content.
- **Policy:** unclear - robots.txt allows; terms not reviewed.
- **Terms:** https://www.mirmi.tum.de/mirmi/startseite/ - Not reviewed.
- **Rate limits:** None published | **Polling guidance:** estimate 24 h | **Proposed interval:** 24 h | **Stability:** High: university web platform.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://www.mirmi.tum.de/mirmi/rss.xml - robots allowed=True (robots HTTP 200), HTTP 200, text/xml, 62128 bytes
- **Evidence:**
  - Feed 'RSS des Munich Institute of Robotics and Machine Intelligence' returned entries, latest 2026-10-28 - <https://www.mirmi.tum.de/mirmi/rss.xml>
  - Homepage shows 'Events' and 'News' sections with dated items - <https://www.mirmi.tum.de/mirmi/startseite/>
- **Scores:** relevance 4 (German robotics institute; mostly research news.) | authority 5 (University institute, first-party.) | signal quality 2 (Few explicit application opportunities.) | freshness 5 (Updated 28 Oct 2026.) | integration 4 (Existing adapter; German text.)
- **Uncertainties:** How often feed carries student/job opportunities
- **Next action:** Probe with ohg; review for relevance after 4 weeks.
- **Stages:** A=yes, B=no, C=yes, D=yes, E=no, F=no

### S13 - Kaggle competitions (official API)  
**Status:** RESEARCH_VERIFIED | **Priority:** P1 | **Score:** 20/25 | **Confidence:** medium

- **Publisher:** Kaggle (Google) (first-party platform)
- **Category:** A - AI/ML hackathons and competitions | **Batch:** 2
- **Canonical URL:** https://www.kaggle.com/competitions
- **Endpoint:** https://github.com/Kaggle/kaggle-api
- **Discovery:** Authenticated official API/CLI (the listing page is a JavaScript app); endpoint field points at the official client repository that documents it
- **Opportunity types:** ML competitions; hackathons; prize challenges
- **Audience/eligibility:** Anyone with an account; competition rules apply.
- **Geography / remote:** Global / Yes
- **Value:** Primary venue for ML competitions; official API client lists competitions.
- **Auth / registration:** API credentials required / Kaggle account + API token
- **Adapter fit:** authenticated JSON API (missing) (gap) | stable IDs: Competition slug/id | dates: Deadlines via API (not called) | difficulty: High: credentials, JSON adapter and secret handling needed.
- **Policy:** unclear - Listing page is an app shell (0 visible characters); API requires credentials; no call was made.
- **Terms:** https://www.kaggle.com/terms - Terms page is JavaScript-rendered; not readable by this run.
- **Rate limits:** Not verified | **Polling guidance:** estimate 24 h | **Proposed interval:** 24 h | **Stability:** High.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://github.com/Kaggle/kaggle-api - robots allowed=True (robots HTTP 200), HTTP 404, text/html, 231812 bytes
- **Evidence:**
  - Official README: 'List competitions, download competition data, submit to a competition'; credentials required - <https://raw.githubusercontent.com/Kaggle/kaggle-api/main/README.md>
  - Listing page responds 200 but is a JS app (title 'AI Competitions and Hackathons | Kaggle') - <https://www.kaggle.com/competitions>
- **Scores:** relevance 5 (Directly on target for applied AI.) | authority 5 (First-party platform.) | signal quality 4 (API exposes deadlines (not verified).) | freshness 5 (Continuous flow.) | integration 1 (Needs auth + new adapter; no live probe.)
- **Uncertainties:** Exact API endpoint behaviour/quotas; Terms on automated use
- **Next action:** Decide whether to store an API token; design adapter before activation.
- **Stages:** A=yes, B=yes, C=no, D=no, E=no, F=no

### S14 - European Hackathon League  
**Status:** PROBE_PASSED | **Priority:** P2 | **Score:** 17/25 | **Confidence:** medium

- **Publisher:** European Hackathon League (founded by TUM.ai) (first-party)
- **Category:** A - AI/ML hackathons and competitions | **Batch:** 2
- **Canonical URL:** https://ehl.gg/
- **Endpoint:** https://ehl.gg/
- **Discovery:** Static site with dated matches (HTML)
- **Opportunity types:** competitive hackathon league (5 matches in Munich, Paris, Zurich)
- **Audience/eligibility:** Students/teams (details on site).
- **Geography / remote:** Europe / No (on-site)
- **Value:** Europe-focused AI/tech hackathon league with 10 dated entries on the home page.
- **Auth / registration:** none / none for browsing
- **Adapter fit:** html (existing) | stable IDs: None | dates: Yes (e.g. 19 April 2026, 23 August 2026) | difficulty: Low: tiny static page; yearly refresh.
- **Policy:** unclear - robots.txt allows; terms not reviewed.
- **Terms:** https://ehl.gg/ - No terms page read.
- **Rate limits:** None published | **Polling guidance:** estimate 72 h | **Proposed interval:** 72 h | **Stability:** Medium: new league, annual structure.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://ehl.gg/ - robots allowed=True (robots HTTP 200), HTTP 200, text/html, 267339 bytes
- **Evidence:**
  - Home page: 'Europe's first competitive hackathon league · 5 matches. 3 cities. One champion.' with dates - <https://ehl.gg/>
- **Scores:** relevance 4 (European hackathons relevant to AI students.) | authority 3 (Organiser site; young.) | signal quality 3 (Dates present; eligibility not captured.) | freshness 3 (2026 dates shown; 2027 unknown.) | integration 4 (Static HTML, existing adapter.)
- **Uncertainties:** 2027 season timing; Eligibility
- **Next action:** Probe with ohg; low interval.
- **Stages:** A=yes, B=no, C=yes, D=yes, E=no, F=no

### S15 - FZI Karlsruhe careers (internships, theses, student jobs)  
**Status:** MANUAL_REVIEW | **Priority:** P2 | **Score:** 17/25 | **Confidence:** medium

- **Publisher:** FZI Forschungszentrum Informatik (first-party)
- **Category:** C - Research internships and student technical opportunities | **Batch:** 2
- **Canonical URL:** https://www.fzi.de/en/career/
- **Endpoint:** https://www.fzi.de/en/career/
- **Discovery:** Career landing page (HTML) linking to job and thesis listings
- **Opportunity types:** internships; student assistant jobs; bachelor/master theses; full-time jobs
- **Audience/eligibility:** Students and graduates; positions say per listing.
- **Geography / remote:** Germany (Karlsruhe, Berlin) / Mostly on-site
- **Value:** Applied-research institute close to Mannheim; page states it offers internships, student assistant jobs and theses.
- **Auth / registration:** none / none
- **Adapter fit:** html (existing) | stable IDs: Job posting URLs (not enumerated) | dates: Landing page has few dates; listings not enumerated in this run | difficulty: Medium: listings live on a sub-page not located in this run (guessed /career/jobs-talents/ returned 404).
- **Policy:** unclear - robots.txt allows the landing page; listing page not yet identified. The final pass requested /en/career/ and was redirected to an event page (career fair), so the landing page itself was not confirmed.
- **Terms:** https://www.fzi.de/en/career/ - Not reviewed.
- **Rate limits:** None published | **Polling guidance:** estimate 24 h | **Proposed interval:** 24 h | **Stability:** Medium.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://www.fzi.de/en/career/ - robots allowed=True (robots HTTP 200), HTTP 200, text/html, 135141 bytes
- **Evidence:**
  - Page text: offers for employee positions, theses (Master's/Bachelor's), internships and student assistant jobs - <https://www.fzi.de/en/career/>
- **Scores:** relevance 4 (Applied AI/robotics research near the user (Karlsruhe).) | authority 5 (Institute is the employer/publisher.) | signal quality 2 (Landing page lacks listings; details unknown.) | freshness 3 (Listings not verified.) | integration 3 (Listing sub-page must be found first.)
- **Uncertainties:** Exact job-listing URL and format
- **Next action:** Locate the actual job/thesis listing URL before drafting an entry.
- **Stages:** A=yes, B=no, C=no, D=no, E=no, F=no

### S16 - Sovereign Tech Fellowship  
**Status:** PROBE_PASSED | **Priority:** P2 | **Score:** 18/25 | **Confidence:** medium

- **Publisher:** Sovereign Tech Agency (first-party (German federal agency))
- **Category:** D - Scholarships, fellowships and grants | **Batch:** 2
- **Canonical URL:** https://www.sovereign.tech/
- **Endpoint:** https://www.sovereign.tech/programs/fellowship
- **Discovery:** Programme page (HTML); RSS news feed https://www.sovereign.tech/feed.rss
- **Opportunity types:** fellowships for open-source maintainers, community managers, technical writers
- **Audience/eligibility:** Maintainers of critical open-source components (not a student scholarship).
- **Geography / remote:** Germany-funded; applicants international (verify) / Yes
- **Value:** Funded roles for people maintaining critical open source; relevant to engineers with maintainer experience.
- **Auth / registration:** none / Application form (not used)
- **Adapter fit:** html+rss_atom (existing) | stable IDs: RSS <guid> | dates: Page lists dates (e.g. 6 April 2026 appears several times) | difficulty: Low: static page + feed; check eligibility carefully.
- **Policy:** unclear - robots.txt allows; legal page silent on automation.
- **Terms:** https://www.sovereign.tech/legal - Legal page read (1,457 chars): no automated-access clause found.
- **Rate limits:** None published | **Polling guidance:** estimate 72 h | **Proposed interval:** 72 h | **Stability:** High.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://www.sovereign.tech/programs/fellowship - robots allowed=True (robots HTTP 200), HTTP 200, text/html, 116839 bytes
- **Evidence:**
  - Fellowship page: 'invests directly in the people behind the code, supporting maintainers, community managers, and technical writers' - <https://www.sovereign.tech/programs/fellowship>
  - RSS feed returned 10 items, newest 23 Oct 2026 - <https://www.sovereign.tech/feed.rss>
- **Scores:** relevance 2 (Targets established maintainers, not early students.) | authority 5 (Public agency, first-party.) | signal quality 3 (Programme dates visible; eligibility needs reading.) | freshness 4 (Feed active.) | integration 4 (Existing adapters.)
- **Uncertainties:** Whether bachelor-level contributors qualify
- **Next action:** Read eligibility; keep as long-term lead.
- **Stages:** A=yes, B=yes, C=yes, D=yes, E=no, F=no

### S17 - Erasmus+ opportunities for students  
**Status:** PROBE_PASSED | **Priority:** P2 | **Score:** 15/25 | **Confidence:** medium

- **Publisher:** European Commission (Erasmus+) (first-party)
- **Category:** D - Scholarships, fellowships and grants | **Batch:** 2
- **Canonical URL:** https://erasmus-plus.ec.europa.eu/
- **Endpoint:** https://erasmus-plus.ec.europa.eu/opportunities/individuals/students
- **Discovery:** Official programme pages (HTML)
- **Opportunity types:** student mobility (study/traineeship) grants
- **Audience/eligibility:** Enrolled students at participating institutions.
- **Geography / remote:** EU/associated countries / No
- **Value:** Structural funding route for studies/traineeships abroad; applications run through the university.
- **Auth / registration:** none / Applications go through home institutions
- **Adapter fit:** html (existing) | stable IDs: Page URL | dates: Few; deadlines are institution-specific | difficulty: Medium: little structured data; per-university deadlines are the real signal.
- **Policy:** no_restriction_observed - robots.txt allows; CC BY 4.0 reuse licence stated for EU-owned content.
- **Terms:** https://commission.europa.eu/legal-notice_en - Commission legal notice read: EU-owned content licensed CC BY 4.0 (reuse permitted with credit).
- **Rate limits:** None published | **Polling guidance:** estimate 72-168 h | **Proposed interval:** 168 h | **Stability:** High.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://erasmus-plus.ec.europa.eu/opportunities/individuals/students - robots allowed=True (robots HTTP 200), HTTP 200, text/html, 186633 bytes
- **Evidence:**
  - Page 'Students - Erasmus+' fetched (200) after 301 redirect from the older path - <https://erasmus-plus.ec.europa.eu/opportunities/individuals/students>
  - Legal notice: EU-owned content licensed under CC BY 4.0 - <https://commission.europa.eu/legal-notice_en>
- **Scores:** relevance 3 (Relevant for study abroad; not research-specific.) | authority 5 (European Commission.) | signal quality 2 (Deadlines are set by each university.) | freshness 2 (Static programme pages.) | integration 3 (HTML works, little to extract.)
- **Uncertainties:** Hochschule Mannheim's Erasmus deadlines (own source needed)
- **Next action:** Pair with the university's Erasmus office page.
- **Stages:** A=yes, B=yes, C=yes, D=yes, E=no, F=no

### S18 - NeurIPS dates and deadlines  
**Status:** PROBE_PASSED | **Priority:** P1 | **Score:** 22/25 | **Confidence:** high

- **Publisher:** NeurIPS Foundation (first-party)
- **Category:** E - AI/ML conferences, workshops and summer schools | **Batch:** 2
- **Canonical URL:** https://neurips.cc/
- **Endpoint:** https://neurips.cc/Conferences/2026/Dates
- **Discovery:** Official dates page (HTML)
- **Opportunity types:** conference dates, submission and registration deadlines, workshops, competitions, financial aid pointers
- **Audience/eligibility:** Researchers, students.
- **Geography / remote:** Global (2026: Sydney and Atlanta sites) / Hybrid/virtual options vary
- **Value:** The flagship ML conference; dates page contains 27 deadline-related mentions.
- **Auth / registration:** none / none
- **Adapter fit:** html (existing) | stable IDs: Year in URL | dates: Yes | difficulty: Low-medium: year in URL changes yearly; dates in prose tables.
- **Policy:** unclear - robots.txt allows; terms not reviewed.
- **Terms:** https://neurips.cc/public/PrivacyPolicy - Privacy policy only; terms not read.
- **Rate limits:** None published | **Polling guidance:** estimate 72 h | **Proposed interval:** 72 h | **Stability:** High.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://neurips.cc/Conferences/2026/Dates - robots allowed=True (robots HTTP 200), HTTP 200, text/html, 130627 bytes
- **Evidence:**
  - '2026 Dates and Deadlines' page lists meeting dates (Dec 6-12) and deadline terms - <https://neurips.cc/Conferences/2026/Dates>
- **Scores:** relevance 5 (Top-tier ML venue, includes competitions and workshops.) | authority 5 (Official conference site.) | signal quality 4 (Detailed dates; eligibility for aid elsewhere.) | freshness 4 (2026 page current; 2027 page will appear later.) | integration 4 (Existing adapter; yearly URL update.)
- **Uncertainties:** 2027 URL timing
- **Next action:** Add yearly URL pattern review to the onboarding checklist.
- **Stages:** A=yes, B=no, C=yes, D=yes, E=no, F=no

### S19 - Codeforces contests (official API)  
**Status:** PROBE_PASSED | **Priority:** P2 | **Score:** 20/25 | **Confidence:** high

- **Publisher:** Codeforces (first-party platform)
- **Category:** F - Open-source programmes, technical challenges and cybersecurity | **Batch:** 2
- **Canonical URL:** https://codeforces.com/
- **Endpoint:** https://codeforces.com/api/contest.list?gym=false
- **Discovery:** Documented public JSON API (contest.list)
- **Opportunity types:** programming contests (rounds, ICPC-style, Kotlin Heroes etc.)
- **Audience/eligibility:** Anyone; some rated divisions.
- **Geography / remote:** Global / Yes
- **Value:** Documented API with contest id, name, start time, duration and phase.
- **Auth / registration:** none for public data / none
- **Adapter fit:** JSON API adapter (missing) (gap) | stable IDs: contest id | dates: Yes (startTimeSeconds, durationSeconds) | difficulty: Medium: JSON adapter needed; payload is 413 KB (all contests) so filter by phase=BEFORE.
- **Policy:** no_restriction_observed - Documented public API with a stated rate limit; robots.txt allowed the API path in this run.
- **Terms:** https://codeforces.com/apiHelp - API help documents the limit: 'API may be requested at most 1 time per two seconds'; anonymous access to public data.
- **Rate limits:** 1 request per 2 seconds (documented) | **Polling guidance:** estimate 24 h | **Proposed interval:** 24 h | **Stability:** High.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://codeforces.com/api/contest.list?gym=false - robots allowed=True (robots HTTP 200), HTTP 200, application/json, 412641 bytes
- **Evidence:**
  - API help: 'API may be requested at most 1 time per two seconds'; 'All methods can be requested anonymously' - <https://codeforces.com/apiHelp>
  - contest.list returned status OK with contests incl. phase BEFORE and startTimeSeconds - <https://codeforces.com/api/contest.list?gym=false>
- **Scores:** relevance 3 (Algorithmic contests; useful but peripheral to AI/robotics.) | authority 5 (Operator of the contests.) | signal quality 4 (Structured times; no prizes/eligibility fields.) | freshness 5 (Upcoming rounds listed.) | integration 3 (Needs JSON adapter; API well documented.)
- **Uncertainties:** Value to the user's goals
- **Next action:** Low priority; implement JSON adapter if shared with other APIs.
- **Stages:** A=yes, B=yes, C=no, D=yes, E=no, F=no

### S20 - Google Summer of Code timeline  
**Status:** PROBE_PASSED | **Priority:** P1 | **Score:** 20/25 | **Confidence:** high

- **Publisher:** Google Open Source Programs Office (first-party)
- **Category:** F - Open-source programmes, technical challenges and cybersecurity | **Batch:** 2
- **Canonical URL:** https://developers.google.com/open-source/gsoc
- **Endpoint:** https://developers.google.com/open-source/gsoc/timeline
- **Discovery:** Official timeline page (HTML); the contributor site summerofcode.withgoogle.com is a JavaScript app
- **Opportunity types:** paid open-source contributor programme (summer)
- **Audience/eligibility:** Contributors, including students; eligibility on FAQ (not read).
- **Geography / remote:** Global (remote) / Yes
- **Value:** Best-known open-source programme; official timeline page lists application windows.
- **Auth / registration:** none / Contributor application via GSoC site
- **Adapter fit:** html (existing) | stable IDs: Page URL | dates: Yes, but formatted 'January 19 - 18:00 UTC' under a year heading (yearless per line) | difficulty: Medium: dates need the heading year; strict parser flags yearless lines.
- **Policy:** unclear - robots.txt allows; terms/FAQ not reviewed.
- **Terms:** https://developers.google.com/open-source/gsoc/faq - Not read in this run.
- **Rate limits:** None published | **Polling guidance:** estimate 168 h | **Proposed interval:** 168 h | **Stability:** High.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://developers.google.com/open-source/gsoc/timeline - robots allowed=True (robots HTTP 200), HTTP 200, text/html, 73490 bytes
- **Evidence:**
  - Timeline page: 'Mentoring organizations can apply ... January 22nd to February 6th' and a dated 2026 timeline - <https://developers.google.com/open-source/gsoc/timeline>
  - summerofcode.withgoogle.com/programs renders no text (JS app) - <https://summerofcode.withgoogle.com/programs>
- **Scores:** relevance 4 (Remote, paid OSS work accessible to bachelor students.) | authority 5 (Run by Google.) | signal quality 4 (Clear dates; eligibility on FAQ.) | freshness 3 (Annual cycle; current page shows 2026 timeline.) | integration 4 (Static official HTML.)
- **Uncertainties:** 2027 timeline publication date; Eligibility details
- **Next action:** Probe with ohg; re-check in December.
- **Stages:** A=yes, B=no, C=yes, D=yes, E=no, F=no
