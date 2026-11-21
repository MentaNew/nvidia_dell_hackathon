# site/: the public demo page

Published to GitHub Pages by `.github/workflows/pages.yml` at
https://mentanew.github.io/nvidia_dell_hackathon/

- `index.html`: the landing page (hand-written, no build step).
- `demo.js`, `demo.css`: the in-browser recreation of the command-post app, built from
  El Mehdi El Kasmi's portfolio (`scripts/export-rescuebase-page.mjs`). The app logic (inbox worker,
  deduplication, provenance labels, review states, keyword retrieval, SITREP) is ported from `backend/`;
  the extracted events are recorded, and the inputs are the fixtures from `tests/test_smoke.py`.
