# OpenHypergamy — logo icon

**The idea:** two gateways that share one pillar, the second standing higher.
You walk through one door and the opportunity on the other side is a taller one —
access and ascent in a single silhouette. (Career hypergamy: marry up, professionally.)

## Construction (256 × 256 grid)
- Two identical round-top arches: outer radius 58, inner radius 24, stroke 34.
- They share the middle pillar; the right arch is lifted 80 units.
- Footprint 198 × 192, centred on the canvas. Flat fills only, no strokes, no text, no masks.

## Files
| File | Use |
|---|---|
| `logo-symbol.svg` | Master, Ink on transparent |
| `logo-light.svg` / `logo-dark.svg` | For light / dark backgrounds |
| `logo-monochrome.svg` | `fill="currentColor"` — inherits CSS `color` |
| `logo-symbol-auto.svg` | Switches Ink ↔ Paper with `prefers-color-scheme` |
| `app-icon.svg`, `icon-192.png`, `icon-512.png`, `apple-touch-icon.png` | App / PWA icons |
| `favicon.svg`, `favicon.ico`, `favicon-16/32/48.png` | Browser tab (mark enlarged for small sizes) |
| `brand-preview.png` | Overview board |

## Colours
| Name | Light | Dark |
|---|---|---|
| Paper | `#F4F1EA` (244 241 234) | `#121110` |
| Ink | `#171512` (23 21 18) | `#F2EEE6` |
| Signal | `#C93E1B` (201 62 27) | `#E0532B` |

Signal is the single accent: used for the icon tile and for small highlights, never for body text.
Paper on Signal is 4.4 : 1.

Add to your existing tokens:
```css
:root{--signal:#C93E1B}
@media (prefers-color-scheme:dark){:root{--signal:#E0532B}}
```

## HTML
```html
<link rel="icon" href="/brand/favicon.svg" type="image/svg+xml">
<link rel="icon" href="/brand/favicon.ico" sizes="any">
<link rel="apple-touch-icon" href="/brand/apple-touch-icon.png">
```
Inline next to the `h1` (inherits `--ink`):
```html
<h1><img src="/brand/logo-symbol-auto.svg" alt="" width="32" height="32"> OpenHypergamy</h1>
```

## Rules
- Clear space: one pillar width (34/256 of the mark's height) on every side.
- Minimum size: 16 px with the favicon file; 20 px for the bare symbol.
- Don't rotate, mirror (it must ascend left → right), outline, add gradients or re-colour the two arches differently.

*No trademark search has been done — run one before registering.*
