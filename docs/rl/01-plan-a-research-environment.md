# 方案 A：研究级围棋强化学习环境（Research Go Environment）

> 提案，不是实现。目标：最小依赖、规则可信、可重复、能供算法研究使用；不把生产训练集群、UI 或超强棋力作为本方案交付。
> 依赖：[核心资产与稳定契约](00-core-assets-and-contracts.md)。

## 1. 目标、非目标与首个用户故事

**目标用户**：强化学习算法研究者、教学、通用博弈 benchmark、单机搜索实验。

用户故事：研究者可以在 5×5、9×9 上选择一个明确规则预设，使用固定 seed 重置环境，取得合法动作 mask、保存完整对局、与 Random/Greedy/固定模型对战，运行自己的 PPO、DQN、REINFORCE 或 MCTS，而不修改规则引擎。

**不做**：宣称标准比赛全规则裁决、替用户训练高段位棋手、将环境细节绑死某一种算法；不强制安装 GPU、PyTorch 或 pygame。

## 2. 核心资产贡献

A 是三套方案共同的“地基建设”阶段，而不是最低配 UI：
- `RuleSpec` + `GameState` + `RulesEngine` 作为规则真值；
- `ActionSpec`/`ObservationSpec`/`RewardSpec`，含版本与坐标；
- 独立的 `Arena` 测试驱动和黄金规则 fixtures；
- `EpisodeRecord` 与重放 + seed + manifest；
- 以真实测试/benchmark 证明环境行为正确，性能指标可复现。

这些资产要能够在没有 Gymnasium/PettingZoo 的情况下独立使用。来自 gym 的 `Space` 对象不应出现在 domain 模型内。

## 3. 目标目录（计划结构）

    go_game/
      core/{rules,state,scoring,history,codec}.py
      rl/{specs,observation,mask,rewards,gym_env,pettingzoo_env}.py
      records/{events,replay,sgf_bridge}.py
      eval/{fixtures,agents,arena,statistics,benchmarks}.py
    tests/{core,rl,records,eval}/
    benchmarks/{rules,env}/
    docs/rl/...
    game.py / gameboard.py / sgf.py     # 暂保留兼容 shim
    main.py / go_game/app.py            # 原 pygame/pygbag 入口保持可用

每一步迁移用单独 PR；不可在“纯机械迁移”同 PR 悄然替换旧规则。已有 `tests/test_logging.py` 与根目录 `test_*.py` 保持能够发现与执行。

## 4. 环境协议与动作语义

### 4.1 原生协议（不依赖外部框架）

`CoreGoEnv` 支持：
- `reset(rule_spec, seed, initial_state?) -> StateView`；
- `step(action) -> Transition`；
- `legal_actions() -> bool[N*N+1]`；
- `serialize()/load()/clone()/replay()`；
- `current_player(), score(), outcome(), is_terminal()`；
- `render_ascii()`（轻依赖；pygame 渲染通过原 UI 适配）。
- 参数版本和异常类型必须公开，训练算法不可修改 domain 私有属性绕过核验。

`StateView` 明示 `player_to_move`、`terminal_reason`、`rule_id`、`state_fingerprint`，以及经过 schema 编码的 `observation`。`score()` 与 `finish()` 区分；结果中明示“未自动判死子”。

### 4.2 PettingZoo AEC

`GoAECEnv` 作为原生两人零和环境首选：
- `possible_agents = ["black_0","white_0"]`；每步只有一个当前行动方；
- 当前行动方 `action_space = Discrete(N*N+1)`；
- `observe(agent)` 返回该 agent 的规则规定观察和合法动作 mask；非行动方 mask 约定明示并测试；
- `step(pass_action)` 合法，结算 reward 与 AEC reward 累积机制一致；
- 使用 PettingZoo AEC API tests（适配新版本 API 并锁版本）和自建语义测试；
- 非法动作行为明确配置（实验默认 raise，兼容策略可用 forfeit），不能为空操作；
- 终局/截断需要给所有 agent 一致的完成/清算信息，不能继续允许落子。

文档上的 PettingZoo `classic/go-v5` 仅作为接口参考与**同预设下**的差分候选，不应由于其默认 19×19、komi 7.5 或具体违规惩罚而覆盖本项目语义。

### 4.3 Gymnasium（对手包装）

单智能体 `GoVsOpponentEnv` 的 `step(action)`：受控玩家落一手 -> 如未结束，固定对手执行至受控方下一个决策点或终局 -> 返回受控方观察。需要固定对手策略版本、种子和玩家颜色，`info` 明示内部对手回合数与终局原因。

不能将“黑棋下一手 / 白棋下一手”交替的 PettingZoo 语义直接塞进 Gym 的单智能体 `step` 并宣称训练目标不变。对于双方都学习，优先 AEC；Gym 的最小奖励目标是当前受控 agent 的**局级净输赢**而不是“环境当前下一个玩家”的价值。

Gymnasium `terminated` 与 `truncated` 必须严格分离；`max_moves` 截断返回 `truncated=True` 且不伪造胜负标签。时间限制因外部因素触发时同理。

### 4.4 空间、观察、Action Mask

9×9 action 取值 0..81，Pass=81；19×19 为 0..361，Pass=361。除终局外 Pass 可选。向量长度 `N*N+1` 不变，需对每种尺寸重建/隔离 `spaces`，不允许在同一 Gym 实例中不通知地改变 Space。

