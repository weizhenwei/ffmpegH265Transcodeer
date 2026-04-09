# ffmpegH265Transcodeer
transcode mp4/m3u8 to h265 using ffmpeg.

## Quick Start

```bash
pip install -r requirements.txt
python -m app.cli.main init
python -m app.cli.main submit --input-root ./data/in --output-root ./data/out
python -m app.cli.main run-worker
python -m app.cli.main status --job-id <job_id>
```

## Docker

```bash
docker compose -f deploy/docker-compose.yml up --build
```
