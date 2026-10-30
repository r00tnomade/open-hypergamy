import { useState } from "preact/hooks";
import { api, ApiFailure } from "../api";
import { SaveIndicator, useApp, useAutosave } from "../app";
import type { ProfileData } from "../types";
import { ChoiceCards, ErrorSummary, Field, Group, Icon, TagPicker } from "../ui";
import { StepFooter, StepHeader } from "./common";

type Form = {
  display_name: string;
  degree_level: string;
  current_year: string;
  expected_graduation_year: string;
  institution: string;
  institution_type: string;
  country: string;
  subject_tags: string[];
  research_tags: string[];
  skills: string[];
};

const LABELS: Record<string, string> = {
  display_name: "Name",
  degree_level: "Level of study",
  current_year: "Year of study",
  expected_graduation_year: "Expected graduation",
  institution: "University",
  institution_type: "Type of institution",
  country: "Country",
  subject_tags: "Field of study",
  research_tags: "Interests",
  skills: "Skills",
};

const str = (v: unknown) => (v === null || v === undefined ? "" : String(v));

function initial(p: ProfileData | null | undefined, draft: Record<string, unknown> | undefined): Form {
  const d = draft ?? {};
  const pick = <K extends keyof Form>(k: K, fallback: Form[K]): Form[K] =>
    (k in d ? (d[k] as Form[K]) : fallback) ?? fallback;
  return {
    display_name: pick("display_name", str(p?.display_name)),
    degree_level: pick("degree_level", str(p?.degree_level)),
    current_year: pick("current_year", str(p?.current_year)),
    expected_graduation_year: pick("expected_graduation_year", str(p?.expected_graduation_year)),
    institution: pick("institution", str(p?.institution)),
    institution_type: pick("institution_type", p?.institution_type ?? "unknown"),
    country: pick("country", p?.country ?? ""),
    subject_tags: pick("subject_tags", p?.subject_tags ?? []),
    research_tags: pick("research_tags", p?.research_tags ?? []),
    skills: pick("skills", p?.skills ?? []),
  };
}

const PART_ONE = ["degree_level", "current_year", "country", "institution", "institution_type", "display_name"];

