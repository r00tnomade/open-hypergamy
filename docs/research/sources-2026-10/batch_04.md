# Batch 4 (10 sources)

Verification pass: 2026-10-30T01:17:32+01:00 (Europe/Berlin). Nothing here is activated.

| ID | Cat | Source | Endpoint | Method | Status | Policy | Score | Pri |
|---|---|---|---|---|---|---|---|---|
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

## Profiles

### S31 - ELLIS event calendar  
**Status:** PROBE_PASSED | **Priority:** P1 | **Score:** 20/25 | **Confidence:** medium

- **Publisher:** European Laboratory for Learning and Intelligent Systems (ELLIS) (first-party)
- **Category:** B - Robotics and research opportunities | **Batch:** 4
- **Canonical URL:** https://ellis.eu/
- **Endpoint:** https://ellis.eu/event-calendar
- **Discovery:** Event calendar (HTML)
- **Opportunity types:** workshops, summits, conferences and summer schools at ELLIS units across Europe
- **Audience/eligibility:** AI researchers and students; per event.
- **Geography / remote:** Europe (incl. German units) / Some
- **Value:** Dated pan-European AI events (e.g. 'ELLIS UnConference 2026' on 8 Dec 2026 in Paris; unit summits in Turku, Warsaw, Milan).
- **Auth / registration:** none / none
- **Adapter fit:** html (existing) | stable IDs: Event page URL | dates: Yes (DD/MM/YY format) | difficulty: Low-medium: dates in 'DD/MM/YY' form; the strict parser may flag two-digit years.
- **Policy:** unclear - robots.txt allows; terms not reviewed. /feed returned 404.
- **Terms:** https://ellis.eu/about/privacy-policy - Privacy policy only.
- **Rate limits:** None published | **Polling guidance:** estimate 72 h | **Proposed interval:** 72 h | **Stability:** Medium-high.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://ellis.eu/event-calendar - robots allowed=True (robots HTTP 200), HTTP 200, text/html, 123222 bytes
- **Evidence:**
  - Calendar entries: '08/12/26 • Palais des Congrès de Paris ELLIS UnConference 2026', '26/11/26 • Milan ...' - <https://ellis.eu/event-calendar>
  - Search result: ELLIS summer schools are published as /events/<slug> pages (2026 editions at Tübingen, Munich, Cambridge) - <https://ellis.eu/events/ellis-summer-school-at-institute-tuebingen-2026>
- **Scores:** relevance 5 (AI research events and summer schools in Europe/Germany.) | authority 5 (Official network.) | signal quality 3 (Dates yes; deadlines inside event pages.) | freshness 4 (Events through Dec 2026.) | integration 3 (Date format needs handling; depth-1 crawl for details.)
- **Uncertainties:** Two-digit-year date handling; 2027 summer school listings
- **Next action:** Probe with ohg; follow events pages at depth 1.
- **Stages:** A=yes, B=no, C=yes, D=yes, E=no, F=no

### S32 - Helmholtz AI  
**Status:** PROBE_PASSED | **Priority:** P2 | **Score:** 19/25 | **Confidence:** medium

- **Publisher:** Helmholtz AI (Helmholtz Association) (first-party)
- **Category:** B - Robotics and research opportunities | **Batch:** 4
- **Canonical URL:** https://www.helmholtz.ai/
- **Endpoint:** https://www.helmholtz.ai/
- **Discovery:** Homepage with news and dated event list (HTML)
- **Opportunity types:** AI project funding calls; events and symposia; consulting/compute access for Helmholtz researchers
- **Audience/eligibility:** Mainly researchers in the Helmholtz Association; not student-specific.
- **Geography / remote:** Germany/Europe / Some
- **Value:** German applied-AI research platform; homepage lists dated events (e.g. 02.12.2026, 30.11.2026, 09.11.2026).
- **Auth / registration:** none / none
- **Adapter fit:** html (existing) | stable IDs: None | dates: Yes (DD.MM.YYYY) | difficulty: Low.
- **Policy:** unclear - robots.txt allows; terms not reviewed.
- **Terms:** https://www.helmholtz.ai/ - Not reviewed.
- **Rate limits:** None published | **Polling guidance:** estimate 72 h | **Proposed interval:** 72 h | **Stability:** High.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://www.helmholtz.ai/ - robots allowed=True (robots HTTP 200), HTTP 200, text/html, 167483 bytes
- **Evidence:**
  - Homepage: 'Project funding: Secure funding ... via our AI project call' and dated events '02.12.2026', '30.11.2026', '09.11.2026' - <https://www.helmholtz.ai/>
