# 方案 C：完整围棋 AI 研究与对弈平台（Go AI Platform）

> 状态：深度设计提案。基于 A 的可信规则资产和 B 的训练/评测资产，在需要多人协作、远端训练与可视化时再展开控制平面。
> **不建议**在单人 9×9 基础实验中直接上微服务、Kubernetes 或复杂多租户。

## 1. 北极星目标与使用场景

建立可审计的围棋 AI 工作台，使人类玩家、AI Agent、算法研究者可以共享同一规则、同一对局记录和同一模型评测证据，完成：发起对局、搜索分析、SGF 复盘、模型版本选择、训练实验、基线比赛、模型候选评审与发布。

目标用户故事：
1. 用户打开 Web 棋盘或已有 pygame 界面，选择 9×9、贴目、规则、模型版本，创建对局，落子立即得到权威服务器验收与棋局事件。
2. 一名研究者从一局失败对战跳转到对局 record + checkpoint + search PV + arena report，排查究竟是规则、搜索还是网络问题。
3. 操作者启动小型训练任务，观测输入数据版本和计算资源，候选模型通过验证后发布，不影响正在进行中的对局。
4. 多个客户端观看同一局，并发写入不会制造分叉的“幽灵棋局”；断线可增量恢复。

非目标：从第一天实现大型社交对弈系统、在线匹配/排名商业化、多租户计费、大模型多模态陪练。这些不会改善最核心的规则和评测可信度。

## 2. 必须沉淀的核心资产（而非 UI 功能）

- `GameService` 仅包装 A 的 `RulesEngine`：拥有权威对局 seq、state hash 与命令裁决；
- `GameRecord` + `EventLedger`：人类/Agent/UI/训练对局统一可重放；
- `AnalysisProtocol`：同一盘面和模型下搜索值、PV、policy map 的版本化结构；
- `ArenaReport`：所有上线模型有不可更改的评测依据；
- `ExperimentManifest`：参数、资源和数据谱系，不让“一次模型改进”只剩一张截图；
- `ModelRegistry`：原子发布和回滚；
- `ClientCompatibilityContract`：原 pygame/pygbag 的操作入口不被平台化破坏。

平台最有价值的是**领域结果的可验证性与复用性**，不是“有多少个 dashboard”。

## 3. 控制/数据/交互三平面

    [Web Board] [Existing pygame/pygbag] [CLI/SDK] [External GTP Adapter]
            \           |                |              /
                  [API Gateway / Auth / Rate limits]
                              |
                 [Game Command Service]
                     |                |
             [Authoritative Rules] [Event Ledger]--> [Replay/SGF API]
                     |                |
             [Live Game Events]  [Analysis Requests]
                     |                |
                 [WebSocket/SSE]  [Search/Inference Workers]

    [Experiment Control] --> [Queue/Lease/Scheduler]
               |                   |
         [Dataset/Models]     [Self-Play / Learner Workers]
               |                   |
         [Arena Promotion] <--------+
               |
         [Model Registry] --> [Inference Model Pin]

**数据平面**：规则计算、搜索推理、样本写入、模型训练。**控制平面**：实验计划、任务分派、预算与晋级、审计。**交互平面**：对局指令、观察和回放。交互平面不得直接控制 learner 的内存或权重文件；任何 UI 无权绕过规则内核。

## 4. 状态、命令和事件协议（平台的难点）

### 4.1 对局状态权威性

每局 `game_id` 由服务端创建，固定 `ruleset_id`、棋盘、贴目、开始方、模型/引擎版本；事件流由服务端单写序列化，客户端只能提交命令意图，不直接改 board。对局层提供：
- `expected_seq` 乐观并发控制；
- `command_id` 幂等；同 ID 同 payload 重试返回原结果；不同 payload 必拒绝；
- `actor_id` 与角色权限校验，确保轮到谁、谁能下；
- `state_before_hash` 与提交后的 `state_after_hash` 验证；
- 完整事件日志 + 可校验快照，保证 reconnect/resume；
- 对局规则从头到尾不可变，改贴目必须创建新局或执行显式支持的 setup 事件，不能隐式就地变更。

例：`POST /v1/games/{game_id}/commands` 的请求体（协议草案）：

    {
      "command_id": "uuid",
      "expected_seq": 17,
      "actor_id": "player-black",
      "action": {"kind": "place", "row": 3, "col": 4}
    }

结果：
- 成功：返回最新 `seq`、`state_hash`、新事件 ID、是否终局；
- stale：`409 conflict`，带当前 seq/snapshot reference，客户端重新同步；
- illegal：`422` 或明确协议错误，**不会**推进 seq；
- unauthorized：`403`；重复同 ID 请求与原结果一致。

### 4.2 可恢复实时事件

