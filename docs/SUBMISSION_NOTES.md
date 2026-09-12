# Submission notes (facts only; TODO = only the team can fill it)

1. **What we built (<5 sentences).** RescueBase is an always-on local incident log for infrastructure site
   operations. Drone frames and radio recordings dropped into a local inbox are analysed and transcribed on the GB10,
   become source-linked draft events on a shared timeline, and are confirmed or rejected by people. Every event
   carries its evidence, capture vs ingestion time, provenance label (replay / exercise / satellite), model identity
   and review state. A local OpenClaw agent writes source-linked incident updates from the log. When the external
   internet is cut, ingestion, inference, retrieval and review continue unchanged.
2. **GitHub repository.** https://github.com/MentaNew/nvidia_dell_hackathon
3. **Demo video link.** TODO (Franco).
4. **Pitch deck link.** TODO.
5. **Getting-started experience.** TODO after GB10 setup: note SSD mount discovery (`lsblk`), vLLM launch, which
   flags needed changing, time from power-on to first real inference.
6. **Helpful and missing resources.** Helpful so far: OpenAI-compatible serving (vLLM) let the app stay
   runtime-agnostic; imageio-ffmpeg wheel for aarch64 avoided an apt dependency. Missing: TODO after event
   (e.g. verified launch flags for NVFP4 Nemotron on Blackwell, sample radio audio with rights).
7. **What slowed us down.** Laptop has no CUDA GPU, so all real-model work waited for the GB10; ASTRA_HANDOFF.md was
   on an unmounted SSD; a TCP-connect network probe gave false ONLINE behind a VPN/sandbox (fixed with an HTTP check);
   Docker Desktop would not start headlessly (MongoDB untested, SQLite used). TODO: add GB10-day items.
8. **Models used and roles.** Qwen3-VL 30B-A3B Instruct FP8 (vLLM): image/frame observations, transcript → structured
   reports, query and SITREP synthesis, OpenClaw agent model. Whisper Large v3 Turbo (vLLM transcription endpoint):
   radio audio → transcript. Optional, not required for the demo: Nemotron 3 Nano 30B-A3B NVFP4 (separate reasoner),
   Nemotron Embed 1B (semantic retrieval; keyword retrieval is the default).
9. **Reasons for model choices.** One multimodal instruct model covers vision and text reasoning with constrained
   JSON output, keeping the model set minimal; Whisper is the standard local transcription path with an
   OpenAI-compatible endpoint; NVFP4 Nemotron is on the SSD as the Blackwell-native reasoner if time permits. Medi's
   cloud evaluation informed prompts/settings only; no cloud inference remains in the runtime.
10. **Model setup process.** `scripts/serve_models.sh vlm|stt|llm|embed` (vLLM, weights from the GBeast10 SSD via
    `RESCUEBASE_MODEL_ROOT`), then `tests/test_real.py` prints the measurement block. TODO: record actual vLLM
    version, flags that worked, load time, memory used.
11. **Would we use the hardware again and why.** TODO after the event (say what worked, what did not, with numbers
    from docs/STATUS_LOG.md).
