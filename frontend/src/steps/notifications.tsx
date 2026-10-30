import { useState } from "preact/hooks";
import { api, ApiFailure } from "../api";
import { SaveIndicator, useApp, useAutosave } from "../app";
import type { Snapshot } from "../types";
import { Button, Chips, ErrorSummary, Field, Group, Icon, Notice, SecretInput, Status, Switch } from "../ui";
import { StepFooter, StepHeader } from "./common";

type Prefs = {
  enabled: boolean;
  digest_enabled: boolean;
  digest_weekday: number;
  digest_time: string;
  timezone: string;
  deadline_offsets_days: number[];
  minimum_fit_score_for_immediate_alert: number;
};

const LABELS: Record<string, string> = {
  timezone: "Timezone",
  digest_time: "Delivery time",
  digest_weekday: "Digest day",
  deadline_offsets_days: "Reminders",
  token: "Bot token",
};

type Msg = { tone: "ok" | "warn" | "bad"; text: string } | null;

export function NotificationsStep() {
  const { snap, setSnap, refresh, next } = useApp();
  const s = snap.settings!;
  const sec = snap.secrets!;
  const d = (snap.onboarding.drafts.notifications ?? {}) as Partial<Prefs>;
  const connected = sec.telegram_token !== "unset" && sec.telegram_chat !== "unset";
  const [p, setP] = useState<Prefs>(() => ({
    enabled: d.enabled ?? (s.telegram.enabled && connected),
    digest_enabled: d.digest_enabled ?? s.telegram.digest_enabled,
    digest_weekday: d.digest_weekday ?? s.telegram.digest_weekday,
    digest_time: d.digest_time ?? s.telegram.digest_time,
    timezone: d.timezone ?? s.timezone,
    deadline_offsets_days: d.deadline_offsets_days ?? s.telegram.deadline_offsets_days,
    minimum_fit_score_for_immediate_alert: d.minimum_fit_score_for_immediate_alert ?? s.telegram.minimum_fit_score_for_immediate_alert,
  }));
  const status = useAutosave("notifications", p);
  const set = <K extends keyof Prefs>(k: K, v: Prefs[K]) => setP((prev) => ({ ...prev, [k]: v }));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [summary, setSummary] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (p.enabled && !connected) {
      setSummary("Connect your bot and chat first, or turn Telegram off to continue without it.");
      setErrors({});
      return;
    }
    setBusy(true);
    setSummary(null);
    try {
      setSnap(await api.post<Snapshot>("/api/telegram/settings", p));
      next("notifications");
    } catch (e) {
      if (e instanceof ApiFailure) {
        setErrors(e.fields);
        setSummary(e.message);
      }
    } finally {
      setBusy(false);
    }
  };
  const skip = async () => {
    await api.post("/api/step", { step: "notifications", status: "skipped", current: "ai" });
    setSnap(await refresh());
    next("notifications");
  };

  return (
    <form class="step" noValidate onSubmit={(e) => e.preventDefault()}>
      <StepHeader
        step="notifications"
        title="Want a nudge before deadlines?"
        lead="OpenHypergamy can message you on Telegram: a weekly digest and reminders before deadlines that matter. Totally optional; everything also works without it."
      />
      {summary && <ErrorSummary message={summary} fields={errors} labels={LABELS} />}
      {!s.editable && <Notice tone="warn">Your settings come from a hand-written settings file, so delivery preferences can't be changed here.</Notice>}

      <div class="form-grid">
        <div class={`everything-card ${p.enabled ? "is-on" : ""}`}>
          <Switch checked={p.enabled} onChange={(v) => set("enabled", v)} label="Send me Telegram alerts" hint="Nothing is sent until you press “Send test message” or finish with this on." />
        </div>

        {p.enabled && (
          <>
            {!sec.keychain_available && (
              <Notice tone="warn">
                Secure storage (the macOS Keychain) isn't available here, so this page can't store your token. Set{" "}
                <code>TELEGRAM_BOT_TOKEN</code> and <code>TELEGRAM_CHAT_ID</code> as environment variables, then reload.
              </Notice>
            )}
            <TelegramConnect snap={snap} onChange={async () => setSnap(await refresh())} />

            <Group legend="When should we write?" id="digest_time" error={errors.digest_time}>
              <Switch checked={p.digest_enabled} onChange={(v) => set("digest_enabled", v)} label="Weekly digest" hint="One message a week with what's new and what's due." />
              <div class="row-3">
                <Field label="Day" id="digest_weekday" error={errors.digest_weekday}>
                  {({ id }) => (
                    <select id={id} class="input" value={p.digest_weekday} disabled={!p.digest_enabled} onChange={(e) => set("digest_weekday", Number((e.target as HTMLSelectElement).value))}>
                      {snap.catalog.weekdays.map((w) => (
                        <option key={w.id} value={w.id}>{w.label}</option>
                      ))}
                    </select>
                  )}
                </Field>
                <Field label="Time" id="digest_time_input">
                  {({ id }) => (
                    <input id={id} class="input mono" type="time" value={p.digest_time} onInput={(e) => set("digest_time", (e.target as HTMLInputElement).value)} />
                  )}
                </Field>
                <Field label="Timezone" id="timezone" error={errors.timezone}>
                  {({ id, describedBy }) => (
                    <select id={id} class="input" value={p.timezone} aria-describedby={describedBy} onChange={(e) => set("timezone", (e.target as HTMLSelectElement).value)}>
                      {snap.catalog.timezones.map((z) => (
                        <option key={z} value={z}>{z.replace(/_/g, " ")}</option>
                      ))}
                    </select>
                  )}
                </Field>
              </div>
              <p class="hint">Times apply to the background schedule the next time it's installed.</p>
            </Group>

            <Group legend="Deadline reminders" hint="Days before a confirmed deadline. Estimated dates never trigger reminders." id="deadline_offsets_days" error={errors.deadline_offsets_days}>
              <Chips
                options={snap.catalog.reminder_offsets.map((o) => ({ id: o, label: o === 1 ? "1 day" : `${o} days` }))}
                value={p.deadline_offsets_days}
                onChange={(v) => set("deadline_offsets_days", [...v].sort((a, b) => b - a))}
              />
            </Group>

            <Field
              label={`Instant alert for strong matches: fit ≥ ${p.minimum_fit_score_for_immediate_alert}`}
              hint="Higher means fewer, better pings."
              id="minimum_fit"
            >
              {({ id, describedBy }) => (
                <input id={id} class="range" type="range" min={50} max={95} step={5} value={p.minimum_fit_score_for_immediate_alert} aria-describedby={describedBy} onInput={(e) => set("minimum_fit_score_for_immediate_alert", Number((e.target as HTMLInputElement).value))} />
              )}
            </Field>
          </>
        )}
      </div>

      <SaveIndicator status={status} />
      <StepFooter step="notifications" onContinue={p.enabled ? submit : skip} busy={busy} continueLabel={p.enabled ? "Save and continue" : "Continue without Telegram"} skippable={false} />
    </form>
  );
}

