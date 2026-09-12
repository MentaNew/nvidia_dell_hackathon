
# RESCUEBASE — SOURCE OF TRUTH

Version: Pre-Cornell Hackathon
Status: DEFAULT BUILD ROUTE
Owner: Franco
Event: Dell × NVIDIA BuilderBase — Cornell
Build window: ~12-hour hackathon

======================================================================
1. EXECUTIVE DECISION
======================================================================

DEFAULT PROJECT:
RescueBase

WORKING ONE-LINER:
“When the network goes down, the intelligence layer shouldn’t disappear with it.”

WORKING PRODUCT DESCRIPTION:
RescueBase is a local multimodal incident-intelligence appliance for professional disaster-response teams.

A GB10 at an incident command post processes imagery, video, responder audio, maps, documents, and other local information without requiring the public internet.

The system builds an evidence-linked incident memory and helps humans reconstruct what happened, retrieve relevant information, identify candidate areas/events requiring attention, and produce low-bandwidth operational summaries.

HUMANS MAKE OPERATIONAL DECISIONS.

RescueBase does NOT autonomously:
- command rescuers
- declare victims found
- dispatch teams
- assign medical priority
- alter vehicles/drones
- make life-safety decisions without human review

======================================================================
2. WHY THIS PROJECT
======================================================================

RescueBase is currently preferred over the CVICU/healthcare route because:

1. Offline/local necessity is immediately understandable.
2. GB10 can be materially central rather than incidental.
3. Multimodal processing has an obvious operational purpose.
4. The physical-world demo can be visually compelling.
5. “Pull the network and it keeps working” creates a memorable demo moment.
6. Disaster-response imagery/data makes the problem concrete.
7. One appliance can support an incident-command organization rather than one consumer.
8. The system can demonstrate local vision + speech + retrieval + reasoning + memory.

The healthcare/CVICU research remains valuable but is PARKED.

Do not reopen the healthcare route tomorrow unless RescueBase fails explicit kill criteria.

======================================================================
3. CORE THESIS
======================================================================

The cloud is extremely useful when connectivity is healthy.

Disaster environments can have:

- damaged cellular infrastructure
- disrupted fiber/backhaul
- damaged power infrastructure
- constrained satellite bandwidth
- geographically dispersed teams
- high-volume imagery/video
- rapidly changing terrain
- fragmented observations
- limited ability to continuously upload raw media

RescueBase does NOT claim responders become completely disconnected.

Professional teams may have:

- satellite communications
- radio
- Starlink / VSAT
- deployable LTE
- mesh networks
- portable networking systems

Our thesis is narrower:

Even when a narrow communications path survives, it may be undesirable or impossible to continuously ship every high-bandwidth sensor/media stream to cloud AI.

LOCAL COMPUTE ≠ NO COMMUNICATION.

A local GB10 can perform high-bandwidth intelligence near the source while scarce communications links are reserved for the information humans actually need to transmit.

======================================================================
4. DESIGN PRINCIPLES
======================================================================

A. LOCAL-FIRST
Core inference and incident memory must continue without external internet.

B. EVIDENCE BEFORE ASSERTION
Outputs should point to:
- source
- timestamp
- media/document
- provenance
- verification status

C. ATTENTION FIREWALL
AI should not constantly interrupt operators.

Many observations
→ candidate events
→ evidence aggregation
→ human review
→ rare escalation

D. HUMAN AUTHORITY INCREASES WITH STAKES
AI retrieves, correlates, summarizes, and highlights.
Humans decide.

E. EPISODIC MEMORY
Remember what happened across time and modalities, not merely what was said in chat.

F. FAIL DOWNWARD
Cloud available → useful.
Cloud unavailable → local system remains useful.
Local AI unavailable → humans retain original data/workflows.

G. MINIMUM MODEL SET
Do not use ten models merely because ten are available.

Every model included in the demo must have a clear job.

======================================================================
5. PRIMARY DEMO SCENARIO
======================================================================

Use REAL Nepal disaster-response material where legal and practical.

The exact disaster dates, events, locations, and claims MUST be independently verified before appearing in a deck.

Preferred material:

- real aftermath photography
- aerial/drone video
- satellite imagery
- before/after imagery
- maps
- publicly available official rescue imagery
- public/open disaster datasets

AI can add:

- circles
- regions of interest
- labels
- captions
- event cards
- timestamps
- source links
- confidence/verification labels

DO NOT generatively modify a real documentary image and then present the altered image as factual documentation.

