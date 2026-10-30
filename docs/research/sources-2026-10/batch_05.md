# Batch 5 (10 sources)

Verification pass: 2026-10-30T01:17:32+01:00 (Europe/Berlin). Nothing here is activated.

| ID | Cat | Source | Endpoint | Method | Status | Policy | Score | Pri |
|---|---|---|---|---|---|---|---|---|
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

## Profiles

### S41 - Open Robotics Discourse – Jobs category  
**Status:** PROBE_PASSED | **Priority:** P1 | **Score:** 20/25 | **Confidence:** medium

- **Publisher:** Open Source Robotics Foundation (Open Robotics) (community forum (official ROS community host))
- **Category:** B - Robotics and research opportunities | **Batch:** 5
- **Canonical URL:** https://discourse.openrobotics.org/
- **Endpoint:** https://discourse.openrobotics.org/c/jobs/15
- **Discovery:** Forum category page (HTML). The category RSS (/c/jobs/15.rss) is disallowed by robots.txt for our agent.
- **Opportunity types:** robotics job and internship postings
- **Audience/eligibility:** Per post (internships, postdocs, full-time).
- **Geography / remote:** Global / Many remote/on-site listings
- **Value:** Highest-signal ROS job board: topics dated within days (e.g. 28 Oct 2026).
- **Auth / registration:** none / none to read
- **Adapter fit:** html (existing) | stable IDs: Topic id in URL | dates: Activity dates yes | difficulty: Medium: Discourse markup; RSS cannot be used under robots.txt; HTML is permitted.
- **Policy:** restricted - robots.txt: 'Disallow: /c/*.rss' and 'Disallow: /t/*/*.rss' apply to category/topic RSS; the HTML category path is allowed.
- **Terms:** https://discourse.openrobotics.org/tos - Terms page not read in this run.
- **Rate limits:** Discourse default limits not verified | **Polling guidance:** estimate 24 h | **Proposed interval:** 24 h | **Stability:** High.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://discourse.openrobotics.org/c/jobs/15 - robots allowed=True (robots HTTP 200), HTTP 200, text/html, 72154 bytes
- **Evidence:**
  - Category page lists topics with 'October 28, 2026' activity and tags such as internship, postdoc - <https://discourse.openrobotics.org/c/jobs/15>
  - robots.txt contains 'Disallow: /c/*.rss' - <https://discourse.openrobotics.org/robots.txt>
- **Scores:** relevance 5 (Robotics job/internship posts worldwide.) | authority 3 (Community posts, employers self-report.) | signal quality 4 (Tags and titles; eligibility in post text.) | freshness 5 (Posts on 28 Oct 2026.) | integration 3 (HTML only; RSS blocked.)
- **Uncertainties:** Forum terms on automated access
- **Next action:** Use HTML category page only; do not use .rss.
- **Stages:** A=yes, B=yes, C=yes, D=yes, E=no, F=no

### S42 - RoboCup news and events  
**Status:** MANUAL_REVIEW | **Priority:** P2 | **Score:** 16/25 | **Confidence:** medium

- **Publisher:** RoboCup Federation (first-party)
- **Category:** B - Robotics and research opportunities | **Batch:** 5
- **Canonical URL:** https://www.robocup.org/
- **Endpoint:** https://www.robocup.org/
- **Discovery:** Homepage news (HTML); /events returned HTTP 406 to our agent (not worked around)
- **Opportunity types:** robot competitions, leagues, event announcements (e.g. RoboCup 2026)
- **Audience/eligibility:** Teams and students; national events exist (e.g. German Open, whose site has a TLS fault).
- **Geography / remote:** Global / No
- **Value:** Main international robot-competition body; homepage news mentions the RoboCup 2026 call to teams.
- **Auth / registration:** none / n/a
- **Adapter fit:** html (existing) | stable IDs: None | dates: Sparse | difficulty: Medium: the listing page rejects our agent; homepage has few dated items.
- **Policy:** restricted - Events path returned 406 to our user agent; homepage is accessible. No evasion attempted.
- **Terms:** https://www.robocup.org/ - Not reviewed.
- **Rate limits:** None published | **Polling guidance:** estimate 72 h | **Proposed interval:** 72 h | **Stability:** Medium.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://www.robocup.org/ - robots allowed=True (robots HTTP 200), HTTP 200, text/html, 72381 bytes
- **Evidence:**
  - Homepage 200: 'Robot Competitions ... Recent News ... invite teams from around the world to participate in the RoboCup 2026' - <https://www.robocup.org/>
  - https://www.robocup.org/events returned HTTP 406 to our agent - <https://www.robocup.org/events>
