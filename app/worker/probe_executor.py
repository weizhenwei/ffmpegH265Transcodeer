from app.infra.ffmpeg import probe


class ProbeExecutor:
    def __init__(self, ffprobe_bin: str) -> None:
        self.ffprobe_bin = ffprobe_bin

    def run(self, input_path: str) -> tuple[bool, str]:
        return probe(self.ffprobe_bin, input_path)
