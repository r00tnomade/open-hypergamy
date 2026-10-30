# Batch 3 (10 sources)

Verification pass: 2026-10-30T01:17:32+01:00 (Europe/Berlin). Nothing here is activated.

| ID | Cat | Source | Endpoint | Method | Status | Policy | Score | Pri |
|---|---|---|---|---|---|---|---|---|
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

## Profiles

### S21 - euROBIN events and competitions  
**Status:** PROBE_PASSED | **Priority:** P1 | **Score:** 18/25 | **Confidence:** medium

- **Publisher:** euROBIN (European Robotics and AI Network) (first-party (EU-funded network))
- **Category:** B - Robotics and research opportunities | **Batch:** 3
- **Canonical URL:** https://www.eurobin-project.eu/
- **Endpoint:** https://www.eurobin-project.eu/index.php/events
- **Discovery:** Event listing page (HTML); related pages: /competitions, /competitions/hackathons; open calls run on a separate FundingBox site
- **Opportunity types:** events; robotics competitions/hackathons; open calls (external platform)
- **Audience/eligibility:** Robotics researchers, students, SMEs.
- **Geography / remote:** Europe / Some online
- **Value:** European robotics network with a dated events list (41 dates on the page) plus competition and hackathon pages.
- **Auth / registration:** none / none
- **Adapter fit:** html (existing) | stable IDs: Joomla article URLs | dates: Yes on events page (e.g. 09 July 2026, 17 June 2026) | difficulty: Low-medium: Joomla page; open calls are on a different publisher (FundingBox) and not assessed.
- **Policy:** unclear - robots.txt allows; terms not reviewed. The FundingBox open-call site was not probed.
- **Terms:** https://www.eurobin-project.eu/index.php/privacy-policy - Privacy policy only.
- **Rate limits:** None published | **Polling guidance:** estimate 72 h | **Proposed interval:** 72 h | **Stability:** Medium-low: project-based site; a funded project's site may change when the project ends (estimate, end date not checked).
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://www.eurobin-project.eu/index.php/events - robots allowed=True (robots HTTP 200), HTTP 200, text/html, 105748 bytes
- **Evidence:**
  - Events page lists dated events ('09 July 2026 ... AI-based Robotics in Europe: Live technology demonstration') - <https://www.eurobin-project.eu/index.php/events>
  - Homepage links Competitions, Hackathons, Coopetitions and 'Open calls' (eurobin-network.fundingbox.com) - <https://www.eurobin-project.eu/>
- **Scores:** relevance 4 (Robotics competitions and hackathons in Europe.) | authority 4 (Project consortium, first-party.) | signal quality 3 (Dates yes; eligibility per competition page.) | freshness 3 (Latest listed event July 2026.) | integration 4 (Existing adapter; one listing page.)
- **Uncertainties:** Project end date and site longevity; FundingBox call access policy
- **Next action:** Probe with ohg; evaluate FundingBox separately.
- **Stages:** A=yes, B=no, C=yes, D=yes, E=no, F=no

### S22 - Cyber Valley careers  
**Status:** PROBE_PASSED | **Priority:** P0 | **Score:** 20/25 | **Confidence:** high

