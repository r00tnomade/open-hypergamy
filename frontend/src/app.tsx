import { createContext } from "preact";
import { useCallback, useContext, useEffect, useRef, useState } from "preact/hooks";
import { api, ApiFailure } from "./api";
import { AiStep } from "./steps/ai";
import { HomeView } from "./steps/home";
import { MatchingStep } from "./steps/matching";
import { NotificationsStep } from "./steps/notifications";
import { OpportunitiesStep } from "./steps/opportunities";
import { ProfileStep } from "./steps/profile";
import { ReviewStep } from "./steps/review";
import { WelcomeStep } from "./steps/welcome";
import type { Snapshot, StepId } from "./types";
import { Button, Icon, Notice } from "./ui";

export const STEP_TITLES: Record<StepId, string> = {
  welcome: "Welcome",
  profile: "Your profile",
  opportunities: "What you're after",
  matching: "How matching works",
  notifications: "Notifications",
  ai: "AI enrichment",
  review: "Review & finish",
};

type View = StepId | "home";

type Ctx = {
  snap: Snapshot;
  setSnap: (s: Snapshot) => void;
  refresh: () => Promise<Snapshot>;
  go: (v: View) => void;
  next: (from: StepId) => void;
  /** After onboarding, step pages are editors: "continue" returns to the dashboard. */
  editing: boolean;
};

const AppCtx = createContext<Ctx | null>(null);
export const useApp = () => {
  const c = useContext(AppCtx);
  if (!c) throw new Error("no app context");
  return c;
};

const pathFor = (v: View) => (v === "home" ? "/home" : `/setup/${v}`);
const viewFromPath = (steps: StepId[]): View | null => {
  const m = location.pathname.match(/^\/(?:setup\/([a-z]+)|(home))\/?$/);
  if (!m) return null;
  if (m[2]) return "home";
  return steps.includes(m[1] as StepId) ? (m[1] as StepId) : null;
};

/** Debounced draft autosave. Returns a status for an aria-live "Saved" indicator. */
export function useAutosave(step: string, data: unknown, enabled = true) {
  const [status, setStatus] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const first = useRef(true);
  const json = JSON.stringify(data);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    if (!enabled) return;
    setStatus("saving");
    const t = setTimeout(() => {
      api
        .put("/api/draft", { step, data })
        .then(() => setStatus("saved"))
        .catch(() => setStatus("error"));
    }, 600);
    return () => clearTimeout(t);
  }, [json]);
  return status;
}

export function SaveIndicator({ status }: { status: ReturnType<typeof useAutosave> }) {
  const text = {
    idle: "",
    saving: "Saving draft…",
    saved: "Draft saved",
    error: "Couldn't save the draft. Your answers are still here.",
  }[status];
  return (
    <span class={`save-indicator is-${status}`} aria-live="polite">
      {status === "saved" && <Icon name="check" size={14} />} {text}
    </span>
  );
}

