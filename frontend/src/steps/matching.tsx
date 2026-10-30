import { useEffect, useState } from "preact/hooks";
import { api, ApiFailure } from "../api";
import { useApp } from "../app";
import type { Example } from "../types";
import { Button, Icon, Notice } from "../ui";
import { StepFooter, StepHeader } from "./common";

const COMPONENTS: [string, string][] = [
  ["career_alignment", "Interest match"],
  ["technical_research_value", "Kind & research value"],
  ["eligibility_feasibility", "Eligibility"],
  ["funding_accessibility", "Funding"],
  ["time_cost", "Travel & time"],
];

// The recommended action is what the real planner would do; the band is the priority behind it.
const ACTION: Record<string, string> = {
  apply: "Apply",
  prepare: "Prepare",
  monitor: "Keep an eye on it",
  future_cycle: "Next cycle",
  archived: "Not for you",
};

export function MatchingStep() {
  const { go, next, refresh, setSnap } = useApp();
  const [data, setData] = useState<{ examples: Example[]; weights: Record<string, number> } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api
      .post<{ examples: Example[]; weights: Record<string, number> }>("/api/preview")
      .then(setData)
      .catch((e) => setErr(e instanceof ApiFailure ? e.message : "Couldn't build the preview."));
  }, []);

  const done = async () => {
    setBusy(true);
    try {
      await api.post("/api/step", { step: "matching", status: "done", current: "notifications" });
      setSnap(await refresh());
      next("matching");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div class="step">
      <StepHeader
        step="matching"
        title="Here's how we'd read three opportunities for you."
        lead="Same rules that rank real results, run on made-up examples with your saved profile. Scores are rules, not predictions: they're only as good as what the official page says."
      />

      {data && (
        <div class="weights" aria-label="How the fit score is weighted">
          {COMPONENTS.map(([k, label]) => (
            <div key={k} class="weight" style={{ flexGrow: data.weights[k] ?? 1 }}>
              <span class="weight-bar" aria-hidden="true" />
              <span class="weight-label">
                {label} <span class="mono">{data.weights[k]}%</span>
              </span>
            </div>
          ))}
        </div>
      )}

      {err && <Notice tone="bad">{err}</Notice>}
      {!data && !err && (
        <div class="examples" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <div key={i} class="example skeleton" />
          ))}
        </div>
      )}
      {data && (
        <div class="examples">
          {data.examples.map((ex) => (
            <ExampleCard key={ex.title} ex={ex} />
          ))}
        </div>
      )}

      <Notice>
        Deadline urgency is scored separately and never inflates a weak match. Opportunities you aren't eligible for are
        excluded, and anything the rules can't settle is flagged for you rather than guessed.
      </Notice>

      <StepFooter
        step="matching"
        onContinue={done}
        busy={busy}
        continueLabel="Looks right"
        extra={
          <Button variant="ghost" onClick={() => go("profile")}>
            Adjust interests
          </Button>
        }
      />
    </div>
  );
}

function ExampleCard({ ex }: { ex: Example }) {
  const elTone = ex.eligibility.status === "eligible" ? "ok" : ex.eligibility.status === "ineligible" ? "bad" : "warn";
  return (
    <article class="example" aria-label={`Example: ${ex.title}`}>
      <header class="example-head">
        <span class="tag-example mono">Example</span>
        <span class="mono example-cat">{ex.category}</span>
      </header>
      <h2 class="example-title">{ex.title}</h2>
      <p class="example-meta">{ex.location}</p>
      <div class="example-scores">
        <div class="score">
          <span class="score-num mono">{Math.round(ex.fit)}</span>
          <span class="score-label">fit / 100</span>
        </div>
        <div class="score">
          <span class="score-num mono small">{ex.days_left === null ? "—" : `${ex.days_left}d`}</span>
          <span class="score-label">{ex.days_left === null ? "no confirmed deadline" : "until deadline"}</span>
        </div>
        <span class="band-wrap">
          <span class={`band band-${ex.action === "apply" || ex.action === "prepare" ? ex.band : "low"}`}>{ACTION[ex.action] ?? ex.action}</span>
          <span class="band-note mono">{ex.band} priority</span>
        </span>
      </div>

      <dl class="example-facts">
        <div>
          <dt>Matches your interests</dt>
          <dd>{ex.matched_interests.length ? ex.matched_interests.join(", ") : "None of your interests"}</dd>
        </div>
        <div>
          <dt>Eligibility</dt>
          <dd>
            <span class={`inline-status status-${elTone}`}>
              <Icon name={elTone === "ok" ? "check" : elTone === "bad" ? "x" : "alert"} size={14} /> {ex.eligibility.label}
            </span>
            <ul class="criteria">
              {ex.eligibility.criteria.map((c) => (
                <li key={c.text}>
                  <q>{c.text}</q> <span class="why">{c.why}</span>
                </li>
              ))}
            </ul>
          </dd>
        </div>
        <div>
          <dt>Certainty</dt>
          <dd>
            <span class="mono">{ex.certainty.level}</span>: {ex.certainty.why}
          </dd>
        </div>
      </dl>
      {ex.reasons.length > 0 && (
        <ul class="reasons">
          {ex.reasons.map((r) => (
            <li key={r}>{r}</li>
          ))}
        </ul>
      )}
      <details class="disclosure small">
        <summary>Score breakdown</summary>
        <ul class="breakdown">
          {COMPONENTS.map(([k, label]) => (
            <li key={k}>
              <span>{label}</span>
              <span class="meter" aria-hidden="true">
                <span style={{ width: `${ex.components[k] ?? 0}%` }} />
              </span>
              <span class="mono">{Math.round(ex.components[k] ?? 0)}</span>
            </li>
          ))}
        </ul>
      </details>
    </article>
  );
}
