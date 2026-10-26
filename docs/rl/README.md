# Go 强化学习架构提案总览（2026-10-26）

> 状态：Design proposal / 待评审。本文和下列方案均为设计文档，不代表功能已经实现。代码基线：`main` @ `26344bfd4b8d5f588c84753556ebbffce8eefe52`。
> 面向仓库 `1998x-stack/Go`：Python 3.9+ 围棋游戏，非 Go 语言项目。

## 阅读顺序

1. [核心资产与稳定契约](00-core-assets-and-contracts.md)：三套方案共用，优先评审；定义规则、数据、评测、模型和可恢复性协议。
2. [方案 A：研究级 RL 环境](01-plan-a-research-environment.md)：轻依赖、Gymnasium / PettingZoo 适配、性质测试和环境基准。
3. [方案 B：自我对弈训练引擎](02-plan-b-selfplay-training.md)：PUCT-MCTS、策略价值网络、Actor/Learner、样本语义和性能闭环。
4. [方案 C：围棋 AI 平台](03-plan-c-full-platform.md)：人机与 Agent 对战、竞技场、调度控制平面、模型发布、审计与可观测性。
5. [实施路线与独立验收](04-delivery-and-verification.md)：风险、依赖、门禁、测量口径、回退与可执行的 PR 划分。

## 已核验的仓库起点

- `game.py`：回合管理、连续两次 Pass 终局、**Positional Superko（落子时棋盘局面不得重复）**，历史回放 Undo、简单面积计分。
- `gameboard.py`：二维棋盘、棋块和气、提子、区域计分；合法性通过模拟并还原棋盘，当前并非原生语言增量引擎。
- `ai.py`：`RandomAI` / `GreedyAI`；不是策略价值网络，`GreedyAI` 不具备 MCTS。
- `sgf.py`：严格的线性 SGF 子集（SZ/KM/HA/AB 和棋步），不支持完整变化图或所有标准属性。
- `go_game/app.py`：pygame 应用层，`main.py` 兼容 pygbag；根目录 domain modules 暂未迁移。
- `docs/STYLE_AND_ARCHITECTURE.md`：要求无界面规则层不导入 pygame、避免不必要的框架，不进行行为与路径迁移的混杂改动。
- 现存 `test_*.py` 和 `.github/workflows/test.yml` 是回归起点；没有证据支持当前项目已具备完整 RL 训练系统。

该基线与 [2026-09-21-rules-review](../2026-09-21-rules-review.md) 保持一致。以下任何超出此范围的能力均标注为“计划中”。

## 三套设计方案的边界与价值

| 维度 | A 研究级环境 | B 自我对弈引擎 | C 完整平台 |
| --- | --- | --- | --- |
| 核心使用者 | 算法研究者、课程、benchmark | ML 工程师、搜索研究者 | 研究组、产品团队、多 Agent/人类玩家 |
| 主要能力 | 合法动作、奖励与多智能体接口 | MCTS 与策略价值学习、海量 Self-Play | 服务化对局、任务管理、评测、复盘与发布 |
| 非目标 | 训练超强棋手 | 从第一天建设服务集群/UI | 从第一天重写现有 pygame/pygbag |
| 建设成本 | 低~中 | 中~高（GPU 与数据） | 高（运维及安全面） |
| 最易失控风险 | 规则偏差污染研究结果 | 价值符号错误/数据漂移/吞吐不足 | 服务和训练复杂性掩盖算法正确性 |
| 建议开工顺序 | **先实施** | A 核心质量门通过后 | B 可重复闭环后按需要实施 |

三套方案不是三套互不兼容的代码库：它们共享同一个核心领域模型、动作编号、规则版本、数据 schema 与评测协议。A 的规则真值不随 B 的搜索优化和 C 的平台需求改变。

## 不可谈判的架构决策