WebSocket 或 SSE 订阅 `/v1/games/{id}/events?after_seq=...`；服务端 first emits snapshot_at_seq + ordered events，客户端维护连续 seq 并验证 hash。发生丢包或乱序先补缺口，不通过“重新请求整个局面然后假定没问题”隐藏冲突。背压时可合并纯分析进度事件，但**不能丢弃权威落子事件**。

客户端 UI 的本地临时落子必须标注 pending；仅收到服务器确认后的落子才进入 durable state。观众只读订阅，玩家写事件需鉴权。终局后拒绝新增落子；恢复事件必须保持旧 seq 与 result 不被重写。

### 4.3 外部 AI 与协议适配

计划暴露受限 `AgentMoveAPI` 和可选的 Go Text Protocol（GTP）适配器。适配器需明确引擎双方棋盘、komi、handicap 和 move coordinate 的转换；不能以当前旧 SGF 的双字母 `xy` 编码冒充 GTP。外部引擎即使给出 move，也必须经过平台规则引擎裁决。

AI 请求需带 `game_id`, `expected_seq`, `model_id`, `analysis_budget`；超过资源限额应返回结构化超时/重试信息，不自动判棋手认输。

## 5. 分析工作台与可复核结果

对局详情分为：
- 权威棋盘：落子、提子、合法性、行动方、pass、终局与正式比分；
- 分析侧栏：候选落子概率、价值、搜索 visits、PV（principal variation）、ownership 可选；
- 时间轴：历史走子、模型/搜索版本、sgf 下载、评论和对局异常；
- 实验视图：训练配置、loss、吞吐、数据质量、围棋竞技场（Arena）报告；
- 对战页：模型 A/B 双方换色对局的报告和置信区间。

**数据来源标识**：正式计分与搜索估计分开显示；“胜率 70%”须标为某模型在特定规则/贴目/预算下估计，不是规则真值。不同模型分析结果不在缺失共同基线时强行比较。分析状态 `running / partial / completed / failed / cancelled` 明确。

建议的 `AnalysisResult-v1`：
- `game_id`、`source_seq`、`state_hash`、`rule_id`；
- `model_id`、`search_config_id`、`visits`、`depth`、`latency_ms`；
- `policy`、`pv`、`value_current_to_play`、可选 score/ownership；
- `status`、`analysis_id`、`created_at`、结果 checksum。

客户端应拒绝给不匹配当前 seq/hash 的分析结果画热力图，避免显示“上一手的最佳下点”。

## 6. 实验控制平面

### 6.1 任务模型

定义 `Experiment` -> `Run` -> `Job`，Job 如 `selfplay`, `validate_shard`, `learn`, `evaluate`, `export_model`。每个 Job 绑定：
- `job_id`、`attempt_id`、`idempotency_key`、实验配置 digest；
- 用户/团队、deadline、优先级、最大 CPU/GPU/磁盘使用、允许的模型/数据 schema；
- `lease_owner`、`lease_expires_at`、heartbeat、progress checkpoint；
- 状态：queued -> leased -> running -> succeeded/failed/cancelled（失败可新 attempt）；
- 输出 artifact digest，而不只靠日志声称成功。

当 worker 失去心跳，旧 lease 失效；同一结果使用 attempt_id fencing token 原子提交。旧 worker 即使恢复也不能覆盖新一代结果；自我对弈重复结果按 game ID 幂等归并，避免重复训练记账。工作流能够从当前可用分片恢复，不能把进行中的损坏文件当成训练输入。

### 6.2 规模分层

**C0 单机**：FastAPI（可选）+ SQLite WAL（训练元数据小规模）+ 本地 content-addressed blobs + 进程 Worker；仅用于单机/开发与测试。不依赖 Docker/K8s。

**C1 小团队/多机**：PostgreSQL 控制平面、对象存储 S3-compatible、带 lease 的 worker queue、集中指标日志、GPU inference/learner 独立进程。SQLite 不可假设对网络文件共享上的多机并发有相同可靠性。

**C2 真分布式**：需要证据（多机调度和高利用率已成瓶颈）再评估 Kubernetes/Ray 等；不得为了技术栈而拆服务。复杂调度、认证、网络、存储带来额外故障面，必须先有 C1 可靠性测试。

## 7. 数据与存储

| 存储类型 | 内容 | 一致性与保留 |
| --- | --- | --- |
| Relational metadata | 游戏索引、model pointers、run/job/lease、ACL | 强约束、事务、幂等键 |
| Append-only game ledger | game events、seq、state digest | 每局有序、可恢复、版本化 |
| Object store | SGF、canonical records、dataset shards、checkpoints、arena reports | 内容哈希、校验和、原子发布 manifest |
| Cache | 近期局面 / 合法 mask / 分析热点 | 缓存可删，不能变成规则事实源 |
| Telemetry | 延迟、吞吐、失败原因、资源预算 | 按规则隐私配置脱敏，有有限保留期 |

