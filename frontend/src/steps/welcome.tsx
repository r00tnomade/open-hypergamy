import { useEffect } from "preact/hooks";
import { useApp } from "../app";
import { Button, Icon } from "../ui";

export function WelcomeStep() {
  const { snap, go, next } = useApp();
  const back = snap.onboarding.existing_install || snap.onboarding.completed;
  useEffect(() => {
    document.title = "Welcome · OpenHypergamy setup";
    document.getElementById("welcome-title")?.focus({ preventScroll: true });
  }, []);
  return (
    <div class="welcome">
      <p class="eyebrow mono">{back ? "Welcome back" : "Personal opportunity intelligence"}</p>
      <h1 class="display hero" id="welcome-title" tabIndex={-1}>
        Find opportunities you <em>didn't know existed.</em>
      </h1>
      <p class="lead">
        Summer schools, research programmes, fellowships, hackathons, calls for papers: OpenHypergamy watches the
        official pages you approve, checks the facts, and tells you what's worth your time.
      </p>

      <ol class="how">
        <li>
          <span class="how-n mono">01</span>
          <span>
            <strong>Discover.</strong> Checks official sources on a schedule, politely and only the pages you allow.
          </span>
        </li>
        <li>
          <span class="how-n mono">02</span>
          <span>
            <strong>Verify.</strong> A date only counts as confirmed when the official page says so. AI can help
            read pages but never confirms anything.
          </span>
        </li>
        <li>
          <span class="how-n mono">03</span>
          <span>
            <strong>Match.</strong> Ranks what it finds against your profile, on your computer, and explains why.
          </span>
        </li>
      </ol>

      <div class="privacy-card">
        <p class="privacy-title">
          <Icon name="lock" /> What stays here, and what doesn't
        </p>
        <ul>
          <li>
            Your profile, preferences and database stay on this computer. Tokens go into your system keychain, never
            into files.
          </li>
          <li>
            If you connect Telegram, alerts are sent to <em>your</em> bot. If you turn on AI enrichment, excerpts of{" "}
            <em>public</em> pages go to your local AI gateway, which may forward them to its providers. Your profile
            never does.
          </li>
          <li>No analytics, no accounts, no tracking.</li>
        </ul>
      </div>

      <div class="welcome-actions">
        <Button variant="primary" class="btn-lg" onClick={() => next("welcome")}>
          {back ? "Review my setup" : "Get started"} <Icon name="arrow" />
        </Button>
        {back && snap.onboarding.completed && (
          <Button variant="ghost" onClick={() => go("home")}>
            Go to dashboard
          </Button>
        )}
        {!back && <span class="hint">About 3 minutes. Optional steps can wait.</span>}
      </div>
    </div>
  );
}
