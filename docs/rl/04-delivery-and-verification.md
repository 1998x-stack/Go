# 跨方案实施路线、决策门禁与独立验收

> 本文是可拆成 PR 的交付计划，不是已完成项目报告。估时为粗略工程范围而非承诺；硬件性能与棋力门槛需首轮基准测量后冻结。

## 0. 为什么不应一次性重写

当前 `game.py` / `gameboard.py` / `sgf.py` 已形成可运行的 headless 规则层，`go_game/app.py` / `main.py` 承担 pygame/pygbag 入口，`ai.py` 提供 Random/Greedy。已有规则测试、日志测试与 CI。一次性改变语言、规则、坐标、对局持久化和 UI，会使退化无法归因。

交付必须遵守“**同一 PR 只改变一个可验证抽象边界**”：先保留当前可观察行为，新增独立的 schema / adapter / fixture，之后才替换实现。历史 SGF 与 UI 兼容是正式验收项，而非“以后再补”。

## 1. 依赖关系和关键路径

    [P0 Golden Rules + RuleSpec + Legacy Adapter]
                     |
         [P1 Action/Observation/Reward]
                     |
         [P2 Replay Record + Arena Harness]
                   /   \
             [A RL API]  [B0 Network + MCTS]
                               |
                   [B1 Selfplay -> Learner -> Arena]
                               |
                  [B2 Batched/Native optimization]
                               |
                  [C Model Registry / Game API]
                               |
                [C Event Stream / Experiment Control]
                               |
                        [C Multi-machine]

A、B、C 可以分别定义产品边界，但其依赖不是三条平行线。第一阶段的 P0/P1/P2 不应被任何高级功能跳过。

## 2. 分期计划（每个交付都有不可替代的证明）

| 阶段 | 依赖 | 主要改动 | 强制验收 |
| --- | --- | --- | --- |
| F0 规则基线冻结 | 无 | 记录当前 Game 行为、RuleSpec、冻结样例、明确 PSK | 既有 tests 全绿、金标复盘不变 |
| F1 领域标准接口 | F0 | State/Move/Score、row-major codec、legacy adapter | 行为差分、clone/undo、坐标非对称 |
| F2 记录和评测资产 | F1 | events + game digest + seed + replay + Arena v1 | 断点复盘校验、换色配对比赛 |
| A1 环境完成 | F2 | AEC、Gym VS Opponent、mask/obs 版本 | API tests、非法行为、终局/截断测试 |
| B1 算法小闭环 | A1 的域核心即可 | 5×5 PUCT、小型 CNN、样本生成、Learner | 数据与 model provenance、toy minimax 符号测试 |
| B2 可解释棋力证据 | B1 | 9×9 baseline/champion arena、promotion gate | 配对结果+区间、固定预算、可复跑 |
| B3 性能优化 | B2 | profile 驱动 native、推理批量化、Actor 并行 | 基于相同规则的 before/after 报告 |
| C1 交互服务 | F2+B1 | authoritative game service、model pin、UI | seq CAS、重放、断线恢复、existing UI |
| C2 研究运营平台 | C1+B2 | job leases、模型工件、实验控制 | 幂等/fencing/恢复、候选晋级审计 |
| C3 多机扩容 | C2 | Postgres/对象存储、多机 worker | 故障与吞吐门禁、成本/资源清单 |

粗略人力范围（**仅用于计划评估**）：F0~F2 为 2–5 周，A1 1–3 周，B1~B2 4–10 周，B3 2–8 周（依赖实际性能需求），C1~C2 4–12 周，C3 另行估算。前提：1–2 名有经验工程师、现有 CI 可用、目标只求可研究的原型；棋力达到职业引擎级别不在此估时内。

## 3. 逐 PR 验收模板

每个 PR 描述应包含：
1. **Scope**：改变的语义、触及的稳定 API、刻意保留的 legacy 行为；
2. **Contracts**：RuleSpec、ActionSpec、ObsSpec、RecordSchema、ModelManifest 是否升级；
3. **Tests**：新增测试名称、命令、环境、通过/失败数；
4. **Benchmark**：版本/hardware/seed/sizes/样本数、baseline 与 delta（性能变动时必需）；
5. **Migration**：旧数据/SGF/shim 兼容策略、回滚方法；
6. **Evidence**：CI 链接、fixture 摘要、arena 报告或 E2E 录屏（按变更类型）；
7. **Risks**：未知点与不满足的条件，明确下一 PR 负责，而不是笼统宣称全验证。