- **Scores:** relevance 3 (AI research ecosystem; mostly for Helmholtz staff.) | authority 5 (Official platform.) | signal quality 3 (Dated events; eligibility for students unclear.) | freshness 4 (Events through Dec 2026.) | integration 4 (Existing adapter.)
- **Uncertainties:** Whether students outside Helmholtz can use any offering
- **Next action:** Review which sections are relevant before activation.
- **Stages:** A=yes, B=no, C=yes, D=yes, E=no, F=no

### S33 - Codabench public competitions  
**Status:** MANUAL_REVIEW | **Priority:** P2 | **Score:** 13/25 | **Confidence:** low

- **Publisher:** Codabench (open-source platform, CNRS/Université Paris-Saclay ecosystem) (first-party platform)
- **Category:** A - AI/ML hackathons and competitions | **Batch:** 4
- **Canonical URL:** https://www.codabench.org/
- **Endpoint:** https://www.codabench.org/competitions/public/
- **Discovery:** Public listing page loaded dynamically; API docs linked at /api/docs/ (JavaScript, not readable in this run)
- **Opportunity types:** AI benchmarks and competitions
- **Audience/eligibility:** Researchers and practitioners; per-competition rules.
- **Geography / remote:** Global / Yes
- **Value:** Open-source benchmark platform with a public competition list and documented API link.
- **Auth / registration:** none to browse / Account to participate
- **Adapter fit:** JSON API / JS render (missing) (gap) | stable IDs: competition id | dates: Not visible without JS | difficulty: High until the API contract is confirmed.
- **Policy:** unclear - Listing page returns 497 characters of static text; data loads dynamically.
- **Terms:** https://www.codabench.org/ - Footer lists 'Privacy and Terms'; not read.
- **Rate limits:** Unknown | **Polling guidance:** estimate 24 h | **Proposed interval:** 24 h | **Stability:** Medium.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://www.codabench.org/competitions/public/ - robots allowed=True (robots HTTP 404), HTTP 200, text/html, 13441 bytes
- **Evidence:**
  - Public page links 'API docs' and shows 'Open-source platform for AI benchmarks and competitions' - <https://www.codabench.org/competitions/public/>
  - Documentation site - <https://docs.codabench.org/latest/>
- **Scores:** relevance 3 (Research benchmarks; moderate student relevance.) | authority 4 (Maintained open-source platform.) | signal quality 2 (Not assessed (dynamic).) | freshness 3 (Unknown.) | integration 1 (Needs API contract + adapter.)
- **Uncertainties:** Public list API path and terms
- **Next action:** Read https://www.codabench.org/api/docs/ in a browser and confirm a public listing endpoint.
- **Stages:** A=yes, B=no, C=no, D=no, E=no, F=no

### S34 - Junction hackathon  
**Status:** MANUAL_REVIEW | **Priority:** Hold | **Score:** 11/25 | **Confidence:** low

- **Publisher:** Junction (Hackjunction) (first-party)
- **Category:** A - AI/ML hackathons and competitions | **Batch:** 4
- **Canonical URL:** https://www.hackjunction.com/
- **Endpoint:** https://www.hackjunction.com/
- **Discovery:** Single-page JavaScript site (no static content observed)
- **Opportunity types:** large European hackathon (annual)
- **Audience/eligibility:** Participants of the event; not verified.
- **Geography / remote:** Europe (Finland) / No
- **Value:** Large annual European hackathon; the site is a JavaScript shell (1.6 KB HTML, 0 visible text characters).
- **Auth / registration:** none / n/a
- **Adapter fit:** Playwright (missing) (gap) | stable IDs: None | dates: Not extractable without rendering | difficulty: High: needs Playwright and policy approval; one event per year.
- **Policy:** unclear - robots.txt allows; no content without JavaScript.
- **Terms:** https://www.hackjunction.com/ - Not reviewed.
- **Rate limits:** None | **Polling guidance:** monthly (estimate) | **Proposed interval:** 720 h | **Stability:** Medium.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://www.hackjunction.com/ - robots allowed=True (robots HTTP 200), HTTP 200, text/html, 1615 bytes
- **Evidence:**
  - Fetched page is 1,615 bytes with no visible text; title 'Hackjunction' - <https://www.hackjunction.com/>
  - /events returned 200 with 0 visible characters - <https://www.hackjunction.com/events>
- **Scores:** relevance 3 (One big hackathon per year.) | authority 4 (Organiser site.) | signal quality 1 (No extractable data.) | freshness 2 (Unknown.) | integration 1 (Requires rendering.)
- **Uncertainties:** 2026/2027 dates; Eligibility
- **Next action:** Check manually; skip until a Playwright adapter exists.
- **Stages:** A=yes, B=no, C=no, D=no, E=no, F=no