- **Publisher:** Cyber Valley GmbH (Tübingen/Stuttgart AI & robotics network) (first-party)
- **Category:** B - Robotics and research opportunities | **Batch:** 3
- **Canonical URL:** https://cyber-valley.de/
- **Endpoint:** https://cyber-valley.de/career/
- **Discovery:** Career listing page (HTML); /en/jobs redirects here
- **Opportunity types:** research engineer roles; working student and student assistant positions; PhD/postdoc roles; internships (one listing is for PhD students)
- **Audience/eligibility:** Per listing; includes working-student and student-assistant roles.
- **Geography / remote:** Germany (Baden-Württemberg) / Mostly on-site
- **Value:** Regional AI/robotics hub with listings such as 'Computer Vision Engineer – Working Student' and 'Student Assistant'.
- **Auth / registration:** none / none
- **Adapter fit:** html (existing) | stable IDs: Job URL slug (/job/<slug>/) | dates: Listing page shows titles/locations; dates are on job pages | difficulty: Low-medium: list page + detail pages; crawl depth 1 would reach the details.
- **Policy:** unclear - robots.txt allows; terms not reviewed.
- **Terms:** https://cyber-valley.de/privacy-policy/ - Privacy policy only.
- **Rate limits:** None published | **Polling guidance:** estimate 24 h | **Proposed interval:** 24 h | **Stability:** Medium.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://cyber-valley.de/career/ - robots allowed=True (robots HTTP 200), HTTP 200, text/html, 322803 bytes
- **Evidence:**
  - Careers page links 'Computer Vision Engineer – Working Student', 'Student Assistant CELLnROLL', 'Research internship for PhD students' - <https://cyber-valley.de/career/>
