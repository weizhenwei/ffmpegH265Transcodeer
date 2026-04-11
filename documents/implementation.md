# ffmpegH265Transcodeer 实现说明

## 1. 概述
本文档描述当前代码库的实际实现，而不是规划文档目标。当前系统是一个基于 Python 的转码服务，核心特点如下：
- 通过 CLI 触发任务、查询状态、启动 Worker/Master。
- 采用 Master/Worker 逻辑分层。
- 转码与探测依赖系统 FFmpeg/ffprobe。
- 队列后端已禁用 Redis，当前使用数据库队列（基于 `tasks` 表状态流转）。
- 元数据存储使用 SQLAlchemy，默认 SQLite。

## 2. 目录结构与职责
```text
app/
  cli/                 # 命令行入口与流程编排
  core/                # 配置、枚举、日志、ORM模型
  infra/               # DB封装、队列实现、FFmpeg调用、存储路径、指标
  master/              # 任务创建、扫描、分发、恢复、聚合
  worker/              # 消费执行、探测、转码、结果回写、心跳
configs/
  config.example.yaml  # 默认配置样例
deploy/
  Dockerfile.master
  Dockerfile.worker
  docker-compose.yml
```

## 3. 核心数据模型
定义位置：`app/core/models.py`

### 3.1 Job（作业）
- 关键字段：`id`、`status`、`input_root`、`output_root`、`params_json`
- 统计字段：`total_count`、`success_count`、`failed_count`、`skipped_count`
- 时间字段：`started_at`、`ended_at`、`created_at`、`updated_at`

### 3.2 Task（子任务）
- 关键字段：`id`、`job_id`、`input_path`、`output_path`
- 状态字段：`status`（`PENDING/DISPATCHED/RUNNING/SUCCESS/FAILED/RETRYING/SKIPPED`）
- 重试字段：`retry_count`、`max_retry`
- 结果字段：`ffprobe_json`、`stderr_summary`、`duration_ms`

### 3.3 WorkerNode（执行节点）
- 字段：`worker_id`、`hostname`、`capacity`、`last_heartbeat_at`、`status`
- 用于记录 Worker 注册与心跳信息

## 4. 配置系统
定义位置：`app/core/config.py`

- 使用 `pydantic-settings` 建模配置。
- `get_settings()` 默认读取 `CONFIG_FILE`（默认 `configs/config.example.yaml`）。
- 当前有效配置模块：
  - `app`：角色、节点 ID、日志级别、服务名
  - `db`：数据库连接串
  - `storage`：输入/输出目录与命名策略
  - `transcode`：编码参数、超时、最大重试
  - `worker`：worker_id、轮询阻塞时间、心跳周期
  - `scheduler`：定时配置

## 5. 日志与指标
### 5.1 日志
定义位置：`app/core/logger.py`
- 采用 JSON 结构输出。
- 默认字段：`timestamp/level/logger/message`
- 扩展字段：`service/node_id/job_id/task_id/event`

### 5.2 指标
定义位置：`app/infra/metrics.py`
- 支持 `prometheus_client` 时暴露真实指标。
- 无依赖时自动使用 DummyMetric，避免运行失败。
- 指标包括：job 数、task 数、task 耗时、重试数等。

## 6. 队列实现（当前：数据库队列）
定义位置：`app/infra/redis_queue.py`

文件中保留了三种实现：
- `RedisStreamQueue`：历史实现，当前未在 CLI 路径启用。
- `InMemoryQueue`：进程内队列，不适合 submit/worker 跨进程通信。
- `DatabaseQueue`：当前启用实现。

### 6.1 DatabaseQueue.push
- 通过 `task_id` 更新 `tasks.status = DISPATCHED`。
- 同步更新重试计数相关字段。

### 6.2 DatabaseQueue.pop
- 查询状态为 `DISPATCHED` 的任务，按创建时间升序拉取。
- 拉取时即更新为 `RUNNING`，并写入 `worker_id`、`started_at`。
- 从 `jobs.params_json` 反序列化参数附带到 payload。

### 6.3 DatabaseQueue.ack
- 当前为 no-op（数据库状态已在业务层维护）。

## 7. Master 侧实现
### 7.1 JobService（`app/master/job_service.py`）
- `create_job`：校验输入目录、创建 Job。
- `mark_running`：作业进入 RUNNING。
- `refresh_job_status`：汇总 Task 状态并计算 Job 最终状态。
- `get_job`：按 ID 查询。

