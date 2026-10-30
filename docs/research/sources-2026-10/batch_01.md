# Batch 1 (10 sources)

Verification pass: 2026-10-30T01:17:32+01:00 (Europe/Berlin). Nothing here is activated.

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

## Profiles

### S01 - euRobotics news & calls feed  
**Status:** PROBE_PASSED | **Priority:** P0 | **Score:** 21/25 | **Confidence:** high

- **Publisher:** euRobotics aisbl (first-party)
- **Category:** B - Robotics and research opportunities | **Batch:** 1
- **Canonical URL:** https://eu-robotics.net/
- **Endpoint:** https://eu-robotics.net/feed/
- **Discovery:** RSS 2.0 feed (WordPress)
- **Opportunity types:** calls for papers (ERF); events; news releases; working-group announcements
- **Audience/eligibility:** Robotics researchers, students and companies in Europe; eligibility varies per item.
- **Geography / remote:** Europe / n/a
- **Value:** Official European robotics association; its feed carried the ERF2027 scientific-track call (deadline extended) and event news within the last 3 weeks.
- **Auth / registration:** none / none
- **Adapter fit:** rss_atom (existing) | stable IDs: RSS <guid>/<link> per post | dates: Publication dates yes; deadlines only inside post text | difficulty: Low: feed parses with the existing RSS adapter; deadlines must be mined from article text.
- **Policy:** unclear - robots.txt allows the feed path; terms not reviewed.
- **Terms:** https://eu-robotics.net/ - Terms page not located in this run; no automated-access language read.
- **Rate limits:** No published limit found | **Polling guidance:** none published; estimate 24 h | **Proposed interval:** 24 h | **Stability:** Medium-low: WordPress feed, stable for years but content is mostly news.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://eu-robotics.net/feed/ - robots allowed=True (robots HTTP 200), HTTP 200, text/xml, 36094 bytes
- **Evidence:**
  - Feed returns valid RSS 2.0, 10 items, newest 22 Oct 2026, incl. 'Deadline extended – CALL FOR PAPERS – Scientific Track ERF2027' - <https://eu-robotics.net/feed/>
  - Homepage advertises the feed via <link rel=alternate type=application/rss+xml> - <https://eu-robotics.net/>
- **Scores:** relevance 4 (Robotics-focused, Europe-wide; mostly industry/research news, few student offers.) | authority 4 (Official trade association, first-party announcements.) | signal quality 3 (Dates are in article text; eligibility inconsistent.) | freshness 5 (10 items in ~3 weeks; newest 22 Oct 2026.) | integration 5 (Existing rss_atom adapter; stable feed URL.)
- **Uncertainties:** Whether feed items are tagged by opportunity type; Terms of use
- **Next action:** Review site terms, then enable with a 24 h interval.
- **Stages:** A=yes, B=yes, C=yes, D=yes, E=no, F=no

### S02 - Robotics Institute Germany news feed  
**Status:** PROBE_PASSED | **Priority:** P0 | **Score:** 22/25 | **Confidence:** high

- **Publisher:** Robotics Institute Germany (RIG) (first-party)
- **Category:** B - Robotics and research opportunities | **Batch:** 1
- **Canonical URL:** https://robotics-institute-germany.de/
- **Endpoint:** https://robotics-institute-germany.de/feed/
- **Discovery:** RSS 2.0 feed (WordPress)
- **Opportunity types:** internship programme announcements; lecture series; events; funding news
- **Audience/eligibility:** Robotics students and researchers in Germany.
- **Geography / remote:** Germany / Online lectures
- **Value:** National robotics initiative; its feed announced 'RIG Internship Program 2027: Applications Opening Soon!' on 27 Oct 2026.
- **Auth / registration:** none / none
- **Adapter fit:** rss_atom (existing) | stable IDs: RSS <guid>/<link> | dates: Post dates yes; application dates inside posts | difficulty: Low: existing adapter; internship dates need text extraction.
- **Policy:** unclear - robots.txt allows the feed; legal notice not reviewed for reuse terms.
- **Terms:** https://robotics-institute-germany.de/legal-notice/ - Legal notice page located; automated-access rules not read.
- **Rate limits:** None published | **Polling guidance:** none; estimate 24 h | **Proposed interval:** 24 h | **Stability:** Medium: young initiative (WordPress); may restructure.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://robotics-institute-germany.de/feed/ - robots allowed=True (robots HTTP 200), HTTP 200, application/rss+xml, 103804 bytes
- **Evidence:**
  - Valid RSS 2.0, 10 items; item 'RIG Internship Program 2027: Applications Opening Soon!' (27 Oct 2026) - <https://robotics-institute-germany.de/feed/>
  - Feed autodiscovered from homepage - <https://robotics-institute-germany.de/>
