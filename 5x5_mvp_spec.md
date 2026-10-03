# WinAI / LoseAI：5×5 MVP 实现规格

> 状态：供实现前评审。本文只定义第一阶段 5×5 验证系统；7×7、神经网络训练、历史棋谱和对手建模均不在本阶段范围内。

## 1. 本阶段要回答的问题

5×5 MVP 不试图证明存在长期“AI 社会”，只回答以下四个更基础的问题：

1. 围棋规则、终局、计分和奖励方向是否可靠；
2. WinAI 与 LoseAI 是否会表现出可复现的目标差异；
3. WinAI–LoseAI 是否会出现比同类对局更短、更一致的协调或送棋路线；
4. 搜索预算、随机种子和先后手是否会造成可测量的行为差异。

本阶段没有跨局参数更新，因此观察到的是“规划产生的行为”，不是“长期学习产生的生态演化”。系统跑稳后，再在同一接口上增加学习型 agent。

## 2. 明确排除的内容

- 7×7 和 9×9；
- 神经网络、GPU 训练和 AlphaZero 流程；
- Elo 作为主要结论；
- 历史棋谱、对手 embedding 和隐藏身份；
- 动态奖励、密集奖励和人工送棋奖励；
- 人类棋理解释；
- 图形界面。

## 3. 围棋规则

### 3.1 棋盘与行动

- 棋盘固定为 5×5；
- 黑先，双方轮流行动；
- 行动空间为 25 个落子点加 `pass`，共 26 个动作；
- 落子后，先移除对方无气棋串，再检查己方棋串；
- 自杀手禁止；如果落子能提掉对方棋子并使己方获得气，则合法；
- 非 `pass` 行动使用情境超级劫：落子后不得产生历史上已经出现过的 `(棋盘, 下一行动方)` 状态；
- `pass` 不受超级劫限制。

### 3.2 终局

满足任一条件即终局：

1. 连续两次 `pass`；
2. 行动数达到 `4 × board_size² = 100`。

达到 100 手时直接按当前棋盘计分，并把终局原因记录为 `move_limit`。该上限是安全阀，不应静默当作正常双 pass 终局。

### 3.3 计分

使用完全程序化的 Tromp–Taylor 风格面积计分，不进行人工死子判定：

- 黑方分数 = 盘面黑子数 + 只与黑方相邻的空区域点数；
- 白方分数 = 盘面白子数 + 只与白方相邻的空区域点数 + 贴目；
- 同时接触黑白双方的空区域不属于任何一方；
- 白贴 `2.5` 目；
- `score_margin = black_score - white_score`；
- `score_margin > 0` 为黑胜，否则为白胜。

使用半目贴目后正常情况下没有和棋，但数据结构仍保留 `draw`，便于以后改变规则。

贴目在 MVP 中固定，不把它宣称为 5 路的公平贴目。所有正式比较必须交换先后手，因此结论不依赖单局颜色公平。

## 4. 身份、效用与信息

每个 agent 有固定身份：

- `WIN`：自己赢得 `+1`，和棋 `0`，自己输得 `-1`；
- `LOSE`：自己输得 `+1`，和棋 `0`，自己赢得 `-1`。

身份在对局前公开。双方都知道自己和对手的身份、当前棋盘、轮到谁、历史状态和剩余行动上限。

终局返回效用向量：

```text
(utility_black, utility_white)
```

由此得到三个重要不变量：

```text
WIN  vs WIN  : utility_black = -utility_white
LOSE vs LOSE : utility_black = -utility_white
WIN  vs LOSE : 双方目标一致，效用同号
```

例如黑方为 WinAI、白方为 LoseAI：黑胜时效用为 `(+1, +1)`，白胜时为 `(-1, -1)`。

## 5. Agent

### 5.1 必须实现的基线

1. `RandomAgent`
   - 在全部合法动作（包括 `pass`）中均匀采样；
   - 用于规则压力测试和结果基线。

2. `VectorMCTSAgent`
   - 使用适用于一般和博弈的双效用 MCTS；
   - 每个节点保存访问次数以及黑、白双方的累计效用；
   - 节点由哪一方行动，就使用哪一方的平均效用计算 UCT；
   - 不能使用传统零和 MCTS 的逐层取负回传；
   - 终局效用向量原样回传到整条路径；
   - rollout 在所有合法动作（包括 `pass`）中均匀采样；
   - rollout 同样受 100 手总上限约束；
   - 根节点最终选择访问次数最多的动作，访问次数相同时由固定 seed 随机打破平局。

UCT 选择使用：

\[
Q_{p}(s,a) + c\sqrt{\frac{\ln N(s)}{N(s,a)}}
\]

其中 `p` 是当前节点的行动方，`Q_p` 是该行动方自己的平均效用。默认探索常数 `c = sqrt(2)`。

MVP 不使用跨落子的搜索树复用、不使用 transposition table，以降低超级劫历史与缓存键不一致的风险。

### 5.2 计算档位

先实现三个可配置档位：

```text
shallow = 64 simulations / move
medium  = 256 simulations / move
deep    = 1024 simulations / move
```

冒烟测试只要求 shallow；正式实验先跑 shallow 和 medium。deep 仅在本机耗时可接受时加入，不作为 MVP 完成条件。

### 5.3 个体定义

一个 agent 由以下字段唯一确定：

```text
agent_id
identity
algorithm
compute_level
seed
```

