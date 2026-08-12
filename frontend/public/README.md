# Static assets

Everything in this folder is copied verbatim to the web root at build time, so
a file here called `x.png` is served at `/x.png`. Nothing needs importing or
rebuilding a component to change these — replace the file and rebuild the
frontend image.

Two files are expected:

| File | Size | Used for |
| --- | --- | --- |
| `its-pico.ico` | 16×16 and/or 32×32 | Browser tab favicon, referenced from `index.html` |
| `its-pico.bmp` | 64×64 | Application logo, first element in the toolbar |

Both are **optional**. If either is missing the application still works: the
browser falls back to its default tab icon, and the toolbar logo hides itself
rather than showing a broken-image placeholder.

The BMP is displayed at `--logo-size` (20px by default, set in `styles.css`),
scaled down from 64×64 so it stays sharp on a high-DPI screen. To show it
larger, change that one variable — the toolbar grows to fit.