- **Scores:** relevance 4 (Robotics competitions for students.) | authority 5 (Federation.) | signal quality 2 (Homepage lacks structured events.) | freshness 3 (News current.) | integration 2 (Listing endpoint unavailable to us.)
- **Uncertainties:** Event listing URL accessible to automated clients
- **Next action:** Find an accessible feed/listing or contact the federation.
- **Stages:** A=yes, B=no, C=no, D=no, E=no, F=no

### S43 - Devpost hackathons  
**Status:** MANUAL_REVIEW | **Priority:** Hold | **Score:** 15/25 | **Confidence:** low

- **Publisher:** Devpost, Inc. (platform)
- **Category:** A - AI/ML hackathons and competitions | **Batch:** 5
- **Canonical URL:** https://devpost.com/
- **Endpoint:** https://devpost.com/hackathons
- **Discovery:** Listing page behind a Cloudflare bot challenge
- **Opportunity types:** online and in-person hackathons
- **Audience/eligibility:** Per hackathon.
- **Geography / remote:** Global / Many
- **Value:** Largest hackathon platform; blocked to our agent, so unusable without permission.
- **Auth / registration:** Bot challenge / n/a
- **Adapter fit:** none until access is permitted (gap) | stable IDs: hackathon slug | dates: Unknown | difficulty: Blocked: HTTP 403 'Just a moment...' challenge.
- **Policy:** blocked - robots.txt allows the path, but the site serves a bot challenge (403). Not circumvented.
- **Terms:** https://devpost.com/ - Not read; page not accessible.
- **Rate limits:** Unknown | **Polling guidance:** none | **Proposed interval:** 720 h | **Stability:** High.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://devpost.com/hackathons - robots allowed=True (robots HTTP 200), HTTP 403, text/html, 5613 bytes
- **Evidence:**
  - HTTP 403 with title 'Just a moment...' (Cloudflare challenge) for /hackathons - <https://devpost.com/hackathons>
  - Web search: Devpost describes itself as running AI hackathons (third-party snippets only) - <https://scriptagc.wasmer.app/https_info_devpost_com/product/ai-hackathons>
- **Scores:** relevance 4 (Many online AI hackathons.) | authority 4 (Platform.) | signal quality 3 (Unknown (not accessible).) | freshness 4 (Unknown.) | integration 0 (Blocked for automated clients.)
- **Uncertainties:** Any permitted machine access (API/feed)
- **Next action:** Check for an official API or ask for access; otherwise review manually.
- **Stages:** A=yes, B=yes, C=no, D=no, E=no, F=no

### S44 - DrivenData competitions  
**Status:** MANUAL_REVIEW | **Priority:** Hold | **Score:** 13/25 | **Confidence:** high

- **Publisher:** DrivenData (first-party)
- **Category:** A - AI/ML hackathons and competitions | **Batch:** 5
- **Canonical URL:** https://www.drivendata.org/
- **Endpoint:** https://www.drivendata.org/competitions/
- **Discovery:** Server-rendered listing (HTML)
- **Opportunity types:** social-impact data science competitions with prizes
- **Audience/eligibility:** Anyone; per-competition rules.
- **Geography / remote:** Global / Yes
- **Value:** Credible prize competitions (e.g. $300,000 GEMS Prize Challenge); but the terms forbid automated access.
- **Auth / registration:** none / Account to participate
- **Adapter fit:** html (existing) | stable IDs: Competition URL | dates: Relative only ('4 weeks left'), no absolute dates | difficulty: Medium, and policy-blocked.
- **Policy:** prohibited - Explicit prohibition of automated access in the terms of use.
- **Terms:** https://www.drivendata.org/termsofuse/ - Terms of use prohibit: 'Use any robot, spider or other automatic device, process or means to access the Website for any purpose, including monitoring or copying any of the material'.
- **Rate limits:** n/a | **Polling guidance:** none | **Proposed interval:** 720 h | **Stability:** High.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://www.drivendata.org/competitions/ - robots allowed=True (robots HTTP 200), HTTP 200, text/html, 287258 bytes
- **Evidence:**
  - Terms of use text prohibits robots/spiders/automatic devices - <https://www.drivendata.org/termsofuse/>
  - Listing shows cards such as 'The Geologic Enhanced Mapping System (GEMS) Prize Challenge ... $300,000 in prizes 4 weeks left' - <https://www.drivendata.org/competitions/>