建议 v1 使用：
- `observation` = dict，`board` 与 `history` 为已规范编码张量；
- `action_mask` = int8/bool 向量；
- `metadata` = 可以放入 info 的 rule_id、komi、to_play，但要评估是否为 policy 必须输入；
- observation 可配置 `obs-basic-v1`、`obs-history-v1`；两个版本分别记录 C、dtype、历史帧含义，不共享不兼容的模型权重。

关键反例：只提供当前棋盘的观察无法完整预测 PSK 的动作合法性（有历史依赖）。因此适配器提供 mask，不应给“完全 Markov 状态”错误标签；研究用算法若要求 Markov，则采用完整规则历史编码、记忆网络或重新选择无历史依赖的研究规则并明确实验局限。

## 5. 规则可靠性建设与失败模式

| 主题 | 参考真值与验收 |
| --- | --- |
| 提子 | 由完整 group 计算，一组相邻多边只计一次 |
| 自杀与逆收气 | 落子先提对方、后检查己方棋块气 |
| 超级劫 | 新键包含初始历史；测试多手重复及不同历史同盘 |
| 让子/贴目 | 兼容 19×19 旧 let-handicap 语义；新规则显式补充 |
| two-pass | 两次连续 Pass 正常结算，落子重置 pass count |
| 计分 | 单方包围空域，`area_simple` 不会神奇去除死子 |
| SGF | Legacy SGF 子集无损往返；超出支持范围清楚失败 |
| Undo/Clone | 100% 恢复棋盘、历史、行棋方、captured、score |
| D4 | 非对称局面上 moves/masks/outcomes 经过逆变换完全对应 |
| 非法动作 | 不静默 step，不损坏当前状态，不泄漏下一个玩家 |

为规则属性测试定义可生成的合法对局（5×5 和 9×9）、重复输入、断点重放、捕获统计守恒、执行-回滚等性质；所有失败记录 seed、rule_id 和最小重现棋谱。可考虑以 OpenSpiel/其他引擎作为差分 oracle，但必须先对齐 scoring、ko、suicide、terminal 预设。

## 6. API 交付示例（伪代码）

    env = GoAECEnv(rule_id="research-psk-v1", board_size=9, komi_half_points=11)
    env.reset(seed=20261026)
    while env.agents:
        actor = env.agent_selection
        obs, reward, terminated, truncated, info = env.last()
        if terminated or truncated:
            env.step(None)
        else:
            legal = allowed_indices(obs["action_mask"])
            env.step(policy_choose(legal))
    record = env.export_game_record()
    verified = replay_and_verify(record)

注意：此代码为**目标 API 示例**，不是仓库目前可运行的导入路径。

## 7. 衡量与版本目标

### 功能门禁（必须）
- 根目录 legacy 单元测试、SGF 测试、py39/311/313 CI 继续运行；
- AEC API test + 基础 Gymnasium env checker 通过；另有明确自定义零和/视角/截断测试；
- golden fixtures 和随机生成对局全部可重放，非法动作无状态突变；
- 对 fixture 集执行完整 `apply/undo/clone/SGF` 交叉对照，结果相同；
- 9×9 对局可固定 seed 复跑，硬件随机性有标记。

### 性能门禁（测后冻结，不捏造数字）
从现有 Python `Game.can_play`/ `GameBoard.resulting_key` 开始测：分别记录 5×5 / 9×9 / 19×19 的 masks/s、step/s、undo/s 与单进程 games/hour。目标 P1 是没有明显正确性回归并提供可比较 baseline；真正性能改造属于后续 profile 驱动的 PR。

### 交付里程碑

| PR | 内容 | 合并门槛 |
| --- | --- | --- |
| A0 | 固定规则 fixtures + `RuleSpec` + 行为黄金测试 | legacy 行为不变 |
| A1 | 纯 domain adapter、稳定坐标/动作编码 | 交叉对照与非对称坐标测试通过 |
| A2 | PettingZoo AEC wrapper + API tests | 双方 reward/mask/terminal 测试通过 |
| A3 | Gym 固定对手 wrapper + baselines | 与 AEC 对局计分一致 |
| A4 | Record/replay、SGF bridge、benchmark CLI | 记录可复核且结果报告带 manifest |

## 8. 方案 A 的独立可用性

A 完成后，用户可以安装轻量 `go_game[rl]`（未来包装选项），在 CPU 上训练小网络或执行自己的算法，使用 Random/Greedy 和独立 Arena 跑 benchmark；运行项目原来的 pygame/pygbag 无需依赖 GPU。即使 B/C 永远不实施，A 的核心资产也能独立保值。

## 9. 开放决策与回退

需要在 A0 冻结：默认贴目（不能把既有默认与 9×9 教学默认混淆）、超步数截断策略、illegal action 策略、历史观测长度、是否存在随机开局。每项进入 `EnvSpec` 并保存实验元数据。遇到兼容回归时切换回 legacy domain adapter，而不是通过临时修补 SGF 历史掩盖 bug。

关联：[项目总览](README.md) | [核心资产](00-core-assets-and-contracts.md) | [实施与验收](04-delivery-and-verification.md)。
