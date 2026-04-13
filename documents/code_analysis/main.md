# `app/cli/main.py` 源码详细分析

## 1. 文件定位与职责
`main.py` 是当前项目的命令行总入口，承担了“应用编排层”的职责：
- 暴露 CLI 命令接口（submit/status/retry-failed/run-master/run-worker/run-scheduler/init）。
- 负责实例化底层依赖（Settings、DB、Queue、Service）。
- 串联 Master/Worker 相关服务形成可执行流程。
- 提供运行日志与最小指标集成入口。

该文件不承载复杂业务算法，核心价值在于“把模块组装成可运行系统”。

## 2. 顶部依赖分析
## 2.1 标准库
- `json`：输出命令结果 JSON。
- `logging`：记录运行日志。
- `time`：master 循环休眠。
- `Path`：初始化时创建目录。

## 2.2 第三方库
- `typer`：CLI 框架。
- `sqlalchemy.select`：用于 `retry-failed` 查询失败任务。

## 2.3 项目内模块
- 配置与基础设施：
  - `get_settings`（配置加载）
  - `Database`（数据库会话）
  - `DatabaseQueue`（当前队列后端，已替代 Redis）
  - `job_total/start_metrics_server`（指标）
- 业务服务：
  - Master 侧：`JobService`、`ScanService`、`DispatchService`、`RecoveryService`、`AggregationService`、`SchedulerService`
  - Worker 侧：`WorkerConsumer`、`HeartbeatService`、`ProbeExecutor`、`TranscodeExecutor`、`ResultReporter`

## 3. 全局对象
```python
cli = typer.Typer(help="H.265 distributed transcoder CLI")
logger = logging.getLogger(__name__)
```
- `cli` 作为命令注册中心。
- `logger` 用于输出结构化日志（格式由 `setup_logging` 决定）。

## 4. 基础工厂函数
## 4.1 `get_queue(settings, db)`
行为：
- 直接返回 `DatabaseQueue(db)`。
- 输出日志事件：`queue_backend_database`。

意义：
- 明确当前是“禁用 Redis”后的数据库队列模式。
- submit 与 worker 通过数据库共享任务，避免跨进程内存队列不共享问题。

## 4.2 `get_db(settings)`
行为：
- 通过 `settings.db.url` 构造 `Database`。
- 调用 `db.create_all()` 确保表存在。
- 输出 `database_ready` 日志。

影响：
- 每次命令执行都会触发表检查/创建，简化部署但在大规模场景可能有额外开销。

## 5. 命令逐个分析
## 5.1 `submit`
### 5.1.1 输入参数
- `--input-root`（必填）
- `--output-root`（必填）
- `--suffix`（默认 `_h265`）
- `--mode`（默认 `mirror`）
- `--crf`（默认 `28`）
- `--max-retry`（默认 `2`）

### 5.1.2 执行流程
1. 加载配置并初始化日志。
2. 初始化 DB 与队列对象。
3. 创建 Master 侧服务实例。
4. 组装转码参数 `params`（从 settings 与 CLI 参数融合）。
5. `create_job` 创建任务。
6. `mark_running` 将 Job 状态切换到 RUNNING。
7. `scan_and_create_tasks` 扫描目录并建 Task。
8. `dispatch_pending_tasks` 分发待执行任务。
9. 增加 `job_total{status="RUNNING"}` 指标。
10. 输出 JSON：`job_id/task_total/dispatched`。

### 5.1.3 特点
- 这是系统入口中最核心命令，承担“创建 + 扫描 + 分发”完整责任。
- 命令完成后并不执行转码，真正转码依赖 `run-worker`。

## 5.2 `status`
### 5.2.1 执行流程
1. 初始化配置、日志、DB。
2. 创建 `JobService` + `AggregationService`。
3. 先 `aggregate(job_id)` 汇总状态，再读取 Job。
4. 若不存在则抛 `BadParameter`。
5. 输出 JSON：`status/total/success/failed/skipped`。

### 5.2.2 设计点评
- “查询前先聚合”可以保证查询结果尽量新鲜。
- 但聚合逻辑耦合在读取流程中，后续可抽象成统一 read-model 更新策略。

## 5.3 `retry-failed`
### 5.3.1 执行流程
1. 查询指定 Job 下 `FAILED` 任务。
2. 对未超过 `max_retry` 的任务：
   - 改为 `DISPATCHED`
   - `retry_count += 1`
   - 调用 `queue.push(...)`
3. 输出 `resent` 数量。

### 5.3.2 注意点
- payload 中 `params` 当前传 `{}`，实际参数回填依赖 `DatabaseQueue.pop` 从 `jobs.params_json` 再读取，属于“后补参数”策略。