- **Scores:** relevance 3 (Good competitions, many in non-AI-systems domains.) | authority 4 (Operator.) | signal quality 2 (No absolute deadlines in the list.) | freshness 4 (Active.) | integration 0 (Automated access prohibited.)
- **Uncertainties:** Whether the operator would permit a low-rate personal reader
- **Next action:** Do not activate. Track manually or request permission.
- **Stages:** A=yes, B=yes, C=no, D=no, E=no, F=no

### S45 - ESA careers portal (students & graduates)  
**Status:** MANUAL_REVIEW | **Priority:** Hold | **Score:** 12/25 | **Confidence:** low

- **Publisher:** European Space Agency (first-party)
- **Category:** C - Research internships and student technical opportunities | **Batch:** 5
- **Canonical URL:** https://jobs.esa.int/
- **Endpoint:** https://jobs.esa.int/
- **Discovery:** JavaScript careers portal behind a cookie consent
- **Opportunity types:** student placements, young graduate roles
- **Audience/eligibility:** Per listing (not read).
- **Geography / remote:** Europe / No
- **Value:** Relevant robotics/autonomy placements exist at ESA, but the portal exposes no static content to our fetcher (guessed student pages returned 404).
- **Auth / registration:** none to browse / Account to apply
- **Adapter fit:** Playwright (missing) (gap) | stable IDs: Unknown | dates: Unknown | difficulty: High: JS portal; static pages not located.
- **Policy:** unclear - robots.txt allows; portal content not available without JavaScript.
- **Terms:** https://www.esa.int/Services/Terms_and_conditions - ESA terms page read (8,493 chars): no scraping/automation clause found by keyword scan.
- **Rate limits:** Unknown | **Polling guidance:** manual | **Proposed interval:** 720 h | **Stability:** Medium.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://jobs.esa.int/ - robots allowed=True (robots HTTP 200), HTTP 200, text/html, 63006 bytes
- **Evidence:**
  - jobs.esa.int returns 200 with cookie-consent text only (no job content) - <https://jobs.esa.int/>
  - ESA terms and conditions page - <https://www.esa.int/Services/Terms_and_conditions>
- **Scores:** relevance 3 (Space/robotics roles; limited bachelor fit unknown.) | authority 5 (Official agency.) | signal quality 1 (No visible data.) | freshness 2 (Unknown.) | integration 1 (JS only.)
- **Uncertainties:** Student programme URL and any feed
- **Next action:** Locate an official static student-opportunity page or RSS.
- **Stages:** A=yes, B=yes, C=no, D=no, E=no, F=no

### S46 - EURAXESS jobs  
**Status:** MANUAL_REVIEW | **Priority:** Hold | **Score:** 18/25 | **Confidence:** high

