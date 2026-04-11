from pathlib import Path

from app.infra.ffmpeg import CmdResult, build_ffmpeg_command, run_cmd


class TranscodeExecutor:
    def __init__(self, ffmpeg_bin: str) -> None:
        self.ffmpeg_bin = ffmpeg_bin

    def run(self, input_path: str, output_path: str, params: dict, timeout_sec: int) -> CmdResult:
        out_path = Path(output_path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        suffix = out_path.suffix or ".mp4"
        tmp_path = out_path.with_name(f"{out_path.stem}.tmp{suffix}")
        if tmp_path.exists():
            tmp_path.unlink()
        cmd = build_ffmpeg_command(
            ffmpeg_bin=self.ffmpeg_bin,
            input_path=input_path,
            output_path=str(tmp_path),
            video_codec=params.get("video_codec", "libx265"),
            crf=int(params.get("crf", 28)),
            preset=params.get("preset", "medium"),
            gop=int(params.get("gop", 48)),
            audio_codec=params.get("audio_codec", "aac"),
            audio_bitrate=params.get("audio_bitrate", "128k"),
        )
        result = run_cmd(cmd, timeout_sec=timeout_sec)
        if result.ok:
            tmp_path.replace(out_path)
        elif tmp_path.exists():
            tmp_path.unlink()
        return result
