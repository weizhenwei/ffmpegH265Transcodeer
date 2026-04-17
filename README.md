# ffmpegH265Transcodeer
一个基于 FFmpeg 的 H.265 分布式转码系统，支持单机和多机部署。

## 1. 系统能力
- 支持目录级批量扫描输入文件（`.mp4`、`.m3u8`）。
- 支持 Master/Worker 架构，主节点调度，计算节点执行。
- 支持共享存储增量扫描，仅处理新增未转码文件。
- 支持按在线 Worker 的 `capacity` 加权平均分配任务。
- 支持任务状态查询、失败重试、超时回收、节点心跳保活。
- 默认使用数据库队列（`tasks` 状态流转），无需 Redis。

## 2. 核心架构
- `主节点（Master）`：扫描输入目录、创建任务、分发任务、回收超时任务、统计结果。
- `计算节点（Worker）`：启动注册、周期心跳、领取任务、执行 ffprobe + ffmpeg、回传结果。
- `共享存储`：所有节点共享 `input/output` 目录。
- `共享数据库`：单机与分布式验证均使用 SQLite（`sqlite:///./transcode.db`）。

## 3. 目录结构
```text
app/
  cli/                 # CLI 入口与命令
  core/                # 配置、模型、日志、枚举
  infra/               # DB、队列、ffmpeg、metrics
  master/              # 扫描、分发、聚合、恢复
  worker/              # 消费、探测、转码、结果回写、心跳
configs/
  config.example.yaml
deploy/
  docker-compose.yml
  Dockerfile.master
  Dockerfile.worker
documents/
  user_guide.md        # 详细使用手册
```

## 4. 环境要求
- Python 3.11+
- FFmpeg/ffprobe（建议加入 PATH）
- 单机与分布式验证均使用 SQLite（默认）

## 5. 安装初始化
```bash
pip install -r requirements.txt
python -m app.cli.main init
```

初始化后会确保：
- 输入目录：`./data/in`
- 输出目录：`./data/out`
- 数据库表结构创建完成

## 6. 单机使用手册
### 6.1 准备输入
- 将待转码文件放入 `./data/in`。

### 6.2 启动 Worker
```bash
python -m app.cli.main run-worker
```

### 6.3 提交任务
```bash
python -m app.cli.main submit --input-root ./data/in --output-root ./data/out
```

返回示例：
```json
{"job_id":"<JOB_ID>","task_total":12,"dispatched":10}
```

### 6.4 查看进度
```bash
python -m app.cli.main status --job-id <JOB_ID>
python -m app.cli.main stats --job-id <JOB_ID>
```

### 6.5 失败重试
```bash
python -m app.cli.main retry-failed --job-id <JOB_ID>
```

## 7. 分布式使用手册
### 7.1 准备共享资源
- 所有节点挂载同一个输入目录与输出目录（例如 `/mnt/transcode/input`、`/mnt/transcode/output`）。
- 所有节点连接同一个数据库（本手册统一使用 SQLite）。

### 7.2 节点环境变量
Windows PowerShell:
```powershell
$env:DB_URL="sqlite:///./transcode.db"
$env:STORAGE_INPUT_ROOT="\\nas\transcode\input"
$env:STORAGE_OUTPUT_ROOT="\\nas\transcode\output"
```

Linux/macOS:
```bash
export DB_URL="sqlite:///./transcode.db"
export STORAGE_INPUT_ROOT="/mnt/transcode/input"
export STORAGE_OUTPUT_ROOT="/mnt/transcode/output"
```

### 7.3 启动顺序（推荐）
1. 主节点执行初始化（一次）：
```bash
python -m app.cli.main init
```
2. 主节点启动调度恢复循环：
```bash
python -m app.cli.main run-master
```
3. 每个计算节点启动 worker（每台唯一 ID）：
```bash
export WORKER_WORKER_ID="worker-01"
python -m app.cli.main run-worker
```
4. 主节点发起转码（使用共享目录）：
```bash
python -m app.cli.main start-transcode
```
5. 查询节点与任务统计：
```bash
python -m app.cli.main workers
python -m app.cli.main stats
```

## 8. 命令速查
```bash
python -m app.cli.main --help
python -m app.cli.main init
python -m app.cli.main submit --input-root ./data/in --output-root ./data/out --suffix _h265 --mode mirror --crf 28 --max-retry 2
python -m app.cli.main start-transcode
python -m app.cli.main status --job-id <JOB_ID>
python -m app.cli.main retry-failed --job-id <JOB_ID>
python -m app.cli.main run-master
python -m app.cli.main run-worker
python -m app.cli.main workers
python -m app.cli.main stats
python -m app.cli.main stats --job-id <JOB_ID>
```

## 9. 配置项与环境变量
默认配置文件：`configs/config.example.yaml`

关键环境变量：
- `DB_URL`
- `TRANSCODE_FFMPEG_BIN`
- `TRANSCODE_FFPROBE_BIN`
- `WORKER_WORKER_ID`
- `STORAGE_INPUT_ROOT`
- `STORAGE_OUTPUT_ROOT`
- `STORAGE_OUTPUT_MODE`（`mirror/flat`）
- `STORAGE_OUTPUT_SUFFIX`

## 10. SQLite 模式（单机 + 分布式验证）
本项目默认使用 SQLite，适合快速验证单机与分布式核心流程。

### 10.1 数据库配置
Linux/macOS:
```bash
export DB_URL="sqlite:///./transcode.db"
```

Windows PowerShell:
```powershell
$env:DB_URL="sqlite:///./transcode.db"
```

### 10.2 初始化数据库表
```bash
python -m app.cli.main init
```

### 10.3 验证数据库接入
```bash
python -m app.cli.main workers
python -m app.cli.main stats
```

### 10.4 使用注意
- 分布式验证时建议所有进程运行在同一台机器，共用同一个 `transcode.db` 文件。
- 已启用 SQLite 并发优化（WAL + busy_timeout），适合开发验证场景。
- 生产环境或高并发多机部署再切换 PostgreSQL。

## 11. Docker 使用
```bash
docker compose -f deploy/docker-compose.yml up --build
docker compose -f deploy/docker-compose.yml up --scale worker=3 -d
```

## 12. 常见问题
### 12.1 Worker 一直运行不退出
- 正常行为。`run-worker` 是常驻进程。

### 12.2 已提交任务但未执行
- 检查 `workers` 输出是否有在线节点。
- 检查所有节点 `DB_URL` 是否一致。
- 检查共享目录路径是否在所有节点可访问。

### 12.3 ffmpeg/ffprobe 找不到
- 安装后加入 PATH，或通过 `TRANSCODE_FFMPEG_BIN`/`TRANSCODE_FFPROBE_BIN` 指定绝对路径。

### 12.4 输出目录无结果
- 用 `status/stats` 看失败或跳过数量。
- 查看日志中的 `task_probe_failed` 或 `task_transcode_failed` 详情。