训练产生的大规模原始数据不要塞进关系数据库大字段；数据库保存索引与校验摘要。模型对象上传必须完成 checksum 验证再将 registry 指针指向它。删除训练结果遵循明确保留策略，不删除仍被 champion 或评测报告引用的工件。

## 8. 安全、可信度与滥用防护

- 不可信 SGF、外部 Agent 输出、任意上传棋谱均经过长度/大小、节点数、棋盘尺寸、递归深度、非法动作及时间预算限制；
- 不执行用户提交的 Python/模型代码于 API 进程；若允许自定义算法，须隔离进程/容器、限制计算/网络/文件访问；
- 鉴权采用最小权限：viewer、player、researcher、operator、admin；客户端创建会话无法自行提升到 operator；
- 限流：对局提交频率、批量分析总计算量、每个实验 GPU 小时与存储配额；资源耗尽时有确定性错误，不反复重试轰炸 worker；
- 记录 command/job/model 发布 audit event，不打印完整 SGF 或其他过量敏感上下文到 INFO 日志（符合现有日志规范）；
- API 使用 schema 校验、统一错误码、速率限制；跨来源访问及 WebSocket 身份验证和 TLS 需要明确部署策略；
- 资产供应链：模型/样本 manifest 校验来源与哈希，冻结依赖与镜像；发布的 checkpoint 不来自未认证 worker。

## 9. 可靠性 SLO（预案，须按基线调整）

| 关键链路 | 度量及阶段性门槛草案 |
| --- | --- |
| Game command | 100% 服务器接受的动作被 ledger 存储并可 replay；非法命令 0 状态突变 |
| Reconnect | 断连后 snapshot+events 恢复无缺 seq、无重复落子 |
| Model pin | 在游戏生命周期中 100% inference responses 带同一 model digest |
| Job leasing | 重试/重复 worker 无双重发布 artifact；旧 lease fenced |
| Publish | 未经 schema 与 Arena gate 的 candidate 绝不成为 champion |
| Observability | 每一次失败的 command/job 都有可定位的 reason code / trace ID |

P95 延迟、SSE 延迟、可用性百分比需在实际运行基础上确定，不以未实测数字作承诺。对局状态事件是强一致权威链路；分析 heatmap 允许 eventual consistency，但必须绑定 source_seq 才能显示。

## 10. 用户体验与兼容策略

第一阶段可给现有 pygame 增加通过 Python Domain API 加载模型的能力，不动 `main.py` 浏览器打包路径；再发展轻量 Web Board。平台 UI 是增量产品，不能牺牲 headless CI 和 pygbag 已有入口。sgf 导入对不支持的变化/属性明确返回“无法完全导入”，不要静默裁剪造成对局信息丢失。

标准复盘测试：浏览器创建 9×9 对局、白棋由固定 champion 决策、客户端断网重连、另一窗口旁观、故意并发相同 seq 落子、对局结束显示结算、下载 SGF + canonical record、使用 CLI 验证 replay digest。**这条完整链路**才是平台阶段第一项端到端验收。

## 11. 里程碑与上线门槛

| PR | 能力 | 可验证完成条件 |
| --- | --- | --- |
| C0 | 单进程 `GameService` 与 authoritative seq | 两客户端并发下不可产生冲突分支 |
| C1 | 记录账本 + snapshot + reconnect | 断线重放结果及每步 hash 一致 |
| C2 | 简单 Web 棋盘/既有 pygame AI Adapter | 可对弈、可看分析状态，不破坏现有 UI |
| C3 | Model registry、analysis worker | 错位 source_seq 结果不会污染 UI |
| C4 | 实验 manifest + 任务队列 + worker lease | kill/restart/retry/fencing 故障测试 |
| C5 | Postgres + object store 多机部署 | 原子提交、队列重试、恢复演练 |
| C6 | Arena promotion gate + 生产发布/回滚 | champion/历史对局均可固定版本重现 |

每一步必须有安全/正确性/恢复测试，不因前端 demo 可展示而跨越 gate。

## 12. 重要取舍

最有野心且最稳妥的建设方式，不是立即实现 20 个微服务，而是把 **Rules Truth + Reproducible Records + Model Provenance + Independent Arena** 打磨为可验证的公共协议。它们天然支撑单人游戏、研究系统和多人服务，并允许未来更换 Python、Rust、C++、数据库和模型架构而不破坏历史数据。

关联：[项目总览](README.md) | [核心资产](00-core-assets-and-contracts.md) | [方案 B](02-plan-b-selfplay-training.md) | [实施与验收](04-delivery-and-verification.md)。
