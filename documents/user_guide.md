# ffmpegH265Transcodeer 用户手册

## 1. 文档目标
本手册面向使用者与运维人员，说明如何安装、配置、启动、提交任务、查看结果与排障。

## 2. 软件简介
ffmpegH265Transcodeer 是一个命令行驱动的批量转码工具，支持将目录中的 MP4/M3U8 文件转为 H.265 编码输出。

当前版本关键特性：
- 批量目录扫描与任务化处理。
- Master/Worker 运行模式。
- 基于数据库队列的跨进程任务分发（已禁用 Redis）。
- JSON 结构化日志。
- 基础任务状态统计与失败重试。

## 3. 环境准备
### 3.1 必备软件
- Python 3.11+
- FFmpeg（同时包含 ffprobe）

### 3.2 校验命令
```bash
python --version
ffmpeg -version
ffprobe -version
```

## 4. 安装步骤
在项目根目录执行：

```bash
pip install -r requirements.txt
python -m app.cli.main init
```

执行 `init` 后会创建/确保：
- `data/in` 输入目录
- `data/out` 输出目录
- 数据库表结构（由 `DB_URL` 指定的数据库承载，推荐 PostgreSQL）

## 5. 快速开始
### 步骤 1：准备输入文件
将待转码文件放入 `data/in`，支持：
- `.mp4`
- `.m3u8`

### 步骤 2：提交任务
```bash
python -m app.cli.main submit --input-root ./data/in --output-root ./data/out
```

返回示例：
```json
{"job_id":"<JOB_ID>","task_total":12,"dispatched":12}
```

### 步骤 3：启动 Worker
```bash
python -m app.cli.main run-worker
```

说明：
- 该命令为常驻进程，持续消费任务，不会自动退出。
- 无任务时会周期输出 `worker_idle_waiting` 日志。

### 步骤 4：查询任务状态
```bash
python -m app.cli.main status --job-id <JOB_ID>
```

返回示例：
```json
{"job_id":"<JOB_ID>","status":"PARTIAL_SUCCESS","total":12,"success":9,"failed":3,"skipped":0}
```

### 步骤 5：重试失败任务
```bash
python -m app.cli.main retry-failed --job-id <JOB_ID>
```

## 6. 命令手册
### 6.1 查看帮助
```bash
python -m app.cli.main --help
```

### 6.2 初始化
```bash
python -m app.cli.main init
```

### 6.3 提交任务
```bash
python -m app.cli.main submit \
  --input-root ./data/in \
  --output-root ./data/out \
  --suffix _h265 \
  --mode mirror \
  --crf 28 \
  --max-retry 2
```

参数说明：
- `--input-root`：输入目录
- `--output-root`：输出目录
- `--suffix`：输出后缀，默认 `_h265`
- `--mode`：输出模式，`mirror` 或 `flat`
- `--crf`：H.265 质量参数
- `--max-retry`：最大重试次数

### 6.4 查询任务
```bash
python -m app.cli.main status --job-id <JOB_ID>
```

### 6.5 重试失败任务
```bash
python -m app.cli.main retry-failed --job-id <JOB_ID>
```

### 6.6 启动 Master（可选）
```bash
python -m app.cli.main run-master
```

说明：
- Master 主要执行超时任务恢复逻辑。
- 单机小规模使用可不启动，但推荐启动以提升鲁棒性。

### 6.7 启动 Scheduler（可选）
```bash
python -m app.cli.main run-scheduler
```

## 7. 配置说明
默认配置文件：
- `configs/config.example.yaml`

可通过环境变量覆盖常用项：
- `DB_URL`：数据库连接地址
- `TRANSCODE_FFMPEG_BIN`：ffmpeg 可执行路径
- `TRANSCODE_FFPROBE_BIN`：ffprobe 可执行路径
- `WORKER_WORKER_ID`：worker 唯一标识（为空时自动生成 `hostname-pid`）

示例：
```bash
set DB_URL=postgresql+psycopg://transcoder:transcoder@localhost:5432/transcode
set WORKER_WORKER_ID=worker-2
python -m app.cli.main run-worker
```

分布式运行建议：
- submit/master/worker 必须使用同一个 `DB_URL`。
- 多 worker 实例请使用不同 `WORKER_WORKER_ID`（或留空自动生成）。
- 多节点部署时，所有节点需挂载同一输入/输出存储路径。

## 8. 输出文件规则
- 输出文件默认统一为 `.mp4` 封装。
- 文件名规则：`原文件名 + 后缀 + .mp4`
- 示例：`sample-5s.mp4 -> sample-5s_h265.mp4`
- `mode=mirror`：保留输入目录层级
- `mode=flat`：平铺输出到根目录

## 9. 日志与监控
### 9.1 日志格式
日志为 JSON，常见字段：
- `timestamp`
- `level`
- `logger`
- `message`
- `event`
- `job_id/task_id/node_id`

### 9.2 常见关键事件
- 提交链路：`cli_submit_start`、`cli_submit_done`
- 分发链路：`dispatch_started`、`task_dispatched`
- Worker 链路：`task_received`、`task_transcode_success`
- 失败链路：`task_probe_failed`、`task_transcode_failed`
- 空闲链路：`worker_idle_waiting`

### 9.3 指标端口
- Master 默认 `9108`
- Worker 默认 `9109`

## 10. Docker 使用
```bash
docker compose -f deploy/docker-compose.yml up --build
# 按需扩容 worker
docker compose -f deploy/docker-compose.yml up --scale worker=3 -d
```

容器说明：
- `postgres`：共享元数据库
- `master`：恢复与调度相关循环
- `worker`：消费并执行转码

## 11. 常见问题排查
### 11.1 run-worker 没有“结束”
- 正常现象。worker 是常驻消费进程。

### 11.2 提交成功但无转码输出
检查顺序：
1. 是否已启动 `run-worker`
2. submit/master/worker 的 `DB_URL` 是否一致并可连通
3. `status` 是否有 `DISPATCHED/RUNNING`
4. 日志是否出现 `task_probe_failed` 或 `task_transcode_failed`
5. 输入目录是否确实包含可读文件

### 11.3 ffmpeg/ffprobe 找不到
- 安装 FFmpeg 并加入 PATH
- 或设置环境变量 `TRANSCODE_FFMPEG_BIN`/`TRANSCODE_FFPROBE_BIN`

### 11.4 m3u8 转码失败
- 常见原因：清单引用资源不可达、协议/权限问题、索引文件损坏
- 建议先验证同目录 MP4 是否能成功转码，以区分系统问题与数据源问题

### 11.5 出现大量失败任务
- 使用 `status` 观察失败规模
- 使用 `retry-failed` 重试临时失败
- 结合日志 `stderr_summary` 分析根因

## 12. 推荐运行流程
1. `init`
2. 启动 `run-master`（推荐）
3. 启动一个或多个 `run-worker`
4. `submit` 提交任务
5. `status` 追踪进度
6. `retry-failed` 做补偿
7. 检查 `data/out` 输出与日志

## 13. 升级与维护建议
- 定期清理历史任务数据（jobs/tasks 表）避免数据库膨胀。
- 为生产环境改用 PostgreSQL 等外部数据库。
- 多 worker 运行时保证 `WORKER_WORKER_ID` 唯一（或留空自动生成）。