function TelegramConnect({ snap, onChange }: { snap: Snapshot; onChange: () => Promise<void> }) {
  const sec = snap.secrets!;
  const [token, setToken] = useState("");
  const [tokenErr, setTokenErr] = useState<string | undefined>();
  const [msg, setMsg] = useState<Msg>(null);
  const [chatMsg, setChatMsg] = useState<Msg>(null);
  const [testMsg, setTestMsg] = useState<Msg>(null);
  const [chats, setChats] = useState<{ ref: string; label: string; kind: string }[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const tokenSet = sec.telegram_token !== "unset";
  const chatSet = sec.telegram_chat !== "unset";
  const where = (src: string) => (src === "environment" ? "from your environment" : "in your Keychain");

  const run = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    try {
      await fn();
    } finally {
      setBusy(null);
    }
  };

  const saveToken = () =>
    run("token", async () => {
      setTokenErr(undefined);
      setMsg(null);
      if (!/^\d{5,12}:[A-Za-z0-9_-]{30,64}$/.test(token.trim())) {
        setTokenErr("It should look like 123456789:AA… (copy it from @BotFather).");
        return;
      }
      try {
        const r = await api.post<{ verified: boolean; bot_username: string | null; warning: string | null }>("/api/telegram/token", { token: token.trim() });
        setToken(""); // never keep the secret around once it's stored
        setMsg(r.verified ? { tone: "ok", text: `Connected to @${r.bot_username ?? "your bot"}.` } : { tone: "warn", text: r.warning ?? "Saved." });
        await onChange();
      } catch (e) {
        if (e instanceof ApiFailure) {
          setTokenErr(e.fields.token);
          setMsg({ tone: "bad", text: e.message });
        }
      }
    });

  const detect = () =>
    run("detect", async () => {
      setChatMsg(null);
      try {
        const r = await api.post<{ stored: boolean; label?: string; chats: { ref: string; label: string; kind: string }[]; hint?: string }>("/api/telegram/chat/detect");
        if (r.stored) {
          setChats([]);
          setChatMsg({ tone: "ok", text: `Linked to ${r.label}.` });
          await onChange();
        } else if (r.chats?.length) {
          setChats(r.chats);
        } else setChatMsg({ tone: "warn", text: r.hint ?? "No chats found yet." });
      } catch (e) {
        setChatMsg({ tone: "bad", text: e instanceof ApiFailure ? e.message : "Couldn't reach Telegram." });
      }
    });

  const pick = (ref: string, label: string) =>
    run("detect", async () => {
      try {
        await api.post("/api/telegram/chat", { ref, label });
        setChats([]);
        setChatMsg({ tone: "ok", text: `Linked to ${label}.` });
        await onChange();
      } catch (e) {
        setChatMsg({ tone: "bad", text: e instanceof ApiFailure ? e.message : "Couldn't save that chat." });
      }
    });

  const test = () =>
    run("test", async () => {
      setTestMsg(null);
      try {
        await api.post("/api/telegram/test");
        setTestMsg({ tone: "ok", text: "Sent. Check Telegram." });
      } catch (e) {
        setTestMsg({ tone: "bad", text: e instanceof ApiFailure ? e.message : "The test didn't go through." });
      }
    });

  const forget = () =>
    run("forget", async () => {
      await api.post("/api/telegram/forget");
      setMsg(null);
      setChatMsg(null);
      setTestMsg(null);
      await onChange();
    });

  return (
    <ol class="connect-steps">
      <li class={tokenSet ? "is-done" : ""}>
        <h2 class="connect-title">
          <span class="mono">1</span> Your bot
        </h2>
        {tokenSet ? (
          <Status tone="ok" label="Bot token saved" detail={where(sec.telegram_token)} />
        ) : (
          <p class="hint">
            In Telegram, open <strong>@BotFather</strong>, send <code>/newbot</code>, and paste the token it gives you. It's stored in your
            Keychain and never shown again.
          </p>
        )}
        {sec.keychain_available && (
          <Field label={tokenSet ? "Replace bot token" : "Bot token"} error={tokenErr} id="token">
            {({ id, describedBy, invalid }) => (
              <div class="inline-form">
                <SecretInput id={id} value={token} onInput={setToken} describedBy={describedBy} invalid={invalid} placeholder="123456789:AA…" />
                <Button variant="secondary" busy={busy === "token"} disabled={!token.trim()} onClick={saveToken}>
                  Save & verify
                </Button>
              </div>
            )}
          </Field>
        )}
        {msg && <Status tone={msg.tone} label={msg.text} />}
      </li>

      <li class={chatSet ? "is-done" : ""}>
        <h2 class="connect-title">
          <span class="mono">2</span> Your chat
        </h2>
        {chatSet ? (
          <Status tone="ok" label="Chat linked" detail={where(sec.telegram_chat)} />
        ) : (
          <p class="hint">Open your new bot in Telegram, press <strong>Start</strong> (or send it anything), then:</p>
        )}
        <Button variant="secondary" busy={busy === "detect"} disabled={!tokenSet || !sec.keychain_available} onClick={detect}>
          <Icon name="refresh" size={16} /> {chatSet ? "Find my chat again" : "Find my chat"}
        </Button>
        {chats.length > 0 && (
          <fieldset class="chat-pick">
            <legend class="field-label">Which chat should get the alerts?</legend>
            {chats.map((c) => (
              <Button key={c.ref} variant="secondary" onClick={() => pick(c.ref, c.label)}>
                {c.label} <span class="mono hint">{c.kind}</span>
              </Button>
            ))}
          </fieldset>
        )}
        {chatMsg && <Status tone={chatMsg.tone} label={chatMsg.text} />}
      </li>

      <li>
        <h2 class="connect-title">
          <span class="mono">3</span> Test it
        </h2>
        <p class="hint">Sends one message to your chat. Only when you press the button.</p>
        <div class="inline-form">
          <Button variant="secondary" busy={busy === "test"} disabled={!tokenSet || !chatSet} onClick={test}>
            Send test message
          </Button>
          {(tokenSet || chatSet) && sec.keychain_available && (
            <Button variant="ghost" busy={busy === "forget"} onClick={forget}>
              Disconnect
            </Button>
          )}
        </div>
        {testMsg && <Status tone={testMsg.tone} label={testMsg.text} />}
      </li>
    </ol>
  );
}