export function App() {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [fatal, setFatal] = useState<string | null>(null);
  const [view, setView] = useState<View>("welcome");

  const refresh = useCallback(async () => {
    const s = await api.get<Snapshot>("/api/state");
    setSnap(s);
    return s;
  }, []);

  useEffect(() => {
    (async () => {
      try {
        await api.connect();
        const s = await refresh();
        const fromUrl = viewFromPath(s.steps);
        const initial: View =
          fromUrl ?? (s.onboarding.completed ? "home" : s.onboarding.current_step || "welcome");
        history.replaceState({ view: initial }, "", pathFor(initial));
        setView(initial);
      } catch (e) {
        setFatal(e instanceof ApiFailure ? e.message : "Couldn't start the setup page.");
      }
    })();
    const onPop = (e: PopStateEvent) => {
      const v = (e.state?.view as View | undefined) ?? "welcome";
      setView(v);
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const go = useCallback((v: View) => {
    history.pushState({ view: v }, "", pathFor(v));
    setView(v);
    window.scrollTo({ top: 0 });
    if (v !== "home") {
      api.post("/api/step", { step: v, status: "visited", current: v }).catch(() => undefined);
    }
  }, []);

  if (fatal) {
    return (
      <main class="center-page">
        <h1 class="display-sm">Setup can't continue</h1>
        <Notice tone="bad">{fatal}</Notice>
      </main>
    );
  }
  if (!snap) {
    return (
      <main class="center-page" aria-busy="true">
        <span class="spinner big" aria-hidden="true" />
        <p class="sr-only">Loading</p>
      </main>
    );
  }
  if (snap.config_error) return <Recovery snap={snap} refresh={refresh} />;

  const editing = snap.onboarding.completed;
  const next = (from: StepId) => {
    if (editing) return go("home");
    const i = snap.steps.indexOf(from);
    go(snap.steps[i + 1] ?? "review");
  };
  const ctx: Ctx = { snap, setSnap, refresh, go, next, editing };

  return (
    <AppCtx.Provider value={ctx}>
      <a href="#main" class="skip-link">
        Skip to content
      </a>
      <div class={`shell ${view === "home" ? "is-home" : ""}`}>
        <Rail view={view} />
        <main id="main" class="stage" key={view}>
          {view === "home" ? <HomeView /> : <StepView step={view} />}
        </main>
      </div>
    </AppCtx.Provider>
  );
}

function StepView({ step }: { step: StepId }) {
  switch (step) {
    case "welcome":
      return <WelcomeStep />;
    case "profile":
      return <ProfileStep />;
    case "opportunities":
      return <OpportunitiesStep />;
    case "matching":
      return <MatchingStep />;
    case "notifications":
      return <NotificationsStep />;
    case "ai":
      return <AiStep />;
    case "review":
      return <ReviewStep />;
  }
}

function Rail({ view }: { view: View }) {
  const { snap, go, editing } = useApp();
  const steps = snap.steps;
  const idx = view === "home" ? steps.length : Math.max(0, steps.indexOf(view));
  const pct = Math.round((idx / (steps.length - 1)) * 100);
  return (
    <header class="rail">
      <div class="brand">
        <img class="brand-mark" src="/static/brand/logo-symbol-auto.svg" alt="" width="28" height="28" />
        <span class="brand-name">OpenHypergamy</span>
      </div>
      {view !== "home" && (
        <>
          <p class="rail-count mono" aria-hidden="true">
            {String(idx + 1).padStart(2, "0")} <span>/ {String(steps.length).padStart(2, "0")}</span>
          </p>
          <div
            class="progress"
            role="progressbar"
            aria-label="Setup progress"
            aria-valuemin={0}
            aria-valuemax={steps.length}
            aria-valuenow={idx + 1}
            aria-valuetext={`Step ${idx + 1} of ${steps.length}: ${STEP_TITLES[view as StepId]}`}
          >
            <span style={{ width: `${pct}%` }} />
          </div>
          <nav aria-label="Setup steps" class="steps-nav">
            <ol>
              {steps.map((s, i) => {
                const st = snap.onboarding.steps[s];
                const reachable = editing || i <= idx || st !== undefined || i <= steps.indexOf(snap.onboarding.current_step);
                return (
                  <li key={s} class={`${s === view ? "is-current" : ""} ${st ? `is-${st}` : ""}`}>
                    <button
                      type="button"
                      disabled={!reachable}
                      aria-current={s === view ? "step" : undefined}
                      onClick={() => go(s)}
                    >
                      <span class="step-dot" aria-hidden="true">
                        {st === "done" ? <Icon name="check" size={12} /> : st === "skipped" ? <Icon name="minus" size={12} /> : null}
                      </span>
                      <span class="step-name">{STEP_TITLES[s]}</span>
                      {snap.optional_steps.includes(s) && <span class="step-tag">optional</span>}
                      <span class="sr-only">{st === "done" ? " (done)" : st === "skipped" ? " (skipped)" : ""}</span>
                    </button>
                  </li>
                );
              })}
            </ol>
          </nav>
        </>
      )}
      {editing && view !== "home" && (
        <Button variant="ghost" class="rail-home" onClick={() => go("home")}>
          <Icon name="back" size={16} /> Dashboard
        </Button>
      )}
      <p class="rail-privacy">
        <Icon name="lock" size={14} /> Runs on this computer. Nothing here is sent anywhere unless you connect it.
      </p>
    </header>
  );
}

function Recovery({ snap, refresh }: { snap: Snapshot; refresh: () => Promise<Snapshot> }) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  return (
    <main class="center-page">
      <p class="eyebrow mono">Setup paused</p>
      <h1 class="display-sm">Your settings file needs attention</h1>
      <Notice tone="warn">{snap.config_error}</Notice>
      {snap.recoverable ? (
        <>
          <p>
            We can move the broken file aside (it's kept, renamed, next to the original) and continue with safe
            defaults. Your profile and saved answers are not affected.
          </p>
          {err && <Notice tone="bad">{err}</Notice>}
          <Button
            variant="primary"
            busy={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await api.post("/api/recover/settings");
                location.reload();
              } catch (e) {
                setErr(e instanceof ApiFailure ? e.message : "Couldn't reset the file.");
                setBusy(false);
                await refresh().catch(() => undefined);
              }
            }}
          >
            Reset settings and continue
          </Button>
        </>
      ) : (
        <p>This file was written by hand, so we won't touch it. Fix the problem above, then reload this page.</p>
      )}
    </main>
  );
}
