import { useEffect, useRef, useState } from "preact/hooks";
import { api, ApiFailure } from "../api";
import { useApp } from "../app";
import type { StepId, Summary } from "../types";
import { Button, Icon, labelFor, Notice, Status } from "../ui";
import { StepHeader } from "./common";

export function SummaryList({ s, edit }: { s: Summary; edit: (step: StepId) => void }) {
  const { snap } = useApp();
  const c = snap.catalog;
  const rows: { step: StepId; title: string; tone: "ok" | "warn" | "off"; label: string; detail: string }[] = [
    {
      step: "profile",
      title: "Profile",
      tone: s.profile ? "ok" : "warn",
      label: s.profile ? "Saved" : "Missing",
      detail: s.profile
        ? `${labelFor(c.degrees, s.profile.degree_level)} in ${labelFor(c.countries, s.profile.country)} · ${s.profile.interests} interest${s.profile.interests === 1 ? "" : "s"}`
        : s.profile_problem ?? "Not set up yet",
    },
    {
      step: "opportunities",
      title: "Opportunities",
      tone: s.profile ? "ok" : "warn",
      label: s.everything ? "Everything relevant" : `${s.categories.length} kind${s.categories.length === 1 ? "" : "s"}`,
      detail: s.everything ? "Ranked purely by fit" : s.categories.join(", "),
    },
    {
      step: "notifications",
      title: "Telegram",
      tone: s.telegram.enabled && s.telegram.connected ? "ok" : s.telegram.enabled ? "warn" : "off",
      label: s.telegram.enabled ? (s.telegram.connected ? "Connected" : "On, not connected") : "Off",
      detail: s.telegram.enabled ? (s.telegram.digest ? "Weekly digest and reminders" : "Reminders only") : "You can connect it later",
    },
    {
      step: "ai",
      title: "AI enrichment",
      tone: s.ai.effective && s.ai.acknowledged ? "ok" : s.ai.enabled ? "warn" : "off",
      label: !s.ai.enabled ? "Off" : s.ai.acknowledged ? "Ready to use" : "Waiting for acknowledgement",
      detail: s.ai.enabled ? "Results stay marked unverified" : "Deterministic rules only",
    },
  ];
  return (
    <ul class="summary">
      {rows.map((r) => (
        <li key={r.step}>
          <div class="summary-main">
            <span class="summary-title">{r.title}</span>
            <Status tone={r.tone} label={r.label} detail={r.detail} />
          </div>
          <Button variant="ghost" onClick={() => edit(r.step)} aria-label={`Edit ${r.title}`}>
            Edit
          </Button>
        </li>
      ))}
    </ul>
  );
}

export function ReviewStep() {
  const { go, refresh, setSnap, editing } = useApp();
  const [s, setS] = useState<Summary | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<Summary | null>(null);
  const doneRef = useRef<HTMLHeadingElement>(null);

  useEffect(() => {
    api.get<Summary>("/api/summary").then(setS).catch((e) => setErr(e instanceof ApiFailure ? e.message : "Couldn't load the summary."));
  }, []);
  useEffect(() => {
    if (done) doneRef.current?.focus();
  }, [done]);

  const finish = async () => {
    setBusy(true);
    setErr(null);
    try {
      const r = await api.post<{ summary: Summary }>("/api/finish");
      setDone(r.summary);
      setSnap(await refresh());
    } catch (e) {
      setErr(e instanceof ApiFailure ? e.message : "Couldn't finish setup.");
    } finally {
      setBusy(false);
    }
  };

  if (done) {
    return (
      <div class="step success">
        <span class="success-mark" aria-hidden="true">
          <Icon name="check" size={36} />
        </span>
        <h1 class="display" tabIndex={-1} ref={doneRef}>
          You're set up.
        </h1>
        <p class="lead">Everything is saved and checked. OpenHypergamy will rank what it finds against this profile from now on.</p>
        {done.todo.length > 0 && (
          <div class="todo">
            <h2 class="card-title">Still to do, whenever you like</h2>
            <ul>
              {done.todo.map((t) => (
                <li key={t}>{t}</li>
              ))}
            </ul>
          </div>
        )}
        <Button variant="primary" class="btn-lg" onClick={() => go("home")}>
          Open dashboard <Icon name="arrow" />
        </Button>
      </div>
    );
  }

  return (
    <div class="step">
      <StepHeader step="review" title="Looks good?" lead="Here's what's set. Change anything now, or later from the dashboard." />
      {err && <Notice tone="bad">{err}</Notice>}
      {!s && !err && <div class="example skeleton" aria-busy="true" />}
      {s && <SummaryList s={s} edit={go} />}
      {s && s.todo.length > 0 && (
        <div class="todo">
          <h2 class="card-title">Optional, for later</h2>
          <ul>
            {s.todo.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        </div>
      )}
      <div class="step-footer">
        <div class="step-footer-left">
          {!editing && (
            <Button variant="ghost" onClick={() => go("ai")}>
              <Icon name="back" size={16} /> Back
            </Button>
          )}
        </div>
        <div class="step-footer-right">
          <Button variant="primary" class="btn-lg" busy={busy} disabled={!s?.profile} onClick={finish}>
            Start discovering opportunities <Icon name="arrow" />
          </Button>
        </div>
      </div>
    </div>
  );
}
