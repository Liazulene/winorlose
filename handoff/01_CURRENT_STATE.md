# 当前状态与完整事实底座

## 1. 研究问题

项目研究固定且公开的两种身份在围棋式环境中的规划行为：

- `WIN`：自己的颜色盘面赢得 `+1`，和棋 `0`，盘面输得 `-1`。
- `LOSE`：自己的颜色盘面输得 `+1`，和棋 `0`，盘面赢得 `-1`。

这不是训练实验。现阶段没有跨局参数更新、神经网络、历史棋谱输入、对手建模或种群演化。不同个体只在随机 seed 上不同，不应被命名为稳定棋风、社会角色或训练谱系。

四类对局的博弈结构不同：

- WIN/WIN：零和，双方都想让自己的颜色赢。
- LOSE/LOSE：零和，双方都想让自己的颜色输。
- WIN/LOSE：共同目标是黑色 WIN 获胜，终局可出现 `(+1,+1)`。
- LOSE/WIN：共同目标是白色 WIN 获胜，终局可出现 `(+1,+1)`。

因此 mixed 不是“一个赢一个输的对抗”，而是围绕同一盘面赢家的共同利益规划。

## 2. G0 规则

- 棋盘：5×5。
- 黑先。
- 白贴 2.5。
- Tromp–Taylor 风格面积计分。
- 禁止自杀。
- 非 pass 动作受情境超级劫约束；pass 豁免。
- 连续两次 pass 终局。
- 最多 100 手，达到上限按当前盘面计分。
- 身份固定且双方可见。

本实现对歧义的具体处理见 `AMBIGUITIES.md`。不要在不更新版本和预注册说明的情况下改变其中任何语义。

## 3. Agent 与搜索

当前仅实现两种 agent：

- `RandomAgent`：在全部合法动作（包括 pass）中均匀采样。
- `VectorMCTSAgent`：一般和双效用 MCTS。

MCTS 每个节点保存 `(N, Σu_black, Σu_white)`。当前行动方用自己的平均效用做 UCT 选择，终局效用向量原样回传，不逐层取负，也不用对手 Q 替代自己的 Q。计算档位为：

- shallow：64 simulations/手；
- medium：256 simulations/手；
- deep：1024 simulations/手。

正式规划阶段只运行了 shallow；medium/deep 已实现但尚未做正式批次。

## 4. 工程能力

代码为 Python，核心对局运行仅依赖标准库。分析脚本使用 `models` 环境中的 NumPy/SciPy，测试使用 pytest。

主要模块：

- `src/winai_loseai/game/`：规则、吃子、超级劫、终局与计分。
- `src/winai_loseai/agents/`：Random 和 Vector MCTS。
- `src/winai_loseai/league/`：配对、确定性 seed、并发流式运行、断点续跑、存储与回放。
- `src/winai_loseai/analysis/`：批次汇总和统计。
- `scripts/`：正式批次独立验证、跨 seed 分析、代表局审阅、报告重建和交付验证。

确定性设计：每局随机数由 `sha256(局 seed | 颜色 | agent seed)` 派生独立流。同一计划在不同并发数、顺序执行或中断恢复后，除墙钟字段外逐手一致。

正式批次持久化能力：

- 运行前写入 `plan.json`、`manifest.json`、`game_seeds.json`。
- 完整 game 先写 `.tmp`，再原子替换。
- `games.jsonl` 每局只追加一次并 flush，当前正式版本严格按 `game_index` 升序。
- 有界进程池，内存不随总局数线性增长。
- `--resume` 校验批次配置、版本、Python、source fingerprint、计划和已有记录。
- 仅自动修复末尾撕裂行，或从完整且匹配的 game JSON 重建缺失 metadata；中间损坏、重复或计划外 game id 明确拒绝。
- 完整性失败置 `failed`；全量 replay 失败置 `validation_failed`；只有全部通过才置 `completed`。
- 现有输出目录默认拒绝覆盖；`--overwrite` 只清理本包拥有的实验产物。

Windows 并发入口必须有 `if __name__ == "__main__"` 保护。使用 `run.py` 或 pytest 是安全入口，不要用无保护的 stdin/`python -c` 驱动进程池。

## 5. 正式数据

### Batch A：Random 基线

- 路径：`outputs/batch_A_seed0`
- 10,000/10,000 局完成，10,000/10,000 全量回放通过。
- 四种身份组合各 2,500 局。
- 9,892 局 double pass，108 局 move limit。
- 超级劫候选排除 2,634 次。
- Random 行为不使用身份，因此身份组合间盘面差异只应是抽样噪声。
- 这是历史 0.1.0 数据：JSONL 是完成顺序，不是索引顺序；没有新版本 source fingerprint；保持只读，不能在 0.2.0 下续跑。

### Batch B：shallow MCTS

每个 seed：8 个体（4 WIN、4 LOSE），56 个有序非自配对，每配对 50 局，共 2,800 局。5×5、komi 2.5、64 simulations/手、并发 8。

- `outputs/batch_B_shallow_seed0`：2,800/2,800 完成并全量回放。
- `outputs/batch_B_shallow_seed1`：2,800/2,800 完成并全量回放。
- 两批均无 move limit，无 mixed 目标失败。
- 正式 Batch B 源码、版本、Python、计划和数据格式均有锁。

正式总量：15,600 局。

## 6. 主要结果

### 6.1 mixed 明显更短，但不是固定长前缀协议

mixed−same 的平均长度差：

|范围|差值（手）|95% CI|
|---|---:|---:|
|seed 0|−7.042|[−7.977, −6.115]|
|seed 1|−6.561|[−7.454, −5.690]|
|合并|−6.802|[−7.434, −6.164]|
|Random 基线|+0.408|[−0.247, +1.058]|