同一身份和预算下建立 4 个不同 seed 的个体。MVP 中 seed 只影响 rollout 与平局处理，不代表已经形成了学习历史。

## 6. 实验批次

所有批次必须支持命令行配置 seed、并发数、对局数和输出目录。

### Batch A：规则与随机基线

- RandomAgent vs RandomAgent；
- 至少 10,000 局；
- 黑白身份覆盖 `WIN/WIN`、`LOSE/LOSE`、`WIN/LOSE`、`LOSE/WIN`；
- 主要检查终局原因、长度分布、颜色胜率、超级劫触发和回放一致性。

RandomAgent 的落子不因身份变化，因此不同身份条件下的棋盘结果分布应只存在抽样误差；变化的只是效用解释。

### Batch B：MCTS 功能验证

- 每种身份 4 个个体；
- 首先使用 shallow；
- 每一对不同个体都交换黑白；
- 冒烟规模：每个有序配对 20 局；
- 首轮正式规模：每个有序配对 50 局；
- 出现稳定差异的关键条件再扩展到每个有序配对至少 200 局；
- 所有配对使用预先生成并保存的 game seed，保证重跑可复现。

### Batch C：预算对照

- shallow 与 medium 进行同身份和异身份交叉比赛；
- 每个条件交换颜色；
- 首轮每个有序条件 50 局，关键条件再扩展到至少 200 局；
- 比较正常胜棋能力与身份目标实现率，不假设更深搜索一定在所有 matchup 上更好。

## 7. 每局必须保存的数据

建议每局保存一条 JSONL 元数据，并把完整棋谱保存为可独立回放的 JSON：

```text
game_id
batch_id
game_seed
board_size
komi
black_agent_id
white_agent_id
black_identity
white_identity
black_algorithm
white_algorithm
black_compute_level
white_compute_level
winner
black_score
white_score
score_margin
black_utility
white_utility
move_count
termination_reason
superko_rejections
moves
```

对 MCTS 每一步额外保存：

```text
chosen_action
legal_action_count
root_visit_count
action_visit_counts
action_q_black
action_q_white
simulations_used
search_time_ms
```

所有输出都必须带 `schema_version` 和当前代码版本标识；若目录不是 Git 仓库，则允许代码版本标识为显式版本字符串。

## 8. 第一版分析输出

每个批次自动生成 CSV/JSON 汇总，至少包含：

- 按双方身份、算法、预算和颜色分组的棋局数；
- 盘面胜率与各自目标实现率；
- 平均、中位数和分位数对局长度；
- `double_pass` 与 `move_limit` 比例；
- matchup matrix；
- 前 4、8、12 手 opening hash 的唯一数量和集中度；
- 最常见的前缀及其占比；
- Win–Lose 与同类对局的长度差异；
- 每一步平均搜索耗时和整局耗时。

“握手 / 协议坍缩”在 MVP 中只作为操作性信号，不直接作为结论。暂定信号为：

- Win–Lose 对局长度显著低于同预算的同类对局；并且
- 前 8 手完全相同的最高频前缀占比持续升高，或 opening hash 有效数量明显下降。

报告必须展示原始计数和置信区间，不能只给一句“发现了协议”。

## 9. 测试与验收

### 9.1 规则单元测试

必须覆盖：

- 单子和多子提取；
- 自杀手拒绝及提子后非自杀；
- 情境超级劫拒绝；
- `pass` 合法且连续两次终局；
- 面积计分中的单色领地、公共空点和贴目；
- 100 手安全终局；
- 合法动作生成与实际执行结果一致。

### 9.2 属性与回放测试

- 棋盘只能包含空、黑、白三种值；
- 每次合法落子后盘面不存在无气棋串；
- 相同配置与 seed 得到逐手相同的棋谱；
- 保存后重放得到完全相同的终局棋盘、分数和效用；
- 同类身份非和棋时双方效用之和为 0；
- 异类身份非和棋时双方效用相同；
- 所有生成棋局都在 100 手内结束。

### 9.3 MVP 完成条件

满足以下条件才进入 7×7：

1. 全部规则、属性和回放测试通过；
2. 10,000 局 Random 基线无非法状态、崩溃或不可回放棋局；
3. shallow MCTS 的完整正式批次可在本机稳定跑完；
4. 对局数据、搜索数据和汇总结果可以从空目录一条命令重建；
5. 人工抽查至少 20 局，包括最短局、最长局、最高频前缀和所有 `move_limit` 对局；
6. 能清楚区分“盘面赢家”和“身份目标实现者”；
7. 不论是否发现握手协议，都能给出可复现的结果。

## 10. 推荐工程边界

建议实现为一个纯 Python 包，依赖尽量少：

```text
src/
  game/        # 状态、规则、计分、回放
  agents/      # Random 与 Vector MCTS
  league/      # 配对、seed、并行执行
  analysis/    # 汇总、矩阵、前缀统计
tests/
configs/
scripts/
outputs/       # 默认不提交大批量结果
```

规则引擎不得依赖 agent；agent 只通过不可变状态和公开接口访问游戏。实验执行、结果分析与搜索实现分离，确保将来替换成学习型 agent 时不改动规则层。

## 11. 5×5 之后的唯一预留接口

本阶段只预留，不实现：

- `board_size` 参数化，以便迁移到 7×7；
- agent 的 `observe / select_action / on_game_end` 接口，以便加入跨局学习；
- 身份是否公开的信息开关；
- 每局总计算预算字段。

除此之外，不为尚未进行的实验提前增加复杂抽象。
