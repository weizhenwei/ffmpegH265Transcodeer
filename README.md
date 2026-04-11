# ffmpegH265Transcodeer
transcode mp4/m3u8 to h265 using ffmpeg.

## 功能概览
- 目录级批量扫描，支持 MP4、M3U8 输入。
- 统一转码为 H.265（默认 libx265）。
- Master/Worker 分布式架构，支持任务分发与并行执行。
- 支持任务状态查询、失败重试、超时回收。
- 当前版本默认使用数据库队列（已禁用 Redis 依赖）。
- 输出结构支持 `flat`（平铺）和 `mirror`（保留目录层级）两种模式。

## 项目结构
```text
app/
  cli/                 # 命令行入口
  core/                # 配置、模型、日志、枚举
  infra/               # DB、队列、ffmpeg、metrics
  master/              # 扫描、分发、汇总、恢复
  worker/              # 消费、探测、转码、结果回写、心跳
configs/
  config.example.yaml
deploy/
  docker-compose.yml
  Dockerfile.master
  Dockerfile.worker
```

## 环境要求
- Python 3.11+
- 推荐安装 FFmpeg/ffprobe 并加入 PATH
- FFmpeg/ffprobe

## 安装与初始化
```bash
pip install -r requirements.txt
python -m app.cli.main init
```

初始化后会创建：
- `./data/in`：输入目录
- `./data/out`：输出目录
- `./transcode.db`：SQLite 元数据库（默认）

## 本地运行（单机）
### 1) 准备输入文件
- 把待转码 `.mp4` 或 `.m3u8` 放入 `./data/in`。

### 2) 提交任务
```bash
python -m app.cli.main submit --input-root ./data/in --output-root ./data/out
```
返回示例：
```json
{"job_id":"<JOB_ID>","task_total":10,"dispatched":8}
```

### 3) 启动 Worker
```bash
python -m app.cli.main run-worker
```

### 4) 查询状态
```bash
python -m app.cli.main status --job-id <JOB_ID>
```
返回示例：
```json
{"job_id":"<JOB_ID>","status":"RUNNING","total":10,"success":4,"failed":1,"skipped":2}
```

### 5) 重试失败任务
```bash
python -m app.cli.main retry-failed --job-id <JOB_ID>
```

## 常用命令
```bash
python -m app.cli.main --help
python -m app.cli.main init
python -m app.cli.main submit --input-root ./data/in --output-root ./data/out --suffix _h265 --mode mirror --crf 28 --max-retry 2
python -m app.cli.main status --job-id <JOB_ID>
python -m app.cli.main retry-failed --job-id <JOB_ID>
python -m app.cli.main run-master
python -m app.cli.main run-worker
python -m app.cli.main run-scheduler
```

## 配置说明
默认配置文件：`configs/config.example.yaml`

可通过环境变量覆盖关键配置：
- `DB_URL`：数据库连接串
- `TRANSCODE_FFMPEG_BIN`：ffmpeg 可执行程序
- `TRANSCODE_FFPROBE_BIN`：ffprobe 可执行程序
- `WORKER_WORKER_ID`：Worker 标识

示例：
```bash
set DB_URL=sqlite:///./transcode.db
python -m app.cli.main run-worker
```

## 日志与可观测性
- 日志采用 JSON 结构化输出，包含 `event/job_id/task_id/node_id` 等字段。
- 已在 CLI、Master、Worker、队列、转码执行路径补充关键日志，便于排查。
- 指标端口：
  - `run-master` 默认 `9108`
  - `run-worker` 默认 `9109`

常见日志事件示例：
- `cli_submit_start` / `cli_submit_done`
- `task_dispatched`
- `task_received`
- `task_transcode_success`
- `task_transcode_retry`
- `task_transcode_failed`
- `task_recovered`

## Docker 运行
```bash
docker compose -f deploy/docker-compose.yml up --build
```

容器说明：
- `master`：执行超时回收等调度逻辑
- `worker`：执行探测与转码
- 队列：数据库队列（基于 tasks 表状态流转）

## 运行流程建议
1. `init` 初始化目录和数据库。
2. 启动 `run-master`（可选但推荐，用于恢复机制）。
3. 启动一个或多个 `run-worker`。
4. 使用 `submit` 提交任务。
5. 使用 `status` 追踪任务进度。
6. 用 `retry-failed` 处理失败任务。

## 常见问题
### 0) `run-worker` 长时间没有结果
- `run-worker` 是常驻进程，不会自动退出。
- 如果未先执行 `submit`，worker 会持续等待任务，日志会周期输出 `worker_idle_waiting`。
- 如已提交任务但仍无进展，先用 `status` 查看是否有 `DISPATCHED/RUNNING`，再排查 `task_probe_failed`/`task_transcode_failed`。

### 1) 任务提交后无执行
- 检查是否已启动 `run-worker`。
- 检查输入目录是否存在有效 mp4/m3u8 文件。
- 检查日志中是否出现 `queue_backend_database` 事件，并确认 `submit` 已成功分发任务。

### 2) `ffmpeg`/`ffprobe` 找不到
- 确认已安装并加入 PATH。
- 或通过 `TRANSCODE_FFMPEG_BIN` / `TRANSCODE_FFPROBE_BIN` 指定绝对路径。

### 3) 输出目录没有结果
- 检查 `status` 中 `failed/skipped` 数量。
- 查日志 `task_probe_failed`、`task_transcode_failed` 的错误信息。
- 检查输入文件是否损坏或编码不受支持。
