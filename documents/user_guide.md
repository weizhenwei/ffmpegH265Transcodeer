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

## 6. 分布式多机部署指南

在生产环境中，需要通过多台物理机/虚拟机横向扩展转码能力。系统通过**共享数据库**和**共享存储**支持真正的分布式部署。

### 6.1 基础设施要求
1. **统一的 PostgreSQL 数据库**
   - 不再使用本地的 SQLite。
   - 需要提供一个独立运行的 PostgreSQL 实例。
   - 所有 Master 和 Worker 节点必须配置相同的 `DB_URL`。

2. **统一的共享存储 (关键!)**
   - 由于系统本身不包含文件传输协议，所有的文件 I/O 必须通过本地路径访问。
   - **所有的 Master 和 Worker 节点必须将共享存储（如 NFS、SMB、GlusterFS）挂载到机器的完全相同的位置**。
   - **示例**：
     - `节点 A (Master)` 挂载 NFS 到 `/mnt/shared/data`
     - `节点 B (Worker)` 挂载同一 NFS 到 `/mnt/shared/data`
     - `节点 C (Worker)` 挂载同一 NFS 到 `/mnt/shared/data`

### 6.2 部署步骤示例

**1. 准备配置**
在所有节点的环境变量中注入以下配置：
```bash
export DB_URL="postgresql+psycopg://transcoder:transcoder@192.168.1.100:5432/transcode"
export WORKER_WORKER_ID="worker-$(hostname)" # 可选，否则自动生成
```

**2. 启动 Master 节点 (在节点 A 上)**
```bash
python -m app.cli.main run-master
```

**3. 启动 Worker 节点 (在节点 B 和 C 上)**
```bash
python -m app.cli.main run-worker
```

**4. 提交任务 (任意能连数据库的节点)**
```bash
python -m app.cli.main submit \
  --input-root /mnt/shared/data/in \
  --output-root /mnt/shared/data/out
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

## 13. 常见问题 (FAQ)

### 13.1 "No database configured" 或 "Worker idle"
- **原因**：节点之间数据库不通，或者没有共享队列。
- **解决**：确保 `DB_URL` 在所有节点完全一致，且指向共享 PostgreSQL 实例（不能是 sqlite）。

### 13.2 "No such file or directory" (在 Worker 节点)
- **原因**：Worker 找不到输入文件。
- **解决**：这是分布式共享存储没挂载好。请检查 Worker 节点上是否能通过配置的路径看到 Master 节点生成的文件。必须挂载 NFS。

### 13.3 "FFmpeg command failed"
- **原因**：视频文件损坏或 FFmpeg 不支持某种格式。
- **解决**：查看对应 Task ID 的日志。尝试用 `-c:v copy` 等配置跳过重编码。

### 13.4 任务卡在 "RUNNING"
- **原因**：Worker 崩溃或者被强杀，没有发出完成信号。
- **解决**：Master 节点的 `run-master` 进程有一个恢复循环，默认每 20 秒检查一次。它会自动把超时的 Task 重新放回队列（重试状态）。如果没启动 `run-master`，请启动它。

## 14. 运维建议
- 快速验证优先使用 SQLite，配置简单、开箱即用。
- 多 worker 场景保持 `WORKER_WORKER_ID` 唯一。
- 定期清理历史作业与任务数据，避免元数据库膨胀。
