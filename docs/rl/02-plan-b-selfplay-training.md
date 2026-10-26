# 方案 B：AlphaZero 风格自我对弈训练引擎（Self-Play Training Engine）

> 状态：深度设计提案。**前提**：方案 A 的规则契约、历史正确性、对局记录与评测门禁已通过。不宣称能短期达到 KataGo 棋力。
> 共用核心资产：[00-core-assets-and-contracts.md](00-core-assets-and-contracts.md)。

## 1. 产品定义与研究假设

以单机 5×5/9×9 可复现闭环为起点，逐步扩展 13×13/19×19。主要假设：在固定规则、计算预算与相同评测条件下，神经网络引导的 PUCT-MCTS 自我对弈产生的策略与价值训练数据，可使候选模型逐步优于随机、贪心和较弱的历史模型。

**成功定义不是 loss 降低**，而是独立 Arena 中有统计证据的棋力改进、可重放对局、数据可溯源、性能与单位成本可量化。

非目标：直接复制 KataGo 全部复杂技巧、训练数据未经授权的外部棋谱、第一阶段即建设 GPU 集群、在搜索实现中复制另一份围棋规则。

## 2. 训练闭环与组件隔离

    Rules Kernel <----> PUCT Search <----> Batched Inference
         |                   |
         |                   v
         +------------> Self-Play Actor
                             |
                     Canonical Game Ledger
                             |
                  Shard Validator / Replay Buffer
                             |
                    Policy-Value Learner
                             |
                Candidate Model + Manifest
                             |
                  Arena vs Frozen Champion
                             |
                Promotion Gate / Registry
                             |
                         New Actors

区分四条可追踪链：规则语义、训练样本、模型工件、评估证据。Actor 必须绑定单局固定的 `rule_id` / `model_id` / `search_config_id`；可以在下一局切换到新模型，但同一局任意混用模型会导致难以诊断的 off-policy 数据，除非显式在 record 中编码。

### 进程角色

- **Actor**：执行多局 self-play，维护真实状态与搜索树，生成 visits/value/游戏 events；Actor 失败不可提交半局胜负当完整游戏。
- **Inference Server**：按模型版本聚合跨游戏请求、批量输出 logits/value；输入 shape、board size、dtype 和 feature spec 校验。
- **Shuffler/Validator**：游戏尾声算出每个状态的 `z_t`，检查合法性与样本 manifest，去重并写完成分片。
- **Learner**：从已完成不可变分片训练，输出 checkpoint，记录数据窗口、优化器和随机状态。
- **Evaluator/Arena**：使用与 self-play 分离的 worker/数据/固定 seed，评估候选和 champion，生成独立报告。
- **Registry**：候选-正式指针的原子提交，基于 Arena gate，永不直接用最新 checkpoint 覆盖在线模型。

## 3. PUCT-MCTS 算法契约

节点与边：
- Node 持有 state identity（包括历史依赖）、`to_play`、terminal、search metadata；
- Edge 持有 `N(s,a)`、`W(s,a)`、`Q(s,a)=W/N`、`P(s,a)`、child；
- PUCT 推荐明确从**父 state.to_play**视角定义 `Q`，行动选择最大化 `Q+U`。

    U(s,a) = c_puct * P(s,a) * sqrt(sum_b N(s,b)) / (1 + N(s,a))
    a* = argmax_a [ Q(s,a) + U(s,a) ] over legal actions

注意式子是初始 baseline，不代表后期所有超参数必须固定。价值定义：`network_value(s)` 为当前行动方视角；展开 child 后向父边写入 **相反符号**（若存在换手），且每一层回传按边视角正确翻转。测试不能只检查根数值范围，必须检查已知最优一步获胜的小棋盘反例。

### 搜索路径

1. root state 从 Rules Kernel clone 或 apply/undo；legal mask 由规则内核提供，禁止 search 重写 ko；
2. select 时选择合法边，若已到 terminal 则按确切最终结果计算叶价值；
3. 首次 expand：序列化神经网络输入、合批预测、对非法 logits mask 为负无穷、稳定 softmax；
4. 叶估值来自网络的当前行动方视角，已终局则不调用网络；
5. backup 按定义的 Q 视角变号；
6. 根访问次数构造 policy target：`pi(a) = N(s,a)^(1/tau) / sum_b N(s,b)^(1/tau)`（tau->0 时采用最大访问动作）；
7. 采样落子可在开局使用温度和根 Dirichlet 探索噪声，竞技场关闭；输出 visits、P/Q、root value 与策略摘要。

