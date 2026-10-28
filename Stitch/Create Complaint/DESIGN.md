---
name: Enterprise Service System
colors:
  surface: '#faf9ff'
  surface-dim: '#ccdaff'
  surface-bright: '#faf9ff'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f1f3ff'
  surface-container: '#e9edff'
  surface-container-high: '#e1e8ff'
  surface-container-highest: '#d8e2ff'
  on-surface: '#051a3e'
  on-surface-variant: '#424654'
  inverse-surface: '#1d3054'
  inverse-on-surface: '#edf0ff'
  outline: '#727786'
  outline-variant: '#c2c6d7'
  surface-tint: '#0058ca'
  primary: '#004fb6'
  on-primary: '#ffffff'
  primary-container: '#0c66e4'
  on-primary-container: '#ecefff'
  inverse-primary: '#b0c6ff'
  secondary: '#006c47'
  on-secondary: '#ffffff'
  secondary-container: '#97f6c3'
  on-secondary-container: '#00734b'
  tertiary: '#a61b18'
  on-tertiary: '#ffffff'
  tertiary-container: '#c9362e'
  on-tertiary-container: '#ffece9'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#d9e2ff'
  primary-fixed-dim: '#b0c6ff'
  on-primary-fixed: '#001945'
  on-primary-fixed-variant: '#00429b'
  secondary-fixed: '#97f6c3'
  secondary-fixed-dim: '#7bd9a8'
  on-secondary-fixed: '#002112'
  on-secondary-fixed-variant: '#005234'
  tertiary-fixed: '#ffdad5'
  tertiary-fixed-dim: '#ffb4aa'
  on-tertiary-fixed: '#410001'
  on-tertiary-fixed-variant: '#91070c'
  background: '#faf9ff'
  on-background: '#051a3e'
  surface-variant: '#d8e2ff'
typography:
  headline-xl:
    fontFamily: Inter
    fontSize: 28px
    fontWeight: '600'
    lineHeight: 34px
    letterSpacing: -0.01em
  headline-lg:
    fontFamily: Inter
    fontSize: 22px
    fontWeight: '600'
    lineHeight: 28px
    letterSpacing: -0.008em
  headline-sm:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '600'
    lineHeight: 22px
  title-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '600'
    lineHeight: 20px
  title-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 16px
    letterSpacing: 0.02em
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: 20px
  body-sm:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
  label-md:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '600'
    lineHeight: 16px
  label-sm:
    fontFamily: Inter
    fontSize: 11px
    fontWeight: '700'
    lineHeight: 14px
    letterSpacing: 0.04em
  code-sm:
    fontFamily: JetBrains Mono
    fontSize: 12px
    fontWeight: '400'
    lineHeight: 16px
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  gutter: 1rem
  gutter-desktop: 1.5rem
  margin: 1rem
  margin-desktop: 2rem
  space-xs: 0.25rem
  space-sm: 0.5rem
  space-md: 0.75rem
  space-lg: 1rem
  space-xl: 1.5rem
---

## Brand & Style

The design system embodies the operational clarity, technical precision, and structured efficiency of modern enterprise workflows (inspired by the Atlassian Design System, Jira Service Management, and Confluence). Designed for service desk specialists, field engineers, and operations managers, the interface prioritizes immediate clarity, systematic density, and low cognitive overhead under high-volume triage conditions.

The visual style follows **Corporate / Modern** principles:
- **Pragmatic Utilitarianism:** Form follows functional taxonomy. Surfaces remain neutral, allowing issue states, severities, and operational metadata to take visual priority.
- **Systematic Structure:** Strict adherence to rectangular content containers, hairline dividers, structured field-value grids, and clearly isolated utility zones.
- **Calibrated Feedback:** Color is deployed strictly for semantic signaling (lozenge status badges, interactive triggers, operational alerts), preventing visual noise and fatigue.

## Colors

The color palette mirrors the Atlassian refreshed foundation token structure, balancing clean slate neutrals with distinct semantic indicators:

- **Primary (`#0C66E4`):** The signature interactive blue used for active tab underlines, primary buttons, links, focused form strokes, and open ticket indicators.
- **Secondary (`#1F845A`):** Operational success and resolution green used for action completion, resolved status badges, and positive toast messages.
- **Tertiary / Danger (`#E2483D`):** Destructive actions, SLA breaches, error validation states, and critical blockers.
- **Warning / In-Progress (`#B35F00` / `#FFAB00`):** Amber tone reserved for items awaiting review, reopened issues, and active transitions.
- **Neutrals:**
  - Base canvas: `#FAFBFC`
  - Subtle cards and side panels: `#F4F5F7`
  - Hover states: `#EBECF0`
  - Borders and dividers: `#DFE1E6`
  - Heavy borders and inputs: `#C1C7D0`
  - Body text: `#172B4D`
  - Secondary text / field labels: `#6B778C`
  - Primary text / headers: `#091E42`

## Typography

The typography leverages **Inter** for clean legibility across complex multi-column data views, key-value pairs, and nested dialog sheets.

- **Scale & Weight:** Headings use semi-bold (`600`) weights to establish hierarchy without overpowering operational content. Labels and lozenges use `11px` to `12px` upper/title case with slight tracking (`+0.02em` to `+0.04em`) to ensure legibility in high-density queues.
- **Key-Value Pairs:** Labels are consistently set in `label-sm` (`#6B778C`), while data values are set in `body-md` (`#172B4D`) or interactive link styles (`#0C66E4`).
- **Ticket Keys & Codes:** IDs (e.g., `CMP-13`) utilize precise character proportions to remain recognizable at a glance.

