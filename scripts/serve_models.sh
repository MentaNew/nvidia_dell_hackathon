#!/usr/bin/env bash
# Serve the local models on the GB10 as OpenAI-compatible endpoints (vLLM). RescueBase only ever talks HTTP,
# so anything that speaks /v1/chat/completions, /v1/embeddings, /v1/audio/transcriptions works (NIM, llama.cpp...).
#
# First run on the GB10:   lsblk; df -h      -> find the GBeast10 SSD mount, then
#   export RESCUEBASE_MODEL_ROOT=/mnt/<ssd>/GB10_ARSENAL/models
#   scripts/serve_models.sh vlm        # hour-2 goal: this one alone makes the whole slice work
#   scripts/serve_models.sh llm|stt|embed|all
#
# GPU memory: GB10 is unified memory and vLLM sees one device, so the --gpu-memory-utilization fractions
# below must sum to < 1.0 across the servers you run concurrently. Flags follow each model card; verify
# on first launch and adjust here, not in the app.
# DGX Spark note: if pip vLLM lacks Blackwell/aarch64 wheels, use NVIDIA's container, e.g.
#   docker run --gpus all --rm -p 8001:8000 -v "$RESCUEBASE_MODEL_ROOT:/models" nvcr.io/nvidia/vllm:latest \
#     vllm serve /models/vision/qwen3-vl-30b-a3b-instruct-fp8 --served-model-name qwen3-vl ...
set -euo pipefail
: "${RESCUEBASE_MODEL_ROOT:?set RESCUEBASE_MODEL_ROOT=/path/to/GB10_ARSENAL/models}"
M=$RESCUEBASE_MODEL_ROOT
LOGS=$(dirname "$0")/../data/logs; mkdir -p "$LOGS"

serve() {
  case $1 in
    vlm)   # tool-call flags are for the OpenClaw agent loop (integrations/openclaw); RescueBase itself does not need them
           vllm serve "$M/vision/qwen3-vl-30b-a3b-instruct-fp8" --served-model-name qwen3-vl --port 8001 \
             --gpu-memory-utilization 0.40 --max-model-len 16384 --limit-mm-per-prompt '{"image":4}' \
             --enable-auto-tool-choice --tool-call-parser hermes ;;
    llm)   # NVFP4 needs Blackwell kernels. Fallback: "$M/reasoning/qwen3.5-35b-a3b-fp8" (same flags, name it the same)
           vllm serve "$M/reasoning/nemotron-3-nano-30b-a3b-nvfp4" --served-model-name nemotron-nano --port 8002 \
             --gpu-memory-utilization 0.25 --max-model-len 16384 --trust-remote-code ;;
    stt)   # older vLLM: add --task transcription. Alternative server: pip install speaches (faster-whisper)
           vllm serve "$M/speech/whisper-large-v3-turbo" --served-model-name whisper-large-v3-turbo --port 8003 \
             --gpu-memory-utilization 0.05 ;;
    embed) # older vLLM: --task embed ; newer: --runner pooling
           vllm serve "$M/retrieval/nemotron-3-embed-1b-nvfp4" --served-model-name nemotron-embed --port 8004 \
             --gpu-memory-utilization 0.05 --task embed ;;
    *) echo "usage: $0 vlm|llm|stt|embed|all" >&2; exit 2 ;;
  esac
}

if [ "${1:-vlm}" = all ]; then
  for s in vlm llm stt embed; do
    nohup "$0" "$s" > "$LOGS/$s.log" 2>&1 &
    echo "$s -> pid $! (log: $LOGS/$s.log)"
  done
  wait
else
  serve "${1:-vlm}"
fi