**防错清单**：
- 非法动作永远 N=0 且不可被 select；
- Pass 是真正动作，而不是“无合法棋点才可 Pass”；
- 搜索节点的超劫历史不能用纯棋盘 hash 去重；
- `undo` 失败必须终止本次 search 并标记数据作废；
- 接收到不匹配 model_id/spec 的推理响应，必须拒绝，不得错绑定；
- 超时/资源中断不是比赛输赢，必须标注 truncated/search_budget_exhausted；
- 根树复用要求父子状态 fingerprint、rule_id、model_id、search_cfg 均匹配。

## 4. 网络设计：从可验证小模型起步

### 第一版 `pv-resnet-small-v1`

- 输入：统一 `obs-history-v1` 的 `[C,N,N]`，且全局可配置特征准确传入；不在网络里偷偷猜贴目。
- 主干：轻量 CNN/Residual blocks，针对 5×5/9×9 可快速迭代；需要通过形状测试覆盖所有配置。
- Policy head：`N*N+1` logits，最后 1 个专属于 Pass；mask 应用与 log-softmax 在稳定精度下进行。
- Value head：`tanh` 标量 [-1,1]，严格定义为**当前行动方**预期胜负。
- 扩展：score margin head / ownership head / uncertainty head 可作为辅助训练目标，但必须有真实、有质量的标签并在模型 manifest 中版本化；KataGo 风格多目标是后期实验而非 P0 前置条件。

损失函数草案：

    L = lambda_p * CE(target_pi, masked_policy_logits)
      + lambda_v * MSE(target_z, predicted_value)
      + lambda_reg * weight_decay_penalty

注意 optimizer weight_decay 与显式 L2 正则不要无意重复叠加；归一化损失时按有效样本权重/规则分布处理；所有训练样本的非法动作 policy mass 必须是 0。

### 训练稳定性

- 前期采用小 batch、固定学习率基线和可控制的 replay window，先证实不崩溃，再逐步调参。
- checkpoint 必须同时保存模型权重、optimizer、scheduler、grad scaler、迭代步数、随机数状态与完整训练 manifest。
- 若采用 AMP，检查梯度异常、NaN/Inf、梯度裁剪效果；数值失败时跳过坏 batch 并审计，不能伪装训练成功。
- 测数据分布漂移：黑白偏置、快速双 Pass、局长异常、value 极化、policy entropy 退化、相同开局过度重复。
- 快速自我对弈与离线监督混合训练要标注来源，不能简单把 Elo 变化归因于单个新策略。

## 5. Self-Play 数据契约

每局：
- 必填 `game_id`, rule spec, komi, engine version, model digest, seed, search config, initial history key, moves, outcome；
- 每个 ply 写 `observation_spec`, `action_mask`, `visit_counts`, `policy_target`, `root_value`, to_play, ruleset, source state fingerprint；
- 结束时后填 `target_z = winner_result_from_that_ply_to_play`；
- 若中途 actor 崩溃，该局记 aborted，不能充当有监督最终胜负的完整局；
- 写分片前重新 replay 全局校验；只接收 verified records，抽样审计严格复现；
- Replay Buffer 按规则、board size、model age、color/komi 分层采样，避免规模上来后新数据被大规模老数据淹没；
- checkpoint/训练输出只引用完成的 immutable shard manifest，不读取正在追加的文件。

示例目标行（说明 schema，非已存在文件）：

    {
      "game_id": "g-...",
      "ply": 25,
      "to_play": "W",
      "board_size": 9,
      "rule_id": "research-psk-v1",
      "obs_spec_id": "obs-history-v1",
      "model_id": "sha256:...",
      "search_config_id": "search-128-v1",
      "visits": [0,4,8,"...",0],
      "target_pi": "normalized-visits",
      "target_z": -1,
      "state_digest": "sha256:..."
    }

## 6. 自我博弈的病理现象与防御

| 现象 | 早期告警 | 对策 |
| --- | --- | --- |
| 两边不断空转/早早 Pass | 平均局长与 pass 比例畸形 | 固定样本复盘、结果合法性测试；训练可改变探索，但不可暗改计分 |
| 自我对弈过度同质化 | opening diversity/有效状态数下降 | 根噪声、开局温度、历史对手池 |
| 黑白偏差 | 换色配对比赛差异异常 | 交换颜色、贴目分桶、显式棋手视角 |
| 自举强化环境漏洞 | 评分异常、规则夹具不通过 | 内核 gating、差分、每场 record replay |
| 训练指标好但棋力差 | loss 降、Arena 胜率无改进 | 独立冻结评估+champion 保留 |
| 价值反馈错位 | MCTS 在明显必胜局反选 | 一步获胜 + 深度2 minimax 对照 |
| 搜索成本爆炸 | inference p95、actor queue 增长 | batched inference、队列背压、限额和剖析 |
| 模型更新污染 | 一局包含多个不兼容权重 | per-game model pin、digest 验证 |

