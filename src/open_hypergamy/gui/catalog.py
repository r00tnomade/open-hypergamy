"""Choices offered by the onboarding GUI. Every id is a value the profile/scoring code understands.

Interests are `research_tags`: scoring matches them by the keyword table in `scoring/fit.py`,
falling back to the tag's own words. Free-text entries are allowed and normalised the same way.
"""

from __future__ import annotations

import re
import zoneinfo
from typing import Any

INTERESTS: list[tuple[str, str]] = [
    ("applied_ml", "Machine learning"),
    ("ai_systems", "AI systems & LLMs"),
    ("computer_vision", "Computer vision"),
    ("natural_language_processing", "NLP & speech"),
    ("robotics", "Robotics"),
    ("autonomous_systems", "Autonomous systems"),
    ("systems_security", "Cybersecurity"),
    ("embedded_systems", "Embedded & hardware"),
    ("high_performance_computing", "HPC & distributed"),
    ("quantum_computing", "Quantum computing"),
    ("human_computer_interaction", "HCI & design"),
    ("computational_biology", "Computational biology"),
    ("data_science", "Data science"),
    ("open_source", "Open source"),
]

FIELDS: list[tuple[str, str]] = [
    ("computer_science", "Computer science"),
    ("computer_engineering", "Computer engineering"),
    ("electrical_engineering", "Electrical engineering"),
    ("mechanical_engineering", "Mechanical engineering"),
    ("mechatronics", "Mechatronics"),
    ("mathematics", "Mathematics"),
    ("physics", "Physics"),
    ("data_science", "Data science"),
    ("information_systems", "Information systems"),
    ("bioengineering", "Bioengineering"),
    ("cognitive_science", "Cognitive science"),
]

SKILLS: list[tuple[str, str]] = [
    (s.lower().replace(" ", "_").replace("+", "p").replace("#", "sharp"), s)
    for s in (
        "Python", "C", "C++", "Rust", "Go", "Java", "JavaScript", "TypeScript", "Linux",
        "PyTorch", "JAX", "TensorFlow", "CUDA", "ROS", "SQL", "Docker", "Kubernetes", "Git",
        "Embedded C", "Verilog", "MATLAB", "Statistics", "Technical writing",
    )
]  # fmt: skip

DEGREES: list[tuple[str, str]] = [
    ("bachelor", "Bachelor's student"),
    ("master", "Master's student"),
    ("phd", "PhD candidate"),
]

INSTITUTION_TYPES: list[tuple[str, str]] = [
    ("university", "University"),
    ("university_of_applied_sciences", "University of applied sciences"),
    ("technical_university", "Technical university"),
    ("college", "College"),
    ("unknown", "Prefer not to say"),
]

# (id, label, hint). Ids are programme categories (`profile.OpportunityCategory`).
CATEGORIES: list[tuple[str, str, str]] = [
    ("research_programme", "Research programmes", "Undergrad research, lab stays, REUs"),
    ("internship", "Internships", "Industry and research internships"),
    ("summer_school", "Summer schools", "Intensive courses, winter & spring schools"),
    ("fellowship", "Fellowships", "Funded programmes with a cohort"),
    ("scholarship", "Scholarships", "Tuition, stipends, travel support"),
    ("grant", "Grants", "Project and travel funding"),
    ("hackathon", "Hackathons", "Build something in a weekend"),
    ("challenge", "Competitions", "Challenges, contests, CTFs"),
    ("conference", "Conferences", "Attend, volunteer, student tracks"),
    ("workshop", "Workshops", "Short, focused events"),
    ("call_for_papers", "Calls for papers", "Submit your work"),
    ("other", "Everything else", "Open-source programmes and the rest"),
]

REGIONS: list[tuple[str, str]] = [
    ("WORLDWIDE", "Anywhere"),
    ("EUROPE", "Europe (incl. UK, CH)"),
    ("EU", "European Union"),
]

FORMATS: list[tuple[str, str]] = [
    ("online", "Remote / online"),
    ("hybrid", "Hybrid"),
    ("in_person", "In person"),
]

