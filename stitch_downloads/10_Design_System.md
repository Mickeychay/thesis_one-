# Design System Document: Clinical Academic Excellence

## 1. Overview & Creative North Star
**The Creative North Star: "The Precise Curator"**

This design system moves away from the sterile, "template-heavy" look of traditional medical software. Instead, it adopts the aesthetic of a high-end academic journal—clean, authoritative, and intellectually spacious. 

We achieve a signature look by breaking the rigid, boxed-in grid. By utilizing **intentional asymmetry**, **layered tonal depth**, and **editorial-grade typography**, we create an environment that feels like a physical research facility: quiet, organized, and premium. The goal is to convey "Research Integrity" not through heavy borders, but through the sophisticated use of whitespace and material layering.

---

## 2. Colors: Tonal Architecture
The palette is built on the intersection of deep clinical authority (Navy/Slate) and innovative vitality (Teal).

### The "No-Line" Rule
**Explicit Instruction:** Prohibit the use of 1px solid borders for sectioning. 
Boundaries must be defined solely through background color shifts. For example, a `surface-container-low` section sitting on a `surface` background creates a natural, soft-edge containment that feels modern and integrated.

### Surface Hierarchy & Nesting
Treat the UI as a series of stacked sheets of fine, semi-transparent paper.
- **Base Level:** `surface` (The foundation).
- **Secondary Level:** `surface-container-low` (For grouping secondary content).
- **Primary Focus:** `surface-container-lowest` (Used for cards and active data entry to provide a "lifted" appearance).

### The "Glass & Gradient" Rule
To elevate the experience, floating elements (modals, dropdowns) should utilize **Glassmorphism**. 
- **Application:** Use semi-transparent `surface` colors (80% opacity) with a `backdrop-blur` of 12px-20px. 
- **Signature Textures:** For Hero sections or primary CTAs, use a subtle linear gradient from `primary` (#000000/Deep Navy) to `primary_container` (#0f1c2c). This adds "soul" and prevents the UI from feeling digitally flat.

---

## 3. Typography: Editorial Authority
We utilize a pairing that balances human-centric warmth with data-driven precision.

*   **Headings (Manrope):** The "Voice." Use `display-lg` to `headline-sm` for structural storytelling. Manrope’s geometric yet open nature provides an approachable academic tone.
*   **Data & Body (Inter):** The "Intelligence." Use `body-md` and `label-md` for all research data, metrics, and tabular information. Inter is optimized for screen readability and high-density information.

**Hierarchy Strategy:** 
- Use **Optical Tracking:** Reduce letter-spacing on `display` styles (-2%) to feel tighter and more editorial.
- Use **Tonal Contrast:** Use `on_surface` for headlines, but `on_surface_variant` for body text to reduce visual fatigue during long reading sessions.

---

## 4. Elevation & Depth: Tonal Layering
Traditional shadows and borders are replaced by a "Layering Principle."

### The Layering Principle
Depth is achieved by "stacking" surface tiers.
- **Inactive/Background:** `surface_container`
- **Active Content Area:** `surface_container_low`
- **Interactive Card:** `surface_container_lowest`

### Ambient Shadows
If a "floating" effect is mandatory (e.g., a research badge or a popover):
- **Spec:** Blur: 32px, Spread: -4px, Opacity: 6% using the `on_surface` color as the shadow tint. This mimics natural, ambient light rather than a harsh digital drop shadow.

### The "Ghost Border" Fallback
If a border is required for accessibility (e.g., input fields), use the **Ghost Border**:
- **Token:** `outline_variant` at **20% opacity**. Never use 100% opaque, high-contrast borders.

---

## 5. Components

### Research Integrity Badges
Used to verify data status.
- **Style:** Small, `label-sm` caps, using `tertiary_container` (Teal) background with `on_tertiary_container` text.
- **Rounding:** `full` (pill shape) to contrast against the `md` rounding of cards.

### Buttons
- **Primary:** `primary` background with `on_primary` text. Use `xl` (0.75rem) rounding. No border.
- **Secondary:** `secondary_container` background. 
- **Tertiary:** No background. Use `primary` text weight 600.

### Input Fields
- **Style:** "Underline-plus" or "Soft Box." Avoid heavy outlines. Use `surface_container_high` as the fill color with a `ghost border` on the bottom edge only.
- **States:** Focus state transitions the bottom border to `tertiary` (Teal).

### Cards & Lists
- **Strict Rule:** Forbid divider lines.
- **Alternative:** Use 24px of vertical white space or a shift from `surface` to `surface_container_low` to denote a new list item. This maintains a "clean-room" academic aesthetic.

### Status Indicators (Muted Palette)
- **Success:** Muted Green (`on_tertiary_fixed_variant`)
- **Warning:** Amber (`on_secondary_fixed_variant`)
- **Critical:** Red (`error`)
- **Execution:** Indicators should be small "pips" or subtle background washes, never high-saturation blocks that distract from the research data.

---

## 6. Do's and Don'ts

### Do
- **Do** use `surface_container_highest` for "Deep Nesting" (e.g., a code snippet or a data sub-grid inside a card).
- **Do** utilize `Manrope` for all numbers in "Big Metric" displays to maintain the brand’s signature look.
- **Do** ensure 4.5:1 contrast ratios by checking `on_surface_variant` against the specific container tier used.

### Don't
- **Don't** use black (#000000) for text. Use `on_surface` (#191c1e) to keep the "Ink on Paper" feel.
- **Don't** use standard 8px rounding. Stick to the specified scale: `md` (0.375rem) for cards and `xl` (0.75rem) for interactive elements like buttons.
- **Don't** use "Alert Red" for anything other than critical data errors. Academic integrity requires a calm, neutral baseline.