---
name: Archival Clarity
colors:
  surface: '#f9f9f9'
  surface-dim: '#dadada'
  surface-bright: '#f9f9f9'
  surface-container-lowest: '#ffffff'
  surface-container-low: '#f3f3f3'
  surface-container: '#eeeeee'
  surface-container-high: '#e8e8e8'
  surface-container-highest: '#e2e2e2'
  on-surface: '#1a1c1c'
  on-surface-variant: '#444748'
  inverse-surface: '#2f3131'
  inverse-on-surface: '#f0f1f1'
  outline: '#747878'
  outline-variant: '#c4c7c7'
  surface-tint: '#5f5e5e'
  primary: '#000000'
  on-primary: '#ffffff'
  primary-container: '#1c1b1b'
  on-primary-container: '#858383'
  inverse-primary: '#c8c6c5'
  secondary: '#5e5e5e'
  on-secondary: '#ffffff'
  secondary-container: '#e3e2e2'
  on-secondary-container: '#646464'
  tertiary: '#000000'
  on-tertiary: '#ffffff'
  tertiary-container: '#1a1c1c'
  on-tertiary-container: '#838484'
  error: '#ba1a1a'
  on-error: '#ffffff'
  error-container: '#ffdad6'
  on-error-container: '#93000a'
  primary-fixed: '#e5e2e1'
  primary-fixed-dim: '#c8c6c5'
  on-primary-fixed: '#1c1b1b'
  on-primary-fixed-variant: '#474646'
  secondary-fixed: '#e3e2e2'
  secondary-fixed-dim: '#c7c6c6'
  on-secondary-fixed: '#1b1c1c'
  on-secondary-fixed-variant: '#464747'
  tertiary-fixed: '#e3e2e2'
  tertiary-fixed-dim: '#c7c6c6'
  on-tertiary-fixed: '#1a1c1c'
  on-tertiary-fixed-variant: '#464747'
  background: '#f9f9f9'
  on-background: '#1a1c1c'
  surface-variant: '#e2e2e2'
typography:
  headline-lg:
    fontFamily: Inter
    fontSize: 32px
    fontWeight: '500'
    lineHeight: '1.2'
    letterSpacing: -0.02em
  headline-lg-mobile:
    fontFamily: Inter
    fontSize: 24px
    fontWeight: '500'
    lineHeight: '1.2'
    letterSpacing: -0.01em
  headline-md:
    fontFamily: Inter
    fontSize: 20px
    fontWeight: '500'
    lineHeight: '1.4'
  body-lg:
    fontFamily: Inter
    fontSize: 16px
    fontWeight: '400'
    lineHeight: '1.6'
  body-md:
    fontFamily: Inter
    fontSize: 14px
    fontWeight: '400'
    lineHeight: '1.6'
  label-md:
    fontFamily: Inter
    fontSize: 12px
    fontWeight: '500'
    lineHeight: '1'
    letterSpacing: 0.02em
rounded:
  sm: 0.125rem
  DEFAULT: 0.25rem
  md: 0.375rem
  lg: 0.5rem
  xl: 0.75rem
  full: 9999px
spacing:
  base: 8px
  xs: 4px
  sm: 12px
  md: 24px
  lg: 48px
  xl: 80px
  gutter: 20px
  margin: 24px
---

## Brand & Style
This design system is anchored in a "browse-first" philosophy, prioritizing content discovery and intellectual calm over aggressive calls to action. The aesthetic is heavily influenced by archival tools and contemporary digital galleries, emphasizing utility through a quiet, minimalist lens. 

The emotional response should be one of clarity and focus. By stripping away heavy gradients, drop shadows, and vibrant accent colors, the interface recedes to let the user's media and connections take center stage. The style is strictly **Minimalist**, utilizing a limited color palette, intentional whitespace, and a high-quality typographic foundation to create a sophisticated, modular environment.

## Colors
The palette is monochromatic and functional, designed to provide maximum legibility without visual fatigue. 

- **Primary Text (#111111):** Used for headlines and primary body copy to ensure high contrast.
- **Secondary Text (#888888):** Applied to metadata, descriptions, and less critical information.
- **Tertiary Text (#AAAAAA):** Reserved for captions, timestamps, and placeholder states.
- **Surfaces:** The interface relies on two core neutrals—`#FAFAFA` for the primary canvas and `#F5F5F5` for secondary sections or grouped content.
- **Borders:** A consistent `1px` solid border in `#E8E8E8` defines the structure, replacing shadows for element separation.

## Typography
The system uses **Inter** for all roles to maintain a systematic, utilitarian feel. The hierarchy is intentionally "quiet," relying more on subtle changes in color and spacing than dramatic shifts in scale or weight.

A generous line-height of `1.6` is applied to body text to ensure comfortable long-form reading and to enhance the sense of "air" within the layout. Headlines remain medium-weighted to provide structure without feeling heavy or intrusive.

## Layout & Spacing
The layout follows a **block-based philosophy**, where content is contained within clearly defined modules. 

- **Grid System:** Use a fluid 12-column grid for desktop views with a `20px` gutter. 
- **Masonry Layout:** For discovery feeds, a masonry-style arrangement is preferred, allowing blocks of varying heights to sit flush with a consistent horizontal gap.
- **Rhythm:** Spacing follows an 8px scale. Generous padding (`24px` to `48px`) is used between sections to maintain the minimalist aesthetic.
- **Mobile Adaptivity:** On mobile devices, margins reduce to `16px` and the grid collapses to a single or double-column masonry view depending on the content density.

## Elevation & Depth
Depth is created through **tonal layering and borders** rather than shadows. 

1. **Flat Surface:** The base layer is `#FAFAFA`.
2. **Defined Containers:** Blocks and cards use the `1px solid #E8E8E8` border to distinguish themselves from the background.
3. **Interactive Depth:** On hover, elements do not rise or shadow; instead, they receive a subtle background fill change to `#F0F0F0`.
4. **Modals/Overlays:** When an overlay is necessary, a semi-transparent white backdrop (`rgba(250, 250, 250, 0.8)`) is used with a backdrop-blur of `4px` to maintain context without visual clutter.

## Shapes
The shape language is primarily architectural and sharp. 

A "Soft" roundedness (`4px`) is the default for most containers and input fields to prevent the UI from feeling overly harsh or clinical. However, for specific interactive elements like "pills" or tags, a full `rounded-xl` or pill-shape is used to distinguish them from content blocks.

## Components

### Buttons
- **Ghost Buttons:** Transparent background with the standard `1px #E8E8E8` border. Transitions to a `#F0F0F0` background on hover.
- **Text Buttons:** Simple `#111111` text with no border or background. Underline appears only on hover.
- **Pill Buttons:** Solid `#111111` background with white text, using `rounded-xl` for a soft, distinct interactive shape.

### Masonry Blocks
The core unit of the design system. These are white containers with a `1px` border. Images within blocks should be top-aligned with metadata (title, source, date) placed in a footer section below a horizontal separator.

### Input Fields
Minimalist underlines or full-bordered boxes using the `secondary` text color for labels. Focus states switch the border color from `#E8E8E8` to `#111111`.

### Lists
Clean, horizontal rows separated by `1px` borders. High internal padding (`16px`) to ensure touch targets are accessible and the interface remains "airy."

### Chips & Tags
Small, pill-shaped elements with a `#F5F5F5` background and `#888888` text. No borders, used for categorization without drawing excessive attention.