COUNTRIES: list[tuple[str, str]] = [
    ("AR", "Argentina"), ("AU", "Australia"), ("AT", "Austria"), ("BD", "Bangladesh"),
    ("BE", "Belgium"), ("BR", "Brazil"), ("BG", "Bulgaria"), ("CA", "Canada"), ("CL", "Chile"),
    ("CN", "China"), ("CO", "Colombia"), ("HR", "Croatia"), ("CY", "Cyprus"),
    ("CZ", "Czechia"), ("DK", "Denmark"), ("EG", "Egypt"), ("EE", "Estonia"),
    ("ET", "Ethiopia"), ("FI", "Finland"), ("FR", "France"), ("DE", "Germany"),
    ("GH", "Ghana"), ("GR", "Greece"), ("HK", "Hong Kong"), ("HU", "Hungary"),
    ("IS", "Iceland"), ("IN", "India"), ("ID", "Indonesia"), ("IE", "Ireland"),
    ("IL", "Israel"), ("IT", "Italy"), ("JP", "Japan"), ("JO", "Jordan"), ("KE", "Kenya"),
    ("KR", "South Korea"), ("LV", "Latvia"), ("LB", "Lebanon"), ("LI", "Liechtenstein"),
    ("LT", "Lithuania"), ("LU", "Luxembourg"), ("MY", "Malaysia"), ("MT", "Malta"),
    ("MX", "Mexico"), ("MA", "Morocco"), ("NL", "Netherlands"), ("NZ", "New Zealand"),
    ("NG", "Nigeria"), ("NO", "Norway"), ("PK", "Pakistan"), ("PE", "Peru"),
    ("PH", "Philippines"), ("PL", "Poland"), ("PT", "Portugal"), ("RO", "Romania"),
    ("RW", "Rwanda"), ("SA", "Saudi Arabia"), ("RS", "Serbia"), ("SG", "Singapore"),
    ("SK", "Slovakia"), ("SI", "Slovenia"), ("ZA", "South Africa"), ("ES", "Spain"),
    ("LK", "Sri Lanka"), ("SE", "Sweden"), ("CH", "Switzerland"), ("TW", "Taiwan"),
    ("TH", "Thailand"), ("TN", "Tunisia"), ("TR", "Türkiye"), ("UA", "Ukraine"),
    ("AE", "United Arab Emirates"), ("GB", "United Kingdom"), ("US", "United States"),
    ("VN", "Vietnam"),
]  # fmt: skip

WEEKDAYS: list[tuple[int, str]] = [
    (1, "Monday"), (2, "Tuesday"), (3, "Wednesday"), (4, "Thursday"), (5, "Friday"),
    (6, "Saturday"), (0, "Sunday"),
]  # fmt: skip

REMINDER_OFFSETS = [60, 30, 14, 7, 2, 1]

_TAG = re.compile(r"[^a-z0-9]+")


def normalise_tag(text: str) -> str:
    """'Reinforcement Learning ' -> 'reinforcement_learning' (the form scoring matches on)."""
    return _TAG.sub("_", text.strip().lower()).strip("_")[:48]


def timezones() -> list[str]:
    return sorted(z for z in zoneinfo.available_timezones() if "/" in z and not z.startswith("Etc"))


def as_json() -> dict[str, Any]:
    def pairs(xs: list[tuple[Any, str]]) -> list[dict[str, Any]]:
        return [{"id": i, "label": label} for i, label in xs]

    return {
        "interests": pairs(INTERESTS),
        "fields": pairs(FIELDS),
        "skills": pairs(SKILLS),
        "degrees": pairs(DEGREES),
        "institution_types": pairs(INSTITUTION_TYPES),
        "categories": [{"id": i, "label": la, "hint": h} for i, la, h in CATEGORIES],
        "regions": pairs(REGIONS),
        "formats": pairs(FORMATS),
        "countries": pairs(COUNTRIES),
        "weekdays": pairs(WEEKDAYS),
        "reminder_offsets": REMINDER_OFFSETS,
        "timezones": timezones(),
    }
