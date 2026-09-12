#!/usr/bin/env bash
# First 5 minutes on the GB10: inspect the box, find the model SSD, check ports. Prints facts, changes nothing.
echo "== host ==";        uname -a; lsb_release -ds 2>/dev/null; nproc; free -h | head -2
echo "== gpu ==";         nvidia-smi --query-gpu=name,driver_version,memory.total,memory.used --format=csv 2>/dev/null || echo "nvidia-smi missing"
echo "== toolchain ==";   python3 --version; docker --version 2>/dev/null || echo "docker missing"; node --version 2>/dev/null || echo "node missing (OpenClaw needs 24.16+)"
                          ffmpeg -version 2>/dev/null | head -1 || echo "ffmpeg: none on PATH (imageio-ffmpeg wheel will be used)"
                          python3 -c "import vllm; print('vllm', vllm.__version__)" 2>/dev/null || echo "vllm: not importable in this python (use the NVIDIA vLLM container or a venv)"
echo "== disks ==";       lsblk -o NAME,SIZE,FSTYPE,MOUNTPOINT,LABEL | grep -v loop; df -h | grep -E "Filesystem|/mnt|/media|/data" || true
echo "== model root candidates =="
found=$(find /mnt /media /data "$HOME" -maxdepth 4 -type d -name GB10_ARSENAL 2>/dev/null | head -3)
if [ -n "$found" ]; then
  for d in $found; do echo "  $d"; ls "$d/models" 2>/dev/null | sed 's/^/     models\//'; done
  echo "  -> export RESCUEBASE_MODEL_ROOT=$(echo "$found" | head -1)/models"
else
  echo "  GB10_ARSENAL not found under /mnt /media /data ~ : is the GBeast10 SSD mounted? (lsblk above; sudo mount /dev/sdX1 /mnt/gbeast10)"
fi
echo "== ports (8000 app, 8001 vlm, 8002 llm, 8003 stt, 8004 embed, 18789 openclaw) =="
ss -ltnp 2>/dev/null | grep -E ":(8000|8001|8002|8003|8004|18789)\b" || echo "  none listening yet"
echo "== external internet probe =="
curl -s -o /dev/null -w "  http://connectivitycheck.gstatic.com/generate_204 -> HTTP %{http_code} in %{time_total}s\n" --max-time 3 http://connectivitycheck.gstatic.com/generate_204 || echo "  OFFLINE"