### 7.2 ScanService（`app/master/scan_service.py`）
- 递归扫描输入目录。
- 支持后缀：`.mp4`、`.m3u8`（`infra/storage.py`）。
- 不支持格式直接创建 `SKIPPED` 任务。
- 输出路径通过 `build_output_path` 计算。

### 7.3 DispatchService（`app/master/dispatch_service.py`）
- 查询 `PENDING` 任务，构建 payload，调用 `queue.push`。
- 任务置为 `DISPATCHED`。

### 7.4 RecoveryService（`app/master/recovery_service.py`）
- 定期扫描超时 `RUNNING` 任务。
- 可重试则重投并设为 `DISPATCHED`，否则置 `FAILED`。

### 7.5 AggregationService / SchedulerService
- `AggregationService` 仅封装调用 `job_service.refresh_job_status`。
- `SchedulerService` 基于 APScheduler，缺依赖会抛错。

## 8. Worker 侧实现
### 8.1 WorkerConsumer（`app/worker/consumer.py`）
- 主循环：心跳 + 拉取任务 + 执行 + 回写。
- 无任务时每 30 秒输出 `worker_idle_waiting`。
- 任务流程：
  1. `mark_running`
  2. `ffprobe` 探测
  3. `ffmpeg` 转码
  4. 成功 `mark_success`，失败 `mark_failure`
  5. 可重试则重投（retry_count + 1）

### 8.2 ProbeExecutor（`app/worker/probe_executor.py`）
- 调用 `infra.ffmpeg.probe()` 执行 ffprobe 并返回 JSON。

### 8.3 TranscodeExecutor（`app/worker/transcode_executor.py`）
- 使用临时文件输出：`{stem}.tmp{suffix}`（例如 `a.tmp.mp4`）。
- 成功后原子替换为目标文件。
- 失败时删除残留临时文件。

### 8.4 ResultReporter（`app/worker/result_reporter.py`）
- 更新 Task 的 `RUNNING/SUCCESS/FAILED/RETRYING` 状态。
- 保存 `ffprobe_json`、`duration_ms`、`stderr_summary`。

### 8.5 HeartbeatService（`app/worker/heartbeat.py`）
- 首次心跳自动注册 WorkerNode。
- 后续更新容量、在线状态与心跳时间。

## 9. FFmpeg 调用细节
定义位置：`app/infra/ffmpeg.py`

- `run_cmd(args, timeout_sec)` 封装 subprocess 执行。
- `probe(...)` 运行 ffprobe 并解析 JSON。
- `build_ffmpeg_command(...)` 构建转码命令，默认：
  - 视频编码：`libx265`
  - `crf=28`、`preset=medium`、`gop=48`
  - 音频：`aac` + `128k`

## 10. CLI 行为
定义位置：`app/cli/main.py`

- `init`：初始化目录与数据库表。
- `submit`：创建 Job -> 扫描 -> 分发。
- `status`：聚合作业状态并输出统计。
- `retry-failed`：重投失败任务。
- `run-master`：启动恢复循环（默认 20 秒）。
- `run-worker`：启动消费循环。
- `run-scheduler`：启动定时器。

## 11. 当前运行模式与边界
- 当前为“无 Redis”模式，队列后端为数据库队列。
- submit 与 worker 可以跨进程共享任务。
- Worker 实际消费是串行拉取（每次 `count=1`）；`worker.concurrency` 目前主要用于心跳上报，不直接驱动并发执行器。
- m3u8 任务是否成功取决于清单内容及其引用资源可达性。

## 12. 部署实现
### 12.1 Dockerfile
- `deploy/Dockerfile.master`：启动 `run-master`
- `deploy/Dockerfile.worker`：启动 `run-worker`

### 12.2 docker-compose
- 当前仅包含 `master` 与 `worker`，共享 `data/in`、`data/out` 卷。
- 依赖数据库文件 `transcode.db`（SQLite）。

## 13. 代码级已知改进方向
- 增加 `Task.claim` 原子锁语义，避免多 Worker 争抢时并发重复领取。
- 将 Worker 并发从“单循环”升级为线程池/协程池。
- 在 `status` 中增加 `DISPATCHED/RUNNING` 细分统计。
- 为 m3u8 增加协议白名单、超时与重试策略分层。