If imagery is synthesized or materially modified, label it clearly:
“Simulation”
“Illustrative visualization”
or equivalent.

Real imagery should remain real.

======================================================================
6. IDEAL DEMO NARRATIVE
======================================================================

ACT 1 — REALITY

Show a real disaster scene.

Establish:
- damaged infrastructure
- difficult terrain
- many incoming observations
- constrained communications

ACT 2 — LOCAL INGESTION

Feed RescueBase:
- aerial/drone image or video
- field image
- responder audio or simulated responder-radio sample
- map/satellite image
- local document/manual

ACT 3 — MULTIMODAL UNDERSTANDING

Local models create structured observations.

Example categories:
- blocked access
- structural damage candidate
- terrain change
- observed vehicle/person/object
- infrastructure condition
- reported location/event
- uncertainty

Do not claim victim detection unless actually validated.

ACT 4 — INCIDENT MEMORY

Observations become events with:
- timestamp
- source
- location if available
- provenance
- confidence
- verification state
- relationships to other events

ACT 5 — COMMAND QUERY

Example:

“What materially changed in Sector 4?”

or

“What unresolved observations should a commander review?”

The response should link back to evidence.

ACT 6 — NETWORK FAILURE

Disconnect external internet.

Prominent UI:

EXTERNAL NETWORK: OFFLINE
LOCAL RESCUEBASE: OPERATIONAL

Ask another question or ingest another local asset.

System still works.

ACT 7 — CLOSE

“When the cloud goes dark, RescueBase stays on.”

======================================================================
7. DEMO TRUTHFULNESS
======================================================================

We prefer a smaller REAL system over a larger fake system.

Never fake model inference and imply it occurred live.

If something is simulated:
label it.

Examples:

SIMULATED RESPONDER RADIO
SIMULATED DRONE TELEMETRY
DEMO INCIDENT

Using real disaster imagery with simulated operational metadata is acceptable if clearly labeled.

======================================================================
8. TECHNICAL ARCHITECTURE
======================================================================

Target conceptual architecture:

INPUTS
│
├── image / aerial photo
├── drone video
├── audio / radio
├── map / satellite image
├── local documents
└── optional structured telemetry
        │
        ▼
LOCAL INFERENCE — GB10
│
├── VLM
├── speech-to-text
├── reasoning
├── embeddings / retrieval
└── optional physical/video reasoning
        │
        ▼
STRUCTURED EVENT LAYER
        │
        ▼
LOCAL INCIDENT MEMORY
MongoDB
        │
        ▼
BOUNDED AGENT LAYER
OpenClaw / NemoClaw / OpenShell as required/useful
        │
        ▼
COMMAND UI
│
├── map / spatial context
├── evidence/media panel
├── timeline
├── transcript/events
├── command query
└── network/local-status indicator

======================================================================
9. EVENT OBJECT
======================================================================

Preferred conceptual event structure:

event_id
timestamp
source_type
source_id
source_uri/local_path
location
observation
event_type
confidence
verification_state
model_name
related_event_ids
evidence_refs
human_notes
created_at

verification_state should support states such as:

UNVERIFIED
AI_CANDIDATE
HUMAN_CONFIRMED
HUMAN_REJECTED
UNKNOWN

Do not collapse uncertainty into certainty.

======================================================================
10. LOCAL MODEL ARSENAL
======================================================================

External SSD:
GBeast10

Windows source location:
D:\GB10_ARSENAL

Actual Linux mount path on the GB10 is UNKNOWN until tomorrow.

DO NOT hardcode the Windows path into production code.

On GB10 first run:

lsblk
df -h

Then resolve the SSD mount path.

DOWNLOADED MODELS:

PRIMARY REASONING
NVIDIA Nemotron 3 Nano 30B A3B NVFP4
~18.03 GB
models/reasoning/nemotron-3-nano-30b-a3b-nvfp4

GENERAL / BACKUP MULTIMODAL
Qwen 3.5 35B A3B FP8
~34.92 GB
models/reasoning/qwen3.5-35b-a3b-fp8

CODE / TOOL MODEL
Qwen3 Coder 30B A3B Instruct FP8
~32.52 GB
models/coding/qwen3-coder-30b-a3b-instruct-fp8

PRIMARY VISION-LANGUAGE MODEL
Qwen3-VL 30B A3B Instruct FP8
~30.05 GB
models/vision/qwen3-vl-30b-a3b-instruct-fp8

PHYSICAL / VIDEO REASONING
NVIDIA Cosmos Reason2 2B
~4.55 GB
models/vision/cosmos-reason2-2b

