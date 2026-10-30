import type { ComponentChildren, JSX } from "preact";
import { useEffect, useId, useMemo, useRef, useState } from "preact/hooks";
import type { Option } from "./types";

// --- icons (decorative; always paired with text) ----------------------------------------------

const paths: Record<string, string> = {
  check: "M5 12.5l4.5 4.5L19 7.5",
  x: "M6 6l12 12M18 6L6 18",
  arrow: "M5 12h14M13 6l6 6-6 6",
  back: "M19 12H5M11 6l-6 6 6 6",
  dot: "M12 12h.01",
  lock: "M7 11V8a5 5 0 0110 0v3M6 11h12v9H6z",
  alert: "M12 8v5M12 16.5h.01M10.3 3.9L2.6 17.5A2 2 0 004.3 20.5h15.4a2 2 0 001.7-3L13.7 3.9a2 2 0 00-3.4 0z",
  plus: "M12 5v14M5 12h14",
  refresh: "M20 11a8 8 0 10-2.3 5.7M20 5v6h-6",
  minus: "M6 12h12",
};

export function Icon({ name, size = 18 }: { name: keyof typeof paths; size?: number }) {
  return (
    <svg
      class="icon"
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width={name === "dot" ? 6 : 2}
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d={paths[name]} />
    </svg>
  );
}

// --- buttons ----------------------------------------------------------------------------------

type ButtonProps = JSX.HTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  busy?: boolean;
  type?: "button" | "submit";
  disabled?: boolean;
};

export function Button({ variant = "secondary", busy, children, disabled, type = "button", ...rest }: ButtonProps) {
  return (
    <button
      {...rest}
      type={type}
      class={`btn btn-${variant} ${rest.class ?? ""}`}
      disabled={disabled || busy}
      aria-busy={busy ? "true" : undefined}
    >
      {busy && <span class="spinner" aria-hidden="true" />}
      {children}
    </button>
  );
}

// --- form fields ------------------------------------------------------------------------------

export function Field({
  label,
  hint,
  error,
  optional,
  children,
  id,
}: {
  label: string;
  hint?: ComponentChildren;
  error?: string | undefined;
  optional?: boolean;
  children: (ids: { id: string; describedBy: string | undefined; invalid: boolean }) => ComponentChildren;
  id?: string;
}) {
  const auto = useId();
  const fid = id ?? `f-${auto}`;
  const hintId = hint ? `${fid}-hint` : undefined;
  const errId = error ? `${fid}-err` : undefined;
  const describedBy = [errId, hintId].filter(Boolean).join(" ") || undefined;
  return (
    <div class={`field ${error ? "has-error" : ""}`}>
      <label for={fid} class="field-label">
        {label}
        {optional && <span class="optional">optional</span>}
      </label>
      {hint && (
        <p class="hint" id={hintId}>
          {hint}
        </p>
      )}
      {children({ id: fid, describedBy, invalid: Boolean(error) })}
      {error && (
        <p class="error-text" id={errId}>
          <Icon name="alert" size={16} /> {error}
        </p>
      )}
    </div>
  );
}

/** A fieldset for groups of toggles (chips, cards, radios). */
export function Group({
  legend,
  hint,
  error,
  optional,
  children,
  id,
}: {
  legend: string;
  hint?: ComponentChildren;
  error?: string | undefined;
  optional?: boolean;
  children: ComponentChildren;
  id?: string;
}) {
  const auto = useId();
  const gid = id ?? `g-${auto}`;
  return (
    <fieldset
      class={`field group ${error ? "has-error" : ""}`}
      id={gid}
      tabIndex={-1}
      aria-describedby={[error ? `${gid}-err` : "", hint ? `${gid}-hint` : ""].filter(Boolean).join(" ") || undefined}
    >
      <legend class="field-label">
        {legend}
        {optional && <span class="optional">optional</span>}
      </legend>
      {hint && (
        <p class="hint" id={`${gid}-hint`}>
          {hint}
        </p>
      )}
      {children}
      {error && (
        <p class="error-text" id={`${gid}-err`}>
          <Icon name="alert" size={16} /> {error}
        </p>
      )}
    </fieldset>
  );
}