- **Scores:** relevance 5 (German robotics internships and lectures match the primary profile directly.) | authority 4 (Official national robotics institute.) | signal quality 3 (Internship details sit in linked posts, not in feed fields.) | freshness 5 (Posts on 21-27 Oct 2026.) | integration 5 (Existing rss_atom adapter, simple feed.)
- **Uncertainties:** Reuse terms; Internship eligibility (bachelor?)
- **Next action:** Read the 2027 internship post; review terms; enable.
- **Stages:** A=yes, B=yes, C=yes, D=yes, E=no, F=no

### S03 - lablab.ai AI hackathons  
**Status:** PROBE_PASSED | **Priority:** P1 | **Score:** 19/25 | **Confidence:** medium

- **Publisher:** lablab.ai (platform (hosts and lists sponsor hackathons))
- **Category:** A - AI/ML hackathons and competitions | **Batch:** 1
- **Canonical URL:** https://lablab.ai/
- **Endpoint:** https://lablab.ai/ai-hackathons
- **Discovery:** Structured listing page (HTML, JSON-LD CollectionPage present)
- **Opportunity types:** online and hybrid AI hackathons; sponsor challenges
- **Audience/eligibility:** Developers worldwide; per-event rules vary.
- **Geography / remote:** Global (online-first) / Yes
- **Value:** Dense, dated AI hackathon listing with status (Live/Finished), format, date range and participant counts.
- **Auth / registration:** none / none for browsing
- **Adapter fit:** html (existing) | stable IDs: Event slug in URL (e.g. /ai-hackathons/<slug>) | dates: Date ranges yes (e.g. 'NOV 3 - 8', '3–8 November 2026') | difficulty: Medium: listing is large (~930 KB) and mixes finished events; dates partly yearless.
- **Policy:** unclear - robots.txt allows /ai-hackathons; terms silent on automation.
- **Terms:** https://lablab.ai/terms-of-use - Terms read: no automated-access or scraping clause found by keyword scan; this is not permission.
- **Rate limits:** None published | **Polling guidance:** none; estimate 24 h | **Proposed interval:** 24 h | **Stability:** Medium: commercial platform; markup changes likely.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://lablab.ai/ai-hackathons - robots allowed=True (robots HTTP 200), HTTP 200, text/html, 932052 bytes
- **Evidence:**
  - Listing shows event cards with dates, e.g. 'Vultr: Agent Rush Hackathon', 3-8 November 2026 (hybrid) - <https://lablab.ai/ai-hackathons>
  - Terms of use scanned for scraping/robot/automated clauses: none found - <https://lablab.ai/terms-of-use>
- **Scores:** relevance 4 (AI-specific hackathons, mostly online so accessible from Germany.) | authority 3 (Platform listing sponsor events; not the legal organiser of each.) | signal quality 4 (Dates and format shown; eligibility and prizes per event page.) | freshness 5 (Live and upcoming events in Oct-Nov 2026.) | integration 3 (HTML adapter works but page is heavy and noisy.)
- **Uncertainties:** Per-event eligibility; Whether JSON-LD can be used instead of text
- **Next action:** Probe with ohg; decide max_pages and filter finished events.
- **Stages:** A=yes, B=yes, C=yes, D=yes, E=no, F=no

### S04 - MLH season events  
**Status:** PROBE_PASSED | **Priority:** P1 | **Score:** 20/25 | **Confidence:** medium