SPEECH-TO-TEXT
Whisper Large v3 Turbo
~1.51 GB
models/speech/whisper-large-v3-turbo

FAST TTS
Kokoro 82M
~0.34 GB
models/speech/kokoro-82m

EXPRESSIVE TTS
Sesame CSM 1B
~18.24 GB including multiple checkpoint formats
models/speech/csm-1b

EMBEDDINGS
NVIDIA Nemotron Embed 1B NVFP4
~0.97 GB
models/retrieval/nemotron-3-embed-1b-nvfp4

HEALTHCARE FALLBACK
MedGemma 4B IT
~8.05 GB
models/healthcare/medgemma-4b-it

SSD FREE SPACE AFTER DOWNLOAD:
~327 GB

======================================================================
11. MODEL ROUTING FOR RESCUEBASE
======================================================================

DO NOT LOAD EVERYTHING.

Preferred app stack:

Qwen3-VL
→ image / visual understanding

Whisper
→ responder audio transcription

Nemotron 3 Nano
→ reasoning / event synthesis / agent brain

Nemotron Embed
→ retrieval

MongoDB
→ incident state

Optional:
Cosmos Reason2
→ video / physical-world reasoning IF it materially improves demo

Optional:
Kokoro
→ spoken output only if voice clearly improves experience

Development/fallback:
Qwen3 Coder
Qwen 3.5

Currently unnecessary:
MedGemma
CSM

======================================================================
12. GB10 NECESSITY
======================================================================

DO NOT SAY:
“We need GB10 because local AI is cool.”

Preferred argument:

A disaster command post may receive high-bandwidth local sensor/media streams while external connectivity is degraded or bandwidth-constrained.

Instead of continuously transmitting raw video/images/audio to cloud inference, RescueBase performs multimodal processing locally.

The GB10 becomes a shared local intelligence appliance for the incident site.

GB10 necessity must still be honestly tested tomorrow.

Questions:

Could a laptop do the demonstrated workload?
Could a Jetson do it?
Could a cheap edge box do it?
Are we demonstrating enough concurrent/high-bandwidth/local inference to justify GB10?

If not, improve the workload honestly.
Do not manufacture compute requirements.

======================================================================
13. USER EXPERIENCE
======================================================================

DO NOT build a sci-fi military HUD.

Target UI:

TOP BAR
RescueBase
Incident name
LOCAL / NETWORK status

MAIN LEFT
Map or spatial context

MAIN CENTER
Selected video/image/feed

RIGHT
Evidence / candidate-event cards

BOTTOM OR SIDE
Incident timeline

COMMAND BAR
Natural-language incident query

Potential visual language:
clean
operational
high contrast
few colors
large readable type
obvious provenance
obvious uncertainty

No tiny dashboard clutter.

======================================================================
14. REAL MEDIA RULES
======================================================================

Real Nepal imagery should be used to invoke emotion and ground the product.

For every asset, record:

source
creator/publisher
URL
license
redistribution terms
whether hackathon presentation use is permitted
whether screenshots/clips are allowed
whether attribution is required

Classes:

PUBLIC DOMAIN
OPEN LICENSE
EDITORIAL / LICENSED
RESEARCH ONLY
UNKNOWN

Never silently treat editorial media as open-license data.

If licensing is uncertain:
use it only as research/reference until clarified.

======================================================================
15. LIKELY BUYERS — HYPOTHESES, NOT FACTS
======================================================================

Potential users/buyers:

- professional SAR organizations
- emergency management
- fire/rescue
- utilities
- hydropower operators
- energy companies
- mining operations
- industrial emergency-response teams
- disaster-response NGOs
- defense / civil defense
- insurers / catastrophe response

Do not claim validated demand.

Important research question:

A private infrastructure/industrial buyer may be a faster initial customer than government procurement.

This remains OPEN.

======================================================================
16. CURRENT COMPETITIVE QUESTION
======================================================================

We must investigate whether existing systems already solve most of this.

Research:

ATAK
Esri emergency management
Palantir
Motorola public safety
Everbridge
Sahana
DJI enterprise platforms
Skydio
offline GIS
incident-command software
deployable communications systems

The correct competitive question:

“What already solves 80% of RescueBase?”

If something does:
do not hide it.

Find the missing 20%.

======================================================================
17. SAFETY REQUIREMENTS
======================================================================

Major risks:

false victim detection
incorrect geolocation
hallucinated event
stale observation
duplicate event
model overconfidence
incorrect prioritization
sensor failure
operator over-trust