export function ProfileStep() {
  const { snap, setSnap, refresh, next, editing } = useApp();
  const c = snap.catalog;
  const [f, setF] = useState<Form>(() => initial(snap.profile, snap.onboarding.drafts.profile));
  const [part, setPart] = useState<1 | 2>(1);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [summary, setSummary] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const status = useAutosave("profile", f);
  const showSkills = editing || f.skills.length > 0;
  const set = <K extends keyof Form>(k: K, v: Form[K]) => {
    setF({ ...f, [k]: v });
    if (errors[k]) setErrors(({ [k]: _, ...rest }) => rest);
  };

  const validateOne = (k: keyof Form, v = f[k]): string | undefined => {
    if (k === "degree_level" && !v) return "Choose your current level of study.";
    if (k === "country" && !v) return "Choose the country you study in.";
    if (k === "current_year" && v && !/^([1-9]|10)$/.test(String(v))) return "Enter a year between 1 and 10.";
    if (k === "expected_graduation_year" && v && !/^(19|20|21)\d\d$/.test(String(v))) return "Enter a four-digit year.";
    return undefined;
  };
  const blur = (k: keyof Form) => {
    const e = validateOne(k);
    setErrors((prev) => {
      const { [k]: _, ...rest } = prev;
      return e ? { ...rest, [k]: e } : rest;
    });
  };

  const toPartTwo = () => {
    const errs: Record<string, string> = {};
    for (const k of ["degree_level", "country", "current_year"] as (keyof Form)[]) {
      const e = validateOne(k);
      if (e) errs[k] = e;
    }
    setErrors(errs);
    if (Object.keys(errs).length) {
      setSummary("A couple of answers need another look.");
      return;
    }
    setSummary(null);
    setPart(2);
    window.scrollTo({ top: 0 });
    requestAnimationFrame(() => document.getElementById("part-two")?.focus());
  };

  const submit = async () => {
    setBusy(true);
    setSummary(null);
    try {
      await api.post<{ profile: ProfileData }>("/api/profile", {
        ...f,
        current_year: f.current_year || null,
        expected_graduation_year: f.expected_graduation_year || null,
      });
      setSnap(await refresh());
      next("profile");
    } catch (e) {
      if (e instanceof ApiFailure) {
        setErrors(e.fields);
        setSummary(e.message);
        if (Object.keys(e.fields).some((k) => PART_ONE.includes(k))) setPart(1);
      } else setSummary("Something went wrong. Your answers are still here.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form class="step" noValidate onSubmit={(e) => e.preventDefault()}>
      <StepHeader
        step="profile"
        title={part === 1 ? "First, a little about you." : "What are you into?"}
        lead={
          part === 1
            ? "Eligibility rules mostly hinge on your level and where you study. That's all we need to start."
            : "Interests drive the ranking. Pick a few, or add your own: anything you type is matched against opportunity descriptions."
        }
      />
      {snap.profile_problem && <p class="notice notice-warn">{snap.profile_problem}</p>}
      {summary && <ErrorSummary message={summary} fields={errors} labels={LABELS} />}

      <div class="part-tabs mono" aria-hidden="true">
        <span class={part === 1 ? "is-on" : ""}>1 · About you</span>
        <span class={part === 2 ? "is-on" : ""}>2 · Interests</span>
      </div>

      {part === 1 ? (
        <div class="form-grid">
          <Group legend="Where are you in your studies?" error={errors.degree_level} id="degree_level">
            <ChoiceCards name="degree" options={c.degrees} value={f.degree_level ? [f.degree_level] : []} onChange={(v) => { set("degree_level", v[0] ?? ""); }} />
          </Group>

          <div class="row-2">
            <Field label="Year of study" optional hint="Some programmes are for 2nd year and up." error={errors.current_year} id="current_year">
              {({ id, describedBy, invalid }) => (
                <input id={id} class="input" inputMode="numeric" maxLength={2} value={f.current_year} aria-describedby={describedBy} aria-invalid={invalid ? "true" : undefined} onInput={(e) => set("current_year", (e.target as HTMLInputElement).value.trim())} onBlur={() => blur("current_year")} />
              )}
            </Field>
            <Field label="Country you study in" hint="Used for “enrolled at an EU university”-style rules." error={errors.country} id="country">
              {({ id, describedBy, invalid }) => (
                <select id={id} class="input" value={f.country} aria-describedby={describedBy} aria-invalid={invalid ? "true" : undefined} onChange={(e) => set("country", (e.target as HTMLSelectElement).value)} onBlur={() => blur("country")}>
                  <option value="">Choose a country</option>
                  {c.countries.map((o) => (
                    <option key={o.id} value={o.id}>{o.label}</option>
                  ))}
                  {f.country && !c.countries.some((o) => o.id === f.country) && <option value={f.country}>{f.country}</option>}
                </select>
              )}
            </Field>
          </div>

          <details class="disclosure" open={Boolean(f.institution || f.display_name || f.institution_type !== "unknown")}>
            <summary>More about you <span class="optional">optional</span></summary>
            <div class="row-2">
              <Field label="University or organisation" optional hint="Only shown back to you." error={errors.institution} id="institution">
                {({ id, describedBy }) => (
                  <input id={id} class="input" autocomplete="organization" maxLength={120} value={f.institution} aria-describedby={describedBy} onInput={(e) => set("institution", (e.target as HTMLInputElement).value)} />
                )}
              </Field>
              <Field label="Type of institution" optional id="institution_type" error={errors.institution_type}>
                {({ id }) => (
                  <select id={id} class="input" value={f.institution_type} onChange={(e) => set("institution_type", (e.target as HTMLSelectElement).value)}>
                    {c.institution_types.map((o) => (
                      <option key={o.id} value={o.id}>{o.label}</option>
                    ))}
                  </select>
                )}
              </Field>
            </div>
            <Field label="What should we call you?" optional hint="Just for the greeting. Never sent anywhere." error={errors.display_name} id="display_name">
              {({ id, describedBy }) => (
                <input id={id} class="input" autocomplete="given-name" maxLength={80} value={f.display_name} aria-describedby={describedBy} onInput={(e) => set("display_name", (e.target as HTMLInputElement).value)} />
              )}
            </Field>
          </details>
        </div>
      ) : (
        <div class="form-grid" id="part-two" tabIndex={-1}>
          <Group legend="Interests" hint="The single biggest factor in how opportunities are ranked." error={errors.research_tags} id="research_tags">
            <TagPicker options={c.interests} value={f.research_tags} onChange={(v) => set("research_tags", v)} addLabel="Add an interest, e.g. reinforcement learning" max={20} />
          </Group>
          <Group legend="Field of study" optional hint="Helps with “students of computer science or related fields” rules." error={errors.subject_tags} id="subject_tags">
            <TagPicker options={c.fields} value={f.subject_tags} onChange={(v) => set("subject_tags", v)} addLabel="Add a field" max={10} />
          </Group>
          {/* Skills don't affect ranking yet, so first-run setup doesn't ask; the profile editor still offers them. */}
          <details class="disclosure" open={f.skills.length > 0 || Boolean(f.expected_graduation_year)}>
            <summary>{showSkills ? "Skills and graduation" : "Graduation"} <span class="optional">optional</span></summary>
            {showSkills && (
              <Group legend="Skills" optional hint="Kept in your profile for your own reference. Ranking doesn't use them yet." error={errors.skills} id="skills">
                <TagPicker options={c.skills} value={f.skills} onChange={(v) => set("skills", v)} addLabel="Add a skill" max={30} />
              </Group>
            )}
            <Field label="Expected graduation year" optional error={errors.expected_graduation_year} id="expected_graduation_year">
              {({ id, describedBy, invalid }) => (
                <input id={id} class="input input-short" inputMode="numeric" maxLength={4} value={f.expected_graduation_year} aria-describedby={describedBy} aria-invalid={invalid ? "true" : undefined} onInput={(e) => set("expected_graduation_year", (e.target as HTMLInputElement).value.trim())} onBlur={() => blur("expected_graduation_year")} />
              )}
            </Field>
          </details>
        </div>
      )}

      <SaveIndicator status={status} />
      {part === 1 ? (
        <StepFooter step="profile" onContinue={toPartTwo} continueLabel="Next: interests" />
      ) : (
        <div class="step-footer">
          <div class="step-footer-left">
            <button type="button" class="btn btn-ghost" onClick={() => setPart(1)}>Back to about you</button>
          </div>
          <div class="step-footer-right">
            <StepFooterSubmit busy={busy} onClick={submit} />
          </div>
        </div>
      )}
    </form>
  );
}

function StepFooterSubmit({ busy, onClick }: { busy: boolean; onClick: () => void }) {
  const { editing } = useApp();
  return (
    <button type="submit" class="btn btn-primary" disabled={busy} aria-busy={busy ? "true" : undefined} onClick={onClick}>
      {busy && <span class="spinner" aria-hidden="true" />}
      {editing ? "Save profile" : "Save and continue"} <Icon name="arrow" size={16} />
    </button>
  );
}