- **Publisher:** Major League Hacking (MLH) (first-party (league of student hackathons))
- **Category:** A - AI/ML hackathons and competitions | **Batch:** 1
- **Canonical URL:** https://www.mlh.com/
- **Endpoint:** https://www.mlh.com/seasons/2027/events
- **Discovery:** Structured listing page (HTML)
- **Opportunity types:** student hackathons (in-person and digital)
- **Audience/eligibility:** Students (13+/18+ rules vary per event).
- **Geography / remote:** Global incl. Europe / Some digital events
- **Value:** Largest student hackathon league; the 2027 season page lists upcoming events with dates, city and format.
- **Auth / registration:** none / none for browsing
- **Adapter fit:** html (existing) | stable IDs: Event page slug | dates: Dates without year inside a season page (e.g. 'OCT 31 - NOV 01') | difficulty: Medium: yearless dates must be interpreted from the season header; strict parser will flag them for review.
- **Policy:** unclear - robots.txt allows; terms silent on automation.
- **Terms:** https://www.mlh.com/terms - Terms read: no automated-access clause found by keyword scan; this is not permission.
- **Rate limits:** None published | **Polling guidance:** none; estimate 24 h | **Proposed interval:** 24 h | **Stability:** Medium: season URL changes each year (/seasons/2027/events).
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://www.mlh.com/seasons/2027/events - robots allowed=True (robots HTTP 200), HTTP 200, text/html, 612490 bytes
- **Evidence:**
  - 2027 season page lists events such as 'Since AI Hackathon' (Turku, FI, NOV 06-08) - <https://www.mlh.com/seasons/2027/events>
  - mlh.io/seasons/2026/events redirects (302) to mlh.com - <https://mlh.io/seasons/2026/events>
- **Scores:** relevance 4 (Student-focused hackathons including European cities.) | authority 5 (First-party league with long track record.) | signal quality 3 (Dates, city, mode shown; no year per date; eligibility on event pages.) | freshness 5 (Events from 31 Oct 2026 onwards listed.) | integration 3 (HTML adapter feasible; yearly URL change needs a config update.)
- **Uncertainties:** Per-event age/eligibility rules; Year-rollover handling
- **Next action:** Probe with ohg; add both 2026 and 2027 season URLs.
- **Stages:** A=yes, B=yes, C=yes, D=yes, E=no, F=no

### S05 - CERN openlab summer student programme  
**Status:** PROBE_PASSED | **Priority:** P0 | **Score:** 20/25 | **Confidence:** high

- **Publisher:** CERN openlab (first-party)
- **Category:** C - Research internships and student technical opportunities | **Batch:** 1
- **Canonical URL:** https://openlab.cern/
- **Endpoint:** https://openlab.cern/cern-openlab-summer-student-programme/
- **Discovery:** Programme page (HTML)
- **Opportunity types:** 9-week summer placement in computing/AI for bachelor and master students
- **Audience/eligibility:** Bachelor's and master's students in computer science and related subjects (programme text).
- **Geography / remote:** Switzerland (CERN) / No (on-site, estimate)
- **Value:** Prestigious, recurring research placement; page states the 2027 call opens in November 2026.
- **Auth / registration:** none / Application portal at CERN careers (not accessed)
- **Adapter fit:** html (existing) | stable IDs: Stable page URL; no per-edition IDs | dates: Call opening month stated; exact deadline not yet published | difficulty: Low: static page; the facts change once a year.
- **Policy:** unclear - robots.txt allows; terms not reviewed.
- **Terms:** https://openlab.cern/ - Site terms not located in this run.
- **Rate limits:** None published | **Polling guidance:** estimate 24-72 h | **Proposed interval:** 72 h | **Stability:** High: long-lived programme page.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://openlab.cern/cern-openlab-summer-student-programme/ - robots allowed=True (robots HTTP 200), HTTP 200, text/html, 266442 bytes
- **Evidence:**
  - Page text: 'The call for applications for the 2027 CERN openlab summer student programme will open in november 2026' - <https://openlab.cern/cern-openlab-summer-student-programme/>
  - Page text: nine-week programme for bachelor's and master's students specialising in computer science - <https://openlab.cern/cern-openlab-summer-student-programme/>
  - Homepage links the programme page (the earlier guessed URL /summer-student-programme returned 404) - <https://openlab.cern/>
- **Scores:** relevance 4 (Computing/AI research placement open to bachelor students; Europe.) | authority 5 (CERN-run programme, first-party.) | signal quality 3 (Eligibility stated; deadline not yet published.) | freshness 4 (2027 call imminent per the page.) | integration 4 (Static HTML; existing adapter; low maintenance.)
- **Uncertainties:** 2027 deadline; Exact nationality/residency rules
- **Next action:** Enable weekly polling once the 2027 call opens; confirm deadline from the official call.
- **Stages:** A=yes, B=yes, C=yes, D=yes, E=no, F=no

### S06 - DESY Summer Student Programme  
**Status:** PROBE_PASSED | **Priority:** P2 | **Score:** 17/25 | **Confidence:** high