Safeguards:

source provenance
timestamps
verification state
evidence links
UNKNOWN state
human confirmation
no automatic dispatch
no autonomous rescue command
no autonomous medical decisions
clear model-generated labeling

======================================================================
18. HACKATHON BUILD PRIORITIES
======================================================================

PRIORITY 1:
Working vertical slice.

input
→ local model
→ structured event
→ Mongo
→ UI

PRIORITY 2:
Second modality.

PRIORITY 3:
Evidence-linked incident query.

PRIORITY 4:
Offline demo.

PRIORITY 5:
Required event-stack integration.

PRIORITY 6:
Visual polish.

Everything else is optional.

======================================================================
19. BUILD CLOCK
======================================================================

0:00–0:45
Inspect:
- exact challenge
- judging rubric
- provided stack
- team
- GB10 environment
- available datasets/hardware

Decision checkpoint at ~45 minutes.

If RescueBase still fits:
FREEZE PROJECT.

0:45–2:00
Environment + one model + backend + UI skeleton.

2:00–4:00
FIRST VERTICAL SLICE MUST WORK.

4:00–6:00
Second modality + incident memory.

6:00–8:00
Agent/runtime integration + offline path.

8:00–9:30
Demo reliability.

9:30–10:30
UI/deck polish.

10:30
FEATURE FREEZE.

10:30–12:00
Pitch practice, failure testing, backups.

======================================================================
20. DEMO FAILURE PLAN
======================================================================

Every major live operation should have:

A. live path
B. cached/local fallback
C. screenshot/video fallback

If a 30B model crashes:
fallback to another downloaded local model.

If live video fails:
use preloaded local media.

If map API fails:
use local/static map asset.

If internet dies early:
that should NOT destroy the demo.

The demo must not depend on external APIs.

======================================================================
21. CURRENT VALIDATION STATUS
======================================================================

VERIFIED:
- local model arsenal is downloaded to SSD
- core model weight shards were inspected
- enough disk space remains
- concept can be constructed without cloud inference

INFERRED:
- local multimodal synthesis may reduce information burden during disconnected operations
- local incident memory may be useful
- bandwidth preservation may be valuable

SPECULATIVE:
- buyer willingness to pay
- exact procurement path
- operational superiority to existing systems
- exact GB10 workload requirement
- responder demand for this UI
- measurable response-time improvement

Do not convert SPECULATIVE into VERIFIED.

======================================================================
22. MUSE RESEARCH
======================================================================

A separate Meta Muse research council is investigating:

- Nepal case study
- responder workflows
- communications systems
- datasets
- competitors
- buyers
- GB10 necessity
- kill criteria

Its output is NOT automatically truth.

Any Muse finding must be classified as:
VERIFIED
INFERRED
SPECULATIVE

before entering this source of truth.

======================================================================
23. KILL CRITERIA
======================================================================

Seriously reconsider RescueBase if tomorrow we discover:

1. Event prompt strongly favors a different domain/problem.
2. Required sponsor stack cannot reasonably fit this architecture.
3. Existing disaster-command software already performs the exact workflow extremely well.
4. The demo's “local advantage” can be reproduced trivially on a basic laptop.
5. Useful real/public data cannot be legally or practically obtained.
6. The product requires fake outputs to look compelling.
7. We cannot produce a vertical slice by Hour 4.
8. GB10 becomes decorative instead of necessary.

======================================================================
24. FROZEN DECISIONS
======================================================================

Unless strong new evidence appears:

- RescueBase is default route.
- local/offline operation is central.
- human authority remains central.
- evidence/provenance is visible.
- no autonomous life-safety decisions.
- no cloud dependency in core demo.
- use minimum necessary model set.
- real disaster material preferred over synthetic spectacle.
- UI stays operational, not sci-fi.
- demo culminates in network-loss resilience.

======================================================================
25. OPEN DECISIONS
======================================================================

Tomorrow determine:

- precise buyer wedge
- exact Nepal assets
- exact dataset licenses
- whether Cosmos materially helps
- exact map implementation
- exact sponsor integration
- whether video is live or preloaded
- exact OpenClaw/NemoClaw/OpenShell action
- final product subtitle
- final pricing/business model
- whether any physical drone hardware is available

======================================================================
26. NORTH STAR
======================================================================

Do not win by showing the most AI.

Win by showing a real operational problem for which LOCAL AI materially changes what remains possible when infrastructure fails.

The models are machinery.

The product is RescueBase.