避免凭经验直接启用自动认输阈值：误判认输会污染最终胜负标签。若后期引入，必须设计有对照的错误认输率检测与抽样继续对局审核。

## 7. 性能工程与资源计划

**先 profile，再换语言**：规则层目前基于 Python 二维列表、深拷贝和逐点局面模拟；大规模 MCTS 的显著瓶颈可能在合法动作生成与 `clone`，但要以基准数据确认。

三层优化路线：
1. Python：避免不必要全盘扫描、缓存一致合法 mask、增量更新简单数据结构；保留正确性对照。
2. Native：必要时选 Rust/PyO3 或 C++/pybind11，链路 `apply/undo`、union-find/棋块气增量管理、Zobrist history 与 batched search；同个行为 fixtures 跑两个后端差分。
3. Actor-Learner：CPU actor + GPU 共享 inference 批次，按 model_id/shape/rules 分组，设最大等待窗口、microbatch fallback、队列容量和 backpressure；计算 `games/hour/GPU`, `training-samples/hour`, `simulations/sec`、GPU 空闲率、延迟 p50/p95。

必须测量 CPU-only baseline、单卡、多个 actor 并行的拐点。设计吞吐 SLO 由测得结果和预算反推，不预先捏造“提升 N 倍”。

## 8. 模型竞技场与提升门禁

候选对 champion + 固定 baselines 在相同规则、相同 MCTS visits、相同时间预算和固定开局集合换色成对对战。禁止候选用 800 次搜索、champion 只用 80 次还把胜利当作权重进步。

建议事先登记最小竞技局数、置信区间计算方式、胜率改善阈值与消耗预算。灰度结果：
- pass -> promote 候选 manifest 指针；
- insufficient evidence -> continue evaluation，不能伪称胜利；
- fail -> 不提升，保存证据；
- game engine/schema 变化 -> 旧/新模型的棋力对比必须确认规则一致或标记不可比较。

保留 baseline 集合长期不变，避免仅与“昨天的自己”比较造成灾难性遗忘。

## 9. 里程碑（先证明，后扩张）

| PR | 交付 | 验收 |
| --- | --- | --- |
| B0 | 小网络 + features + policy/value 形状/视角测试 | 单样本过拟合测试、非法动作概率=0 |
| B1 | 纯 Python PUCT + 确定性 toy game 的 minimax 对照 | backup 符号、Pass、ko 一致 |
| B2 | 5×5 Self-Play + 样本生成与 replay 验证 | 100% 已提交局可重放、无非法动作 |
| B3 | Learner + checkpoint 恢复 + 小样本 loss smoke | 恢复后 optimizer 状态完整、无 NaN |
| B4 | 9×9 Arena + champion gate | 统计报告含 CI、配对颜色、预算 |
| B5 | batched inference / 并行 actor / 原生引擎（按测量选） | throughput 改善且 golden fixtures 全通过 |
| B6 | 13×13/19×19 研究实验 | 资源账单、耗时与棋力证据完整 |

验收最小闭环：不同种子重复至少两次端到端 smoke、停掉 learner/actor 后恢复、故障注入半局/重复 shard、训练结果从源记录可追溯。**不以“进程能跑”替代完整验证。**

## 10. 运行与回退策略

开发单机默认同步小样本流程（确定性更好）；多个 actor 后采用异步队列但保留 epoch/window 边界、数据版本和 staleness 监控。registry 采用 last-known-good 指针，发现规则回归、模型异常或评测失败立即冻结发布，已有 pygame 与 legacy AI 继续可用。

参考：[KataGo SelfplayTraining](https://github.com/lightvector/KataGo/blob/master/SelfplayTraining.md)，其异步 selfplay、shuffler、trainer、exporter 分离设计值得借鉴；实现依旧需根据本仓库规模量力而行。

关联：[方案 A](01-plan-a-research-environment.md) | [方案 C](03-plan-c-full-platform.md) | [验收计划](04-delivery-and-verification.md)。