- **Publisher:** Deutsches Elektronen-Synchrotron DESY (first-party)
- **Category:** C - Research internships and student technical opportunities | **Batch:** 1
- **Canonical URL:** https://summerstudents.desy.de/
- **Endpoint:** https://summerstudents.desy.de/
- **Discovery:** Programme page (HTML)
- **Opportunity types:** summer research programme for undergraduate students (physics and related)
- **Audience/eligibility:** Undergraduate students in physics or related disciplines (page text).
- **Geography / remote:** Germany (Hamburg/Zeuthen) / No
- **Value:** Helmholtz research centre programme in Germany; page title 'Summer Student Programme 2027' and says it is in preparation.
- **Auth / registration:** none / Application portal (not accessed)
- **Adapter fit:** html (existing) | stable IDs: Stable page URL | dates: None yet: 'The 2027 Programme is currently in preparation' | difficulty: Low: static page.
- **Policy:** unclear - robots.txt allows; terms not reviewed.
- **Terms:** https://www.desy.de/data_privacy_policy/ - Privacy policy only; no automated-access rules read.
- **Rate limits:** None published | **Polling guidance:** estimate 72 h | **Proposed interval:** 72 h | **Stability:** High.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://summerstudents.desy.de/ - robots allowed=True (robots HTTP 200), HTTP 200, text/html, 19781 bytes
- **Evidence:**
  - Page title 'Summer Student Programme 2027'; text 'The 2027 Programme is currently in preparation' - <https://summerstudents.desy.de/>
  - Audience statement: undergraduate students in physics or related disciplines - <https://summerstudents.desy.de/>
- **Scores:** relevance 3 (Physics-oriented; relevant to CS students only via computing projects.) | authority 5 (DESY is the organiser.) | signal quality 2 (No dates yet; eligibility general.) | freshness 3 (Annual refresh; nothing published yet for 2027.) | integration 4 (Static HTML with existing adapter.)
- **Uncertainties:** Whether computing/AI projects are offered; 2027 dates
- **Next action:** Poll weekly; review relevance when the call opens.
- **Stages:** A=yes, B=no, C=yes, D=yes, E=no, F=no

### S07 - NLnet grants (calls + news Atom)  
**Status:** PROBE_PASSED | **Priority:** P0 | **Score:** 23/25 | **Confidence:** high

- **Publisher:** NLnet Foundation (first-party)
- **Category:** D - Scholarships, fellowships and grants | **Batch:** 1
- **Canonical URL:** https://nlnet.nl/
- **Endpoint:** https://nlnet.nl/propose/
- **Discovery:** Programme page (HTML) with Atom news feed https://nlnet.nl/feed.atom
- **Opportunity types:** grants for open-source/open-internet projects (NGI Zero etc.)
- **Audience/eligibility:** Individuals and organisations proposing open-source work.
- **Geography / remote:** EU/Europe-centred, applicants worldwide (per page, not verified in detail) / Yes
- **Value:** Recurring bimonthly-style calls with a published next deadline; individual developers can apply.
- **Auth / registration:** none / Proposal form (not used)
- **Adapter fit:** html+rss_atom (existing) | stable IDs: Atom <id>/<link> | dates: Yes: 'Next deadline: November 3rd 2026 12:00 CET (noon)' | difficulty: Low: deadline sits in page text; Atom feed is 2.8 MB (352 entries since 1999), so use conditional requests.
- **Policy:** unclear - robots.txt allows; terms not reviewed.
- **Terms:** https://nlnet.nl/ - No terms page read; robots.txt allows both paths.
- **Rate limits:** None published | **Polling guidance:** estimate 24 h for /propose, 24 h for the feed with conditional GET | **Proposed interval:** 24 h | **Stability:** High.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://nlnet.nl/propose/ - robots allowed=True (robots HTTP 200), HTTP 200, text/html, 43246 bytes
- **Evidence:**
  - Propose page: 'Next deadline: November 3rd 2026 12:00 CET (noon)' - <https://nlnet.nl/propose/>
  - Atom feed parses: 352 entries, newest 2026-10-29, items about grants and policy - <https://nlnet.nl/feed.atom>
- **Scores:** relevance 3 (Open-source funding; fits independent developers, less so AI/robotics specifically.) | authority 5 (Foundation publishes its own calls.) | signal quality 5 (Explicit deadline and time zone on the page.) | freshness 5 (Feed updated 29 Oct 2026.) | integration 5 (Both endpoints use existing adapters.)
- **Uncertainties:** Individual-eligibility details per fund; Size cost of the 2.8 MB feed on slow links
- **Next action:** Probe with ohg; enable page + feed with conditional requests.
- **Stages:** A=yes, B=no, C=yes, D=yes, E=no, F=no

