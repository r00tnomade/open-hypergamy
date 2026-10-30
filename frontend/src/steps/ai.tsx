import { useEffect, useState } from "preact/hooks";
import { api, ApiFailure } from "../api";
import { useApp } from "../app";
import type { LlmStatus, Snapshot } from "../types";
import { Button, Field, Icon, Notice, SecretInput, Status, Switch } from "../ui";
import { StepFooter, StepHeader } from "./common";

type Msg = { tone: "ok" | "warn" | "bad"; text: string } | null;

export function AiStep() {
  const { snap, setSnap, refresh, next } = useApp();
  const [st, setSt] = useState<LlmStatus | null>(null);
  const [checking, setChecking] = useState(false);
  const [checkErr, setCheckErr] = useState<string | null>(null);
  const [key, setKey] = useState("");
  const [keyErr, setKeyErr] = useState<string | undefined>();
  const [understood, setUnderstood] = useState(false);
  const [testMsg, setTestMsg] = useState<Msg>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const editable = snap.settings?.editable ?? false;

  const check = async () => {
    setChecking(true);
    setCheckErr(null);
    try {
      setSt(await api.post<LlmStatus>("/api/llm/status"));
    } catch (e) {
      setCheckErr(e instanceof ApiFailure ? e.message : "Couldn't check the gateway.");
    } finally {
      setChecking(false);
    }
  };
  useEffect(() => {
    void check();
  }, []);

  const run = async (k: string, fn: () => Promise<void>) => {
    setBusy(k);
    try {
      await fn();
    } finally {
      setBusy(null);
    }
  };

  const toggle = (enabled: boolean) =>
    run("toggle", async () => {
      setSnap(await api.post<Snapshot>("/api/llm/settings", { enabled }));
      await check();
    });

  const ack = () =>
    run("ack", async () => {
      await api.post("/api/llm/ack", { accept: true });
      setSnap(await refresh());
      await check();
    });

  const saveKey = () =>
    run("key", async () => {
      setKeyErr(undefined);
      try {
        await api.post("/api/llm/key", { key: key.trim() });
        setKey("");
        await check();
      } catch (e) {
        if (e instanceof ApiFailure) setKeyErr(e.fields.key ?? e.message);
      }
    });

  const test = () =>
    run("test", async () => {
      setTestMsg(null);
      try {
        const r = await api.post<{ ok: boolean; model: string | null }>("/api/llm/test");
        setTestMsg(r.ok ? { tone: "ok", text: `Working: answered via ${r.model ?? "the gateway"}.` } : { tone: "warn", text: "The gateway answered, but not with the expected reply. Enrichment may be unreliable." });
      } catch (e) {
        setTestMsg({ tone: "bad", text: e instanceof ApiFailure ? e.message : "The test didn't complete." });
      }
    });

  const finish = async (status: "done" | "skipped") => {
    await api.post("/api/step", { step: "ai", status, current: "review" });
    setSnap(await refresh());
    next("ai");
  };

  const enabled = st?.enabled ?? snap.settings?.llm.enabled ?? false;
  const local = st?.provider === "local";
  const ready = Boolean(st && st.effective && st.reachable && st.model_listed && st.acknowledged && (local || st.api_key !== "unset"));

  return (
    <div class="step">
      <StepHeader
        step="ai"
        title="Let AI help read messy pages?"
        lead="Optional. A local AI gateway can pull dates and requirements out of long pages. Its answers are always marked unverified and must quote the page word for word. OpenHypergamy works fine without it."
      />

      <div class="form-grid">
        <div class={`everything-card ${enabled ? "is-on" : ""}`}>
          <Switch checked={enabled} disabled={!editable || busy === "toggle"} onChange={toggle} label="Use AI enrichment" hint="Turned off, discovery and matching run on deterministic rules only." />
        </div>
        {!editable && <Notice tone="warn">Your settings come from a hand-written settings file; change <code>llm.enabled</code> there.</Notice>}

        <section class="card" aria-labelledby="ai-status-title">
          <div class="card-head">
            <h2 id="ai-status-title" class="card-title">Gateway status</h2>
            <Button variant="ghost" busy={checking} onClick={check}>
              <Icon name="refresh" size={16} /> Check again
            </Button>
          </div>
          {checkErr && <Notice tone="bad">{checkErr}</Notice>}
          {!st && !checkErr && <Status tone="busy" label="Checking…" />}
          {st && (
            <div class="status-list" aria-live="polite">
              <Status tone={st.reachable ? "ok" : "bad"} label={st.reachable ? "Gateway reachable" : "Gateway not reachable"} detail={<span class="mono">{st.base_url}</span>} />
              <Status
                tone={st.model_listed ? "ok" : st.reachable ? "bad" : "off"}
                label={st.model_listed ? "Model route available" : st.model_listed === false ? "Model route not found" : "Model route unknown"}
                detail={<span class="mono">{st.model}</span>}
              />
              {!local && <Status tone={st.api_key !== "unset" ? "ok" : "warn"} label={st.api_key !== "unset" ? "API key stored" : "No API key yet"} detail={st.api_key === "environment" ? "from your environment" : st.api_key === "keychain" ? "in your Keychain" : undefined} />}
              <Status tone={st.acknowledged ? "ok" : "warn"} label={st.acknowledged ? "Data policy acknowledged" : "Data policy not acknowledged yet"} />
              {st.error && <Notice tone="bad">{st.error}</Notice>}
            </div>
          )}
        </section>

        {st && !st.acknowledged && (
          <section class="card" aria-labelledby="ack-title">
            <h2 id="ack-title" class="card-title">Before anything is sent</h2>
            <Checklist text={snap.llm_checklist} />
            <label class="check-row">
              <input type="checkbox" checked={understood} onChange={(e) => setUnderstood((e.target as HTMLInputElement).checked)} />
              <span>I understand: only public page excerpts are sent, through my local gateway, which may forward them to free-tier providers.</span>
            </label>
            <Button variant="secondary" disabled={!understood} busy={busy === "ack"} onClick={ack}>
              Acknowledge
            </Button>
          </section>
        )}

        {st && !local && snap.secrets?.keychain_available && (
          <section class="card" aria-labelledby="key-title">
            <h2 id="key-title" class="card-title">Gateway key</h2>
            <Field label={st.api_key !== "unset" ? "Replace the unified key" : "Unified key from FreeLLMAPI"} hint="Stored in your Keychain, never in files or this page." error={keyErr} id="llm_key">
              {({ id, describedBy, invalid }) => (
                <div class="inline-form">
                  <SecretInput id={id} value={key} onInput={setKey} describedBy={describedBy} invalid={invalid} />
                  <Button variant="secondary" busy={busy === "key"} disabled={!key.trim()} onClick={saveKey}>
                    Save key
                  </Button>
                </div>
              )}
            </Field>
          </section>
        )}

        {st && (
          <section class="card" aria-labelledby="test-title">
            <h2 id="test-title" class="card-title">Try it</h2>
            <p class="hint">Sends one tiny, fixed test request (no personal data) through the gateway.</p>
            <Button variant="secondary" busy={busy === "test"} disabled={!st.effective || !st.reachable || !st.acknowledged} onClick={test}>
              Run a test
            </Button>
            {testMsg && <Status tone={testMsg.tone} label={testMsg.text} />}
          </section>
        )}

        {st && !ready && (
          <details class="disclosure" open={!st.reachable}>
            <summary>Setting up FreeLLMAPI (manual, about 10 minutes)</summary>
            <ol class="guide">
              <li>Install and start FreeLLMAPI on this computer, bound to <code>127.0.0.1:3001</code> only.</li>
              <li>
                Create a model chain named <code>ohg-free</code> containing <strong>only free-tier routes</strong>. Don't add billing-enabled
                credentials or paid routes.
              </li>
              <li>Create a dedicated unified key and paste it above.</li>
              <li>Press <em>Check again</em>. OpenHypergamy can't create the chain for you, and never switches to another provider on its own.</li>
            </ol>
          </details>
        )}
      </div>

      <StepFooter step="ai" onContinue={() => finish(ready ? "done" : "skipped")} continueLabel={ready ? "Continue" : "Continue without AI for now"} />
    </div>
  );
}

/** The CLI's acknowledgement text (llm/ack.py CHECKLIST), reflowed as a list. Same words, same policy. */
function Checklist({ text }: { text: string }) {
  const [title = "", ...rest] = text.split("\n");
  const items = rest
    .join("\n")
    .split(/\n\s*(?=\d+\.\s)/)
    .map((t) => t.replace(/^\s*\d+\.\s*/, "").replace(/\s+/g, " ").trim())
    .filter(Boolean);
  return (
    <div class="checklist">
      <p class="checklist-title">{title}</p>
      <ol>
        {items.map((i) => (
          <li key={i}>{i}</li>
        ))}
      </ol>
    </div>
  );
}
