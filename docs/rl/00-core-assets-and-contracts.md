# 核心资产设计：可信围棋领域内核、版本化数据与评测真值

> 适用于方案 A/B/C。状态：设计契约 v0.1；不表示仓库已实现。
> 变更规则：任何语义破坏必须提升主要版本、发布迁移器与黄金回归夹具；不允许只修改网络/前端解释字段。

## 1. 资产分层及所有权

| 资产 | 事实源/拥有者 | 稳定输出 | 不可变约束 |
| --- | --- | --- | --- |
| Rules Kernel | `go_game.core.rules`（计划包） | 合法走法、状态迁移、终局 | 唯一规则真值；不导入 pygame/PyTorch |
| Game State & Hash | `go_game.core.state` | 快照、undo token、历史 key | clone 与重放等价；历史不丢失 |
| Codec / Feature Spec | `go_game.rl.codec` | 编码后的 planes、action mask | 坐标、视角、历史和 dtype 有版本 |
| Record Ledger | `go_game.records` | game events、canonical replay | 追加不可变、幂等、校验 |
| Training Dataset | `go_game.training.data` | policy/value target + provenance | 可检测缺失、规则漂移和数据污染 |
| Evaluation Suite | `go_game.eval` | fixtures、arena、统计报表 | 被评模型不可自行决定评测结果 |
| Model Registry | `go_game.models` | 内容寻址模型 manifest | 规则与观测 schema 明确兼容 |
| Search Engine | `go_game.search` | 根策略、visit stats、PV | 不负责判定规则；依赖 Kernel |
| Service Protocol | `go_game.protocol` | command/event API | 版本化、认证、可恢复（仅方案 C） |

优先保证前五项不随某一算法生命周期废弃；MCTS、GPU 优化、Web UI 是可以替换的加速/表现层。

## 2. 唯一规则源：Ruleset 与 RulesVersion

### 2.1 兼容预设与扩展预设

兼容性基线 `legacy-psk-v1` 必须与当前 `game.py` 可观察行为严格核对：
- board_size: 2..26（当前构造范围，不代表所有 sizes 已被赛事规则验证）；
- turn_order: 黑先，特定 19×19 固定让子时白先；
- suicide: forbidden；
- repetition: positional_superko_on_placements；初始局面加入 seen；Pass 不受重复局面限制；
- end: consecutive_two_passes；
- scoring: stones + 仅由单一颜色围住的空点，white 加 komi；**不自动判死子**；
- terminal state: 已结束不允许再下；
- SGF：旧格式及旧坐标维持适配，缺失能力需报错。

拟议新增 `research-psk-v1`：保持 PSK、禁止自杀、简单 Area Scoring，但显式提供 max_moves 截断、seed、标准化规则 manifest。拟议 `research-ssk-v1`：Situational Superko；须重新定义历史键为 (完整棋盘, 下一手方)，并处理 Pass/连续 Pass 及初始状态，不允许假装与 PSK 等价。日本式 Territory Scoring、特殊规则、死子协商均推迟独立插件设计。

RuleSpec（JSON 可序列化）至少包含：

    {
      "rule_id": "legacy-psk-v1",
      "rules_schema_version": 1,
      "board_size": 9,
      "komi_half_points": 11,
      "ko_rule": "positional_superko",
      "suicide": "forbidden",
      "scoring": "area_simple",
      "end_protocol": "two_pass_no_adjudication",
      "handicap": {"kind": "none", "placements": []}
    }

约束：komi 推荐以半目整数储存以避免浮点比较；规则支持非半目贴目时需扩充精确有理数而非隐式截断。拒绝未知 rule_id；规则变更不得重解释已存历史。把“不包含自动死子裁决”直接写入结果解释，避免研究胜率被误当职业围棋裁决。

### 2.2 状态模型与可重放性

定义 `GameState` 为包含规则、棋盘、当前行动方、终局标志、连续 Pass、历史完整性、初始摆子以及必要的缓存版本的状态对象；`BoardSnapshot` 仅是不可变盘面，不等于完整状态。

**核心区分**：
- `board_hash`：棋盘 Zobrist 哈希，用于快速比较；
- `situation_hash`：盘面 + 行棋方，用于 SSK；
- `state_fingerprint`：规则版本 + 行棋方 + 两次 Pass 状态 + 历史承诺（如规范事件摘要）+ 棋盘，用于精确复盘校验；
- `position_history`：超级劫判断所需的完整、不可静默裁剪的状态摘要集合与必要碰撞校验数据。

Zobrist 哈希是候选过滤而不是无碰撞身份；在高价值评测/回放模式中，对哈希相等需检查规范盘面或可靠的精确快照。**同盘面同当前玩家的不同历史，合法动作可不同**，不能仅凭棋盘键复用合法动作缓存或 MCTS transposition。

