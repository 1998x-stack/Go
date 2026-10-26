# 方案 C 实施指南：可信围棋协作平台（单机完整纵向切片）

> 实现分支：`feature/plan-c-go-ai-platform-20261026`，从方案 B PR #5 的最新提交派生（B 尚未进入 main），C 的 PR 必须以 B 为 base。此文档说明实现能力及明确限制，**不把单机原型称为已验证的多机生产系统**。

## 1. 已实现架构与共享核心资产

    Browser (Bearer + fetch/SSE)         CLI / Worker (Bearer)
                  |                              |
          Authenticated FastAPI /v1          Operator API
                  |                              |
           +------+------------------------------+
           |                 |                   |
      GameService       AnalysisService       JobService
           |                 |                   |
       RulesEngine        PUCT Search      SQLite leases/fencing
           |              Torch/uniform         |
       EventLedger         predictor        ArtifactStore
           |                  |
      SQLite WAL       LocalRegistry champion
           |
   canonical record / SGF / SSE reconnect

**权威事实源**：`go_game.core.RulesEngine` 沿用方案 A 的 PSK + no-suicide + simple area scoring，方案 B `search` 只做决策；数据库存储每步 `game_id` / seq / cmd ID / actor / 规则状态哈希，与状态表在 **同一 SQLite BEGIN IMMEDIATE 事务**中提交。

**客户端不可信**：落子请求只包含命令意图（row,col / pass）、`expected_seq`、`command_id`、`actor_id`。合法性和当前行棋方由服务端重放验证，旧命令同 ID 同 payload 返回原结果；ID 重用不同 payload 或旧 seq -> 409。命令被拒绝不会推进权威棋局序号。

**分层权限**：所有读接口要求 Bearer；viewer 全局只读；player 必须参加该局才能读写，且不能冒充别的操作者；researcher 具备实验与分析权限；operator 具备任务租约；admin 拥有管理功能。令牌从环境或显式配置注入，服务**没有匿名默认令牌**。生产部署要在 TLS 终止代理后、受限网络环境中运行。

## 2. 模块与端点

| 模块 | 功能与契约 |
| --- | --- |
| `platform.storage` | 单机 SQLite WAL，外键、事务隔离，完整事件落地 |
| `platform.games` | create/snapshot、CAS 落子、actor 核验、重启恢复、可验证 SGF 和 canonical record |
| `platform.analysis` | 绑定棋局 seq + state_hash + rule_id + model_id 的 PUCT 分析；新局的 champion 权重连同 manifest 归档为不可变模型资产，后续 champion 轮换后旧局仍可推理；最多 32 次搜索 |
| `platform.jobs` | 实验/run/job schema，提交幂等，排队、claim、heartbeat、finish、cancel；过期重领、attempt fencing |
| `platform.worker` | 本地独立可信 Worker，支持 selfplay、validate_shard、learn、evaluate、export_model 五类内置工作流；仅使用已验证的规则与已提交工件 |
| `platform.artifacts` | 本地 SHA-256 内容寻址对象，原子硬链接发布与读取时摘要复核 |
| `platform.api` | FastAPI 鉴权、schema 拒绝未知字段、状态码、REST、SSE |
| `platform.web` | 单页响应式棋盘、落子、Pass、MCTS 分析、SGF 下载、实时事件恢复 |
| `platform.run` | Uvicorn ASGI 启动，缺少配置时拒绝匿名启动 |

主要 API：
- `POST /v1/games`、`GET /v1/games/{id}`、`POST /v1/games/{id}/commands`
- `GET /v1/games/{id}/events?after_seq=N`：从 N 之后按连续 seq 恢复，最多 500 条一页，`has_more` 必须继续拉取；
- `GET /v1/games/{id}/stream?after_seq=N`：带 Bearer 的 SSE，`id:` 对应服务端 seq；N=-1 首先发送当前 snapshot，之后从新 seq 追；N>=0 从已知 cursor 补齐历史。
- `GET /v1/games/{id}/record` 与 `/sgf`（SGF 仍受原项目线性子集限制）
- `POST /v1/games/{id}/analysis`：`{"expected_seq":0,"simulations":8}`
- `GET /v1/models/champion`：只读已注册模型；模型权重固定于该局 model_id，不从用户请求加载任意文件。
- `POST /v1/jobs`、`GET /v1/jobs/{id}`、`POST /v1/workers/lease`、`POST /v1/jobs/{id}/heartbeat`、`POST /v1/jobs/{id}/complete`、`POST /v1/jobs/{id}/cancel`
- `POST /v1/artifacts`、`GET /v1/artifacts/{digest}`：上传大小 1 MiB；工作完成时只接受已经校验存在的对象摘要。

