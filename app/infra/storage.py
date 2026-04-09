from pathlib import Path

from app.core.enums import OutputMode


SUPPORTED_EXTENSIONS = {".mp4", ".m3u8"}


def iter_input_files(input_root: str) -> list[Path]:
    root = Path(input_root)
    if not root.exists():
        return []
    return [p for p in root.rglob("*") if p.is_file()]


def is_supported_file(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_EXTENSIONS


def build_output_path(input_root: str, output_root: str, src_file: Path, suffix: str, mode: str) -> Path:
    ext = ".mp4"
    new_name = f"{src_file.stem}{suffix}{ext}"
    if mode == OutputMode.FLAT.value:
        return Path(output_root) / new_name
    relative = src_file.parent.relative_to(Path(input_root))
    return Path(output_root) / relative / new_name