文档设计 PR 无代码改动时，应明确“设计完成，验证尚未执行”。真实代码改动需对应自动化测试与 CI 证据才能使用“已完成”字样。

## 4. 正确性门禁：测试集分级

### Gate R：规则引擎

- 旧测试：`python -m unittest discover -p 'test_*.py' -v`、`python -m unittest discover -s tests -p 'test_*.py' -v`；
- 金标：5×5、9×9、19×19 规定 fixture；提子、打劫、PSK 历史、双 Pass、计分、让子、undo/replay；
- 性质：`apply/undo` 恢复完整 fingerprint；`clone(state)` 不共享可变状态；
- 差分：同一规则预设下 reference 与 optimized engine 对每一步 legal mask、result、captured 一致；故意的哈希碰撞回退测试；
- legacy 对接：旧 UI 输入映射与 SGF roundtrip 不被 row/col 变更破坏。

阻断条件：任何高优先级 fixture 不一致，或 AI 可以执行核心引擎判非法的动作。

### Gate E：环境与研究复现

- PettingZoo AEC API conformance 与 Gymnasium env checker；
- 终局奖励严格零和；截断不得伪造 winner；
- seeds 与 baseline 对局序列可复核；
- 所有状态产生 `N*N+1` 长度动作向量；Pass/非法掩码正确；
- 逐阶段检查 `legal_actions` 不污染状态；测试当前行动方观察视角；
- 测试同盘不同超级劫历史的 mask 差异；D4 对称转换的 policy、history、mask 完整反变换。

阻断条件：模型看到的输入与规则实际合法动作不一致，或状态/奖励视角随行棋双方改变解释。

### Gate T：训练与搜索

- Toy game exhaustive minimax vs MCTS 价值回传；
- terminal / pass / ko 分支无错误展开；
- NaN、非法概率、策略目标和样本 final z 标签受校验；
- 模型固定 batch export/inference 数值一致；
- 自我对弈记录必须先通过 replay validator 再被 Learner 使用；
- 恢复训练同时恢复 optimizer/scaler/RNG/data window，实验 manifest 不被覆盖；
- Arena 固定双方相同搜索预算，并公开统计不确定度。

阻断条件：loss 减少但样本无法复盘；模型价值符号没有通过固定夹具；发布缺 Arena 报告。

### Gate P：平台可靠性、安全与恢复

- 两名客户端同 seq 并发落子，恰一条成功，另一条可按冲突协议恢复；
- 命令重复送达只产生一条落子，客户端断开后事件补齐；
- 模型每局 pin，推理响应不允许混版本；
- worker lease 超时后旧 worker 无法成功提交；对象存储中断后不出现半成品训练分片；
- 对非法、过量 SGF 输入及未知模型 manifest fail-closed；
- 鉴权/角色/权限矩阵和资源预算测试通过；
- pygame 本地桌面流程与 pygbag 浏览器 smoke 保留。

阻断条件：对局分叉、重复写入、错误权限发布 champion、平台服务可以跳过 Domain Rules。

## 5. Benchmark Protocol v1（不可跨配置直接比较）

每份报告统一记录：
- Git commit SHA、Python/Rust/C++ 编译器、CPU/GPU、OS、线程数、内存、容器 digest；
- `rule_id`, board size、komi、默认开局、seed 列表、使用的事件 fixture hash；
- 计算方法：warm-up 次数、测量重复次数、p50/p95、置信区间、计算预算；
- 闭环链路分别测：单步落子 latency，legal_masks/sec，clone+undo/sec，MCTS sims/sec，inference positions/sec，selfplay games/hour，有效训练样本/小时；
- 人均开发/运行成本不与算力费用混为一谈，若统计美元成本须包含所用硬件定价口径；
- 成本与棋力一起报告，避免 GPU 投入翻倍却只比较绝对胜率。

**性能门禁拟议**：优化后正确性必须完全一致；若性能收益在重复测量的误差范围内，不引入复杂性。正式数值门槛应根据 F0 的环境和真实基线测量，在性能 PR 前冻结。

## 6. 可重复实验协议 v1