## 3. 开发运行方式

建议 Python 3.11 环境，先安装可选依赖（不修改原 pygame/pygbag 部署）：

```bash
python -m pip install 'fastapi>=0.115,<1' 'uvicorn>=0.30,<1' 'httpx>=0.27,<1'
# 仅需要已训练模型推理时，再安装匹配的 CPU/GPU Torch。
```

先自行生成高熵 token。演示环境下可配置两个玩家、operator 以及 viewer，**下面的字符串仅供本机测试，不可用于公开部署**：

```bash
export GO_PLATFORM_TOKENS_JSON='{"replace-with-random-token-alice-001":{"subject":"alice","role":"player"},"replace-with-random-token-bob-002":{"subject":"bob","role":"player"},"replace-with-random-token-operator-003":{"subject":"ops","role":"operator"},"replace-with-random-token-viewer-004":{"subject":"viewer","role":"viewer"}}'
export GO_PLATFORM_DB="runs/platform.sqlite3"
export GO_PLATFORM_ARTIFACTS="runs/artifacts"
uvicorn go_game.platform.run:app --host 127.0.0.1 --port 8008
```

打开 `http://127.0.0.1:8008/`，填入账号 token，创建 5×5 / 9×9 棋局。另一位玩家在另一浏览器打开相同 Game ID 登录白方账号：两端通过后端事件流实时更新。未经服务端确认的落子不算成功。

### 运行可信本地 Worker

在相同数据库与工件根目录下，独立终端运行（需安装 CPU PyTorch 才能执行 learn/evaluate/export 任务）：

```bash
python -m go_game.platform.worker \\
  --db runs/platform.sqlite3 \\
  --artifacts runs/artifacts \\
  --worker-id go-local-1 --max-jobs 10
```

`--max-jobs` 限制本次处理的作业总数；Worker 不从 API 接受脚本或任意文件路径，严格校验每类 `inputs` 字段。演示 Self-Play 的提交体：

```json
{
  "request_key": "selfplay-demo-001",
  "kind": "selfplay",
  "spec": {
    "experiment_id": "go-small-board",
    "run_id": "trial-001",
    "inputs": {
      "rules": {
        "schema": "rules-v1",
        "rule_id": "research-psk-v1",
        "board_size": 2,
        "komi_half_points": 11,
        "handicap": 0,
        "ko_rule": "positional_superko",
        "suicide": "forbidden",
        "scoring": "area_simple",
        "end_protocol": "two_pass_no_adjudication"
      },
      "seed": 42,
      "simulations": 2,
      "max_moves": 200
    },
    "budget": {
      "cpu_seconds": 120,
      "gpu_seconds": 0,
      "storage_mb": 16
    }
  }
}
```

完成后返回的 `artifact_digest` 可作为下一条 `validate_shard` 或 `learn` Job 的输入。批量 Worker 不承担公网不可信代码执行，且当前 CPU 时间预算执行后审查而非硬隔离时钟；上线须在外层进程/容器施加硬 CPU/RAM/IO 限额。

## 4. 核心数据与重连