- **单一事实源**：一次合法落子是否允许，只由 `RulesEngine` 判定。任何前端、MCTS、动作掩码、SGF 回放不得自行另造规则。
- **先定义规则，再谈棋力**：保留现有 `positional-superko + no-suicide + area-scoring` 作为兼容预设 `legacy-psk-v1`。SSK、Japanese territory、死子协商都是新预设/协议，不允许在迁移时悄然切换。
- **传输记录与训练记录分离**：SGF 是棋谱交换格式，不包含完整 MCTS 访问分布、历史合法性证明、模型和运行清单；训练样本另行版本化。
- **稳定坐标契约**：新 RL 标准规定 `a = row * N + col`, `pass = N*N`，row/col 从 0 开始；旧项目 `grid[x][y]` 必须经过适配器，不能直接假定 x 就是 row。
- **结果必须可复核**：同一个游戏的起始状态、规则版本、行为序列、对局结果、训练模型、随机种子和代码版本可一一追踪。
- **控制平面与数据平面隔离**：评估服务只读候选模型；在线服务不能偷偷修改模型；训练失败不应破坏现有桌面/浏览器游戏。
- **正确性优先于单点性能**：原生引擎必须与 Python 规则参考实现差分比对，才能切换为默认实现。

## 一体化目标架构

    [pygame / pygbag]     [Gymnasium / PettingZoo]       [Web / GTP API]
             \                     |                           /
               ------------ Domain API -----------------------
                                 |
                  [Rules / State / Hash / Score]
                                 |
                      [Versioned Record + SGF]
                                 |
             +-------------------+-------------------+
             |                                       |
       [Search + Self-Play]                     [Arena + Evaluator]
             |                                       |
       [Replay Dataset]---->[Learner]------>[Model Registry]
                                                      |
                                         [Inference / Publish API]

**硬性依赖方向**：UI -> Domain；RL Adapter -> Domain；Search -> Domain+Inference；Self-Play -> Search+Record；Learner -> Dataset；Arena -> Registry+Domain；服务化控制平面调用这些稳定接口，Domain 不能反向依赖它们。

## 投资优先级：先积累什么资产

| 资产 | 优先级 | 复用范围 | 何时证明完成 |
| --- | --- | --- | --- |
| 规则内核与金标案例 | P0 | A/B/C | 差分、性质测试、SGF 复盘一致 |
| 行为/观测/奖励/历史版本契约 | P0 | A/B/C | 同一批固定棋局在三个 Adapter 输出一致 |
| 对局记录、样本与可恢复性 | P0 | B/C，也支持 A 实验 | 重放和校验无损；坏记录隔离 |
| 评测竞技场与对手基线 | P0 | A/B/C | 冷启动、换色、配对胜率可重现 |
| Policy/Value 模型与发布工件 | P1 | B/C | schema、规则、模型和推理输出一致 |
| MCTS 与并行批推理 | P1 | B/C | 正确性、吞吐和质量相对基线均达标 |
| 多租户调度/可视化/在线交互 | P2 | C | 故障隔离、权限、资源预算、回退演练通过 |

## 采纳建议

- 默认推荐 **A -> B -> 按需求选 C**，而不是直接实施 C。
- A 的第一个交付是严格可复现的规则与环境测试，不是网页。
- B 的第一个交付是 5×5/9×9 可证明改进的小规模训练闭环，不是“分布式”标签。
- C 的第一个交付是单机可观测的一次人机/Agent 对局及模型版本绑定，不是复杂微服务。
- 各方案均使用 [核心资产契约](00-core-assets-and-contracts.md) 中的版本键，架构变更需要 ADR 和迁移验收。

## 参考资料

- [当前仓库 README](../../README.md)、[代码风格与架构](../STYLE_AND_ARCHITECTURE.md)、[规则审查](../2026-09-21-rules-review.md)
- [PettingZoo Go](https://pettingzoo.farama.org/environments/classic/go/)：动作空间、mask、AEC 适配参考；其规则与观察语义不能代替本仓库真值。
- [Gymnasium Env API](https://gymnasium.farama.org/api/env/)：terminated/truncated 语义。
- [KataGo SelfplayTraining](https://github.com/lightvector/KataGo/blob/master/SelfplayTraining.md)：分离 selfplay/shuffle/train/export 的成熟做法。
- [OpenSpiel](https://github.com/google-deepmind/open_spiel)：通用博弈、算法和多智能体测试参考。

## 文档状态

本次只提交设计，不包含执行后的性能指标、训练棋力宣称或未经验证的代码改动。基准阈值均视为**目标/验收门槛草案**，非实测值；将在 PR 评审与第一次 Benchmark 中冻结。
