import { useEffect, useRef, useState } from "preact/hooks";
import { api, ApiFailure } from "../api";
import { useApp } from "../app";
import type { Summary } from "../types";
import { Notice } from "../ui";
import { SummaryList } from "./review";

export function HomeView() {
  const { snap, go } = useApp();
  const [s, setS] = useState<Summary | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const h1 = useRef<HTMLHeadingElement>(null);
  const name = snap.profile?.display_name;

  useEffect(() => {
    document.title = "Dashboard · OpenHypergamy";
    h1.current?.focus({ preventScroll: true });
    api.get<Summary>("/api/summary").then(setS).catch((e) => setErr(e instanceof ApiFailure ? e.message : "Couldn't load your status."));
  }, []);

  const src = s?.sources;
  return (
    <div class="step home">
      <p class="eyebrow mono">Dashboard</p>
      <h1 class="display" tabIndex={-1} ref={h1}>
        {name ? `Hey ${name}.` : "Your setup."}
      </h1>
      {err && <Notice tone="bad">{err}</Notice>}

      <section class="stats" aria-label="Sources">
        <div class="stat">
          <span class="stat-num mono">{src?.configured ?? "—"}</span>
          <span class="stat-label">sources configured <span class="mono">/ {src?.target ?? 200} target</span></span>
        </div>
        <div class="stat">
          <span class="stat-num mono">{src?.enabled ?? "—"}</span>
          <span class="stat-label">enabled</span>
        </div>
        <div class="stat">
          <span class="stat-num mono">{src?.healthy_30d ?? "—"}</span>
          <span class="stat-label">healthy in the last 30 days</span>
        </div>
      </section>
      {src && src.enabled === 0 && (
        <Notice>
          No sources are enabled yet, so there's nothing to discover. Sources are reviewed and added in batches; this setup never
          switches any on by itself.
        </Notice>
      )}

      <h2 class="section-title">Settings</h2>
      {s && <SummaryList s={s} edit={go} />}

      <details class="disclosure">
        <summary>For power users</summary>
        <p class="hint">
          Everything here is also available from the terminal: <code>ohg status</code>, <code>ohg profile show</code>,{" "}
          <code>ohg opportunities list</code>, <code>ohg launchd install</code> for the background schedule.
        </p>
      </details>
    </div>
  );
}