对局落子事务流程：
1. `BEGIN IMMEDIATE` 锁定单机 SQLite 写序列。
2. 先查 `(game_id,command_id)` 旧响应：相同 payload 幂等返回，不同 payload 409。
3. 校验 `expected_seq`；基于已存事件重放 `RuleSpec + GameState`，检查 seq、actor、状态链、落子合法性。
4. 新事件持久化 `seq`（对外从 1 开始）、`event_id`、`state_before/after`、canonical action、`command_id`、响应快照。
5. 同事务推进头表 `seq/state_hash/terminal`；COMMIT；断电没有半步落子。
6. 断线端先查询 snapshot，再带 `after_seq=snapshot.seq` 订阅 SSE；丢失 cursor 则使用 `/events` 历史补全，并验证连续 seq。

回放会重新执行已有的方案 A 规则，包括完整超级劫历史。客户端不得仅凭局面图像在本地判定“自杀”“打劫”。较长 19×19 对局每次全局 replay 可能较慢；增量验证快照属于后续性能演进，正确性是基线。

## 5. 任务调度和模型发布的可信边界

Job 不接受任意要在 API 进程执行的 Python 或 shell 字符串；`kind` 仅允许 `selfplay/validate_shard/learn/evaluate/export_model`，manifest 包含 experiment/run、inputs 和 CPU/GPU/存储预算。服务端提供控制平面租约；`LocalWorker` 是可信的本机执行进程，按白名单执行 `selfplay`（2–5 棋盘）、`validate_shard`、`learn`、`evaluate`、`export_model`，工件自动进入内容寻址对象存储，成功任务结果绑定数据摘要。研究者不能向进程上传任意 Python/命令字符串；learn 仅消费已完成 selfplay 的数据，evaluate/export 仅引用已完成 learn 的模型工件。**这不是具备容器隔离、GPU 配额强制和多机容错的生产 Worker 系统。**

worker lease 过期可重新领取，`attempt` 单调增加。旧 worker 的完成/心跳都会得到 `stale_lease`，不能覆盖新 attempt 的结果。当前 SQLite 仅适用于单机，不可部署到 NFS 共享数据库做多主队列；多机时须换 PostgreSQL 事务、对象存储和独立部署测试。

模型发布：采用方案 B 的 `LocalRegistry` 只读 champion，新建对局时把经校验的 champion checkpoint 内容哈希与 manifest 原子归档到 `model_assets`。后续 registry 指针轮换，历史棋局仍从归档不可变工件按 model_id 重建，防止模型漂移。**API 不提供无 Arena 晋级的直接发布操作**。若模型权重或 manifest 不匹配则拒绝分析。

## 6. 测试

```bash
python -m unittest -v tests.test_platform_core
python -m unittest -v tests.test_platform_http
python -m unittest discover -s tests -p 'test_*.py' -v
ruff check go_game main.py tests/test_logging.py renderer.py event_handler.py sound.py
```

CI 除 A/B 的既有 Python 3.9/3.11/3.13、PyTorch、Gym、pygame 外，另加 `platform-http` job 安装 FastAPI/httpx。核心门禁为：
- 12 个线程相同 seq 并发写入，恰好 1 个成功、其他全部 409；
- 同一 `command_id` 幂等，改变 payload 409，非法落子 422 且状态不变；
- 重启和读取断点事件可复现与 SGF 匹配，篡改链被检出；
- 双 Pass 正式终局且不把尚未解决死子的行为错误标注为裁决；
- 任务超时重领、attempt fencing、旧 worker 无法重复发布；
- 内容寻址读写防篡改、超大/非法路径拒绝；
- HTTP 无 token 401，viewer 写入 403，演员冒充 403，分析只在正确 seq/model 下可见。

## 7. 仍未完成的方案 C 高阶能力

**C0–C4 的单机基础链路**已形成可运行实现；C5/C6 中完整 PostgreSQL + S3 多机部署、跨主机故障恢复、集群级资源隔离、生产级 TLS/集中身份服务、专业 GTP 桥接、GPU 推理微批与正式模型发布后台仍需独立实施与验证。当前前端是轻量研究看板，不提供完整多用户账户系统。本地 Worker 可执行五类白名单任务，但不是长期运行的多机生产执行调度系统。

参考：[方案 C 设计](03-plan-c-full-platform.md) · [核心资产](00-core-assets-and-contracts.md) · [方案 B 实现](06-plan-b-implementation.md)。