## 5.4 `run-master`
### 5.4.1 执行流程
1. 初始化日志、指标、DB、队列。
2. 构造 `RecoveryService`。
3. 进入死循环，每 `recovery_interval_sec` 执行一次 `reclaim_stuck_tasks`。
4. 发生回收时输出 `master_reclaimed_tasks` 日志。

### 5.4.2 角色定位
- 当前 master 主要做“恢复器”而不是复杂调度器。
- 对单机也有价值：能自动处理超时卡死任务。

## 5.5 `run-worker`
### 5.5.1 执行流程
1. 初始化日志、指标、DB、队列。
2. 初始化 `HeartbeatService`、`ResultReporter`、`ProbeExecutor`、`TranscodeExecutor`。
3. 构造 `WorkerConsumer`，注入心跳回调。
4. 调用 `consumer.run_forever()` 进入消费循环。

### 5.5.2 关键行为
- 这是常驻命令，不会自动退出。
- 没有任务时属于正常等待状态（当前 worker 已有 idle 日志）。

## 5.6 `run-scheduler`
### 5.6.1 执行流程
1. 初始化配置与日志。
2. 构建 `SchedulerService`。
3. 注册一个 cron 任务 `tick`（当前仅日志行为）。
4. 启动调度器。

### 5.6.2 现状
- 该命令具备框架能力，但业务触发动作目前是占位实现（只打日志）。

## 5.7 `init`
### 5.7.1 执行流程
1. 初始化日志。
2. 创建输入输出目录（`settings.ensure_directories()`）。
3. 创建数据库结构（`db.create_all()`）。
4. 创建本地日志目录 `logs`。
5. 输出 `initialized`。

### 5.7.2 作用
- 提供快速冷启动入口，适合本地开发和首次部署。

## 6. 调用链视图
## 6.1 提交到执行
`submit` -> `JobService`(create/running) -> `ScanService`(create tasks) -> `DispatchService`(DISPATCHED)

`run-worker` -> `WorkerConsumer.pop`(取 DISPATCHED) -> probe/transcode -> `ResultReporter`(SUCCESS/FAILED/RETRYING)

`status` -> `AggregationService` -> `JobService.refresh_job_status`

## 6.2 恢复链路
`run-master` -> `RecoveryService.reclaim_stuck_tasks` -> 重新投递或失败终止

## 7. 日志策略分析
本文件日志覆盖点较完整，具备以下优势：
- 每个命令都有 start/done 事件。
- 关键流程带 `job_id` 与 `task_id` 便于串联。
- 错误场景（如 job not found）有显式 error 事件。

可优化点：
- `run-master`/`run-worker` 可增加启动参数快照日志（interval/metrics_port/worker_id）。
- `submit` 可记录 `input_root/output_root` 便于审计。

## 8. 异常处理分析
现状：
- 业务异常多由下层 service 抛出，CLI 层未统一捕获。
- `status` 命令有显式 not found 处理。

建议：
- 增加统一异常边界（例如 CLI 层 try/except 输出标准错误 JSON）。
- 为命令返回值引入统一结构：`code/message/data`，方便自动化调用。

## 9. 并发与一致性关注点
- 当前 `run-worker` 通过 `WorkerConsumer` 单循环消费，扩展多个进程/实例时要关注任务领取原子性。
- 数据库队列模型依赖状态流转，若并发 worker 增多，建议引入“原子 claim”机制防止重复领取。
- `retry-failed` 与 worker 同时操作同一任务时可能产生竞态，需增加状态校验与乐观锁策略。

## 10. 与配置/部署的关联
- `main.py` 强依赖配置项：DB、worker、transcode、scheduler。
- `run-master/run-worker` 默认会启动指标端口（9108/9109）。
- 部署中需要保证：
  - DB 可访问；
  - FFmpeg/ffprobe 可执行；
  - 输入输出目录挂载可读写。

## 11. 文件优点总结
- 职责清晰：编排层与业务层分离。
- 命令完备：覆盖初始化、提交、查询、重试、执行、恢复、定时。
- 可观测性较好：日志事件设计清晰。
- 兼容无 Redis：数据库队列保证跨进程任务共享。

## 12. 改进建议（按优先级）
1. **高优先级**：为 worker 领取任务增加原子锁语义，提升多 worker 一致性。
2. **高优先级**：统一 CLI 错误返回格式与异常出口。
3. **中优先级**：`run-scheduler` 从日志占位升级为真实 submit 触发。
4. **中优先级**：增强 status 输出，增加 `DISPATCHED/RUNNING/RETRYING` 分项。
5. **低优先级**：抽象依赖注入容器，减少 main.py 手工组装代码。

## 13. 结论
`main.py` 当前实现已具备可用的生产雏形编排能力，能够把项目内 Master/Worker/DBQueue/FFmpeg 组件组织成端到端可运行链路。该文件最大的风险点不在“功能缺失”，而在“并发一致性与异常出口规范化”仍有提升空间。