- **Publisher:** European Commission (EURAXESS) (first-party)
- **Category:** C - Research internships and student technical opportunities | **Batch:** 5
- **Canonical URL:** https://euraxess.ec.europa.eu/
- **Endpoint:** https://euraxess.ec.europa.eu/jobs/search
- **Discovery:** Job search (HTML); robots.txt disallows /jobs/* for all agents
- **Opportunity types:** research jobs and fellowships across Europe
- **Audience/eligibility:** Researchers; some listings for early-stage researchers.
- **Geography / remote:** Europe / Some
- **Value:** Authoritative European researcher job portal, but our agent is disallowed.
- **Auth / registration:** none / none to browse
- **Adapter fit:** none while robots disallows (gap) | stable IDs: job node id | dates: Yes | difficulty: Blocked by robots.txt.
- **Policy:** blocked - robots.txt has 'Allow: /jobs' followed by 'Disallow: /jobs/*'; our robots-checked fetch refused /jobs/search.
- **Terms:** https://commission.europa.eu/legal-notice_en - EU legal notice: EU-owned content licensed CC BY 4.0 (reuse allowed with credit); robots.txt still disallows /jobs/*.
- **Rate limits:** Unknown | **Polling guidance:** none | **Proposed interval:** 720 h | **Stability:** High.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://euraxess.ec.europa.eu/jobs/search - robots allowed=False (robots HTTP 200), HTTP None, None, None bytes - blocked by robots.txt for our agent; not fetched
- **Evidence:**
  - robots.txt lines: 'Allow: /jobs' and 'Disallow: /jobs/*' - <https://euraxess.ec.europa.eu/robots.txt>
  - EU legal notice states CC BY 4.0 for EU-owned content - <https://commission.europa.eu/legal-notice_en>
- **Scores:** relevance 4 (Research jobs across Europe.) | authority 5 (European Commission.) | signal quality 4 (Rich structured data (not retrieved).) | freshness 5 (Continuous.) | integration 0 (Disallowed by robots.txt.)
- **Uncertainties:** Existence of an official data feed/API
- **Next action:** Search for an official EURAXESS API/export before any use.
- **Stages:** A=yes, B=yes, C=no, D=no, E=no, F=no

### S47 - Fulbright Germany  
**Status:** PROBE_PASSED | **Priority:** P2 | **Score:** 17/25 | **Confidence:** medium

- **Publisher:** German-American Fulbright Commission (first-party)
- **Category:** D - Scholarships, fellowships and grants | **Batch:** 5
- **Canonical URL:** https://www.fulbright.de/
- **Endpoint:** https://www.fulbright.de/
- **Discovery:** Programme site (HTML, Nuxt)
- **Opportunity types:** exchange scholarships between Germany and the USA
- **Audience/eligibility:** Not verified for bachelor students in this run.
- **Geography / remote:** Germany/USA / n/a
- **Value:** Prestigious exchange funder; the homepage shows 19 dated entries (e.g. 02.10.2026, 30.09.2026) including deadline wording.
- **Auth / registration:** none / Application portal (not accessed)
- **Adapter fit:** html (existing) | stable IDs: None | dates: Yes (DD.MM.YYYY) | difficulty: Medium: dates are in news/teasers; programme eligibility is on sub-pages.
- **Policy:** unclear - robots.txt allows; terms not reviewed.
- **Terms:** https://www.fulbright.de/ - Not reviewed.
- **Rate limits:** None published | **Polling guidance:** estimate 168 h | **Proposed interval:** 168 h | **Stability:** High.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://www.fulbright.de/ - robots allowed=True (robots HTTP 200), HTTP 200, text/html, 382567 bytes
- **Evidence:**
  - Homepage mentions 'Seit 1952 ermöglicht die Deutsch-Amerikanische Fulbright-Kommission ...' and carries dated entries - <https://www.fulbright.de/>
- **Scores:** relevance 3 (Prestigious but graduate-leaning (to verify).) | authority 5 (Binational commission.) | signal quality 3 (Dates on homepage; eligibility elsewhere.) | freshness 3 (Dated items 2026.) | integration 3 (Existing adapter.)
- **Uncertainties:** Eligibility for bachelor students; Which dates are deadlines
- **Next action:** Read programme pages; add the specific scholarship page to the entry.
- **Stages:** A=yes, B=no, C=yes, D=yes, E=no, F=no

### S48 - RSS: Robotics Science and Systems 2027  
**Status:** PROBE_PASSED | **Priority:** P1 | **Score:** 22/25 | **Confidence:** high

- **Publisher:** Robotics: Science and Systems Foundation (first-party)
- **Category:** E - AI/ML conferences, workshops and summer schools | **Batch:** 5
- **Canonical URL:** https://roboticsconference.org/
- **Endpoint:** https://roboticsconference.org/
- **Discovery:** Conference homepage (HTML); the Atom feed is stale (items from 2019)
- **Opportunity types:** conference dates, call for papers/participation, deadlines
- **Audience/eligibility:** Researchers, students.
- **Geography / remote:** Global (2027: Athens, Greece) / n/a
- **Value:** Top robotics venue; homepage shows July 6-11, 2027 in Athens and several dated deadlines (December 4, 2026; February 5, 2027; February 12, 2027).
- **Auth / registration:** none / none
- **Adapter fit:** html (existing) | stable IDs: None | dates: Yes | difficulty: Low.
- **Policy:** unclear - robots.txt returned 404 (no restrictions per RFC 9309); terms not reviewed.
- **Terms:** https://roboticsconference.org/ - Not reviewed.
- **Rate limits:** None published | **Polling guidance:** estimate 168 h | **Proposed interval:** 168 h | **Stability:** Medium: site rebuilt per year.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://roboticsconference.org/ - robots allowed=True (robots HTTP 404), HTTP 200, text/html, 11452 bytes
- **Evidence:**
  - Homepage: 'Robotics: Science and Systems July 6-11, 2027 Athens, Greece' with deadline dates - <https://roboticsconference.org/>
  - Atom feed newest item dated 2019-12-04 (stale) - <https://roboticsconference.org/atom.xml>
- **Scores:** relevance 5 (Core robotics venue.) | authority 5 (Official site.) | signal quality 4 (Several explicit dates on homepage.) | freshness 4 (2027 edition announced.) | integration 4 (Existing adapter.)
- **Uncertainties:** Which dates map to submission vs registration
- **Next action:** Probe with ohg.
- **Stages:** A=yes, B=no, C=yes, D=yes, E=no, F=no

### S49 - Eastern European Machine Learning (EEML) Summer School  
**Status:** PROBE_PASSED | **Priority:** P2 | **Score:** 17/25 | **Confidence:** medium

- **Publisher:** EEML / Montenegrin AI Association (first-party)
- **Category:** E - AI/ML conferences, workshops and summer schools | **Batch:** 5
- **Canonical URL:** https://www.eeml.eu/
- **Endpoint:** https://www.eeml.eu/
- **Discovery:** Programme site (HTML, Google Sites)
- **Opportunity types:** annual ML summer school
- **Audience/eligibility:** Students and researchers (details not read).
- **Geography / remote:** Europe (2026: Cetinje, Montenegro) / No
- **Value:** Established annual ML summer school; the 2026 edition (27 July - 1 August 2026) has finished and its application deadline passed.
- **Auth / registration:** none / Application form (not accessed)
- **Adapter fit:** html (existing) | stable IDs: None | dates: 2026 dates stated; 2027 unknown | difficulty: Low.
- **Policy:** unclear - robots.txt returned 404 (no restrictions per RFC 9309); terms not reviewed.
- **Terms:** https://www.eeml.eu/ - Not reviewed.
- **Rate limits:** None published | **Polling guidance:** estimate 168-720 h | **Proposed interval:** 720 h | **Stability:** Medium.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://www.eeml.eu/ - robots allowed=True (robots HTTP 404), HTTP 200, text/html, 428485 bytes
- **Evidence:**
  - Homepage: 'Eastern European Machine Learning Summer School 27 July-1 August 2026, Cetinje, Montenegro ... The deadline for applications has passed' - <https://www.eeml.eu/>
- **Scores:** relevance 4 (ML summer school in Europe; bachelor eligibility unknown.) | authority 4 (Organisers' own site.) | signal quality 3 (Dates clear for 2026; nothing for 2027 yet.) | freshness 2 (Between editions.) | integration 4 (Static page.)
- **Uncertainties:** 2027 edition; Eligibility for bachelor students
- **Next action:** Low-frequency polling until the 2027 call appears.
- **Stages:** A=yes, B=no, C=yes, D=yes, E=no, F=no

### S50 - LFX Mentorship  
**Status:** MANUAL_REVIEW | **Priority:** Hold | **Score:** 13/25 | **Confidence:** low

- **Publisher:** The Linux Foundation (first-party)
- **Category:** F - Open-source programmes, technical challenges and cybersecurity | **Batch:** 5
- **Canonical URL:** https://lfx.linuxfoundation.org/tools/mentorship/
- **Endpoint:** https://mentorship.lfx.linuxfoundation.org/
- **Discovery:** JavaScript application (static HTML shows placeholder counters)
- **Opportunity types:** paid/unpaid open-source mentorship terms across foundations
- **Audience/eligibility:** Per programme.
- **Geography / remote:** Global / Yes
- **Value:** Broad open-source mentorship programme, but the listing is rendered in the browser; no static data or API was verified.
- **Auth / registration:** none to browse / LFX account to apply
- **Adapter fit:** Playwright / JSON API (missing) (gap) | stable IDs: Unknown | dates: Unknown | difficulty: High until an API/feed is found.
- **Policy:** unclear - robots.txt returned 404 on lfx.*; listing needs JavaScript.
- **Terms:** https://www.linuxfoundation.org/legal/terms - LF terms: site content licensed CC BY 3.0 per the terms page; no automated-access rule found by keyword scan.
- **Rate limits:** Unknown | **Polling guidance:** manual | **Proposed interval:** 720 h | **Stability:** Medium.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://mentorship.lfx.linuxfoundation.org/ - robots allowed=True (robots HTTP 200), HTTP 200, text/html, 32124 bytes
- **Evidence:**
  - Page shows '0 mentees graduated since 2019' and '0 programs across 0 foundations' placeholders (JS-populated) - <https://mentorship.lfx.linuxfoundation.org/>
  - CNCF mentoring repository lists programmes in Markdown on GitHub (alternative lead source) - <https://github.com/cncf/mentoring>
- **Scores:** relevance 3 (Open-source mentorship; moderate fit.) | authority 5 (Linux Foundation.) | signal quality 1 (No static data.) | freshness 3 (Unknown.) | integration 1 (JS only.)
- **Uncertainties:** Public API or feed
- **Next action:** Find a documented API; consider CNCF mentoring GitHub as a substitute lead.
- **Stages:** A=yes, B=yes, C=no, D=no, E=no, F=no