每个 Run 提交：
- `experiment_id` + `run_id` + Git SHA/dirty flag、build ID、container digest；
- rule/obs/action/reward schema、board sizes/komi；
- selfplay models、search cfg、temperature schedule、exploration noise；
- dataset snapshot、shard digest、sampling weights 与时间窗口；
- optimizer/hyperparams、训练硬件、random seeds、checkpoint 指纹；
- arena seeds/opening rules、相同 visits/time budget、结果区间、模型发布 decision。

确定性承诺分层：
1. **逻辑级**：相同规则+事件序列重放，状态 hash 必须一致。
2. **CPU 级**：指定版本、seed、硬件约束下的对局与搜索具有可复核结果。
3. **GPU 级**：由于 kernel 和并行调度导致的浮点非确定性，无法天然保证 bitwise 一致；必须记录环境、评估结果区间及数值容忍范围，不能宣称跨硬件逐位复现。

## 7. 风险登记册

| 风险 | 可能后果 | 最早发现方式 | 响应 |
| --- | --- | --- | --- |
| legacy PSK 被误改 SSK | 旧棋谱回放失配 | rules fixture、旧 SGF CI | 规则 preset 隔离、禁止无版本迁移 |
| 死棋未处理致计分误读 | 标签错/棋力异常 | problem position fixture | 不宣称正式裁决；先捕获再 Pass |
| 坐标 x/y 与 row/col 对调 | 策略热力图错位 | 非对称局面转换测试 | Adapter 和版本 spec |
| 重复历史错误压缩 | 超级劫被漏判 | 同盘不同历史对照 | state+history identity |
| 非法动作被静默忽略 | 训练数据污染 | 状态不变式 | 核心层强拒绝 |
| MCTS 价值符号反转 | 策略学反 | toy minimax | 单元测试阻断 |
| 中断分片被训练 | 数据完整性损坏 | kill -9 故障注入 | manifest atomic commit |
| 自我对弈与评测同源 | 看似高胜率但泄漏 | dataset/fixture digest 审计 | 独立评估隔离 |
| Python 全盘扫描瓶颈 | 模拟率过低 | profile/bench | Native 增量优化，保留 reference |
| Web 调度超前设计 | 复杂性和维护成本高 | 无真实使用场景/成本审查 | C0 单机先行 |
| 老棋盘模型不兼容 | 推理形状错 | model manifest validation | 明确 supported board sizes |
| 训练样本利用不当 | 法律与许可风险 | dataset manifest license field | 不接收许可不明外部数据 |

## 8. 外部参考和决策依据

- [README](../../README.md)、[STYLE_AND_ARCHITECTURE](../STYLE_AND_ARCHITECTURE.md)、[规则回顾](../2026-09-21-rules-review.md) 是现有仓库契约的事实源。
- [PettingZoo Go](https://pettingzoo.farama.org/environments/classic/go/) 与 [Gymnasium Env](https://gymnasium.farama.org/api/env/) 说明标准 API；详细版本必须在实现 PR 中 pin。
- [OpenSpiel](https://github.com/google-deepmind/open_spiel) 用于探索通用博弈 API/搜索/benchmark，但规则语义必须单独检查。
- [MiniGo](https://github.com/tensorflow/minigo) 为简化 AlphaZero 风格自我对弈参考。
- [KataGo 自我对弈训练](https://github.com/lightvector/KataGo/blob/master/SelfplayTraining.md) 展示成熟的 selfplay/shuffle/training/export pipeline；大 GPU 集群不是每个 PoC 的前提。

## 9. 本次文档提交的验收定义

本次文档工作仅满足：
- 在 `docs/rl/` 给出**三套方案 + 共享核心资产 + 实施/验收**的互相链接文档；
- 与当前代码/规则约束一致，不把计划模块描述成已存在；
- 关键协议含字段、不变量、故障模式、版本与迁移/回退计划；
- 有可执行的 PR 范围及测试门禁，外部参考清楚；
- GitHub PR 的变更仅包含文档，便于独立评审。

**不在此 PR 的范围**：实际引入 Gym/PettingZoo、PyTorch/MCTS、服务端 API、重写现有 SGF、运行训练或性能 benchmark。上述能力须在后续实现 PR 通过对应门禁后，才能标记实现完成。
