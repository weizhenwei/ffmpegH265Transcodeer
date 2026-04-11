import json
import logging
import subprocess
import time
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class CmdResult:
    ok: bool
    return_code: int
    stdout: str
    stderr: str
    duration_ms: int


def run_cmd(args: list[str], timeout_sec: int | None = None) -> CmdResult:
    start = time.time()
    logger.debug("executing command: %s", " ".join(args))
    proc = subprocess.run(args, text=True, capture_output=True, timeout=timeout_sec, check=False)
    duration_ms = int((time.time() - start) * 1000)
    logger.debug("command finished code=%s duration_ms=%s", proc.returncode, duration_ms)
    return CmdResult(
        ok=proc.returncode == 0,
        return_code=proc.returncode,
        stdout=proc.stdout,
        stderr=proc.stderr,
        duration_ms=duration_ms,
    )


def probe(ffprobe_bin: str, input_path: str, timeout_sec: int = 60) -> tuple[bool, str]:
    logger.debug("ffprobe start input=%s", input_path)
    result = run_cmd(
        [ffprobe_bin, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", input_path],
        timeout_sec,
    )
    if not result.ok:
        logger.warning("ffprobe failed input=%s", input_path)
        return False, result.stderr
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        logger.error("ffprobe returned invalid json input=%s", input_path)
        return False, "invalid ffprobe json"
    logger.debug("ffprobe success input=%s", input_path)
    return True, json.dumps(payload, ensure_ascii=False)


def build_ffmpeg_command(
    ffmpeg_bin: str,
    input_path: str,
    output_path: str,
    video_codec: str,
    crf: int,
    preset: str,
    gop: int,
    audio_codec: str,
    audio_bitrate: str,
) -> list[str]:
    return [
        ffmpeg_bin,
        "-y",
        "-i",
        input_path,
        "-c:v",
        video_codec,
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-g",
        str(gop),
        "-c:a",
        audio_codec,
        "-b:a",
        audio_bitrate,
        output_path,
    ]