- **Scores:** relevance 5 (AI/robotics roles in Baden-Württemberg including student jobs.) | authority 4 (Network's own listing; employers are institutes.) | signal quality 3 (Titles/locations in list; details on job pages.) | freshness 4 (Current listings present (Oct 2026).) | integration 4 (Existing adapter with depth-1 crawl.)
- **Uncertainties:** Posting dates/deadlines on job pages
- **Next action:** Probe with ohg using follow_internal_links depth 1; review listings for student eligibility.
- **Stages:** A=yes, B=no, C=yes, D=yes, E=no, F=no

### S23 - TUM.ai events and hackathons  
**Status:** PROBE_PASSED | **Priority:** P1 | **Score:** 17/25 | **Confidence:** medium

- **Publisher:** TUM.ai (student initiative at TU Munich) (first-party student initiative)
- **Category:** A - AI/ML hackathons and competitions | **Batch:** 3
- **Canonical URL:** https://www.tum-ai.com/
- **Endpoint:** https://www.tum-ai.com/events
- **Discovery:** Events page (HTML); /hackathons is a historical list (oldest first)
- **Opportunity types:** hackathons (Makeathon, league), workshops, founder events
- **Audience/eligibility:** Students; per-event rules.
- **Geography / remote:** Germany (Munich) / Some
- **Value:** Germany's leading AI student initiative; events page lists dozens of dated items (68 date mentions) and sponsor-backed challenges.
- **Auth / registration:** none / none for browsing
- **Adapter fit:** html (existing) | stable IDs: None observed | dates: Yes | difficulty: Medium: page mixes past/future events (items from 2025 and 2026 observed) and is partly JS-built.
- **Policy:** unclear - robots.txt returned 404 (no restrictions per RFC 9309); terms not reviewed.
- **Terms:** https://www.tum-ai.com/ - No terms read.
- **Rate limits:** None published | **Polling guidance:** estimate 72 h | **Proposed interval:** 72 h | **Stability:** Medium.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://www.tum-ai.com/events - robots allowed=True (robots HTTP 404), HTTP 200, text/html, 777641 bytes
- **Evidence:**
  - /events lists dated events (e.g. '24 September 2025', '24 September 2026 ELAB: Women in Startups') - <https://www.tum-ai.com/events>
  - /hackathons: 'Every TUM.ai hackathon, oldest first' with dates from 2021; points to the events page for upcoming ones - <https://www.tum-ai.com/hackathons>
- **Scores:** relevance 4 (AI hackathons for students in Germany.) | authority 4 (Organiser's own site.) | signal quality 3 (Dates present; eligibility/deadlines unclear.) | freshness 3 (Mixed old and new items.) | integration 3 (HTML adapter works but filtering past events is needed.)
- **Uncertainties:** Which events are currently open
- **Next action:** Probe /events with ohg; keep EHL (S14) as the league source.
- **Stages:** A=yes, B=no, C=yes, D=yes, E=no, F=no

### S24 - EvalAI challenges  
**Status:** MANUAL_REVIEW | **Priority:** P2 | **Score:** 16/25 | **Confidence:** medium

- **Publisher:** EvalAI (CloudCV) (first-party platform)
- **Category:** A - AI/ML hackathons and competitions | **Batch:** 3
- **Canonical URL:** https://eval.ai/
- **Endpoint:** https://eval.ai/api/challenges/challenge/present/approved/public
- **Discovery:** Public JSON endpoint used by the platform's own web app (observed, not found in documentation during this run)
- **Opportunity types:** ML/AI evaluation challenges
- **Audience/eligibility:** Researchers and practitioners; per-challenge rules.
- **Geography / remote:** Global / Yes
- **Value:** Open-source challenge platform; the endpoint returned count=18 ongoing approved public challenges.
- **Auth / registration:** none observed / none for this endpoint
- **Adapter fit:** JSON API adapter (missing) (gap) | stable IDs: challenge id | dates: Yes in JSON (not parsed in this run) | difficulty: Medium: JSON adapter; endpoint stability unknown because it is not shown to be a documented API.
- **Policy:** unclear - robots.txt allowed the path; the endpoint is undocumented in our evidence, so permission to automate is unclear.
- **Terms:** https://eval.ai/ - Terms not read; documentation of this endpoint not verified.
- **Rate limits:** Unknown | **Polling guidance:** estimate 24 h | **Proposed interval:** 24 h | **Stability:** Medium-low (undocumented API).
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://eval.ai/api/challenges/challenge/present/approved/public - robots allowed=True (robots HTTP 200), HTTP 200, application/json, 167658 bytes
- **Evidence:**
  - GET returned 200 application/json: {count: 18, results: [{id: 2703, title: 'CLIP2 - The 2nd Cadenza Lyrics Intelligibility Prediction Challenge', ...}]} - <https://eval.ai/api/challenges/challenge/present/approved/public>
  - Docs site exists (API Reference / Endpoints sections); specific page for this endpoint not located - <https://evalai.readthedocs.io/en/latest/>
- **Scores:** relevance 3 (Research-benchmark challenges, fewer student-friendly prizes.) | authority 4 (Operated by the open-source maintainers.) | signal quality 3 (JSON has dates; eligibility inside description HTML.) | freshness 4 (18 ongoing challenges.) | integration 2 (New adapter + undocumented endpoint risk.)
- **Uncertainties:** Whether the endpoint is a supported public API; Terms of use
- **Next action:** Find API documentation or ask maintainers before relying on this endpoint.
- **Stages:** A=yes, B=no, C=no, D=no, E=no, F=no

### S25 - IAESTE Germany  
**Status:** MANUAL_REVIEW | **Priority:** P2 | **Score:** 13/25 | **Confidence:** medium

- **Publisher:** IAESTE Germany (DAAD-run national committee) (first-party)
- **Category:** C - Research internships and student technical opportunities | **Batch:** 3
- **Canonical URL:** https://www.iaeste.de/
- **Endpoint:** https://www.iaeste.de/de/
- **Discovery:** Programme pages (HTML); site RSS feed exists but returned 0 items
- **Opportunity types:** technical internships abroad for students
- **Audience/eligibility:** Students (page text: 'Du studierst und willst ein Praktikum im Ausland machen?').
- **Geography / remote:** Germany outbound, international / No
- **Value:** Established route to engineering/IT internships abroad for students at German universities.
- **Auth / registration:** none / Application via the internship portal (not accessed)
- **Adapter fit:** html (existing) | stable IDs: None | dates: None on the landing page | difficulty: Medium: landing page has no listings; offers live in a portal that was not accessed.
- **Policy:** unclear - robots.txt allows the landing page; internship portal access unverified.
- **Terms:** https://www.iaeste.de/ - Not reviewed.
- **Rate limits:** None published | **Polling guidance:** estimate 168 h | **Proposed interval:** 168 h | **Stability:** High.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://www.iaeste.de/de/ - robots allowed=True (robots HTTP 200), HTTP 200, text/html, 60142 bytes
- **Evidence:**
  - Landing page: 'Für Studierende ... Praktikum im Ausland machen?' - <https://www.iaeste.de/de/>
  - RSS feed https://www.iaeste.de/de/feed/ is valid but has 0 entries - <https://www.iaeste.de/de/feed/>
- **Scores:** relevance 3 (Relevant to students but not AI-specific.) | authority 5 (National committee.) | signal quality 1 (No listings, deadlines or eligibility in the probed page.) | freshness 2 (Static.) | integration 2 (Actual offers are elsewhere.)
- **Uncertainties:** Where offers and deadlines are published
- **Next action:** Locate the internship offer portal and its access rules.
- **Stages:** A=yes, B=no, C=no, D=no, E=no, F=no

### S26 - Max Planck Institute for Informatics job openings  
**Status:** MANUAL_REVIEW | **Priority:** P2 | **Score:** 17/25 | **Confidence:** medium

- **Publisher:** Max Planck Institute for Informatics (Saarbrücken) (first-party)
- **Category:** C - Research internships and student technical opportunities | **Batch:** 3
- **Canonical URL:** https://www.mpi-inf.mpg.de/
- **Endpoint:** https://www.mpi-inf.mpg.de/career/job-openings
- **Discovery:** Career page (HTML)
- **Opportunity types:** student assistant, PhD, postdoc and group-leader positions
- **Audience/eligibility:** Per listing; page mentions student assistants.
- **Geography / remote:** Germany (Saarbrücken) / No
- **Value:** Top German CS institute with departments in Computer Vision & ML and Visual Computing & AI.
- **Auth / registration:** none / none
- **Adapter fit:** html (existing) | stable IDs: None observed | dates: None on the page | difficulty: Medium: page links department job lists; listings not enumerated in this run.
- **Policy:** unclear - robots.txt allows; terms not reviewed.
- **Terms:** https://www.mpi-inf.mpg.de/ - Not reviewed.
- **Rate limits:** None published | **Polling guidance:** estimate 24-72 h | **Proposed interval:** 72 h | **Stability:** High.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://www.mpi-inf.mpg.de/career/job-openings - robots allowed=True (robots HTTP 200), HTTP 200, text/html, 106617 bytes
- **Evidence:**
  - Page: 'Whether you're a student assistant, Ph.D. student, postdoc, or research group leader'; lists departments D2 and D6 - <https://www.mpi-inf.mpg.de/career/job-openings>
- **Scores:** relevance 4 (Strong CV/ML research environment; hiring is mostly graduate-level.) | authority 5 (Max Planck institute.) | signal quality 2 (Landing page lacks listings.) | freshness 3 (Unknown posting recency.) | integration 3 (Needs link-following to listings.)
- **Uncertainties:** Where actual openings are listed and in what format
- **Next action:** Identify the listing URLs from the career page before drafting.
- **Stages:** A=yes, B=no, C=no, D=no, E=no, F=no

### S27 - Studienstiftung des deutschen Volkes  
**Status:** PROBE_PASSED | **Priority:** P2 | **Score:** 14/25 | **Confidence:** low

- **Publisher:** Studienstiftung des deutschen Volkes (first-party)
- **Category:** D - Scholarships, fellowships and grants | **Batch:** 3
- **Canonical URL:** https://www.studienstiftung.de/
- **Endpoint:** https://www.studienstiftung.de/
- **Discovery:** Homepage news (HTML); the linked /rss URL returns an HTML page, not a feed
- **Opportunity types:** scholarship programme and related programmes (e.g. CERN network programme mentioned on the homepage)
- **Audience/eligibility:** Not verified in this run.
- **Geography / remote:** Germany / n/a
- **Value:** Germany's largest scholarship foundation; homepage mentions a CERN-network technical programme.
- **Auth / registration:** none / Application/nomination process (not read)
- **Adapter fit:** html (existing) | stable IDs: None | dates: None on homepage | difficulty: Medium: application information is on sub-pages not read.
- **Policy:** unclear - robots.txt allows; terms not reviewed.
- **Terms:** https://www.studienstiftung.de/ - Not reviewed.
- **Rate limits:** None published | **Polling guidance:** estimate 168 h | **Proposed interval:** 168 h | **Stability:** High.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://www.studienstiftung.de/ - robots allowed=True (robots HTTP 200), HTTP 200, text/html, 44095 bytes
- **Evidence:**
  - Homepage news block including 'Mission CERN: Mit dem CERN-Netzwerk baut die Studienstiftung ein technikorientiertes Angebot ...' - <https://www.studienstiftung.de/>
  - Link '/rss' returns an HTML page, so no usable feed was verified - <https://www.studienstiftung.de/rss>
- **Scores:** relevance 3 (Relevant long-term scholarship, but eligibility is competitive/nomination-based (not verified here).) | authority 5 (Official foundation.) | signal quality 1 (Homepage lacks deadlines/eligibility.) | freshness 2 (News only.) | integration 3 (Static HTML; low yield.)
- **Uncertainties:** Application route and deadlines; Eligibility for the target profile
- **Next action:** Read the application sub-pages; probably track manually.
- **Stages:** A=yes, B=no, C=yes, D=yes, E=no, F=no

### S28 - ICLR 2027  
**Status:** PROBE_PASSED | **Priority:** P1 | **Score:** 21/25 | **Confidence:** high

- **Publisher:** International Conference on Learning Representations (first-party)
- **Category:** E - AI/ML conferences, workshops and summer schools | **Batch:** 3
- **Canonical URL:** https://iclr.cc/
- **Endpoint:** https://iclr.cc/
- **Discovery:** Conference homepage (HTML)
- **Opportunity types:** conference dates, call for papers, workshops, volunteering/financial aid
- **Audience/eligibility:** Researchers, students.
- **Geography / remote:** Global (2027: California) / n/a
- **Value:** Top ML venue; homepage states ICLR 2027, California, April 26-30, 2027.
- **Auth / registration:** none / none
- **Adapter fit:** html (existing) | stable IDs: Year in URL | dates: Yes | difficulty: Low: yearly page.
- **Policy:** unclear - robots.txt allows; terms not reviewed.
- **Terms:** https://iclr.cc/public/PrivacyPolicy - Privacy policy only.
- **Rate limits:** None published | **Polling guidance:** estimate 168 h | **Proposed interval:** 168 h | **Stability:** High.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://iclr.cc/ - robots allowed=True (robots HTTP 200), HTTP 200, text/html, 58731 bytes
- **Evidence:**
  - Homepage: 'ICLR 2027 The Fifteenth International Conference on Learning Representations California April 26-30, 2027' - <https://iclr.cc/>
- **Scores:** relevance 5 (Core ML venue.) | authority 5 (Official site.) | signal quality 3 (Dates yes; deadlines on sub-pages.) | freshness 4 (2027 page live.) | integration 4 (Existing adapter.)
- **Uncertainties:** Submission deadline page
- **Next action:** Add the 'Dates' sub-page to the entry.
- **Stages:** A=yes, B=no, C=yes, D=yes, E=no, F=no

### S29 - CVPR 2027  
**Status:** PROBE_PASSED | **Priority:** P1 | **Score:** 21/25 | **Confidence:** high

- **Publisher:** IEEE/CVF (first-party)
- **Category:** E - AI/ML conferences, workshops and summer schools | **Batch:** 3
- **Canonical URL:** https://cvpr.thecvf.com/
- **Endpoint:** https://cvpr.thecvf.com/
- **Discovery:** Conference homepage (HTML)
- **Opportunity types:** conference dates, call for papers/workshops, announcements
- **Audience/eligibility:** Researchers, students.
- **Geography / remote:** Global (2027: Seattle) / n/a
- **Value:** Top computer-vision venue; homepage: CVPR 2027, Seattle, June 20-25, 2027, with dated announcements (28 Oct 2026).
- **Auth / registration:** none / none
- **Adapter fit:** html (existing) | stable IDs: Year in URL | dates: Announcement dates yes | difficulty: Low.
- **Policy:** unclear - robots.txt allows; terms not reviewed.
- **Terms:** https://cvpr.thecvf.com/Conferences/2024/PrivacyPolicy - Privacy policy only.
- **Rate limits:** None published | **Polling guidance:** estimate 168 h | **Proposed interval:** 168 h | **Stability:** High.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://cvpr.thecvf.com/ - robots allowed=True (robots HTTP 200), HTTP 200, text/html, 38229 bytes
- **Evidence:**
  - Homepage: 'CVPR 2027 Seattle WA June 20-25, 2027 ... Oct 28: CVPR 2026 Program Committee Releases Compute Report' - <https://cvpr.thecvf.com/>
- **Scores:** relevance 5 (Computer vision is a stated priority domain.) | authority 5 (Official site.) | signal quality 3 (Announcement list, deadlines on sub-pages.) | freshness 4 (Announcements within last 2 days.) | integration 4 (Existing adapter.)
- **Uncertainties:** Deadline page URL
- **Next action:** Add the dates page to the entry.
- **Stages:** A=yes, B=no, C=yes, D=yes, E=no, F=no

### S30 - Outreachy internships  
**Status:** PROBE_PASSED | **Priority:** P2 | **Score:** 20/25 | **Confidence:** high

- **Publisher:** Outreachy (Software Freedom Conservancy) (first-party)
- **Category:** F - Open-source programmes, technical challenges and cybersecurity | **Batch:** 3
- **Canonical URL:** https://www.outreachy.org/
- **Endpoint:** https://www.outreachy.org/
- **Discovery:** Programme homepage (HTML) and /apply/ guide
- **Opportunity types:** remote paid open-source internships
- **Audience/eligibility:** People subject to systemic bias/underrepresentation; the apply guide says 'We have strict eligibility rules'.
- **Geography / remote:** Global / Yes
- **Value:** Remote paid internships with published rounds; eligibility is restricted and must be read per applicant.
- **Auth / registration:** none / Account required to apply
- **Adapter fit:** html (existing) | stable IDs: None | dates: Yes (e.g. February 13, 2026, August 17, 2026 on the homepage) | difficulty: Low: static pages; dates in text.
- **Policy:** unclear - robots.txt returned 404 (no restrictions per RFC 9309); terms not reviewed.
- **Terms:** https://www.outreachy.org/privacy-policy/ - Privacy policy only.
- **Rate limits:** None published | **Polling guidance:** estimate 168 h | **Proposed interval:** 168 h | **Stability:** High.
- **Final-pass probe:** 2026-10-30T01:17:32+01:00 - GET https://www.outreachy.org/ - robots allowed=True (robots HTTP 404), HTTP 200, text/html, 17017 bytes
- **Evidence:**
  - Homepage lists application round dates incl. 'August 17, 2026' - <https://www.outreachy.org/>
  - Apply guide: 'We have strict eligibility rules for people with...' - <https://www.outreachy.org/apply/>
- **Scores:** relevance 3 (Relevant if the operator meets eligibility; unknown.) | authority 5 (Program operator.) | signal quality 4 (Rounds and rules clear.) | freshness 4 (Current rounds listed.) | integration 4 (Existing adapter.)
- **Uncertainties:** Whether the operator is eligible
- **Next action:** User reads the eligibility rules before onboarding.
- **Stages:** A=yes, B=no, C=yes, D=yes, E=no, F=no
