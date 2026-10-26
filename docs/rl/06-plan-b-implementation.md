# 方案 B：实现、使用与验收记录

> 状态：实现分支候选。**以 PR 的实际 GitHub Actions 结果为准**，本文不预先声称测试通过或棋力超越现有引擎。
> 本分支从方案 A 的提交 `5a0852d8dac34dbcf4b6a97c8035dde3e1471639` 派生，因为 A 的 PR #4 在开发时尚未合入 main。B 的 PR 必须面向 A 分支或等 A 合并后 rebase，不能绕过依赖。

## 目标范围

交付 **可重复的小棋盘 AlphaZero 风格研究闭环**：规则可信的 PUCT 搜索、自我对弈、经过完整 replay 检查的样本、PyTorch 小型残差网络、policy/value 损失、训练 checkpoint 和恢复、换色竞技场、经过统计门禁的 champion 注册与可选进程隔离 Actor。依赖 A 的 `CoreGoEnv`、`RulesEngine`、`EventLedger`、`obs-history4-v1`，不改 `Game` 的 PSK/计分语义。

## 模块与契约

| 模块 | 已实施的设计边界 |
| --- | --- |
| `go_game.training.search` | PUCT 选择、合法动作 prior 归一化、根 Dirichlet 可配置、温度采样、访问分布训练目标；节点含完整状态指纹、不做 board-only transposition |
| `go_game.training.network` | CPU/GPU PyTorch 小型 CNN ResNet；输入 13 通道，Policy N²+Pass，Value 当前行动方视角，批推理 `predict_batch()` 与模型内容哈希 |
| `go_game.training.selfplay` | 每局锁定 model_id/规则/搜索参数，产生完整两 Pass 对局；超过 max_moves 抛错并拒绝错误价值标签 |
| `go_game.training.dataset` | `go-sample-v1`，记录 mask、planes、visits、pi、z、state hash、source record；重放和逐样本交叉检验、完整数据摘要、原子文件写入 |
| `go_game.training.learner` | AdamW policy/value 训练、非法动作 masked CE、梯度裁剪、可选 D4 变换、随机状态/优化器保存恢复 |
| `go_game.training.arena` | 同规则同搜索预算、固定 seed 换色配对、保存 game digests、Hoeffding 95% 区间、truncation 不归胜负 |
| `go_game.training.registry` | 单写者本地 champion pointer，explicit bootstrap；晋级要求预注册数量和下界阈值，匹配候选/旧 champion、checkpoint sha |
| `go_game.training.actors` | ProcessPoolExecutor actor，一局一个固定 checkpoint digest，完成后再通过原子写入 verified shard，最多 8 本地 workers；失败显式上抛 |
| `go_game.training.cli` | 小棋盘命令行 smoke：自我对弈、数据写入、训练、候选模型、Arena 和完整 JSON 报告 |

### 关键防错

1. **MCTS 价值视角**：每条 Edge 的 W/Q 从该边**父局面行棋方**视角定义；回传时根据父子实际 `current_player` 是否变化决定变号。方案 A 的旧 `Game.pass_move` 在第二次 Pass 终局时没有再 flip，因此不能盲目每级乘以 -1。
2. **禁止超劫缓存捷径**：搜索只 clone 包含完整 PSK 历史的 state，比较 fingerprint。没有将同盘面不同历史合并。
3. **可追溯、拒绝半局样本**：只消费 `terminated=True` 的真实规则结果；move-budget 截断仅作为 aborted，不得训练最终 z。
4. **数据来源核验**：shard 验证时将源局从零重放，每步重新编码观察/mask，核对访问数、概率、行动方、状态摘要和最终 z，避免 actor 输出污染训练。
5. **独立棋力证据**：权重改进仅可被竞技场配对结果评估，训练 loss 不是模型发布标准。小规模 smoke 的 Arena 结果通常只表示 `insufficient_evidence`，不会宣称超越模型。
6. **方案 A 零依赖回归**：只有 network/learner/cli/actors 会导入 PyTorch；导入 `go_game.core`、原 UI、Gymnasium 环境不要求安装 Torch。

## 安装与使用

从仓库根目录：

```bash
python -m pip install --index-url https://download.pytorch.org/whl/cpu 'torch==2.5.1'
python -m unittest -v tests.test_training_search tests.test_training_augmentation tests.test_training_torch
python -m go_game.training.cli --size 3 --simulations 2 --games 1 --steps 1 --pairs 1 --max-moves 120 --output runs/plan-b-smoke
```

**完整小规模实验**可以将 `--size` 调整为 5 或 9，并加大 simulations、games 和 steps。13×13/19×19 的张量/动作 ABI 与自我对弈生成器兼容，但尚未进行 GPU 吞吐或棋力规模验证，不能宣称达到实用搜索速度。

使用 Python API 批量生产样本：

```python
from go_game.core import RuleSpec
from go_game.training.search import SearchConfig
from go_game.training.network import NetworkConfig, PolicyValueNet
from go_game.training.learner import Learner
from go_game.training.actors import collect_selfplay

rules = RuleSpec(board_size=5)
learner = Learner(PolicyValueNet(NetworkConfig(5)), seed=42)
# Actor 必须加载可信的、带模型内容摘要的 checkpoint。
manifest = learner.save("runs/initial-model.pt")
items = collect_selfplay("runs/initial-model.pt", manifest["model_id"],
                         rules, SearchConfig(simulations=8),
                         seeds=[101, 102], workers=2,
                         max_moves=200, output="runs/shards")
```

注意：早期模型可能因搜索走法导致对局截断；此时 `IncompleteGame` 会上抛，绝不把截断局当作合法训练样本。调大 max_moves 或改变探索参数后重试，并记录失败种子。示例为 API 用法，不保证随机初始模型必能完成所有局。

## 自动化验收

- **标准库门禁**：Python 3.9/3.11/3.13 对原规则 + 方案 A + MCTS + Replay/D4 测试（无需 Torch）。
- **机器学习门禁**：独立 Python 3.11 CPU PyTorch：网络 shape、masked legality、单步梯度更新、checkpoint 含 optimizer/RNG 的精确续训、Arena 换色、可选 CLI 整条训练回路。
- **原项目门禁**：保留 Ruff、pygame smoke、Gymnasium/PettingZoo API 检查，验证分支保持 A 向后兼容。
- **运行基准**：机器学习程序还应记录真实墙钟时间、GPU 类型、samples/s 和 MCTS sims/s。当前未包含独立原生引擎或性能改善宣称。

## 不属于本次已完成的能力

- KataGo 级棋力、大规模 19×19 训练、分布式 GPU inference server / server-side dynamic microbatch、native Rust/C++ 增量规则引擎；
- 长期的在线多模型训练调度、跨机 lease/fencing、S3 对象存储和模型发布服务，这些能力需要方案 C；
- 对比真人高手胜率、职业裁决、日式规则或未实现的 SSK；
- 可靠的时间成本/吞吐提升尚未有可对比的实测基线。现有 `predict_batch` 是批量推理 API，不等同于独立的 GPU 批调度服务。

## 验收定义

研究闭环的最低可接受证据：①独立规则回归保持通过；②搜索父视角的值符号有固定测试；③所有训练样本能从 GameRecord 精确复原并拒绝非法 mass/错位价值；④带 optimizer/RNG 的 checkpoint 复现训练；⑤Arena 区分截断与终局且报告区间；⑥训练 CLI 端到端完成。

参考：[方案 B 详细设计](02-plan-b-selfplay-training.md) · [核心资产](00-core-assets-and-contracts.md) · [测试门禁](04-delivery-and-verification.md)。
