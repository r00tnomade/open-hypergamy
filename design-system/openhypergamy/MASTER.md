# OpenHypergamy design system: MASTER

Source of truth for the onboarding GUI (`frontend/`). Page-specific overrides go in `pages/<page>.md`. Tokens live in `frontend/src/styles.css`.

## Brand mark

The logo is the owner's kit in `brand/` (README there has construction, clear space and rules). The app uses `logo-symbol-auto.svg` in the rail (28px, switches Ink/Paper with the colour scheme) and the kit's `favicon.svg`, `favicon.ico` and `apple-touch-icon.png`. `frontend/scripts/copy-brand.mjs` copies only those runtime files into the build; the overview board and README stay here. Don't recolour, rotate, mirror or outline the mark.

The kit's Signal is `#C93E1B` (`#E0532B` dark). The GUI's accent below stays `#FF5B1F` on purpose: buttons put Ink text on it (≥ 7:1), while Paper on the kit's Signal is 4.4:1, under the 4.5:1 this system requires for button text. Align the two if the buttons move to large text or the kit's Signal is darkened.

## Direction: "signal on paper"

A personal intelligence tool, not a SaaS dashboard. Warm paper and ink, one loud signal colour used sparingly, editorial type, and mono for anything that is data. Confident, direct, a bit playful in copy, never hustle-guru.

How it was derived (UI UX Pro Max, 2026-10-30):
- `--design-system "personal opportunity intelligence tool onboarding minimal confident internet-native"` suggested *AI-Native UI*, purple `#7C3AED`, Inter. **Rejected**: purple plus Inter is the generic AI-product look the brief rules out.
- `--domain color "dark ink warm paper signal accent developer tool"` gave *Notes & Writing App* (warm ink, amber accent on cream) and *Developer Tool* (dark plus one run colour). Adopted the structure: warm neutrals plus a single accent.
- `--domain typography "editorial technical confident grotesk mono"` gave Space Grotesk (headings) and a mono for data. Adopted Space Grotesk for UI and display, IBM Plex Mono for labels and numbers. Both are **bundled** (`@fontsource`), never Google Fonts: the app must work offline and make no third-party requests.
- `--domain ux` (multi-step form, inline validation, error summary, focus, reduced motion, chips): step indicator with "n of N"; validate on blur and on submit; a focusable error summary that links to fields, with inline errors kept; one or two animated elements per view; chips wrap rather than clip.

## Tokens

| Token | Light | Dark | Use |
|---|---|---|---|
| `--paper` | `#F4F1EA` | `#121110` | page background |
| `--surface` | `#FFFDF8` | `#1B1A17` | cards, inputs |
| `--ink` | `#171512` | `#F2EEE6` | primary text |
| `--ink-2` | `#4A453D` | `#C9C2B5` | secondary text (≥ 7:1) |
| `--ink-3` | `#6A645A` | `#A29B8E` | hints (≥ 4.5:1) |
| `--line` | `#DDD6C8` | `#34302A` | dividers, input borders (with `--line-strong` on focus/hover) |
| `--signal` | `#FF5B1F` | `#FF7A45` | primary button fill, progress, selection. **Text on it is `--ink-on-signal` (#171512)**, never white |
| `--signal-text` | `#A83A0E` | `#FF9A6E` | accent text and links on paper (≥ 4.5:1) |
| `--ok` / `--warn` / `--bad` | `#1D6B40` / `#7A5200` / `#A3261A` | `#6BD49A` / `#E8B85C` / `#FF8F85` | status text; always paired with an icon and a word |

Spacing: 4-based scale `--s-1`…`--s-9` (4, 8, 12, 16, 24, 32, 48, 64, 96). Radius: 10px controls, 16px cards, 999px chips. Shadows: almost none; a hairline plus a 1px offset "paper" shadow on raised cards.

## Type

- Display: Space Grotesk 600, `clamp(2.3rem, 5.5vw, 4.1rem)`, tracking -0.035em, `text-wrap: balance`, max 18ch.
- H2: 1.6–2rem 600. Body: 1rem / 1.55. Never below 0.875rem except mono micro-labels at 0.75rem uppercase +0.08em (decorative or duplicated info only).
- Mono (IBM Plex Mono 500): step counters `02 / 07`, scores, chips' counts, technical values (model ids, ports).

## Components

Step shell (left rail on ≥ 960px, top progress bar below), chip group (`aria-pressed` toggle buttons), tag input with suggestions (combobox plus listbox, keyboard), choice cards (radio or checkbox semantics), switch (`role="switch"`), field (label, hint, inline error via `aria-describedby`), error summary (`role="alert"`, focus on failed submit), status row (icon + word + detail), masked secret field (never pre-filled, cleared after save), example opportunity card (labelled *Example*).

## Rules

- Contrast ≥ 4.5:1 for text, ≥ 3:1 for UI boundaries and focus. Focus ring: 2px `--ink` outline, 2px offset, plus signal halo.
- Targets ≥ 44×44px. No hover-only affordances.
- Motion: 150–220ms ease-out on state changes; step enter is a 12px rise plus fade. Everything is disabled under `prefers-reduced-motion`.
- No emoji as icons; inline SVG, `aria-hidden` when decorative.
- Never colour alone: status is icon + word.
- Copy: plain, second person, short. Explain *why* a field matters next to it. Never claim certainty the rules don't have.
