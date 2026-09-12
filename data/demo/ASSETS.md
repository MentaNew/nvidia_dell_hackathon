# Demo asset license log

Every file in `data/demo/` gets a row BEFORE it is shown to anyone. Rules (Source of Truth §5, §7, §14):
real imagery stays real (no generative edits presented as documentation); simulated material is labelled
`simulated: true` in `manifest.json`; editorial/licensed media is never treated as open data; if the license
is UNKNOWN the asset is research-only until clarified.

License class: PUBLIC DOMAIN | OPEN LICENSE (name it, e.g. CC BY 4.0) | EDITORIAL / LICENSED | RESEARCH ONLY | UNKNOWN

| file | source / publisher | creator | URL | license class | redistribution terms | hackathon presentation OK? | screenshots / clips OK? | attribution required? (text) | real or simulated | notes |
|------|--------------------|---------|-----|---------------|----------------------|----------------------------|-------------------------|------------------------------|-------------------|-------|
|      |                    |         |     |               |                      |                            |                         |                              |                   |       |

Optional `manifest.json` next to the assets (see `manifest.example.json`): per-file `sector`, `simulated`, `note`,
`timestamp` (ISO). Files without an entry are ingested with no sector and `simulated: false`.