两个 seed 中，WIN/LOSE 和 LOSE/WIN 的双方目标均 800/800 达成。它们共享同一个终局目标，因此这不是两份独立成功证据。

到达 8 手或 12 手的正式 Batch B 棋局，其精确动作前缀全部唯一。短局 END 补齐后存在少量局部重复，但 top1 最高只有 2%。没有固定长前缀坍缩，也没有跨局学习，不能宣称协议传播。

### 6.2 LOSE/LOSE 有巨大的颜色效应

- 黑方求输目标率：seed 0 为 94.50%，seed 1 为 94.17%。
- 对应黑方盘面胜率只有 5.50% 和 5.83%。
- 合并黑方目标率 94.33%，Wilson 95% CI [92.88%, 95.51%]。
- WIN/WIN 黑方盘面胜率为 53.00% 和 50.33%，没有同等级的颜色偏差。

LOSE/LOSE 不是普遍的极短竞速：中位长度 23、21，最长 66、56；两批分别只有 61/600、64/600 在 8 手内结束。

### 6.3 没有可靠的个体克制关系

12 个同身份无序配对中只有 7 个在两个 seed 方向一致；控制颜色后的精确检验经 Holm 校正均不显著。seed 个体排名会翻转。不能宣称稳定棋风、优势种群、克制链或派系。

### 6.4 pass 决策体现目标差异

mixed 中 LOSE 更常在前 12 手 pass，也更常丢子。对双方目标有利的终局提议较常被第二次 pass 接受；对双方不利的提议没有被接受。LOSE/LOSE 中，对提议者有利而对对手不利的终局通常被拒绝。这支持目标条件下的终局规划，但不等于复杂语言式握手。

## 7. 最关键的解析机制

当前面积计分、正贴目和允许 pass 的规则下，黑 LOSE 从第一手起永远 pass，可以保证自己的颜色盘面输棋：黑无棋子、无黑领地，得分恒为 0；白至少有 2.5 贴目。

这是合法策略，不是实现漏洞，而且扩大到 7×7 仍然成立。它证明 G0 的 LOSE/LOSE 颜色不对称具有规则基础，但不证明 shallow MCTS 已收敛到该策略：正式数据中黑方全局“始终 pass”是 0/600。

mixed 也有廉价共同目标路线：

- 黑 WIN / 白 LOSE：黑下一子后双方 pass，按面积计分黑可获得整片空区，双方目标同时实现。
- 黑 LOSE / 白 WIN：空盘双 pass，白凭贴目获胜，双方目标同时实现。

这些路线会被更强搜索更稳定地发现，还是会被更丰富的实战路线取代，是下一阶段的核心问题。

## 8. 关于贴目的正确解释

2.5 贴目主要为 WIN/WIN 的先后手平衡服务。没有理论理由要求同一个 komi 同时平衡 LOSE/LOSE；其合适方向甚至可能相反。

主实验不应针对 matchup 临时换贴目，因为这会把身份效应与环境变化混在一起。建议：

- G0 始终保持固定 2.5 komi，使用颜色平衡和分层报告处理不对称；
- 把 komi 扫描作为独立机制实验；
- 如需研究“平衡后的 LOSE/LOSE”，另立清晰命名的 benchmark，不能替代 G0，也不能和 G0 混报。

## 9. 当前结论边界

可以说：

- mixed 规划对局在两个 seed 中稳定短于 same；
- mixed 在当前搜索和规则下稳定达到共同目标；
- LOSE/LOSE 存在强且可解释的颜色效应；
- pass 接受与拒绝行为和身份目标一致；
- 当前没有固定长前缀集中或可靠个体克制证据。

不可以说：

- agent 学会、传播或演化了协议；
- 出现了社会结构、文化、联盟或生态；
- 丢子统计单独证明“蓄意牺牲”；
- 64 simulations 已近似最优策略；
- 7×7 会自动消除 pass/komi 机制；
- 贴目 2.5 对所有 matchup 都公平。

## 10. 保护边界

以下内容只读，不得覆盖或规范化：

- `5x5_mvp_spec.md`
- `winai_loseai_go_experiment_notes_v2.md`
- `outputs/batch_A_seed0`
- `outputs/batch_B_shallow_seed0`
- `outputs/batch_B_shallow_seed1`
- `reports/5x5_planning_phase_report.md`
- `reports/planning_source_0.2.0.zip`
- `reports/planning_source_lock.json`
- `reports/validation/` 中既有验证证据

新实验必须使用新代码版本、新输出目录、新报告目录和新的 source lock。若改动规则、奖励、rollout、搜索选择、终局、计分、seed 逻辑或数据 schema，均视为语义新版本。

## 11. 验证命令

```powershell
& 'D:\MyCondaEnvs\models\python.exe' -m pytest -q -p no:cacheprovider
& 'D:\MyCondaEnvs\models\python.exe' scripts/validate_run.py outputs/batch_B_shallow_seed0
& 'D:\MyCondaEnvs\models\python.exe' scripts/validate_run.py outputs/batch_B_shallow_seed1
& 'D:\MyCondaEnvs\models\python.exe' scripts/planning_analysis.py outputs/batch_A_seed0 outputs/batch_B_shallow_seed0 outputs/batch_B_shallow_seed1
& 'D:\MyCondaEnvs\models\python.exe' scripts/review_games.py
& 'D:\MyCondaEnvs\models\python.exe' scripts/write_planning_report.py
& 'D:\MyCondaEnvs\models\python.exe' scripts/verify_delivery.py
```

2026-10-03 的独立复核结果：89 passed；交付验证无问题，三个正式批次原始 game 文件数分别为 10,000、2,800、2,800，均与此前验证快照一致。

