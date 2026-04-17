# ffmpegH265Transcodeer 详细使用手册

## 1. 适用对象
本手册面向开发、测试、运维人员，覆盖：
- 单机使用流程
- 分布式多机使用流程
- 命令清单、配置清单、排障方法

## 2. 系统说明
ffmpegH265Transcodeer 是一个基于 FFmpeg 的 H.265 转码系统，采用 Master/Worker 架构：
- Master：任务扫描、任务派发、超时恢复、统计聚合
- Worker：节点注册、心跳保活、转码执行、结果回传
- 存储：共享 `input/output` 目录
- 数据：共享元数据库（本手册统一使用 SQLite）

## 3. 功能特性
- 支持输入格式：`.mp4`、`.m3u8`
- 输出编码：H.265（默认 `libx265`）
- 支持输出策略：`mirror`（保留目录）/`flat`（平铺）
- 支持增量扫描：仅派发新增未转码文件
- 支持加权调度：按在线 Worker 的 `capacity` 分配任务
- 支持失败重试、超时回收、节点在线状态统计

## 4. 环境准备
### 4.1 基础依赖
- Python 3.11+
- FFmpeg（含 ffprobe）
- 数据库：单机与分布式验证均使用 SQLite

### 4.2 依赖校验
```bash
python --version
ffmpeg -version
ffprobe -version
```

### 4.3 安装初始化
```bash
pip install -r requirements.txt
python -m app.cli.main init
```

初始化后会创建/确保：
- `data/in`
- `data/out`
- 数据库表结构（由 `DB_URL` 指向）

## 5. 单机使用手册（详细）
### 步骤 1：准备测试视频
- 将视频文件放到 `data/in`。

### 步骤 2：启动 worker（终端 A）
```bash
python -m app.cli.main run-worker
```

### 步骤 3：提交转码任务（终端 B）
```bash
python -m app.cli.main submit --input-root ./data/in --output-root ./data/out
```

输出示例：
```json
{"job_id":"<JOB_ID>","task_total":12,"dispatched":10}
```

### 步骤 4：查看任务状态
```bash
python -m app.cli.main status --job-id <JOB_ID>
python -m app.cli.main stats --job-id <JOB_ID>
```

### 步骤 5：失败任务重试（可选）
```bash
python -m app.cli.main retry-failed --job-id <JOB_ID>
```

### 步骤 6：确认输出
- 检查 `data/out` 中是否生成 `*_h265.mp4`

## 6. 分布式使用手册（详细）
### 6.1 拓扑建议
- 1 台主节点：运行 `run-master` 与发起转码命令
- N 台计算节点：运行 `run-worker`
- 1 套共享存储：所有节点都能访问输入/输出目录
- 1 套共享数据库：所有节点统一 `DB_URL`

### 6.2 共享存储规划示例
- Linux：`/mnt/transcode/input`、`/mnt/transcode/output`
- Windows：`\\nas\transcode\input`、`\\nas\transcode\output`

### 6.3 主节点配置
Linux/macOS:
```bash
export DB_URL="sqlite:///./transcode.db"
export STORAGE_INPUT_ROOT="/mnt/transcode/input"
export STORAGE_OUTPUT_ROOT="/mnt/transcode/output"
```

Windows PowerShell:
```powershell
$env:DB_URL="sqlite:///./transcode.db"
$env:STORAGE_INPUT_ROOT="\\nas\transcode\input"
$env:STORAGE_OUTPUT_ROOT="\\nas\transcode\output"
```

### 6.4 计算节点配置
每台计算节点设置唯一 `WORKER_WORKER_ID`：
```bash
export DB_URL="sqlite:///./transcode.db"
export STORAGE_INPUT_ROOT="/mnt/transcode/input"
export STORAGE_OUTPUT_ROOT="/mnt/transcode/output"
export WORKER_WORKER_ID="worker-01"
```

### 6.5 分布式启动顺序
1. 主节点初始化（一次）：
```bash
python -m app.cli.main init
```
2. 主节点启动调度循环：
```bash
python -m app.cli.main run-master
```
3. 各计算节点启动 worker：
```bash
python -m app.cli.main run-worker
```
4. 主节点发起转码（共享目录）：
```bash
python -m app.cli.main start-transcode
```
5. 主节点查看节点与统计：
```bash
python -m app.cli.main workers
python -m app.cli.main stats
```

## 7. 命令参考
### 7.1 基础命令
```bash
python -m app.cli.main --help
python -m app.cli.main init
python -m app.cli.main submit --input-root ./data/in --output-root ./data/out
python -m app.cli.main start-transcode
python -m app.cli.main status --job-id <JOB_ID>
python -m app.cli.main retry-failed --job-id <JOB_ID>
python -m app.cli.main run-master
python -m app.cli.main run-worker
python -m app.cli.main workers
python -m app.cli.main stats
python -m app.cli.main stats --job-id <JOB_ID>
```

