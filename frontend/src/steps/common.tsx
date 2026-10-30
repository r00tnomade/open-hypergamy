import type { ComponentChildren } from "preact";
import { useEffect, useRef } from "preact/hooks";
import { STEP_TITLES, useApp } from "../app";
import type { StepId } from "../types";
import { Button, Icon } from "../ui";

export function StepHeader({ step, title, lead }: { step: StepId; title: string; lead?: ComponentChildren }) {
  const ref = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    ref.current?.focus({ preventScroll: true });
    document.title = `${STEP_TITLES[step]} · OpenHypergamy setup`;
  }, [step]);
  return (
    <div class="step-header">
      <h1 class="display" tabIndex={-1} ref={ref}>
        {title}
      </h1>
      {lead && <p class="lead">{lead}</p>}
    </div>
  );
}

export function StepFooter({
  step,
  onContinue,
  continueLabel = "Continue",
  busy,
  skippable,
  onSkip,
  extra,
}: {
  step: StepId;
  onContinue: () => void;
  continueLabel?: string;
  busy?: boolean;
  skippable?: boolean;
  onSkip?: () => void;
  extra?: ComponentChildren;
}) {
  const { snap, go, editing } = useApp();
  const i = snap.steps.indexOf(step);
  const prev = snap.steps[i - 1];
  return (
    <div class="step-footer">
      <div class="step-footer-left">
        {prev && !editing && (
          <Button variant="ghost" onClick={() => go(prev)}>
            <Icon name="back" size={16} /> Back
          </Button>
        )}
        {extra}
      </div>
      <div class="step-footer-right">
        {skippable && !editing && (
          <Button variant="secondary" onClick={onSkip}>
            Skip for now
          </Button>
        )}
        <Button variant="primary" type="submit" busy={busy} onClick={onContinue}>
          {editing ? "Save" : continueLabel} <Icon name="arrow" size={16} />
        </Button>
      </div>
    </div>
  );
}
