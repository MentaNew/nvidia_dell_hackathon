# Demo asset license log

Every file in `data/demo/` gets a row BEFORE it is shown to anyone. Rules (Source of Truth §5, §7, §14):
real imagery stays real (no generative edits presented as documentation); simulated material is labelled
`simulated: true` in `manifest.json`; editorial/licensed media is never treated as open data; if the license
is UNKNOWN the asset is research-only until clarified.

License class: PUBLIC DOMAIN | OPEN LICENSE (name it, e.g. CC BY 4.0) | EDITORIAL / LICENSED | RESEARCH ONLY | UNKNOWN

| file | source / publisher | creator | URL | license class | redistribution terms | hackathon presentation OK? | screenshots / clips OK? | attribution required? (text) | real or simulated | notes |
|------|--------------------|---------|-----|---------------|----------------------|----------------------------|-------------------------|------------------------------|-------------------|-------|
| site/images/fema-31790-damaged-bridge.jpg | FEMA Photo Library 31790, via Wikimedia Commons | Patricia Brach (FEMA) | https://commons.wikimedia.org/wiki/File:FEMA_-_31790_-_Aerial_of_floooded_farm_land_and_damaged_bridge_-_PDA_-_Tropical_Storm_Erin.jpg | PUBLIC DOMAIN (PD-USGov-FEMA) | none | yes | yes | courtesy credit shown in the demo | real (20 Aug 2007, Oklahoma) | demo page only; stands in for a drone frame, labelled ARCHIVAL; resized and cropped (black window edge removed) |
| site/images/fema-31833-washed-out-road.jpg | FEMA Photo Library 31833, via Wikimedia Commons | Patricia Brach (FEMA) | https://commons.wikimedia.org/wiki/File:FEMA_-_31833_-_Aerial_of_washed_out_road.jpg | PUBLIC DOMAIN (PD-USGov-FEMA) | none | yes | yes | courtesy credit shown in the demo | real (20 Aug 2007, Caddo County, Oklahoma) | demo page only; labelled ARCHIVAL; resized |
| site/images/fema-35722-road-and-home-lost.jpg | FEMA Photo Library 35722, via Wikimedia Commons | Barry Bahler (FEMA) | https://commons.wikimedia.org/wiki/File:FEMA_-_35722_-_Aerial_of_road_and_home_lost_due_to_flooding_in_Wisconsin.jpg | PUBLIC DOMAIN (PD-USGov-FEMA) | none | yes | yes | courtesy credit shown in the demo | real (14 Jun 2008, Lake Delton, Wisconsin) | demo page only; labelled ARCHIVAL; resized |

Optional `manifest.json` next to the assets (see `manifest.example.json`): per-file `sector`, `simulated`, `note`,
`timestamp` (ISO). Files without an entry are ingested with no sector and `simulated: false`.
