# Dashboard — Claude Instructions

## Architecture
Single-page app: `index.html`, `style.css`, `dashboard.js`, `music-player.js`, `playlist.js`.
No build step. No frameworks. Vanilla JS + CSS.

## Layout
The scene is a pixel-art background (`mission-control-bg.png`) at 1672×941.
All UI elements are absolutely positioned over it using percentage coordinates.
Upper screens show counters. Lower desk slots show animated robots working on runs.

## Key patterns
- Icons are inline SVGs in an `ICONS` map (`dashboard.js`). `createIconEl()` wraps them.
- Robots use `assets/dino-bot.png`. Referenced in `index.html` (idle) and `dashboard.js` (active).
- Beam animations fly from desk positions to counter positions using CSS transitions.
- Counter types: `sweep`, `mergecheck`, `review`, `fix`, `merge`, `fail`.
- CSS uses `currentColor` for SVG fills — color is set on the wrapper, not the SVG.

## Branding panel
`#branding-panel` is an `<a>` overlay covering a static background screen.
Positioned with `left: 28.5%; top: 21%`. Links to the GitHub repo.

## Styling conventions
- All sizes use `clamp()` for responsive scaling.
- Colors use CSS custom properties (`--color-green`, `--color-red`, `--color-magenta`).
- Pixel art images use `image-rendering: pixelated`.
- Panel backgrounds use `--color-bg-panel` (#000422).