### 7.2 submit 参数
- `--input-root`：输入目录
- `--output-root`：输出目录
- `--suffix`：输出后缀（默认 `_h265`）
- `--mode`：`mirror`/`flat`
- `--crf`：质量参数（数值越小质量越高）
- `--max-retry`：最大重试次数

## 8. 配置与环境变量
默认配置文件：`configs/config.example.yaml`

关键环境变量：
- `DB_URL`
- `TRANSCODE_FFMPEG_BIN`
- `TRANSCODE_FFPROBE_BIN`
- `WORKER_WORKER_ID`
- `STORAGE_INPUT_ROOT`
- `STORAGE_OUTPUT_ROOT`
- `STORAGE_OUTPUT_MODE`
- `STORAGE_OUTPUT_SUFFIX`

## 9. SQLite 数据库支持（单机 + 分布式验证）
### 9.1 使用目标
- 单机模式与分布式验证模式统一使用 SQLite。
- 默认数据库文件：`./transcode.db`。

### 9.2 配置连接串
Linux/macOS:
```bash
export DB_URL="sqlite:///./transcode.db"
```

Windows PowerShell:
```powershell
$env:DB_URL="sqlite:///./transcode.db"
```

说明：
- 分布式验证时所有进程需要指向同一个数据库文件。
- 建议在同一台机器启动多个进程模拟分布式。

### 9.3 初始化与验证
```bash
python -m app.cli.main init
python -m app.cli.main workers
python -m app.cli.main stats
```

### 9.4 用 Python 查看 transcode.db 数据
查看所有表名：
```bash
python -c "import sqlite3; conn=sqlite3.connect('transcode.db'); c=conn.cursor(); c.execute(\"SELECT name FROM sqlite_master WHERE type='table' ORDER BY name\"); print([r[0] for r in c.fetchall()]); conn.close()"
```

查看 `jobs` 最近 10 条：
```bash
python -c "import sqlite3; conn=sqlite3.connect('transcode.db'); c=conn.cursor(); rows=c.execute(\"SELECT id,status,created_at FROM jobs ORDER BY created_at DESC LIMIT 10\").fetchall(); print(rows); conn.close()"
```

查看 `tasks` 最近 10 条：
```bash
python -c "import sqlite3; conn=sqlite3.connect('transcode.db'); c=conn.cursor(); rows=c.execute(\"SELECT id,job_id,status,worker_id,created_at FROM tasks ORDER BY created_at DESC LIMIT 10\").fetchall(); print(rows); conn.close()"
```

查看 `workers` 最近心跳：
```bash
python -c "import sqlite3; conn=sqlite3.connect('transcode.db'); c=conn.cursor(); rows=c.execute(\"SELECT worker_id,status,last_heartbeat_at FROM workers ORDER BY last_heartbeat_at DESC LIMIT 10\").fetchall(); print(rows); conn.close()"
```

### 9.5 并发能力说明
- 项目已对 SQLite 启用并发优化（WAL、busy_timeout）。
- 可满足开发调试与核心流程验证。
- 高并发生产场景再切换 PostgreSQL。

## 10. 输出规则
- 输出封装：统一 `.mp4`
- 输出命名：`原文件名 + 后缀 + .mp4`
- `mirror`：保留输入目录层级
- `flat`：输出平铺到目标目录

## 11. 日志与可观测
### 11.1 常见日志字段
- `timestamp`
- `level`
- `event`
- `job_id`
- `task_id`
- `node_id`

### 11.2 常见事件
- 提交：`cli_submit_start`、`cli_submit_done`
- 分发：`dispatch_started`、`task_dispatched`
- 执行：`task_received`、`task_transcode_success`
- 异常：`task_probe_failed`、`task_transcode_failed`、`task_recovered`

### 11.3 指标端口
- Master：`9108`
- Worker：`9109`

## 12. Docker 快速部署
```bash
docker compose -f deploy/docker-compose.yml up --build
docker compose -f deploy/docker-compose.yml up --scale worker=3 -d
```

## 13. 常见问题排障
### 13.1 worker 一直不退出
- 正常现象，worker 是常驻进程。

### 13.2 有任务但不转码
- 检查 `python -m app.cli.main workers` 是否有在线节点。
- 检查所有节点 `DB_URL` 一致且可连通。
- 检查共享目录在所有节点均可读写。

### 13.3 ffmpeg/ffprobe 报错
- 检查 PATH
- 或设置 `TRANSCODE_FFMPEG_BIN`、`TRANSCODE_FFPROBE_BIN`

### 13.4 m3u8 失败
- 多为源地址不可达或清单引用资源缺失
- 可先用 MP4 验证系统链路是否正常

### 13.5 失败任务太多
- 先用 `stats` 看全局失败比例
- 用 `status --job-id` 定位具体作业
- 用 `retry-failed` 重试临时失败任务

## 14. 运维建议
- 快速验证优先使用 SQLite，配置简单、开箱即用。
- 多 worker 场景保持 `WORKER_WORKER_ID` 唯一。
- 定期清理历史作业与任务数据，避免元数据库膨胀。
