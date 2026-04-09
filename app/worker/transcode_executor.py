from pathlib import Path

from app.infra.ffmpeg import CmdResult, build_ffmpeg_command, run_cmd


class TranscodeExecutor:
    def __init__(self, ffmpeg_bin: str) -> None:
        self.ffmpeg_bin = ffmpeg_bin

    def run(self, input_path: str, output_path: str, params: dict, timeout_sec: int) -> CmdResult:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        tmp_output = f"{output_path}.tmp"
        cmd = build_ffmpeg_command(
            ffmpeg_bin=self.ffmpeg_bin,
            input_path=input_path,
            output_path=tmp_output,
            video_codec=params.get("video_codec", "libx265"),
            crf=int(params.get("crf", 28)),
            preset=params.get("preset", "medium"),
            gop=int(params.get("gop", 48)),
            audio_codec=params.get("audio_codec", "aac"),
            audio_bitrate=params.get("audio_bitrate", "128k"),
        )
        result = run_cmd(cmd, timeout_sec=timeout_sec)
        if result.ok:
            Path(tmp_output).replace(output_path)
        return result
