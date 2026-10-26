# 方案 A：实现与验证指南（2026-10-26）

> 实现分支开发记录。本代码实现 **PSK + 无自杀 + 简化面积计分 + 双 Pass** 的研究原型，保留原本 `Game` 规则真值；它不是自动判断死子或完整职业规则裁决器。方案 B/C 尚未实现。

## 能力边界

- `go_game.core.RuleSpec`：不可变规则预设 `legacy-psk-v1`、`research-psk-v1`。拒绝 SSK/日式数目等不支持的规则，避免训练过程中静默改语义。
- `go_game.core.RulesEngine`：规范 `row*N+col` 和 Pass=`N*N`，合法动作、落子、clone、UndoToken、准确的全历史指纹和 ScoreReport；完全委托原有 `Game` 的落子合法性判定。
- `go_game.rl.CoreGoEnv`：仅标准库依赖的轮流落子环境；`Transition` 包含两人零和终局奖励、`terminated` / `truncated` 区分、原因和规则 ID。
- `go_game.rl.features`：`obs-history4-v1` 的 13 planes，包含当前棋子、对方棋子、最后一手、行棋黑标识、相对贴目、前四个棋盘快照；仅当前玩家拥有有效 action mask。返回的观察对象不保证完整超级劫马尔可夫性，搜索必须保留完整 `GoState`。
- `go_game.rl.pettingzoo_env.GoAECEnv`：可选 AEC 双人环境；符合轮流行动、终局 dead steps 的协议；非法落子 raise，非空转。
- `go_game.rl.gym_env.GoVsOpponentEnv`：可选 Gymnasium 单人固定对手，支持受控方黑/白，`random` / `greedy` 两种基准，每步环境会执行一手对手棋。
- `go_game.records.EventLedger` / `replay_and_verify`：规范规则快照、连续事件 seq、动作、落子前后完整摘要、最终胜负与整体记录 digest；支持强制重放核验。当前是单机内存记录，非持久化多客户端并发服务。
- `go_game.eval`：换色配对随机/贪心基线、截断棋局不算和棋、置信区间与非断言微基准 CLI。**不代表算法模型棋力/Elo 评估**。

## 兼容性说明

原 `game.py` 内部 `grid[x][y]` 是原项目坐标契约，新的训练 API 显式约定 `(row,col)`：`legacy.play(col,row)`，SGF 保持原 `x,y`。新增 tests 使用非对称落点核验坐标转换。原 pygame/pygbag 不导入新的可选包，入口、UI 和 GreedyAI 均未改写。

PSK 对完整历史依赖仍由旧 `Game` 的 `_seen` 处理，新的 `fingerprint` 纳入全部已走动作以避免同盘不同历史被混为同一状态；这不是一套使用仅 Zobrist hash 判断重复的快速规则引擎。

### 简单计分的限制

引擎仍依靠双方在最后通过走子提掉必死棋，再双 Pass 进行简单面积计分；不自动识别或移除未提走的死子。因此实验结果仅在这一明确规则语义下成立，不能视为完整竞技裁决。

## 运行（从仓库根目录）

纯 Python / 不需要 pygame 或 Gym：

```bash
python -m unittest discover -p 'test_*.py' -v
python -m unittest discover -s tests -p 'test_*.py' -v
python -m go_game.eval.benchmark --size 9 --repeat 10
```

可选 PettingZoo + Gymnasium：

```bash
python -m pip install 'numpy>=1.26,<3' 'gymnasium>=1.0,<2' 'pettingzoo>=1.25,<2'
python -m unittest -v tests.test_rl_adapters
```

Core API：

```python
from go_game.core import RuleSpec, RulesEngine
from go_game.rl import CoreGoEnv
from go_game.records import replay_and_verify

spec = RuleSpec(board_size=9, komi_half_points=11)
env = CoreGoEnv(spec, max_moves=200)
observation = env.reset(seed=20261026)
while not env.done:
    # Minimal reproducible deterministic baseline: choose the first legal action.
    action = next(i for i, allowed in enumerate(observation.action_mask) if allowed)
    transition = env.step(action)
    observation = transition.observation
record = env.export_record()
assert replay_and_verify(record).state.fingerprint == env.state.fingerprint
```

PettingZoo：

```python
from go_game.core import RuleSpec
from go_game.rl.pettingzoo_env import GoAECEnv

env = GoAECEnv(RuleSpec(board_size=5), max_moves=100)
env.reset(seed=42)
for agent in env.agent_iter():
    obs, reward, terminated, truncated, info = env.last()
    legal = obs["action_mask"].nonzero()[0]
    action = None if terminated or truncated else int(legal[0])
    env.step(action)
env.close()
```

Gym：

```python
from go_game.core import RuleSpec
from go_game.rl.gym_env import GoVsOpponentEnv

env = GoVsOpponentEnv(RuleSpec(board_size=5), controlled_color="X",
                      opponent="random", max_moves=100)
obs, info = env.reset(seed=42)
while True:
    legal = obs["action_mask"].nonzero()[0]
    obs, reward, terminated, truncated, info = env.step(int(legal[0]))
    if terminated or truncated:
        break
env.close()
```

## 必须通过的检查

1. Legacy 测试、Python 3.9/3.11/3.13 编译和 Ruff。
2. 规则/坐标/超级劫/clone/undo、mask、历史编码、record 伪造检测以及终局和截断。
3. PettingZoo `api_test`、Gymnasium `check_env`，在可选 CI 环境运行。
4. 输入固定 seed，得到相同观察与重放；golden replay digest 精确校验。
5. 可选对局与 microbenchmark 只能报告实际测得数值，不能凭空宣称加速。

## 未来工作（不属于 A 本次实现）

- 实现独立参考规则和跨引擎差分/属性 fuzz；正式 rules fixtures 要持续积累更多多手超级劫及死活边界案例。
- 完整 SGF FF[4] 与让子/认输/死子协商协议。
- 高效原生落子和 undo/可增量维护的棋块/气、缓存与碰撞精确比对；当前每次合法 mask 会遍历棋盘并模拟落子。
- ModelRegistry、MCTS、Self-Play、Learner、在线事件流、远程调度与服务器幂等 CAS：属于方案 B/C。
- 在实测中按需求完善规则预设如 SSK，但不改变现有 PSK 默认语义。

关联：[方案 A 设计](01-plan-a-research-environment.md) · [共享核心资产](00-core-assets-and-contracts.md) · [验收](04-delivery-and-verification.md)。