### 2.3 行为接口（算法无关）

    RulesEngine.new_game(rule_spec, seed=None) -> GameState
    RulesEngine.legal_actions(state) -> Bitset[N*N+1]
    RulesEngine.try_apply(state, action) -> MoveResult
    RulesEngine.apply_in_place(state, action) -> UndoToken
    RulesEngine.undo(state, token) -> None
    RulesEngine.clone(state) -> GameState
    RulesEngine.score(state) -> ScoreReport
    RulesEngine.replay(rule_spec, events) -> GameState

`try_apply` 遇非法动作返回结构化 error、状态不变。In-place 高性能接口只允许受控调用，Undo token 必须绑定状态代际、不可跨局复用，错误恢复必须 fail-closed。`score` 不隐式终止游戏；评分内容必须含黑白棋盘面积、贴目、结果、`scoring_method`、`adjudication_status`。超步数是研究环境的 `truncated`，**不能默认为某方输了**。

## 3. 坐标、动作、观察、奖励：跨方案 ABI

### 3.1 坐标迁移风险

仓库中 `grid[x][y]` 的两个索引不是已经声明的 RL row/col。新标准要求所有交互接口按 `(row, col)` 定义：

    action = row * board_size + col
    pass_action = board_size * board_size
    decode(a) = (a // board_size, a % board_size)  # only a < N*N

SGF 文本的横纵编码不能直接用整数位置代替：需要 `LegacyCoordinateAdapter` 和 `SgfCoordinateAdapter`，用非对称棋形（例如 row=1,col=4 的落子）回归，排除镜像/转置错误。旧引擎和 UI 均保持原契约，直至新适配器通过一致性门禁。

### 3.2 观察规范（`obs-v1`）

- 形状：`float32[C,N,N]` 或严格指定的二值张量，Channel-first；相同 `observation_spec_id` 的通道顺序绝不改变。
- 视角：当前 to_play 的己方与对方，不在同一次训练里混用固定黑棋视角。
- 必含：己方棋子、对手棋子、行棋方/颜色指示、近 K 步历史（不足补零）、最近动作、可选规则/贴目全局元数据。
- legality 不从有限历史预测：独立由完整 GameState 得到 `bool[N*N+1]` 的 action mask。
- 对称性 D4：旋转/翻转棋盘、历史特征、mask、动作/策略向量时同步变换，Pass 保持不变；贴目符号按网络明确的视角契约表示。
- 视角切换与历史帧处理需要固定：帧中黑白通道是否随当前行动方变换，都要在 schema 中明示；不能只在最新一帧变换。

注意：有限 K 帧历史无法完整表达 PSK/SSK 所需的历史集合，因此 observation 对使用神经网络的 agent 可能非 Markov。搜索必须持有完整的环境状态；基准报告必须说明 partial observability 或附加 history encoding。

### 3.3 奖励与终止规范（`reward-v1`）

- 标准 terminal zero-sum：胜方 +1、负方 -1、和棋 0；以**被采样时行动方**为视角储存每步 `z_t`。
- 非终局奖励默认 0；Area score margin / score ownership 等可作为独立辅助标签，不擅自替换零和主目标。
- Gymnasium `terminated=True` 仅代表规则终局；`truncated=True` 代表训练预算/外部时间限制；二者信息不能混同。
- PettingZoo AEC：轮流玩家归属和结算奖励遵循 AEC 协议，不将 actor viewpoint reward 直接当作所有 agent 的 reward。
- 非法动作：底层拒绝；适配层可选择 `raise` / `forfeit`，策略需写入 EnvSpec 且固定到评测基准。Pass 默认合法，终局状态全部不可行动。

### 3.4 MCTS 价值约定（最关键不变量）

神经网络 `v(s)` 表示 **state.to_play** 视角的 [-1,+1] 估值。父状态与子状态发生走子方交换，backup 时符号相反；末手结束后终局必须以一致视角结算。唯一检验用夹具：只有一步取胜的局面，正确一手经过树搜索回传后应使父方根值为正。对早终局、pass、换色、探索噪声关闭等写固定测试。

## 4. 对局事件账本（`game-record-v1`）

推荐 canonical 事件定义：

    {
      "schema": "game-record-v1",
      "game_id": "uuid",
      "seq": 17,
      "event_id": "uuid",
      "ruleset_id": "research-psk-v1",
      "state_before": "sha256:...",
      "actor": "B",
      "action": {"kind": "place", "row": 3, "col": 4},
      "state_after": "sha256:...",
      "actor_model_id": "model-sha256:...",
      "wall_time_utc": "...",
      "decision_metadata": {"search_visits": 128}
    }

存储规范：
- 每游戏事件 `seq` 单调且从 0 连续；同 `event_id` 幂等写，不可更改不同 payload；
- 每步验证 `state_before` 与前步 `state_after`、动作合法性和 actor；不符则隔离该游戏；
- 初始记录包含 rule spec、初始棋面/让子、明确贴目、seed、initial_state_hash；
- result event 明示原因：two_pass、resignation（如果开启）、adjudicated、truncation、invalid_forfeit；
- event schema 与 SGF 双轨，SGF 作为外部交换或人工查看，不承担全部训练溯源；
- 支持失败恢复：snapshot + 后续 append-only events；校验和与对象存储原子提交；重复上报只接受相同内容；
- 日志和遥测不包含原始完整棋谱（与当前 logging contract 一致），棋谱进入权限隔离的记录存储。

完整检验：通过 `replay(initial_state, events)` 重建每一步棋盘、当前玩家、捕获数和合法动作；与提交时的 `state_after` 一一一致。记录内容不可直接信任，要经过规则验证。

## 5. 训练样本仓库（`go-sample-v1`）

最小样本字段：

    game_id; ply; ruleset_id; board_size; komi_half_points
    observation_spec_id; action_spec_id; reward_spec_id
    model_id; search_config_hash; sample_actor_color
    features; packed_action_mask; mcts_visit_counts; target_pi
    final_result; target_z_from_sample_actor; generation_seed
    record_digest; code_revision; engine_build_id

原则：
1. `target_pi` 是在**合法动作**上的 MCTS visit 分布；温度为 0 或单步随机选择不等价于访次分布；精确保留 visits 和变换时温度。
2. 每条样本绑定源 game digest，必须能恢复它对应的盘面和 to_play；黑白样本价值标签按照原局最后胜负换算。
3. 训练数据应支持文件不可变版本、分片 manifest（schema、行数、校验和、规则分布、训练/评估划分）、完成标记；禁止半写文件被 Learner 消费。
4. 分片损坏、NaN、mask 空集（非终局）、不匹配动作长度、模型版本缺失、非法概率质量、无穷值均隔离，不能静默修复。
5. 运行数据来自自己生成或授权的数据；外部棋谱需标注来源、使用许可及去重方法。固定评测棋谱从训练集合中排除，防止指标泄漏。
6. `sample-v1` 推荐 Parquet / Arrow metadata + 压缩张量（小规模可 NPZ）；存储格式不应成为数据语义的唯一规范，读写兼容必须跨版本验证。
7. 增加 Dataset Inspector：样本总数、有效率、胜负/棋盘/贴目分布、非法 action mass、数据年龄、policy entropy、重复局比率、来源 hash 完整率。

## 6. 评估基准作为不可变资产

### 6.1 金标规则测试库

`tests/fixtures/go-rules/v1/`（计划）包括：
- 单/多棋块提子、一个组多方向相邻只提一次、接不归、打劫及跨多手超级劫；
- 盘边、盘角、禁入点、提子后看似自杀实际合法、已占点非法；
- 不同历史但同盘面的合法性、首局历史、两次 Pass、终局后拒绝走子；
- 让子初始行动方、Undo + Replay 捕获数、贴目、计分、输赢；
- 非对称坐标 SGF round-trip、非法输入强拒绝、D4 对称变换等价；
- 需覆盖面积极端测试、未知死子裁决状态而不是误当合法判死。
差分测试必须确认对方规则 preset 等价，不能拿允许自杀的规则与禁止自杀的实现直接比。

### 6.2 棋力竞技场

- 同配置两模型轮换黑白，固定成对种子、相同规则/贴目/搜索预算，禁止在竞技场探索噪声与动态换网；
- 固定旧模型、RandomAI、GreedyAI、纯 MCTS 等基线；人类对局不作为唯一客观标尺；
- 报告总胜负/和棋、胜率及 95% 置信区间、换色胜率、平均步数、搜索 visits、平均/尾部延迟、拒绝率和完整规则 manifest；
- 强度指标可以使用成对胜率、Elo/Bradley-Terry 等模型，但需明确区间和小样本不确定性，不把“训练 loss 下降”当棋力提升；
- 升级关卡：候选模型对当前 champion 的配对赛达到事先冻结的统计验收阈值，并保证与 baseline 的非回退要求；样本数和阈值需在训练前登记，不根据结果临时移动。
- 存储每场对局的双方 manifest、胜负、opening seed、规则、完整记录 ID 与评测代码 revision。

### 6.3 性能基准

分开测量 `legal_actions/s`、`apply+undo/s`、`clone/s`、每秒 MCTS simulations、模型批量推理 positions/s、完整自我对弈 games/hour、GPU 利用率与成本/有效训练样本。
每个结果必须附棋盘尺寸、平均局长、规则、硬件、Python/编译器版本、批量大小、seed 和样本数；性能门槛由 A 的基线先测再冻结，不能宣称尚未运行的速度提升。

## 7. 模型与实验清单（`model-manifest-v1`）

不可变模型至少含：
- `model_id`（权重内容哈希）、`checkpoint_uri`、`architecture_id`、weights digest、signature；
- `observation_spec_id`、`action_spec_id`、`reward_spec_id`、`supported_rulesets`、board sizes / padding strategy；
- framework/opset/dtype、training code commit、dataset manifest digest、train run ID、seed；
- eval report digest、父模型 ID、发布时间及 champion/candidate/retired 阶段；
- 推理输入/输出形状、mask/归一化语义、价值当前行动方视角。

导出后的推理产物与 PyTorch 训练 checkpoint 在固定样本上须做近似数值一致性测试；模型发布的原子指针仅在 registry 校验与 Arena gate 后更新，失败自动回到上一个 known-good 模型。

## 8. 演进路径与 ADR 决策清单

| 编号 | 需要批准的决策 | 默认取向 |
| --- | --- | --- |
| ADR-001 | 规则默认值 | 旧游戏固定 `legacy-psk-v1`，RL `research-psk-v1` |
| ADR-002 | 核心实现语言 | 第一阶段 Python 真值，确认瓶颈后 Rust/C++ 可选 |
| ADR-003 | 动作与坐标 | row-major，新适配器兼容旧 `grid[x][y]` |
| ADR-004 | 数据事件 | append-only + content hashes + idempotency |
| ADR-005 | 训练分离 | 数据产生 / 学习 / 评估分离，不混用私有内存状态 |
| ADR-006 | 模型视角 | `value = 当前行动方的期望结果` |
| ADR-007 | 死子处理 | 初期明确不支持自动裁决；独立协议未来补充 |
| ADR-008 | 超级劫历史 | 用完整正确性信息，不以固定大小 hash-only cache 取代 |
| ADR-009 | 随机性和实验 | 所有可设 seed；硬件非确定性必须记录并界定 |
| ADR-010 | 安全与发布 | 训练代码不能直接改在线 champion；工件需校验 |

## 9. 故障模型与恢复演练

| 故障 | 防护 | 故障注入/验收 |
| --- | --- | --- |
| 非法落子被搜索接受 | 所有搜索分支调用唯一 rule kernel | 构造劫与自杀局面，零违规 |
| 父子价值符号颠倒 | 搜索节点视角不变量、一步胜夹具 | 备份结果与 minimax 对照 |
| 游戏事件重复、乱序 | game_id+seq+event_id、CAS/唯一索引 | 断连重发不多一手 |
| 一半数据文件被训练 | 分片原子提交+manifest 完成标记 | 人为中断后只读完整分片 |
| 推理模型版本漂移 | 每局 pin model digest | 模型热更新前后同局不混用 |
| 训练数据/评测污染 | 独立 fixture 划分、digest 审计 | 重复棋谱测试触发隔离 |
| Undo 恢复错误 | 逐步对照 replay oracle | 混合提子/Pass/让子回放 |
| D4 augmentation 错位 | inverse transform round-trip | mask、policy、历史一致 |
| 超级劫 hash 碰撞 | 碰撞后精确盘面比对 | 强制模拟 collision 能正确拒绝/接受 |
| GPU worker 退出 | checkpoint+幂等游戏记录 | 恢复后不重复计数 |

## 10. 对旧代码的渐进迁移

阶段 0：冻结旧引擎行为与 fixtures。不要先把 `game.py` 重写成完全不同结构。
阶段 1：引入 `RuleSpec` / `GameStateAdapter` / `CoordinateAdapter`，直接包装现有 `Game`；仅新增 tests。
阶段 2：收敛 domain API；`game.py`、`gameboard.py`、`sgf.py` 继续通过 shim 兼容，pygame/pygbag 保持原入口。
阶段 3：实现独立纯 Python 参考版本或抽离现有实现，证明跨版本与旧棋局结果一致；给新规则引擎建立第二真值源。
阶段 4：实测性能瓶颈后引入原生语言；新引擎须通过完整差分测试 + perf report，启动时可显式选择后端并可以回退。
阶段 5：在规则 / 数据 / 评测三项资产被冻结后，才允许 B/C 默认复用。

**Definition of Done（核心资产）**：每次合并需同时提交行为契约版本、回归案例、跨模块消费测试、对应 changelog/ADR、恢复路径；如果只具备 UML 而缺乏可重复验证，这项资产尚未交付。