export function Chips<T extends string | number>({
  options,
  value,
  onChange,
  single,
}: {
  options: Option<T>[];
  value: T[];
  onChange: (v: T[]) => void;
  single?: boolean;
}) {
  return (
    <div class="chips">
      {options.map((o) => {
        const on = value.includes(o.id);
        return (
          <button
            key={String(o.id)}
            type="button"
            class={`chip ${on ? "is-on" : ""}`}
            aria-pressed={on}
            onClick={() =>
              onChange(single ? [o.id] : on ? value.filter((v) => v !== o.id) : [...value, o.id])
            }
          >
            <span class="chip-mark" aria-hidden="true">
              {on ? <Icon name="check" size={14} /> : <Icon name="plus" size={14} />}
            </span>
            {o.label}
          </button>
        );
      })}
    </div>
  );
}

export const tagify = (s: string) =>
  s.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 48);

export const labelFor = (options: Option[], id: string) =>
  options.find((o) => o.id === id)?.label ?? id.replace(/_/g, " ");

/**
 * Suggested chips plus "add your own" with a filtered suggestion list (combobox pattern).
 * Custom entries become removable chips.
 */
export function TagPicker({
  options,
  value,
  onChange,
  addLabel,
  max,
}: {
  options: Option[];
  value: string[];
  onChange: (v: string[]) => void;
  addLabel: string;
  max: number;
}) {
  const [text, setText] = useState("");
  const [active, setActive] = useState(-1);
  const inputId = useId();
  const listId = `${inputId}-list`;
  const known = new Set(options.map((o) => o.id));
  const custom = value.filter((v) => !known.has(v));
  const matches = useMemo(() => {
    const q = text.trim().toLowerCase();
    if (!q) return [];
    return options
      .filter((o) => !value.includes(o.id) && o.label.toLowerCase().includes(q))
      .slice(0, 6);
  }, [text, options, value]);
  const full = value.length >= max;

  const add = (id: string) => {
    if (!id || value.includes(id) || full) return;
    onChange([...value, id]);
    setText("");
    setActive(-1);
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "ArrowDown" && matches.length) {
      e.preventDefault();
      setActive((a) => (a + 1) % matches.length);
    } else if (e.key === "ArrowUp" && matches.length) {
      e.preventDefault();
      setActive((a) => (a <= 0 ? matches.length - 1 : a - 1));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const pick = matches[active];
      add(pick ? pick.id : tagify(text));
    } else if (e.key === "Escape") {
      setText("");
      setActive(-1);
    }
  };

  return (
    <div class="tagpicker">
      <Chips options={options} value={value.filter((v) => known.has(v))} onChange={(v) => onChange([...v, ...custom])} />
      {custom.length > 0 && (
        <ul class="chips custom" aria-label="Your additions">
          {custom.map((c) => (
            <li key={c}>
              <span class="chip is-on is-static">
                {c.replace(/_/g, " ")}
                <button type="button" class="chip-remove" aria-label={`Remove ${c.replace(/_/g, " ")}`} onClick={() => onChange(value.filter((v) => v !== c))}>
                  <Icon name="x" size={14} />
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
      <div class="combo">
        <label class="sr-only" for={inputId}>
          {addLabel}
        </label>
        <input
          id={inputId}
          class="input"
          type="text"
          placeholder={full ? `That's the maximum (${max})` : `${addLabel}…`}
          disabled={full}
          value={text}
          role="combobox"
          aria-expanded={matches.length > 0}
          aria-controls={listId}
          aria-autocomplete="list"
          aria-activedescendant={active >= 0 ? `${listId}-${active}` : undefined}
          autocomplete="off"
          spellcheck={false}
          maxLength={48}
          onInput={(e) => {
            setText((e.target as HTMLInputElement).value);
            setActive(-1);
          }}
          onKeyDown={onKey}
        />
        <Button variant="ghost" class="combo-add" disabled={!tagify(text) || full} onClick={() => add(matches[active]?.id ?? tagify(text))}>
          <Icon name="plus" size={16} /> Add
        </Button>
        {matches.length > 0 && (
          <ul class="listbox" id={listId} role="listbox">
            {matches.map((m, i) => (
              <li
                key={m.id}
                id={`${listId}-${i}`}
                role="option"
                aria-selected={i === active}
                class={i === active ? "is-active" : ""}
                onMouseDown={(e) => {
                  e.preventDefault();
                  add(m.id);
                }}
              >
                {m.label}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export function ChoiceCards({
  name,
  options,
  value,
  onChange,
  multiple,
}: {
  name: string;
  options: (Option & { hint?: string })[];
  value: string[];
  onChange: (v: string[]) => void;
  multiple?: boolean;
}) {
  return (
    <div class={`choice-grid ${multiple ? "is-multi" : ""}`}>
      {options.map((o) => {
        const on = value.includes(o.id);
        return (
          <label key={o.id} class={`choice ${on ? "is-on" : ""}`}>
            <input
              type={multiple ? "checkbox" : "radio"}
              name={name}
              value={o.id}
              checked={on}
              onChange={() =>
                onChange(multiple ? (on ? value.filter((v) => v !== o.id) : [...value, o.id]) : [o.id])
              }
            />
            <span class="choice-box" aria-hidden="true">
              {on && <Icon name="check" size={14} />}
            </span>
            <span class="choice-text">
              <span class="choice-label">{o.label}</span>
              {o.hint && <span class="choice-hint">{o.hint}</span>}
            </span>
          </label>
        );
      })}
    </div>
  );
}

export function Switch({
  checked,
  onChange,
  label,
  hint,
  disabled,
}: {
  checked: boolean;
  onChange: (v: boolean) => void;
  label: string;
  hint?: string;
  disabled?: boolean;
}) {
  const id = useId();
  return (
    <div class="switch-row">
      <span class="switch-text">
        <span id={`${id}-l`} class="switch-label">
          {label}
        </span>
        {hint && (
          <span id={`${id}-h`} class="hint">
            {hint}
          </span>
        )}
      </span>
      <button
        type="button"
        role="switch"
        class="switch"
        aria-checked={checked}
        aria-labelledby={`${id}-l`}
        aria-describedby={hint ? `${id}-h` : undefined}
        disabled={disabled}
        onClick={() => onChange(!checked)}
      >
        <span class="switch-thumb" aria-hidden="true" />
      </button>
    </div>
  );
}

export function ErrorSummary({
  message,
  fields,
  labels,
}: {
  message: string;
  fields: Record<string, string>;
  labels: Record<string, string>;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => ref.current?.focus(), [message, fields]);
  const items = Object.entries(fields);
  return (
    <div class="error-summary" role="alert" tabIndex={-1} ref={ref}>
      <p class="error-summary-title">
        <Icon name="alert" /> {message}
      </p>
      {items.length > 0 && (
        <ul>
          {items.map(([k, v]) => (
            <li key={k}>
              <a href={`#${k}`} onClick={(e) => { e.preventDefault(); document.getElementById(k)?.focus(); }}>
                {labels[k] ?? k.replace(/[._]/g, " ")}: {v}
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export type Tone = "ok" | "warn" | "bad" | "off" | "busy";

export function Status({ tone, label, detail }: { tone: Tone; label: string; detail?: ComponentChildren }) {
  const icon = tone === "ok" ? "check" : tone === "bad" ? "x" : tone === "warn" ? "alert" : tone === "busy" ? "refresh" : "minus";
  return (
    <div class={`status status-${tone}`}>
      <span class="status-icon">
        <Icon name={icon} size={16} />
      </span>
      <span>
        <span class="status-label">{label}</span>
        {detail && <span class="status-detail">{detail}</span>}
      </span>
    </div>
  );
}

export function Notice({ tone = "info", children }: { tone?: "info" | "warn" | "bad" | "ok"; children: ComponentChildren }) {
  return (
    <div class={`notice notice-${tone}`} role={tone === "bad" ? "alert" : undefined}>
      {children}
    </div>
  );
}

export function SecretInput({
  id,
  value,
  onInput,
  describedBy,
  invalid,
  placeholder,
}: {
  id: string;
  value: string;
  onInput: (v: string) => void;
  describedBy?: string | undefined;
  invalid?: boolean;
  placeholder?: string;
}) {
  const [show, setShow] = useState(false);
  return (
    <div class="secret">
      <input
        id={id}
        class="input mono"
        type={show ? "text" : "password"}
        value={value}
        autocomplete="off"
        autoCapitalize="off"
        spellcheck={false}
        placeholder={placeholder}
        aria-describedby={describedBy}
        aria-invalid={invalid ? "true" : undefined}
        data-1p-ignore
        data-lpignore="true"
        onInput={(e) => onInput((e.target as HTMLInputElement).value)}
      />
      <Button variant="ghost" class="secret-toggle" aria-pressed={show} onClick={() => setShow(!show)}>
        {show ? "Hide" : "Show"}
      </Button>
    </div>
  );
}