### S08 - CCF-Deadlines conference data (GitHub)  
**Status:** PROBE_PASSED | **Priority:** P1 | **Score:** 20/25 | **Confidence:** medium

- **Publisher:** ccfddl community (GitHub) (community aggregator)
- **Category:** E - AI/ML conferences, workshops and summer schools | **Batch:** 1
- **Canonical URL:** https://github.com/ccfddl/ccf-deadlines
- **Endpoint:** https://raw.githubusercontent.com/ccfddl/ccf-deadlines/main/conference/AI/nips.yml
- **Discovery:** Versioned YAML data files in a public MIT-licensed repository (61 files under conference/AI)
- **Opportunity types:** conference submission deadlines (AI, CV, NLP, robotics categories)
- **Audience/eligibility:** Researchers and students tracking venues.
- **Geography / remote:** Global / n/a
- **Value:** Machine-readable, regularly updated deadline data; avoids scraping many conference sites.
- **Auth / registration:** none / none
- **Adapter fit:** yaml/json data adapter (missing) (gap) | stable IDs: File name per conference + year/edition keys inside YAML | dates: Yes (structured) | difficulty: Medium: needs a data adapter; per-file requests or GitHub contents API (60 unauthenticated requests/hour observed).
- **Policy:** no_restriction_observed - MIT licence observed; raw.githubusercontent.com robots.txt returned 404 (treated as no restrictions per RFC 9309).
- **Terms:** https://docs.github.com/site-policy/github-terms/github-terms-of-service - Repository licence: MIT (GitHub API). GitHub ToS has access clauses for automated collection of public content; not analysed in depth.
- **Rate limits:** GitHub REST API unauthenticated: 60 requests/hour (x-ratelimit-limit header observed) | **Polling guidance:** estimate 24 h via ETag/conditional GET on raw files | **Proposed interval:** 24 h | **Stability:** Medium: community-maintained; repo pushed 2026-10-29 (active).
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://raw.githubusercontent.com/ccfddl/ccf-deadlines/main/conference/AI/nips.yml - robots allowed=True (robots HTTP 404), HTTP 200, text/plain, 2021 bytes
- **Evidence:**
  - GitHub API: license MIT, pushed_at 2026-10-29T15:46:27Z, archived=false - <https://api.github.com/repos/ccfddl/ccf-deadlines>
  - conference/AI directory lists 61 files (e.g. aaai.yml, acl.yml) - <https://api.github.com/repos/ccfddl/ccf-deadlines/contents/conference/AI>
  - Raw file nips.yml fetched successfully (2,021 bytes) - <https://raw.githubusercontent.com/ccfddl/ccf-deadlines/main/conference/AI/nips.yml>
- **Scores:** relevance 4 (Covers the AI/CV/ML venues in scope.) | authority 3 (Community-curated; correctness not guaranteed (must verify on official sites).) | signal quality 5 (Structured deadlines and timezones.) | freshness 5 (Active repo (push on 29 Oct 2026).) | integration 3 (Requires a new YAML/JSON adapter; otherwise simple.)
- **Uncertainties:** Accuracy of individual deadlines; Complete list of robotics conferences in the dataset
- **Next action:** Plan a small data adapter; treat values as T4 leads confirmed on official conference pages.
- **Stages:** A=yes, B=yes, C=no, D=yes, E=no, F=no

### S09 - WikiCFP RSS (machine learning, robotics)  
**Status:** PROBE_PASSED | **Priority:** P2 | **Score:** 15/25 | **Confidence:** medium

- **Publisher:** WikiCFP (community aggregator)
- **Category:** E - AI/ML conferences, workshops and summer schools | **Batch:** 1
- **Canonical URL:** http://www.wikicfp.com/cfp/
- **Endpoint:** http://www.wikicfp.com/cfp/rss?cat=machine%20learning
- **Discovery:** RSS 2.0 feeds per category
- **Opportunity types:** calls for papers for conferences/workshops/journals
- **Audience/eligibility:** Researchers.
- **Geography / remote:** Global / n/a
- **Value:** Long-running CFP index with per-category RSS (verified for machine learning and robotics); good lead source.
- **Auth / registration:** none / none
- **Adapter fit:** rss_atom (existing) | stable IDs: eventid in item link | dates: Deadlines are in the linked event page; feed fields are title/link/summary only | difficulty: Medium: feed items lack dates; follow-up fetch required. Site runs over plain HTTP.
- **Policy:** unclear - robots.txt allows; content licence CC BY-SA 3.0 stated on the terms page; reuse terms for feeds not otherwise specified.
- **Terms:** http://www.wikicfp.com/cfp/terms.jsp - Terms page read: general disclaimer; the wiki content is stated as CC BY-SA 3.0; no automated-access clause found.
- **Rate limits:** None published | **Polling guidance:** estimate 24 h | **Proposed interval:** 24 h | **Stability:** Medium: dated site, but feeds returned fresh items.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET http://www.wikicfp.com/cfp/rss?cat=machine%20learning - robots allowed=True (robots HTTP 200), HTTP 200, application/xml, 9787 bytes
- **Evidence:**
  - RSS feed for category 'machine learning' returned 20 items - <http://www.wikicfp.com/cfp/rss?cat=machine%20learning>
  - RSS feed for category 'robotics' returned 20 items (e.g. 'ICCRT 2027') - <http://www.wikicfp.com/cfp/rss?cat=robotics>
  - Terms page states CC BY-SA 3.0 licence - <http://www.wikicfp.com/cfp/terms.jsp>
