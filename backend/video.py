"""Frame sampling from a recorded clip.

Playback is real time; inference sees one frame every FRAME_INTERVAL_S seconds (at most FRAME_MAX frames). Offsets are
approximate to within half an interval. This is a replay of recorded footage, not continuous video understanding.
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import config


def ffmpeg_exe() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:  # pip package that bundles a static ffmpeg (has aarch64 wheels) — no apt needed on the GB10
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def extract_frames(path: Path, interval_s: float | None = None, max_frames: int | None = None) -> list[tuple[float, bytes]]:
    """[(offset_seconds, jpeg_bytes), ...] sampled every interval_s from the start of the clip."""
    interval_s = interval_s or config.FRAME_INTERVAL_S
    max_frames = max_frames or config.FRAME_MAX
    exe = ffmpeg_exe()
    if not exe:
        raise RuntimeError("ffmpeg not found: `apt install ffmpeg` or `pip install imageio-ffmpeg`")
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "f_%04d.jpg"
        cmd = [exe, "-hide_banner", "-loglevel", "error", "-i", str(path), "-vf", f"fps=1/{interval_s}",
               "-frames:v", str(max_frames), "-q:v", "3", str(out)]
        try:
            subprocess.run(cmd, check=True, capture_output=True, timeout=300)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"ffmpeg failed: {e.stderr.decode(errors='replace')[:300]}") from e
        frames = sorted(Path(td).glob("f_*.jpg"))
        return [(round(i * interval_s, 3), f.read_bytes()) for i, f in enumerate(frames)]
