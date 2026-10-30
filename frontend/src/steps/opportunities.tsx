import { useState } from "preact/hooks";
import { api, ApiFailure } from "../api";
import { SaveIndicator, useApp, useAutosave } from "../app";
import { ChoiceCards, Chips, ErrorSummary, Field, Group, Switch, labelFor } from "../ui";
import { StepFooter, StepHeader } from "./common";

type Form = {
  everything: boolean;
  categories: string[];
  regions: string[];
  formats: string[];
  international_when_funded: boolean;
  needs_funding_or_low_cost: boolean;
  budget_limit_eur: string;
};

const LABELS: Record<string, string> = {
  categories: "Kinds of opportunity",
  regions: "Regions",
  formats: "Formats",
  budget_limit_eur: "Budget",
};

export function OpportunitiesStep() {
  const { snap, setSnap, refresh, next } = useApp();
  const c = snap.catalog;
  const p = snap.profile;
  const d = (snap.onboarding.drafts.opportunities ?? {}) as Partial<Form>;
  const [f, setF] = useState<Form>(() => ({
    everything: d.everything ?? p?.everything ?? true,
    categories: d.categories ?? p?.categories ?? [],
    regions: d.regions ?? p?.regions ?? [],
    formats: d.formats ?? (p?.formats.length ? p.formats : ["online", "hybrid", "in_person"]),
    international_when_funded: d.international_when_funded ?? p?.international_when_funded ?? true,
    needs_funding_or_low_cost: d.needs_funding_or_low_cost ?? p?.needs_funding_or_low_cost ?? true,
    budget_limit_eur: d.budget_limit_eur ?? (p?.budget_limit_eur != null ? String(p.budget_limit_eur) : ""),
  }));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [summary, setSummary] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const status = useAutosave("opportunities", f);
  const set = <K extends keyof Form>(k: K, v: Form[K]) => setF((prev) => ({ ...prev, [k]: v }));
  const country = p ? labelFor(c.countries, p.country) : "your country";

  const submit = async () => {
    const errs: Record<string, string> = {};
    if (!f.everything && f.categories.length === 0) errs.categories = "Pick at least one, or choose “Show me everything relevant”.";
    if (f.formats.length === 0) errs.formats = "Pick at least one format.";
    if (f.budget_limit_eur && !/^\d+(\.\d+)?$/.test(f.budget_limit_eur)) errs.budget_limit_eur = "Enter an amount in euros, or leave it empty.";
    setErrors(errs);
    if (Object.keys(errs).length) {
      setSummary("A couple of answers need another look.");
      return;
    }
    setBusy(true);
    setSummary(null);
    try {
      await api.post("/api/preferences", { ...f, budget_limit_eur: f.budget_limit_eur || null });
      setSnap(await refresh());
      next("opportunities");
    } catch (e) {
      if (e instanceof ApiFailure) {
        setErrors(e.fields);
        setSummary(e.message);
      } else setSummary("Something went wrong. Your answers are still here.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <form class="step" noValidate onSubmit={(e) => e.preventDefault()}>
      <StepHeader
        step="opportunities"
        title="What are you hunting for?"
        lead="This shapes the ranking, not what gets collected, so nothing is hidden for good. You can change it any time."
      />
      {summary && <ErrorSummary message={summary} fields={errors} labels={LABELS} />}

      <div class="form-grid">
        <div class={`everything-card ${f.everything ? "is-on" : ""}`}>
          <Switch
            checked={f.everything}
            onChange={(v) => {
              set("everything", v);
              if (errors.categories) setErrors(({ categories: _, ...r }) => r);
            }}
            label="Show me everything relevant"
            hint="Rank every kind of opportunity by how well it fits your interests."
          />
        </div>

        {!f.everything && (
          <Group legend="Kinds of opportunity" hint="Selected kinds rank higher; the rest rank lower but are still kept." error={errors.categories} id="categories">
            <ChoiceCards name="categories" multiple options={c.categories} value={f.categories} onChange={(v) => { set("categories", v); if (errors.categories) setErrors(({ categories: _, ...r }) => r); }} />
          </Group>
        )}

        <Group legend="Where?" hint={`${country} is always included. Anything far away and unfunded ranks lower.`} id="regions" error={errors.regions}>
          <Chips options={c.regions} value={f.regions} onChange={(v) => set("regions", v)} />
        </Group>

        <Group legend="Formats you'd consider" error={errors.formats} id="formats">
          <Chips options={c.formats} value={f.formats} onChange={(v) => { set("formats", v); if (errors.formats) setErrors(({ formats: _, ...r }) => r); }} />
        </Group>

        <div class="switch-stack">
          <Switch checked={f.needs_funding_or_low_cost} onChange={(v) => set("needs_funding_or_low_cost", v)} label="I need funded or low-cost options" hint="Unfunded opportunities with fees rank lower." />
          <Switch checked={f.international_when_funded} onChange={(v) => set("international_when_funded", v)} label="I'd travel far if it's funded" hint="Far-away, funded opportunities aren't penalised for travel." />
        </div>

        <details class="disclosure" open={Boolean(f.budget_limit_eur)}>
          <summary>Set a budget limit <span class="optional">optional</span></summary>
          <Field label="Maximum fee you'd pay (EUR)" optional hint="Opportunities above this rank much lower." error={errors.budget_limit_eur} id="budget_limit_eur">
            {({ id, describedBy, invalid }) => (
              <input id={id} class="input input-short mono" inputMode="decimal" value={f.budget_limit_eur} aria-describedby={describedBy} aria-invalid={invalid ? "true" : undefined} onInput={(e) => set("budget_limit_eur", (e.target as HTMLInputElement).value.trim())} />
            )}
          </Field>
        </details>
      </div>

      <SaveIndicator status={status} />
      <StepFooter step="opportunities" onContinue={submit} busy={busy} />
    </form>
  );
}