- **Scores:** relevance 3 (Many CFPs, but a lot of low-quality conferences.) | authority 2 (User-submitted listings, unverified.) | signal quality 2 (Feed lacks deadlines; requires per-event fetch.) | freshness 4 (Fresh items present.) | integration 4 (Existing RSS adapter; HTTP only.)
- **Uncertainties:** Spam/low-quality rate; Page structure for deadlines
- **Next action:** Use as lead-only (T4/T5); pair with S08 and official conference pages.
- **Stages:** A=yes, B=yes, C=yes, D=yes, E=no, F=no

### S10 - CTFtime upcoming events (RSS + API)  
**Status:** PROBE_PASSED | **Priority:** P1 | **Score:** 20/25 | **Confidence:** high

- **Publisher:** CTFtime.org (community platform (event directory))
- **Category:** F - Open-source programmes, technical challenges and cybersecurity | **Batch:** 1
- **Canonical URL:** https://ctftime.org/
- **Endpoint:** https://ctftime.org/event/list/upcoming/rss/
- **Discovery:** RSS feed; documented JSON API at https://ctftime.org/api/v1/events/
- **Opportunity types:** capture-the-flag competitions (online and on-site)
- **Audience/eligibility:** Individuals and teams; event rules vary.
- **Geography / remote:** Global / Mostly online
- **Value:** Authoritative CTF calendar with structured JSON (start, duration, format, weight, location, url).
- **Auth / registration:** none / none
- **Adapter fit:** rss_atom (existing) | stable IDs: CTFtime event id | dates: Yes (start time and duration in API) | difficulty: Low via RSS (38 items); richer via JSON API (needs a JSON adapter).
- **Policy:** unclear - Public documented API with a purpose restriction (no clones); our personal alerting is not a clone but this needs a human reading. Our fetcher does not yet honour Crawl-delay.
- **Terms:** https://ctftime.org/api/ - API page: 'provided for data analysis and mobile applications only. You can not use this API to run CTFtime clones'. robots.txt: Crawl-delay: 10.
- **Rate limits:** No numeric API limit published; robots.txt Crawl-delay: 10 (seconds) | **Polling guidance:** honour Crawl-delay 10 s; estimate 12-24 h | **Proposed interval:** 24 h | **Stability:** High: long-running service.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://ctftime.org/event/list/upcoming/rss/ - robots allowed=True (robots HTTP 200), HTTP 200, application/rss+xml, 50450 bytes
- **Evidence:**
  - RSS feed 'CTFtime.org: upcoming CTF events' with 38 items - <https://ctftime.org/event/list/upcoming/rss/>
  - JSON API returns events with start, duration, location, weight, ctftime_url - <https://ctftime.org/api/v1/events/?limit=3>
  - API page states purpose restriction - <https://ctftime.org/api/>
  - robots.txt contains 'Crawl-delay: 10' - <https://ctftime.org/robots.txt>
- **Scores:** relevance 3 (Cybersecurity competitions; secondary to AI/robotics goals.) | authority 4 (Community standard directory; organisers are third parties.) | signal quality 4 (Structured dates, format, weight.) | freshness 5 (Events next day onward.) | integration 4 (RSS works with existing adapter; JSON adapter would be better; crawl-delay gap.)
- **Uncertainties:** Whether personal alerting fits the 'no clones' clause (manual reading)
- **Next action:** Review API terms; use RSS with >= 10 s spacing; consider a JSON adapter later.
- **Stages:** A=yes, B=yes, C=yes, D=yes, E=no, F=no
