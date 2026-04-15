from functools import lru_cache
import os
from pathlib import Path

from pydantic import Field
import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    role: str = "master"
    node_id: str = "node-1"
    log_level: str = "INFO"
    service_name: str = "h265-transcoder"
    model_config = SettingsConfigDict(env_prefix="APP_", extra="ignore")


class DBSettings(BaseSettings):
    url: str = "sqlite:///./transcode.db"
    model_config = SettingsConfigDict(env_prefix="DB_", extra="ignore")


class StorageSettings(BaseSettings):
    input_root: str = "./data/in"
    output_root: str = "./data/out"
    output_mode: str = "mirror"
    output_suffix: str = "_h265"
    overwrite: bool = True
    model_config = SettingsConfigDict(env_prefix="STORAGE_", extra="ignore")


class TranscodeSettings(BaseSettings):
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    video_codec: str = "libx265"
    crf: int = 28
    preset: str = "medium"
    gop: int = 48
    audio_codec: str = "aac"
    audio_bitrate: str = "128k"
    task_timeout_sec: int = 1800
    max_retry: int = 2
    model_config = SettingsConfigDict(env_prefix="TRANSCODE_", extra="ignore")


class WorkerSettings(BaseSettings):
    worker_id: str = ""
    concurrency: int = 2
    heartbeat_interval_sec: int = 10
    poll_block_ms: int = 5000
    model_config = SettingsConfigDict(env_prefix="WORKER_", extra="ignore")


class SchedulerSettings(BaseSettings):
    enabled: bool = False
    cron: str = "0 */1 * * *"
    model_config = SettingsConfigDict(env_prefix="SCHEDULER_", extra="ignore")


class Settings(BaseSettings):
    config_file: str = Field(default="configs/config.example.yaml")
    app: AppSettings = AppSettings()
    db: DBSettings = DBSettings()
    storage: StorageSettings = StorageSettings()
    transcode: TranscodeSettings = TranscodeSettings()
    worker: WorkerSettings = WorkerSettings()
    scheduler: SchedulerSettings = SchedulerSettings()

    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    def ensure_directories(self) -> None:
        Path(self.storage.input_root).mkdir(parents=True, exist_ok=True)
        Path(self.storage.output_root).mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    config_path = os.getenv("CONFIG_FILE", "configs/config.example.yaml")
    payload: dict = {}
    if Path(config_path).exists():
        with open(config_path, "r", encoding="utf-8") as fp:
            payload = yaml.safe_load(fp) or {}

    # Explicit env overrides for critical runtime settings in containerized/distributed deployments.
    db_url = os.getenv("DB_URL")
    if db_url:
        payload.setdefault("db", {})["url"] = db_url
    ffmpeg_bin = os.getenv("TRANSCODE_FFMPEG_BIN")
    if ffmpeg_bin:
        payload.setdefault("transcode", {})["ffmpeg_bin"] = ffmpeg_bin
    ffprobe_bin = os.getenv("TRANSCODE_FFPROBE_BIN")
    if ffprobe_bin:
        payload.setdefault("transcode", {})["ffprobe_bin"] = ffprobe_bin
    worker_id = os.getenv("WORKER_WORKER_ID")
    if worker_id is not None:
        payload.setdefault("worker", {})["worker_id"] = worker_id
    storage_input_root = os.getenv("STORAGE_INPUT_ROOT")
    if storage_input_root:
        payload.setdefault("storage", {})["input_root"] = storage_input_root
    storage_output_root = os.getenv("STORAGE_OUTPUT_ROOT")
    if storage_output_root:
        payload.setdefault("storage", {})["output_root"] = storage_output_root
    storage_output_mode = os.getenv("STORAGE_OUTPUT_MODE")
    if storage_output_mode:
        payload.setdefault("storage", {})["output_mode"] = storage_output_mode
    storage_output_suffix = os.getenv("STORAGE_OUTPUT_SUFFIX")
    if storage_output_suffix:
        payload.setdefault("storage", {})["output_suffix"] = storage_output_suffix

    return Settings.model_validate(payload)