## Layout & Spacing

The layout employs a responsive split-pane master-detail pattern characteristic of enterprise issue trackers:

- **Desktop (1280px+):** Fixed global top utility navigation (48px height), followed by a dual-pane work area. The left list pane spans 320px–360px with dedicated search and filter ribbons. The right detail panel occupies the remaining fluid space with an internal 2-column or 3-column field metadata grid.
- **Tablet (768px - 1024px):** Collapsible split view where the list collapses into a sliding drawer or full-width list that transitions to the detail view upon ticket selection.
- **Mobile (< 768px):** Single-column stacked layout. Modals reflow into bottom sheets or full-screen overlays with fixed bottom action footers.
- **Rhythm:** An 8px base grid rhythm governs component dimensions, with 4px sub-grid padding for tight components (inputs, lozenges, compact button sets).

## Elevation & Depth

Visual hierarchy uses crisp hairline borders paired with subtle, low-opacity ambient shadows:

- **Base / Flat (0dp):** Canvas background (`#FAFBFC`), embedded panels, and list rows maintain flat elevation separated by `#DFE1E6` borders.
- **Card / Surface (1dp):** Focused detail containers and card modules use `#FFFFFF` with a 1px border (`#DFE1E6`) and an ambient shadow: `0 1px 1px rgba(9, 30, 66, 0.25), 0 0 1px 1px rgba(9, 30, 66, 0.13)`.
- **Raised / Popover (2dp):** Dropdowns, filter menus, and action overflow menus use `0 4px 8px -2px rgba(9, 30, 66, 0.25), 0 0 1px rgba(9, 30, 66, 0.31)`.
- **Overlay / Modal (3dp):** Centered modal sheets and drawer panels use `#FFFFFF` resting over a `rgba(9, 30, 66, 0.54)` backdrop, casting an elevation shadow of `0 8px 16px -4px rgba(9, 30, 66, 0.25), 0 0 1px rgba(9, 30, 66, 0.31)`.

## Shapes

The design system maintains Atlassian-style compact geometry with **Soft** radius foundations (`roundedness: 1`):

- **Interactive Controls (3px / 0.25rem):** Buttons, inputs, filter dropdowns, and tabs have tight 3px–4px corners, reinforcing a structured software tool aesthetic.
- **Lozenges & Badges (3px):** Compact rectangular status badges with 3px border-radius, maintaining a distinct shape separate from rounded pill tags.
- **Containers & Modals (4px - 8px):** Modal dialogs, floating banners, and major cards use 6px–8px radius (`0.5rem`) for subtle structural framing.
- **Avatars (Circular):** User profile indicators, assignees, and reporter badges remain 100% circular (full radius) to differentiate human actors from rectangular issue data.

## Components

### Buttons
- **Primary:** Solid `#0C66E4` background, white text, 3px border radius, font weight 500, padding `8px 16px`. Active: `#0052CC`.
- **Success / Action Primary:** Solid `#1F845A` background, white text (e.g., "Resolve complaint", "Submit complaint"). Hover: `#216E4E`.
- **Subtle / Secondary:** `#091E420F` (`rgba(9, 30, 66, 0.06)`) background, `#172B4D` text. Hover: `#091E4214`.
- **Subtle Link / Ghost:** Transparent background, `#0C66E4` or `#42526E` text, underline on hover.

### Status Lozenges (Badges)
- **Subtle Open / New:** Light blue background (`#E9F2FF`), text `#0C66E4`, border `1px solid transparent`.
- **Subtle In-Progress / Needs Details:** Light yellow background (`#FFF7D6`), text `#7F5F01`.
- **Subtle Resolved / Closed:** Light green background (`#DCFCE7` / `#E3FCEF`), text `#216E4E`.
- **Subtle Reopened / Warning:** Soft amber background (`#FFE380`), text `#7A4B04`.
- **Typography:** `label-sm` font, uppercase or capitalized, 2px horizontal padding, 3px corner radius.

### Form Inputs & Selects
- **Text & Select Controls:** 36px standard height, `#FAFBFC` base background, 1px border (`#DFE1E6`), 3px border radius.
- **Focus State:** White background, 2px outer border in `#0C66E4`, zero outline offset.
- **Labels:** Semibold 12px `#6B778C`, 4px bottom margin, red asterisk (`#AE2E24`) for required fields.

### Navigation Tabs
- Horizontal track with transparent background.
- Inactive item: `#42526E` text, 8px padding horizontal.
- Active item: `#0C66E4` text, with a 2px solid `#0C66E4` bottom underline indicator flush with the track divider.

### Modals & Dialog Sheets
- **Header:** 20px padding, bold title, top-right 32px close button with subtle hover state.
- **Body:** 20px padding with 16px field gap spacing.
- **Footer:** Fixed bottom bar, `#FAFBFC` background, hairline top border (`#DFE1E6`), right-aligned primary and cancel buttons.

### Key-Value Metadata Grid
- Structured 2-column or 4-column attribute sections (e.g., National ID, Phone, Branch, Reported Date).
- Label above value: 11px uppercase gray label (`#6B778C`) with 14px dark gray value (`#172B4D`).