### S35 - TH Mannheim Career Center  
**Status:** MANUAL_REVIEW | **Priority:** P2 | **Score:** 16/25 | **Confidence:** medium

- **Publisher:** Technische Hochschule Mannheim (first-party (the user's own university))
- **Category:** C - Research internships and student technical opportunities | **Batch:** 4
- **Canonical URL:** https://www.career.hs-mannheim.de/
- **Endpoint:** https://www.career.hs-mannheim.de/
- **Discovery:** Career Center page (HTML); student job board runs on JobTeaser (access model unverified)
- **Opportunity types:** career events, company contact fairs (e.g. CareerStation 29 April 2027), job board
- **Audience/eligibility:** Students and alumni of the university.
- **Geography / remote:** Mannheim / n/a
- **Value:** The user's own institution; the Career Center page shows dated events (14 date mentions) and the annual CareerStation fair on 29 April 2027.
- **Auth / registration:** Unknown for the job board / Likely student login for JobTeaser (unverified)
- **Adapter fit:** html (existing) | stable IDs: None | dates: Yes for events | difficulty: Medium-high: the actual job listings are on JobTeaser and probably login-gated.
- **Policy:** unclear - The Career Center page is public; job board access likely requires login which must not be bypassed.
- **Terms:** https://www.hs-mannheim.de/unternehmen/jobteaser.html - Page describes JobTeaser career network for recruiters; student access rules not stated.
- **Rate limits:** n/a | **Polling guidance:** estimate 72 h for the events page | **Proposed interval:** 72 h | **Stability:** Medium.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://www.career.hs-mannheim.de/ - robots allowed=True (robots HTTP 200), HTTP 200, text/html, 74166 bytes
- **Evidence:**
  - Career Center page lists dated events (e.g. '1. September 2026', '02.12.2026') - <https://www.career.hs-mannheim.de/>
  - CareerStation fair: 'Willkommen bei der CareerStation 2027' (29. April 2027) - <https://www.hs-mannheim.de/studierende/careerstation-fuer-studierende.html>
  - JobTeaser Karrierenetzwerk of the university - <https://www.hs-mannheim.de/unternehmen/jobteaser.html>
- **Scores:** relevance 4 (Local jobs/internships, but not AI-specific.) | authority 5 (The university itself.) | signal quality 2 (Events are dated; jobs not visible.) | freshness 3 (Current events listed.) | integration 2 (Job board likely gated.)
- **Uncertainties:** Whether JobTeaser exposes a public feed; Login requirements
- **Next action:** Check with the Career Center whether a public feed exists; track events page meanwhile.
- **Stages:** A=yes, B=yes, C=no, D=no, E=no, F=no

### S36 - DAAD scholarship database  
**Status:** MANUAL_REVIEW | **Priority:** Hold | **Score:** 16/25 | **Confidence:** low

- **Publisher:** Deutscher Akademischer Austauschdienst (DAAD) (first-party)
- **Category:** D - Scholarships, fellowships and grants | **Batch:** 4
- **Canonical URL:** https://www.daad.de/
- **Endpoint:** https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/
- **Discovery:** Search-form database (the English page verified is the inbound variant for international applicants)
- **Opportunity types:** scholarships for study, research stays and internships
- **Audience/eligibility:** Page verified for 'international students and researchers'; the outbound variant for German students was not located (guessed outbound URLs returned 404).
- **Geography / remote:** Germany and abroad / n/a
- **Value:** DAAD is the main funder of study/research stays; secondary sources say the database is the starting point for German bachelor students searching with status 'Studierende'.
- **Auth / registration:** none / none to browse
- **Adapter fit:** form/search (missing) (gap) | stable IDs: programme id in URL | dates: Per programme | difficulty: High: results come from form queries; no static list.
- **Policy:** unclear - robots.txt returned 404; form-driven search is not a polling target.
- **Terms:** https://www.daad.de/ - Not reviewed.
- **Rate limits:** None published | **Polling guidance:** manual | **Proposed interval:** 720 h | **Stability:** High.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/ - robots allowed=True (robots HTTP 404), HTTP 200, text/html, 23476 bytes
- **Evidence:**
  - Database page: 'Here you will find information about our DAAD scholarship programmes for international students and researchers' - <https://www2.daad.de/deutschland/stipendium/datenbank/en/21148-scholarship-database/>
  - Secondary: Uni Mannheim page says Bachelor students search with status 'Studierende' (search snippet, not fetched) - <https://www.uni-mannheim.de/studium/von-mannheim-ins-ausland/austauschstudium/finanzierung/stipendien>
- **Scores:** relevance 4 (Major funder for stays abroad; the relevant outbound entry point is unverified.) | authority 5 (Official funder.) | signal quality 3 (Rich per-programme data, but only via search.) | freshness 3 (Continuously updated.) | integration 1 (No static endpoint.)
- **Uncertainties:** Outbound database URL; Any public data feed
- **Next action:** Manual review: find the German outbound database URL; consider monthly human check.
- **Stages:** A=yes, B=no, C=no, D=no, E=no, F=no

### S37 - Deutschlandstipendium (BMFTR)  
**Status:** PROBE_PASSED | **Priority:** P2 | **Score:** 14/25 | **Confidence:** medium

- **Publisher:** German Federal Ministry (BMFTR) (first-party)
- **Category:** D - Scholarships, fellowships and grants | **Batch:** 4
- **Canonical URL:** https://www.deutschlandstipendium.de/
- **Endpoint:** https://www.deutschlandstipendium.de/deutschlandstipendium/de/home/home_node.html
- **Discovery:** Official programme site (HTML); applications go through each university
- **Opportunity types:** merit scholarship (EUR 300/month, estimate from programme knowledge, not verified in this run)
- **Audience/eligibility:** Students at participating German universities.
- **Geography / remote:** Germany / n/a
- **Value:** Directly applicable at universities of applied sciences; the national site gives general information and news.
- **Auth / registration:** none / Via the student's university
- **Adapter fit:** html (existing) | stable IDs: None | dates: None on the home page | difficulty: Medium: per-university deadlines are the real signal and live on each university site (Mannheim page not located).
- **Policy:** unclear - robots.txt allows; terms not reviewed.
- **Terms:** https://www.deutschlandstipendium.de/ - Not reviewed.
- **Rate limits:** None published | **Polling guidance:** estimate 168 h | **Proposed interval:** 168 h | **Stability:** High.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://www.deutschlandstipendium.de/deutschlandstipendium/de/home/home_node.html - robots allowed=True (robots HTTP 200), HTTP 200, text/html, 111173 bytes
- **Evidence:**
  - Home page 'Startseite - BMFTR Deutschlandstipendium' with news items - <https://www.deutschlandstipendium.de/deutschlandstipendium/de/home/home_node.html>
- **Scores:** relevance 3 (Relevant to the user but deadlines are at the university.) | authority 5 (Federal ministry.) | signal quality 1 (No dates on probed page.) | freshness 2 (News only.) | integration 3 (Low data yield.)
- **Uncertainties:** Hochschule Mannheim's application window
- **Next action:** Add the university's scholarship page as its own source.
- **Stages:** A=yes, B=no, C=yes, D=yes, E=no, F=no

### S38 - CoRL 2026  
**Status:** PROBE_PASSED | **Priority:** P1 | **Score:** 19/25 | **Confidence:** high

- **Publisher:** Conference on Robot Learning (first-party)
- **Category:** E - AI/ML conferences, workshops and summer schools | **Batch:** 4
- **Canonical URL:** https://www.corl.org/
- **Endpoint:** https://www.corl.org/
- **Discovery:** Conference site (HTML, Google Sites)
- **Opportunity types:** conference dates, calls, workshops, volunteering
- **Audience/eligibility:** Researchers, students.
- **Geography / remote:** Global (2026: Austin, Texas) / n/a
- **Value:** Premier robot-learning venue; homepage: CoRL 2026, November 9-12, 2026, Austin, Texas.
- **Auth / registration:** none / none
- **Adapter fit:** html (existing) | stable IDs: Year in site | dates: Yes | difficulty: Low-medium: Google Sites page structure; yearly redesign.
- **Policy:** unclear - robots.txt returned 404 (no restrictions per RFC 9309); terms not reviewed.
- **Terms:** https://www.corl.org/ - Not reviewed.
- **Rate limits:** None published | **Polling guidance:** estimate 168 h | **Proposed interval:** 168 h | **Stability:** Medium: site is recreated each year.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://www.corl.org/ - robots allowed=True (robots HTTP 404), HTTP 200, text/html, 279783 bytes
- **Evidence:**
  - Homepage: 'Conference on Robot Learning November 9-12, 2026 | Austin, Texas, US' - <https://www.corl.org/>
- **Scores:** relevance 5 (Robot learning is a stated focus.) | authority 5 (Official site.) | signal quality 3 (Dates yes; other deadlines on sub-pages.) | freshness 3 (2026 edition within weeks; 2027 unknown.) | integration 3 (Yearly URL/structure drift.)
- **Uncertainties:** 2027 site timing
- **Next action:** Re-check after the 2026 conference for the 2027 site.
- **Stages:** A=yes, B=no, C=yes, D=yes, E=no, F=no

### S39 - Cyber Security Challenge Germany (CSCG)  
**Status:** PROBE_PASSED | **Priority:** P2 | **Score:** 17/25 | **Confidence:** medium

- **Publisher:** NFITS e.V. (first-party)
- **Category:** F - Open-source programmes, technical challenges and cybersecurity | **Batch:** 4
- **Canonical URL:** https://cscg.de/
- **Endpoint:** https://cscg.de/
- **Discovery:** Programme site (HTML); RSS at /index.xml exists but its newest item is from March 2024
- **Opportunity types:** annual online security competition (1 March - 1 May) feeding Germany's ECSC team
- **Audience/eligibility:** People in Germany; age/eligibility on the site (not read).
- **Geography / remote:** Germany / Yes (online qualifier)
- **Value:** Germany's national CTF qualifier; page states it runs yearly from 1 March to 1 May online.
- **Auth / registration:** none / Participation via play.cscg.live
- **Adapter fit:** html (existing) | stable IDs: None | dates: Annual window stated | difficulty: Low: tiny static page.
- **Policy:** unclear - robots.txt returned 404 (no restrictions per RFC 9309); terms not reviewed.
- **Terms:** https://cscg.de/ - Not reviewed.
- **Rate limits:** None published | **Polling guidance:** estimate 168 h | **Proposed interval:** 168 h | **Stability:** High.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://cscg.de/ - robots allowed=True (robots HTTP 404), HTTP 200, text/html, 5486 bytes
- **Evidence:**
  - Page: 'Die CSCG findet jährlich vom 1. März bis zum 1. Mai online statt.' - <https://cscg.de/>
  - RSS feed parses (28 entries) but newest observed entry is 'Start der CSCG 2024' (1 Mar 2024), so it is stale - <https://cscg.de/index.xml>
- **Scores:** relevance 3 (Security competition in Germany; secondary priority.) | authority 4 (Organiser (NFITS e.V.).) | signal quality 3 (Annual window stated; eligibility to be read.) | freshness 3 (Feed stale since 2024; page current.) | integration 4 (Static HTML.)
- **Uncertainties:** 2027 edition announcement date; Eligibility
- **Next action:** Poll the page weekly in February.
- **Stages:** A=yes, B=no, C=yes, D=yes, E=no, F=no

### S40 - European Cybersecurity Challenge (ECSC)  
**Status:** PROBE_PASSED | **Priority:** P2 | **Score:** 15/25 | **Confidence:** high

- **Publisher:** ENISA / ECSC organisers (first-party)
- **Category:** F - Open-source programmes, technical challenges and cybersecurity | **Batch:** 4
- **Canonical URL:** https://ecsc.eu/
- **Endpoint:** https://ecsc.eu/
- **Discovery:** Programme site (HTML)
- **Opportunity types:** annual European security competition
- **Audience/eligibility:** Selected national teams; individuals qualify through national competitions.
- **Geography / remote:** Europe / No (on-site finals)
- **Value:** Pan-European security championship (2026: Bochum, 12-16 Oct 2026) with national qualifier pipeline.
- **Auth / registration:** none / National team selection (via national qualifiers such as CSCG)
- **Adapter fit:** html (existing) | stable IDs: None | dates: Edition dates stated | difficulty: Low.
- **Policy:** unclear - robots.txt returned 404 (no restrictions per RFC 9309); terms not reviewed.
- **Terms:** https://ecsc.eu/ - Not reviewed.
- **Rate limits:** None published | **Polling guidance:** estimate 168 h | **Proposed interval:** 168 h | **Stability:** High.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://ecsc.eu/ - robots allowed=True (robots HTTP 404), HTTP 200, text/html, 48229 bytes
- **Evidence:**
  - Homepage: 'EUROPEAN CYBERSECURITY CHALLENGE 2026 ... 12th - 16th October 2026 Bochum, Germany' - <https://ecsc.eu/>
- **Scores:** relevance 2 (Individuals reach it only via national qualifiers.) | authority 5 (Official organisers.) | signal quality 2 (Edition info; no application details.) | freshness 2 (2026 edition just ended.) | integration 4 (Static HTML.)
- **Uncertainties:** 2027 host/dates
- **Next action:** Track yearly; mostly redundant with S39.
- **Stages:** A=yes, B=no, C=yes, D=yes, E=no, F=no
