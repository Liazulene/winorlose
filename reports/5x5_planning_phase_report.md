# WinAI / LoseAI：5×5 无学习规划阶段最终报告

报告日期：2026-09-22。所有结果来自已落盘棋局；两批 Batch B 使用同一锁定源码。

## 结论与 7×7 决策

**本轮 5×5 无学习规划实验已完成；对“下一步直接扩到 7×7”的建议是 NO-GO（暂缓）。** 原因是需要先辨明规则与浅搜索的贡献，而不是要求必须发现握手协议。工程上，正式数据生成、源码锁定、恢复保护、全量回放和汇总均通过；研究上，当前最强现象具有明确的颜色／pass 解释，单纯扩大棋盘不能排除它。

两批正式 Batch B 各 2,800 局，共 5,600 局；另重新验证旧 Batch A 的 10,000 局。两 seed 都得到 mixed 比 same 更短的结果：seed 0 为 −7.042 手，95% CI [−7.977, −6.115]；seed 1 为 −6.561 手，95% CI [−7.454, −5.690]。合并差 −6.802 手，95% CI [−7.434, −6.164]。Random 基线为 +0.408 手，95% CI [−0.247, +1.058]。区间来自本文统一的有序配对分层 bootstrap，可能与原始 summary 的非分层 bootstrap 略有不同。

|判断|两个 seed 的证据|结论边界|
|---|---|---|
|mixed 的目标协调|每 seed 的 WIN/LOSE、LOSE/WIN 均为 800/800 双方目标达成；合并每方向 1,600/1,600，Wilson 下界约 99.76%|这是共同效用的一个结果，不是两份独立成功证据；支持本配置下的规划协调|
|简短终局路线|WIN/LOSE 三手局分别 60/800、56/800；LOSE/WIN 空盘双 pass 分别 12/800、16/800|局部路线可复现；也直接利用面积计分和贴目，不能据此证明复杂合作|
|固定长前缀集中|达到 8 手的所有棋局，seed 0 为 2,561/2,561 唯一，seed 1 为 2,581/2,581 唯一；12 手也全部唯一|未发现精确长前缀坍缩；未合并空间对称，也没有跨局学习的时间趋势|
|LOSE/LOSE 求输竞争|黑方目标率 567/600=94.50%、565/600=94.17%；中位长度 23、21 手，最长 66、56 手|稳定的是颜色偏差和竞争性终局选择，不是普遍极短、对称的“争相求输”|
|个体差异／克制|12 个同身份无序配对中仅 7 个两 seed 同方向；颜色控制的精确检验经 Holm 校正均 p=1.000|没有支持稳定克制关系的证据；不能反过来证明所有个体完全等价|

## 跨 seed 的具体变化

WIN/WIN 均长从 29.958 到 30.982（+1.023 手），LOSE/LOSE 从 27.650 到 25.632（−2.018 手），WIN/LOSE 从 23.774 到 23.852（+0.079 手），LOSE/WIN 从 19.750 到 19.639（−0.111 手）。mixed 的两个颜色方向变化很小；同身份组尤其 LOSE/LOSE 的尾部更敏感：LOSE/LOSE 的 Q3 从 45.5 降到 37，≥60 手从 5/600 降到 0/600。不能把总体均值一致当作整条分布一致。

WIN/WIN 黑方盘面胜率为 53.00%、50.33%，两批区间均包含 50%；没有清晰的强颜色优势。LOSE/LOSE 黑方**盘面胜率**仅 5.50%、5.83%，对应黑方**求输目标率**94.50%、94.17%。合并黑目标率 94.33%，Wilson 95% CI [92.88%, 95.51%]。颜色效应远大于个体间经黑白平衡后的差异。mixed 中白 WIN 方向平均比黑 WIN 方向短 4.024、4.214 手；这是描述性颜色差异，不能把贴目、先后手与搜索效应单独分离。

个体方面，WIN-s1 对同身份的目标率从 158/300（52.67%）变成 147/300（49.00%），WIN-s3 从 154/300（51.33%）变成 157/300（52.33%）；排名首位由 s1 换成 s3。LOSE-s3 两次均居首，但仅 153/300（51.00%）与 155/300（51.67%），区间仍覆盖 50%。WIN-s2 对 WIN-s4 从 46% 变为 58%，方向翻转。不能将这些随机流个体命名为稳定棋风、优势种群或克制链。四个同身份个体只在随机 seed 上不同，没有训练或特化参数。

每个有序配对有 50 局。LOSE/LOSE 黑目标率的配对范围为 seed 0 的 88%–98%、seed 1 的 92%–98%，说明强颜色效应并非一个配对驱动；均长范围却为 23.68–32.26 和 19.72–27.44 手，仍有相当波动。完整逐配对数据及区间在后文链接的 CSV 中，避免只挑极端格子。

## 协调、送棋和求输的操作性解释

mixed 中，LOSE 一方在前 12 手更常 pass，且丢子更多。WIN/LOSE 白 LOSE 的早期 pass 比例为 7.73%、7.88%，黑 WIN 为 3.47%、3.60%；白 LOSE 被提掉的子占其实际落子总数 38.26%、38.53%，黑 WIN 仅 1.33%、1.61%。LOSE/WIN 黑 LOSE 对应丢子比例为 24.62%、24.50%，白 WIN 为 1.35%、1.44%。这是与求输目标一致的行为信号，但被提子也可能来自浅搜索错误，不能仅凭这些统计判定“蓄意牺牲”。

更直接的规则反事实是“第一次 pass 后，对手是否接受第二次 pass”。在 mixed 中，对双方共同目标有利的提议有较高接受率；不利提议两 seed 均没有被接受。这里“不利”指如果立即终局，两人的身份目标都失败。LOSE/LOSE 中，对提议者有利的终局提议通常被对手拒绝：黑方提议接受率分别 133/2052、99/1727（6.48%、5.73%），白方 18/304、17/285（5.92%、5.96%）；相反，白方对自己不利的提议被接受 434/483、466/507（89.86%、91.91%）。这支持相反目标下的拒绝终局行为；同局多次提议相互依赖，不能当作数千个独立样本。

LOSE/LOSE 黑方早期 pass 率为 12.61%、12.74%，白方为 7.57%、8.42%；黑方丢子均值 4.472、3.735，白方 0.975、0.867。只有 61/600、64/600 局在 8 手以内结束，并有明显长尾。因而“双方都追求自己输”是效用定义，“对称地争抢极短输法”则没有得到数据支持。不能沿用 24 局 smoke 的强表述。

短局不能被前缀口径隐藏。把结束后的动作补为 END 后，WIN/LOSE 的 8 手 top1 占比为 1.00%、0.75%，top4 为 3.125%、2.125%；LOSE/WIN 的 top1 为 1.50%、2.00%，主要是空盘双 pass。存在可解释的局部集中，但还不是一个占主导的固定路线。设计中“更短且更一致”的复合信号只获得前一部分强支持；没有证据表明某条协议随时间传播。

## 规则层面的关键解释

在当前面积计分、正贴目和允许 pass 的规则下，**黑 LOSE 从第一手起始终 pass 是一条保证自己盘面输棋的策略**：黑盘上始终没有棋子，所以既无黑子面积，也不可能有仅邻接黑子的黑方领地；黑得分恒为 0，白至少有 2.5 贴目。无论白方如何合法落子或何时结束，黑方目标都能实现。该论证同样适用于采用这些规则和正贴目的更大棋盘，不是 5×5 专属的实现漏洞。

这是一条可用策略的数学解释，不是说 MCTS 已经稳定执行了它。事实上，两批 LOSE/LOSE 中黑方从头到尾只 pass 的棋局都是 **0/600**。浅搜索仍会落子、提子和拒绝终局。两三手棋局在 WIN/WIN 中也出现：两批各有 3 局空盘双 pass，黑 WIN 直接失败。这提示还要区分奖励方向、规则允许的捷径和 64 次模拟的决策噪声。

## 代表局审阅结论

本次代理逐手审阅 seed 0 的 30 张、seed 1 的 29 张最终代表卡片，另有此前 20 张指定索引卡片；存在重复时不重复计作独立样本。全体 5,600 局均无 move_limit、无 mixed 目标失败，所以这两类异常清单为空，不是遗漏。超级劫候选排除总数为 438、397，均已逐手复算一致；这不是非法落子或死循环数。

- seed 0 `g000266` 与 seed 1 `g000315`：各自 END 补齐最高频 WIN/LOSE 前缀，黑下一子后双 pass，双方目标实现。最高频仅 8 次、6 次。
- seed 0 `g001400` 与 seed 1 `g001445`：LOSE/WIN 空盘双 pass，白盘面赢、黑白都实现身份目标。
- seed 0 `g000497` 与 seed 1 `g001090`：同样的空盘终局出现在 WIN/WIN，却使黑 WIN 目标失败；短局本身不等于合作。
- seed 0 `g001743`（66 手）与 seed 1 `g002381`（56 手）：LOSE/LOSE 长局，白在拒绝多次 pass 后几乎占满棋盘，盘面赢但身份目标失败。说明“求输竞争”可产生拖长的终局过程。
- seed 1 `g000020` 与 `g001089`：全批最长均为 68 手，都是 WIN/WIN；大块提子和反复优势变化后合法双 pass，未触发 100 手上限。
- seed 0 `g001987`：LOSE/LOSE 黑盘面赢、白求输成功，是黑方强目标优势之外的反例。

下文代表局索引提供每个原始 JSON 的路径，核查卡片提供逐手行动、提子、当前面积分、根访问数和所选 Q。Q 为浅搜索样本均值，不是校准胜率；中途面积分不等于必然终局结果。

## 下一阶段优先级（本轮未启动）

1. **P0：先在 5×5 固定问题与对照。** 保留本批原始定义作为对照，预先明确要研究“合法求输捷径”还是排除此捷径后的复杂行为。将始终 pass 的解析策略、空盘／单子终局与浅搜索误判列为诊断对象；对候选规则或 pass 限制作出的任何改变，都必须另立版本和输出目录，不能回写本实验。
2. **P1：增加独立 seed 与机制对照。** 预先确定更多 batch seed、颜色平衡和统计终点；分别设计贴目、早期 pass、搜索预算的对照，一次只改变一个因素，并继续报告目标率、长度尾部与 END 敏感性前缀。预算扩展属于后续新实验，本轮未启动 Batch C 或 medium/deep。先确认现象不是少量模拟或 rollout 偏差的产物。
3. **P1：提高解释分辨率。** 对代表性局面比较合法备选动作的终局反事实或更可靠的值估计，检验“丢子”是否实际改善 LOSE 目标；加做棋盘对称归一化的前缀分析。分析脚本与生成源码分别归档，保持原始棋谱只读。
4. **P2：满足上述诊断后再做 7×7。** 若目标是在更大状态空间复现已解释的规划现象，7×7 有价值；但不能把扩大棋盘当成消除正贴目 pass 策略的方法。迁移时重新标定预算／分支因子、资源和终局上限，重新锁版本。独立人类规则／棋谱复核也可补充本次代理审阅。

本报告没有启动任何后续实验，也不将这些固定算法、无跨局更新的结果描述为长期学习、协议传播、社会形成或生态演化。


## 实验问题、规则和方法

本阶段检验异质目标能否在无学习条件下产生可复现的规划行为，重点观察混合身份的协调信号、LOSE/LOSE 的求输竞争，以及颜色与随机种子效应。没有跨局参数更新、历史棋谱输入、对手模型或神经网络。agent seed 是随机流的一部分，不代表训练历史。

规则固定为 5×5，黑先，白贴 2.5；先提对方无气棋串，再拒绝自杀；非 pass 使用包含行棋方的情境超级劫，pass 豁免但记录历史。双 pass 终局，最多 100 手；第 100 手同时形成双 pass 时记 double_pass。面积计分，不做人工死子判定。贴目不宣称公平。

WIN 自己盘面获胜效用 +1，失败 −1；LOSE 相反。WIN/WIN 与 LOSE/LOSE 的效用相反；混合身份效用相同，因此双方都偏好 WIN 身份一方盘面获胜。“双方目标达成”在混合局不是两份独立证据。

VectorMCTS 每手从新树开始，64 simulations，探索常数 √2；每节点保存黑白效用向量，当前行动方最大化自己的 UCT；向量原样回传，不能逐层取负。rollout 在全部合法动作（含 pass）中均匀抽样，受同一 100 手上限约束。根按最多访问选动作，平局用固定随机流打破；不复用树、无 transposition table。

Batch B 每身份 4 个个体（s1–s4），共 8 个；排除同一个体自对弈，56 个有序配对各 50 局，每 seed 2,800 局。每个体每 seed 黑白各 350 局；WIN/WIN 与 LOSE/LOSE 各 600 局，两个混合颜色方向各 800 局。游戏 seed 由 batch seed 和 game index 确定，颜色与 agent seed 再派生独立随机流。

## 代码溯源与验收

正式版本：`winai_loseai-0.2.0-planning`；Python `3.12.13`。
源码 SHA-256：`a4d6d9e033b88f6b7eb469d49088d69cb45ceb34b3770087b8ecd3a23a890e2e`。
源码压缩包 SHA-256：`7ab5b7cadcdb37a0da742752634ead7afa68e879b83b048b101b4ff3642c9b76`。

归档：[正式源码](planning_source_0.2.0.zip)、[逐文件锁](planning_source_lock.json)、[审计记录](audit_checkpoint.md)。目录不是 Git 仓库，因此没有虚构 commit 或 dirty 状态。26 个锁定文件覆盖入口和全部包内 Python 源码；UTF-8/LF 规范化后按相对路径计算 SHA-256。

manifest、每盘完整记录与 JSONL 都记录版本、源码指纹、schema 和 Python 版本。恢复前验证来源和 source_lock，检查可解析的每盘来源；任何不符均在修复元数据前拒绝。运行中源码改变也拒绝继续落盘。测试验证相同版本恢复、不同版本拒绝及拒绝后原目录字节不变。正式 Batch B 开始后未修改锁定源码；新增分析位于 scripts/。

全套自动化测试：**89 passed，0 failed**（24.42 秒）；涵盖原有 71 项、溯源保护 10 项、分析及故障注入 8 项。见 [测试记录](validation/final_tests.json)。

|批次|manifest|完成/计划|全量回放|JSONL 严格升序|验证问题数|
|---|---|---|---|---|---|
|batch_A_seed0|completed|10000/10000|10000/10000|False|0|
|batch_B_shallow_seed0|completed|2800/2800|2800/2800|True|0|
|batch_B_shallow_seed1|completed|2800/2800|2800/2800|True|0|


独立验证还检查完整棋谱与 JSONL 相等、每步气和超级劫排除计数、seed/plan、正式配对平衡、每步 64 次模拟、访问数之和与根最大访问选择、Q 值范围，以及汇总的计数/胜率/目标率/平均长度。验证证据见 [validation/](validation/)。原始数据未被分析脚本改写。

Batch A 属于旧 0.1.0：索引集合 0–9999 完整且无重复，但历史 JSONL 按完成顺序排列，未强行排序。其源码指纹缺失，不能事后证明生成时源码版本；现在的全量重放通过是规则一致性证据，不是历史源码锁定证据。

|批次|开始 UTC|manifest 完成 UTC|历时分钟|每手搜索均值ms|每局累计搜索均值s|
|---|---|---|---|---|---|
|batch_B_shallow_seed0|2026-09-22T12:33:39+00:00|2026-09-22T13:25:48+00:00|52.15|358.04|8.872|
|batch_B_shallow_seed1|2026-09-22T13:27:06+00:00|2026-09-22T13:56:54+00:00|29.80|206.04|5.060|


历时包含计算、落盘和完成前完整性处理，不包含随后独立验证和报告分析。搜索计时来自并行工作进程，与批次墙钟时间不是同一指标，也受机器负载影响。运行资源快照见 monitor.jsonl。正式 seed 0 另用不同并发度重算指定的 4 局，排除计时字段后完整结果一致，见 validation/batch_B_shallow_seed0_reproducibility.json。

独立分析版本 `1.1`，Python `3.12.13`、NumPy `2.4.6`、SciPy `1.17.1`；分析脚本 SHA-256 `65cb199c94fdd0d446ca09629560d8ffa9b0320ca839002a8829cb5ff89c7481`。

## Batch A 随机基线

|黑/白身份|n|黑方盘面胜率|均长|中位|双 pass|上限|超级劫排除|
|---|---|---|---|---|---|---|---|
|WIN/WIN|2500|972/2500 (38.88%)|37.653|34.0|2473|27|629|
|LOSE/LOSE|2500|1034/2500 (41.36%)|37.724|35.0|2483|17|618|
|WIN/LOSE|2500|997/2500 (39.88%)|37.616|34.0|2463|37|651|
|LOSE/WIN|2500|969/2500 (38.76%)|38.577|35.0|2473|27|736|


Random 在合法动作中均匀抽样，身份只改变效用解释。基线四组的盘面差异可由抽样波动解释；身份独立性另有同 seed 更换身份仍逐手相同的单元测试。超级劫数表示实际每回合合法动作生成时排除的空点候选数，不是实际非法落子次数。

## Batch B：batch_B_shallow_seed0

|黑/白身份|n|黑盘面胜|白盘面胜|黑目标达成|白目标达成|黑目标率 95% CI|
|---|---|---|---|---|---|---|
|WIN/WIN|600|318/600 (53.00%)|282/600 (47.00%)|318/600 (53.00%)|282/600 (47.00%)|[49.00%, 56.96%]|
|LOSE/LOSE|600|33/600 (5.50%)|567/600 (94.50%)|567/600 (94.50%)|33/600 (5.50%)|[92.38%, 96.06%]|
|WIN/LOSE|800|800/800 (100.00%)|0/800 (0.00%)|800/800 (100.00%)|800/800 (100.00%)|[99.52%, 100.00%]|
|LOSE/WIN|800|0/800 (0.00%)|800/800 (100.00%)|800/800 (100.00%)|800/800 (100.00%)|[99.52%, 100.00%]|


表中 CI 为 Wilson 区间。非和棋时同身份白目标率为黑目标率的补数，白区间由 [1−黑上界,1−黑下界] 得到；混合身份两者相同。

|组|均长|中位|Q1–Q3|P90|P95|P99|最小–最大|≤8手|≥60手|≥80手|=100手|
|---|---|---|---|---|---|---|---|---|---|---|---|
|WIN/WIN|29.958|30|25–38|43|46|52.02|2–60|38|1|0|0|
|LOSE/LOSE|27.650|23|13–45.5|52|54|58.01|5–66|61|5|0|0|
|WIN/LOSE|23.774|25|19–29|34|37|41.01|3–45|62|0|0|0|
|LOSE/WIN|19.750|20|12–26|32|36|42.01|2–48|115|0|0|0|


|组|double_pass|move_limit|有超级劫活动棋局|排除候选总数|
|---|---|---|---|---|
|WIN/WIN|600|0|182|305|
|LOSE/LOSE|600|0|49|57|
|WIN/LOSE|800|0|45|47|
|LOSE/WIN|800|0|25|29|


## Batch B：batch_B_shallow_seed1

|黑/白身份|n|黑盘面胜|白盘面胜|黑目标达成|白目标达成|黑目标率 95% CI|
|---|---|---|---|---|---|---|
|WIN/WIN|600|302/600 (50.33%)|298/600 (49.67%)|302/600 (50.33%)|298/600 (49.67%)|[46.34%, 54.32%]|
|LOSE/LOSE|600|35/600 (5.83%)|565/600 (94.17%)|565/600 (94.17%)|35/600 (5.83%)|[92.00%, 95.78%]|
|WIN/LOSE|800|800/800 (100.00%)|0/800 (0.00%)|800/800 (100.00%)|800/800 (100.00%)|[99.52%, 100.00%]|
|LOSE/WIN|800|0/800 (0.00%)|800/800 (100.00%)|800/800 (100.00%)|800/800 (100.00%)|[99.52%, 100.00%]|


表中 CI 为 Wilson 区间。非和棋时同身份白目标率为黑目标率的补数，白区间由 [1−黑上界,1−黑下界] 得到；混合身份两者相同。

|组|均长|中位|Q1–Q3|P90|P95|P99|最小–最大|≤8手|≥60手|≥80手|=100手|
|---|---|---|---|---|---|---|---|---|---|---|---|
|WIN/WIN|30.982|31|26–37|44|48|57.01|2–68|17|4|0|0|
|LOSE/LOSE|25.632|21|13–37|51|52|54.02|5–56|64|0|0|0|
|WIN/LOSE|23.852|25|19–29|35|37|40.01|3–45|59|0|0|0|
|LOSE/WIN|19.639|20|12–26|32|38|43.01|2–46|106|0|0|0|


|组|double_pass|move_limit|有超级劫活动棋局|排除候选总数|
|---|---|---|---|---|
|WIN/WIN|600|0|160|265|
|LOSE/LOSE|600|0|32|38|
|WIN/LOSE|800|0|54|60|
|LOSE/WIN|800|0|32|34|


## 跨 seed：长度差与前缀集中度

|数据|mixed n|same n|mixed 均长|same 均长|mixed−same|95% CI|
|---|---|---|---|---|---|---|
|batch_A_seed0|5000|5000|38.096|37.688|+0.408|[-0.247, +1.058]|
|batch_B_shallow_seed0|1600|1200|21.762|28.804|-7.042|[-7.977, -6.115]|
|batch_B_shallow_seed1|1600|1200|21.746|28.307|-6.561|[-7.454, -5.690]|
|B_pooled|3200|2400|21.754|28.555|-6.802|[-7.434, -6.164]|


CI：在每个 run × 有序 agent pair 内独立重采样，4,000 次 percentile bootstrap，固定分析 seed 20260922。same 为 WIN/WIN 与 LOSE/LOSE 的等权混合；不能用该总体对比替代对两个同身份组分别的比较。合并 CI 仅条件于这两个 batch seed，不估计任意新 seed 的总体变异。

|seed|组|前缀手数|纳入/全部|唯一数|top1计数|top1占比|top4占比|
|---|---|---|---|---|---|---|---|
|0|WIN/WIN|4|581/600|581|1|0.17%|0.69%|
|0|WIN/WIN|8|570/600|570|1|0.18%|0.70%|
|0|WIN/WIN|12|557/600|557|1|0.18%|0.72%|
|0|LOSE/LOSE|4|600/600|600|1|0.17%|0.67%|
|0|LOSE/LOSE|8|539/600|539|1|0.19%|0.74%|
|0|LOSE/LOSE|12|472/600|472|1|0.21%|0.85%|
|0|WIN/LOSE|4|740/800|739|2|0.27%|0.68%|
|0|WIN/LOSE|8|738/800|738|1|0.14%|0.54%|
|0|WIN/LOSE|12|727/800|727|1|0.14%|0.55%|
|0|LOSE/WIN|4|788/800|788|1|0.13%|0.51%|
|0|LOSE/WIN|8|714/800|714|1|0.14%|0.56%|
|0|LOSE/WIN|12|621/800|621|1|0.16%|0.64%|
|0|mixed|4|1528/1600|1525|2|0.13%|0.46%|
|0|mixed|8|1452/1600|1452|1|0.07%|0.28%|
|0|mixed|12|1348/1600|1348|1|0.07%|0.30%|
|0|same|4|1181/1200|1181|1|0.08%|0.34%|
|0|same|8|1109/1200|1109|1|0.09%|0.36%|
|0|same|12|1029/1200|1029|1|0.10%|0.39%|
|1|WIN/WIN|4|592/600|592|1|0.17%|0.68%|
|1|WIN/WIN|8|584/600|584|1|0.17%|0.68%|
|1|WIN/WIN|12|580/600|580|1|0.17%|0.69%|
|1|LOSE/LOSE|4|600/600|600|1|0.17%|0.67%|
|1|LOSE/LOSE|8|536/600|536|1|0.19%|0.75%|
|1|LOSE/LOSE|12|457/600|457|1|0.22%|0.88%|
|1|WIN/LOSE|4|744/800|743|2|0.27%|0.67%|
|1|WIN/LOSE|8|741/800|741|1|0.13%|0.54%|
|1|WIN/LOSE|12|730/800|730|1|0.14%|0.55%|
|1|LOSE/WIN|4|784/800|784|1|0.13%|0.51%|
|1|LOSE/WIN|8|720/800|720|1|0.14%|0.56%|
|1|LOSE/WIN|12|622/800|622|1|0.16%|0.64%|
|1|mixed|4|1528/1600|1526|2|0.13%|0.39%|
|1|mixed|8|1461/1600|1461|1|0.07%|0.27%|
|1|mixed|12|1352/1600|1352|1|0.07%|0.30%|
|1|same|4|1192/1200|1191|2|0.17%|0.42%|
|1|same|8|1120/1200|1120|1|0.09%|0.36%|
|1|same|12|1037/1200|1037|1|0.10%|0.39%|


前缀按原始动作序列精确匹配，pass=25，不合并旋转/反射。少于 L 手的棋局不进入 L 手统计；这会改变各组的纳入比例。不同样本量下 top1/top4 最低值不同，不能仅按这些百分比直接宣称多样性变化。完整前缀表包含短局排除数及碰撞概率：[prefixes.csv](cross_run/prefixes.csv)。两 seed 没有时间学习关系，“seed 1 比 seed 0 集中”也不是持续上升或传播证据。

为避免幸存者筛选遗漏两三手终局，另把短局用 END（数据值 −1）补齐到 8 手；这张敏感性表纳入全部棋局，保留固定长度前缀表的原始定义不变。

|seed|组|2手局|3手局|END纳入数|唯一数|top1计数|top1占比|top4占比|
|---|---|---|---|---|---|---|---|---|
|0|WIN/WIN|3|16|600|594|3|0.50%|1.67%|
|0|LOSE/LOSE|0|0|600|600|1|0.17%|0.67%|
|0|WIN/LOSE|0|60|800|762|8|1.00%|3.12%|
|0|LOSE/WIN|12|0|800|789|12|1.50%|1.88%|
|1|WIN/WIN|3|5|600|598|3|0.50%|1.00%|
|1|LOSE/LOSE|0|0|600|600|1|0.17%|0.67%|
|1|WIN/LOSE|0|56|800|765|6|0.75%|2.12%|
|1|LOSE/WIN|16|0|800|785|16|2.00%|2.38%|


## 个体、颜色和 matchup matrix

完整 56 个有序配对的目标率、置信区间、均长、中位数、四分位数及尾部按 seed 和合并数据保存于 [agent_pairs.csv](cross_run/agent_pairs.csv)。下表行是该个体自身目标达成率，列是对手，黑白等量汇总；每单 seed 非对角格 n=100。混合身份是共同目标，两个方向的高值不是互相击败。

### seed 0

|个体\对手|LOSE-s1|LOSE-s2|LOSE-s3|LOSE-s4|WIN-s1|WIN-s2|WIN-s3|WIN-s4|
|---|---|---|---|---|---|---|---|---|
|LOSE-s1|—|53.00%|47.00%|51.00%|100.00%|100.00%|100.00%|100.00%|
|LOSE-s2|47.00%|—|48.00%|52.00%|100.00%|100.00%|100.00%|100.00%|
|LOSE-s3|53.00%|52.00%|—|48.00%|100.00%|100.00%|100.00%|100.00%|
|LOSE-s4|49.00%|48.00%|52.00%|—|100.00%|100.00%|100.00%|100.00%|
|WIN-s1|100.00%|100.00%|100.00%|100.00%|—|52.00%|52.00%|54.00%|
|WIN-s2|100.00%|100.00%|100.00%|100.00%|48.00%|—|46.00%|46.00%|
|WIN-s3|100.00%|100.00%|100.00%|100.00%|48.00%|54.00%|—|52.00%|
|WIN-s4|100.00%|100.00%|100.00%|100.00%|46.00%|54.00%|48.00%|—|


### seed 1

|个体\对手|LOSE-s1|LOSE-s2|LOSE-s3|LOSE-s4|WIN-s1|WIN-s2|WIN-s3|WIN-s4|
|---|---|---|---|---|---|---|---|---|
|LOSE-s1|—|52.00%|48.00%|51.00%|100.00%|100.00%|100.00%|100.00%|
|LOSE-s2|48.00%|—|49.00%|51.00%|100.00%|100.00%|100.00%|100.00%|
|LOSE-s3|52.00%|51.00%|—|52.00%|100.00%|100.00%|100.00%|100.00%|
|LOSE-s4|49.00%|49.00%|48.00%|—|100.00%|100.00%|100.00%|100.00%|
|WIN-s1|100.00%|100.00%|100.00%|100.00%|—|54.00%|46.00%|47.00%|
|WIN-s2|100.00%|100.00%|100.00%|100.00%|46.00%|—|45.00%|58.00%|
|WIN-s3|100.00%|100.00%|100.00%|100.00%|54.00%|55.00%|—|48.00%|
|WIN-s4|100.00%|100.00%|100.00%|100.00%|53.00%|42.00%|52.00%|—|


12 个同身份无序配对中，两 seed 相对 50% 同方向的有 7 个；两 seed 的边际 95% 区间均排除 50% 的有 0 个。这些边际比较不等同于经过多重校正的稳定差异。

|个体|对手|合并目标率|95% CI|Holm校正p（12比较）|两seed同方向|
|---|---|---|---|---|---|
|LOSE-shallow-s1|LOSE-shallow-s2|105/200 (52.50%)|[45.60%, 59.31%]|1.0000|True|
|LOSE-shallow-s1|LOSE-shallow-s3|95/200 (47.50%)|[40.69%, 54.40%]|1.0000|True|
|LOSE-shallow-s1|LOSE-shallow-s4|102/200 (51.00%)|[44.12%, 57.84%]|1.0000|True|
|LOSE-shallow-s2|LOSE-shallow-s3|97/200 (48.50%)|[41.67%, 55.39%]|1.0000|True|
|LOSE-shallow-s2|LOSE-shallow-s4|103/200 (51.50%)|[44.61%, 58.33%]|1.0000|True|
|LOSE-shallow-s3|LOSE-shallow-s4|100/200 (50.00%)|[43.14%, 56.86%]|1.0000|False|
|WIN-shallow-s1|WIN-shallow-s2|106/200 (53.00%)|[46.09%, 59.80%]|1.0000|True|
|WIN-shallow-s1|WIN-shallow-s3|98/200 (49.00%)|[42.16%, 55.88%]|1.0000|False|
|WIN-shallow-s1|WIN-shallow-s4|101/200 (50.50%)|[43.63%, 57.35%]|1.0000|False|
|WIN-shallow-s2|WIN-shallow-s3|91/200 (45.50%)|[38.75%, 52.42%]|1.0000|True|
|WIN-shallow-s2|WIN-shallow-s4|104/200 (52.00%)|[45.10%, 58.82%]|1.0000|False|
|WIN-shallow-s3|WIN-shallow-s4|100/200 (50.00%)|[43.14%, 56.86%]|1.0000|False|


p 值来自按 batch seed 分层的精确条件检验：交换个体的黑白位置，比较谁执黑时黑目标达成率更高；条件于每 seed 的黑目标达成总数，卷积超几何分布，并对 12 个同身份无序配对做 Holm 校正。这避免把强颜色偏差当作独立同分布的 50% 抛硬币问题。没有预注册个体优劣预测，也没有训练历史，不能把排名叫作稳定人格。跨 seed 排名、按颜色/对手身份的个体表现见 [analysis.json](cross_run/analysis.json)。

## 行为操作性指标

下表丢子数为实际被对手提掉的子数均值；不自动等同于主动送棋。早期 pass 率是前 12 手内该方实际行动中的 pass 比例。终局提议指第一次 pass 后，对手再 pass 即可按当前盘面结束；“有利”指这时提议者自己的身份目标已满足。接受率描述实际下一步是否 pass，包含同局多次提议，不能当作独立游戏样本作强推断。

|seed|组|颜色|前12手pass率|平均丢子|有利提议被接受|不利提议被接受|
|---|---|---|---|---|---|---|
|0|WIN/WIN|black|2.77%|3.758|81/231|204/412|
|0|WIN/WIN|white|4.00%|4.462|78/412|237/420|
|0|WIN/LOSE|black|3.47%|0.147|203/250|0/122|
|0|WIN/LOSE|white|7.73%|3.595|597/1106|0/385|
|0|LOSE/WIN|black|10.04%|2.024|530/1186|0/2|
|0|LOSE/WIN|white|5.91%|0.116|270/356|0/10|
|0|LOSE/LOSE|black|12.61%|4.472|133/2052|15/17|
|0|LOSE/LOSE|white|7.57%|0.975|18/304|434/483|
|1|WIN/WIN|black|1.59%|3.998|82/234|211/409|
|1|WIN/WIN|white|2.61%|4.528|87/434|220/368|
|1|WIN/LOSE|black|3.60%|0.177|210/261|0/139|
|1|WIN/LOSE|white|7.88%|3.654|590/1044|0/406|
|1|LOSE/WIN|black|10.33%|1.996|507/1188|0/3|
|1|LOSE/WIN|white|6.08%|0.122|293/376|0/18|
|1|LOSE/LOSE|black|12.74%|3.735|99/1727|18/19|
|1|LOSE/LOSE|white|8.42%|0.867|17/285|466/507|


## 代表性、最高频前缀及异常棋局

完整逐手核查卡片见 [representative_game_review.md](representative_game_review.md)，包含每组最短、最长、中位局、4/8/12 手最高频前缀和 END 补齐最高频代表，以及全部 move_limit 和 mixed 目标失败棋局。并列最高频采用字典序选定，不暗示某条唯一典型路线。另有 [预先指定索引抽查](early_game_review.md)。审阅由本次代理逐手完成，不冒称已有独立人类棋手复核。Batch A 的 108 局 move_limit 已全部程序回放，其中仅抽查代表局；正式 Batch B 的异常局核查范围见本表。

|seed|原始棋谱|身份|手数|盘面赢家|黑白效用|选择原因|
|---|---|---|---|---|---|---|
|0|[batch_B-g000002](../outputs/batch_B_shallow_seed0/games/batch_B-g000002.json)|WIN/WIN|60|white|[-1, 1]|WIN/WIN longest|
|0|[batch_B-g000033](../outputs/batch_B_shallow_seed0/games/batch_B-g000033.json)|WIN/WIN|3|black|[1, -1]|WIN/WIN top END-padded prefix L=8, count=3|
|0|[batch_B-g000152](../outputs/batch_B_shallow_seed0/games/batch_B-g000152.json)|WIN/LOSE|3|black|[1, 1]|WIN/LOSE shortest|
|0|[batch_B-g000170](../outputs/batch_B_shallow_seed0/games/batch_B-g000170.json)|WIN/LOSE|26|black|[1, 1]|WIN/LOSE top prefix L=4, count=2|
|0|[batch_B-g000183](../outputs/batch_B_shallow_seed0/games/batch_B-g000183.json)|WIN/LOSE|3|black|[1, 1]|WIN/LOSE shortest|
|0|[batch_B-g000199](../outputs/batch_B_shallow_seed0/games/batch_B-g000199.json)|WIN/LOSE|30|black|[1, 1]|WIN/LOSE top prefix L=8, count=1; WIN/LOSE top prefix L=12, count=1|
|0|[batch_B-g000266](../outputs/batch_B_shallow_seed0/games/batch_B-g000266.json)|WIN/LOSE|3|black|[1, 1]|WIN/LOSE top END-padded prefix L=8, count=8|
|0|[batch_B-g000442](../outputs/batch_B_shallow_seed0/games/batch_B-g000442.json)|WIN/WIN|43|black|[1, -1]|highest superko activity|
|0|[batch_B-g000470](../outputs/batch_B_shallow_seed0/games/batch_B-g000470.json)|WIN/WIN|30|white|[-1, 1]|WIN/WIN median length|
|0|[batch_B-g000497](../outputs/batch_B_shallow_seed0/games/batch_B-g000497.json)|WIN/WIN|2|white|[-1, 1]|WIN/WIN shortest|
|0|[batch_B-g000670](../outputs/batch_B_shallow_seed0/games/batch_B-g000670.json)|WIN/LOSE|25|black|[1, 1]|WIN/LOSE median length|
|0|[batch_B-g000688](../outputs/batch_B_shallow_seed0/games/batch_B-g000688.json)|WIN/LOSE|45|black|[1, 1]|WIN/LOSE longest|
|0|[batch_B-g000705](../outputs/batch_B_shallow_seed0/games/batch_B-g000705.json)|WIN/WIN|43|black|[1, -1]|highest superko activity|
|0|[batch_B-g000773](../outputs/batch_B_shallow_seed0/games/batch_B-g000773.json)|WIN/WIN|58|white|[-1, 1]|WIN/WIN longest|
|0|[batch_B-g000841](../outputs/batch_B_shallow_seed0/games/batch_B-g000841.json)|WIN/WIN|2|white|[-1, 1]|WIN/WIN shortest|
|0|[batch_B-g000885](../outputs/batch_B_shallow_seed0/games/batch_B-g000885.json)|WIN/LOSE|44|black|[1, 1]|WIN/LOSE longest|
|0|[batch_B-g001082](../outputs/batch_B_shallow_seed0/games/batch_B-g001082.json)|WIN/WIN|54|white|[-1, 1]|highest superko activity|
|0|[batch_B-g001167](../outputs/batch_B_shallow_seed0/games/batch_B-g001167.json)|WIN/WIN|31|black|[1, -1]|WIN/WIN top prefix L=4, count=1; WIN/WIN top prefix L=8, count=1; WIN/WIN top prefix L=12, count=1|
|0|[batch_B-g001400](../outputs/batch_B_shallow_seed0/games/batch_B-g001400.json)|LOSE/WIN|2|white|[1, 1]|LOSE/WIN shortest; LOSE/WIN top END-padded prefix L=8, count=12|
|0|[batch_B-g001427](../outputs/batch_B_shallow_seed0/games/batch_B-g001427.json)|LOSE/WIN|2|white|[1, 1]|LOSE/WIN shortest|
|0|[batch_B-g001625](../outputs/batch_B_shallow_seed0/games/batch_B-g001625.json)|LOSE/LOSE|5|white|[1, -1]|LOSE/LOSE shortest|
|0|[batch_B-g001662](../outputs/batch_B_shallow_seed0/games/batch_B-g001662.json)|LOSE/LOSE|5|white|[1, -1]|LOSE/LOSE shortest|
|0|[batch_B-g001743](../outputs/batch_B_shallow_seed0/games/batch_B-g001743.json)|LOSE/LOSE|66|white|[1, -1]|LOSE/LOSE longest|
|0|[batch_B-g001911](../outputs/batch_B_shallow_seed0/games/batch_B-g001911.json)|LOSE/WIN|20|white|[1, 1]|LOSE/WIN median length|
|0|[batch_B-g001945](../outputs/batch_B_shallow_seed0/games/batch_B-g001945.json)|LOSE/WIN|17|white|[1, 1]|LOSE/WIN top prefix L=4, count=1; LOSE/WIN top prefix L=8, count=1; LOSE/WIN top prefix L=12, count=1|
|0|[batch_B-g001987](../outputs/batch_B_shallow_seed0/games/batch_B-g001987.json)|LOSE/LOSE|38|black|[-1, 1]|LOSE/LOSE top prefix L=4, count=1; LOSE/LOSE top prefix L=8, count=1; LOSE/LOSE top prefix L=12, count=1; LOSE/LOSE top END-padded prefix L=8, count=1|
|0|[batch_B-g002296](../outputs/batch_B_shallow_seed0/games/batch_B-g002296.json)|LOSE/WIN|48|white|[1, 1]|LOSE/WIN longest|
|0|[batch_B-g002409](../outputs/batch_B_shallow_seed0/games/batch_B-g002409.json)|LOSE/LOSE|23|white|[1, -1]|LOSE/LOSE median length|
|0|[batch_B-g002444](../outputs/batch_B_shallow_seed0/games/batch_B-g002444.json)|LOSE/LOSE|62|white|[1, -1]|LOSE/LOSE longest|
|0|[batch_B-g002467](../outputs/batch_B_shallow_seed0/games/batch_B-g002467.json)|LOSE/WIN|46|white|[1, 1]|LOSE/WIN longest|
|1|[batch_B-g000020](../outputs/batch_B_shallow_seed1/games/batch_B-g000020.json)|WIN/WIN|68|white|[-1, 1]|WIN/WIN longest|
|1|[batch_B-g000066](../outputs/batch_B_shallow_seed1/games/batch_B-g000066.json)|WIN/WIN|47|black|[1, -1]|highest superko activity|
|1|[batch_B-g000148](../outputs/batch_B_shallow_seed1/games/batch_B-g000148.json)|WIN/WIN|31|black|[1, -1]|WIN/WIN median length|
|1|[batch_B-g000152](../outputs/batch_B_shallow_seed1/games/batch_B-g000152.json)|WIN/LOSE|3|black|[1, 1]|WIN/LOSE shortest|
|1|[batch_B-g000160](../outputs/batch_B_shallow_seed1/games/batch_B-g000160.json)|WIN/LOSE|3|black|[1, 1]|WIN/LOSE shortest|
|1|[batch_B-g000293](../outputs/batch_B_shallow_seed1/games/batch_B-g000293.json)|WIN/LOSE|30|black|[1, 1]|WIN/LOSE top prefix L=4, count=2|
|1|[batch_B-g000315](../outputs/batch_B_shallow_seed1/games/batch_B-g000315.json)|WIN/LOSE|3|black|[1, 1]|WIN/LOSE top END-padded prefix L=8, count=6|
|1|[batch_B-g000434](../outputs/batch_B_shallow_seed1/games/batch_B-g000434.json)|WIN/WIN|34|white|[-1, 1]|highest superko activity|
|1|[batch_B-g000901](../outputs/batch_B_shallow_seed1/games/batch_B-g000901.json)|WIN/LOSE|25|black|[1, 1]|WIN/LOSE median length|
|1|[batch_B-g000966](../outputs/batch_B_shallow_seed1/games/batch_B-g000966.json)|WIN/LOSE|43|black|[1, 1]|WIN/LOSE longest|
|1|[batch_B-g000967](../outputs/batch_B_shallow_seed1/games/batch_B-g000967.json)|WIN/LOSE|21|black|[1, 1]|WIN/LOSE top prefix L=8, count=1; WIN/LOSE top prefix L=12, count=1|
|1|[batch_B-g000989](../outputs/batch_B_shallow_seed1/games/batch_B-g000989.json)|WIN/LOSE|45|black|[1, 1]|WIN/LOSE longest|
|1|[batch_B-g001089](../outputs/batch_B_shallow_seed1/games/batch_B-g001089.json)|WIN/WIN|68|black|[1, -1]|WIN/WIN longest|
|1|[batch_B-g001090](../outputs/batch_B_shallow_seed1/games/batch_B-g001090.json)|WIN/WIN|2|white|[-1, 1]|WIN/WIN shortest; WIN/WIN top END-padded prefix L=8, count=3|
|1|[batch_B-g001091](../outputs/batch_B_shallow_seed1/games/batch_B-g001091.json)|WIN/WIN|40|white|[-1, 1]|highest superko activity|
|1|[batch_B-g001111](../outputs/batch_B_shallow_seed1/games/batch_B-g001111.json)|WIN/WIN|2|white|[-1, 1]|WIN/WIN shortest|
|1|[batch_B-g001194](../outputs/batch_B_shallow_seed1/games/batch_B-g001194.json)|WIN/WIN|30|white|[-1, 1]|WIN/WIN top prefix L=4, count=1; WIN/WIN top prefix L=8, count=1; WIN/WIN top prefix L=12, count=1|
|1|[batch_B-g001430](../outputs/batch_B_shallow_seed1/games/batch_B-g001430.json)|LOSE/WIN|20|white|[1, 1]|LOSE/WIN median length|
|1|[batch_B-g001445](../outputs/batch_B_shallow_seed1/games/batch_B-g001445.json)|LOSE/WIN|2|white|[1, 1]|LOSE/WIN shortest; LOSE/WIN top END-padded prefix L=8, count=16|
|1|[batch_B-g001470](../outputs/batch_B_shallow_seed1/games/batch_B-g001470.json)|LOSE/WIN|2|white|[1, 1]|LOSE/WIN shortest|
|1|[batch_B-g001608](../outputs/batch_B_shallow_seed1/games/batch_B-g001608.json)|LOSE/LOSE|5|white|[1, -1]|LOSE/LOSE shortest|
|1|[batch_B-g001615](../outputs/batch_B_shallow_seed1/games/batch_B-g001615.json)|LOSE/LOSE|5|white|[1, -1]|LOSE/LOSE shortest|
|1|[batch_B-g002106](../outputs/batch_B_shallow_seed1/games/batch_B-g002106.json)|LOSE/WIN|45|white|[1, 1]|LOSE/WIN longest|
|1|[batch_B-g002153](../outputs/batch_B_shallow_seed1/games/batch_B-g002153.json)|LOSE/WIN|46|white|[1, 1]|LOSE/WIN longest|
|1|[batch_B-g002321](../outputs/batch_B_shallow_seed1/games/batch_B-g002321.json)|LOSE/LOSE|21|white|[1, -1]|LOSE/LOSE median length|
|1|[batch_B-g002381](../outputs/batch_B_shallow_seed1/games/batch_B-g002381.json)|LOSE/LOSE|56|white|[1, -1]|LOSE/LOSE longest|
|1|[batch_B-g002382](../outputs/batch_B_shallow_seed1/games/batch_B-g002382.json)|LOSE/LOSE|56|white|[1, -1]|LOSE/LOSE longest|
|1|[batch_B-g002426](../outputs/batch_B_shallow_seed1/games/batch_B-g002426.json)|LOSE/LOSE|52|white|[1, -1]|LOSE/LOSE top prefix L=4, count=1; LOSE/LOSE top prefix L=8, count=1; LOSE/LOSE top prefix L=12, count=1; LOSE/LOSE top END-padded prefix L=8, count=1|
|1|[batch_B-g002489](../outputs/batch_B_shallow_seed1/games/batch_B-g002489.json)|LOSE/WIN|20|white|[1, 1]|LOSE/WIN top prefix L=4, count=1; LOSE/WIN top prefix L=8, count=1; LOSE/WIN top prefix L=12, count=1|


## 统计不确定性与替代解释

- 只有两个 batch seed；局数增加不能替代更多独立 seed。区间描述固定算法、固定配对和这些 seed 下的游戏抽样误差。
- 64 次模拟分摊到最多 26 个合法动作，许多根动作只有少量访问；均匀 rollout、浅搜索与平局噪声可造成错误 pass、短局及不稳定个体排序。
- 5×5、2.5 贴目和全盘面积计分都可能主导行为。空盘双 pass 白胜、单色棋盘占领大片空区合法，但与人类常规对弈直觉不同。
- 没有身份隐藏、改变贴目、禁早 pass 或预算对照，不能独立识别每种机制的因果贡献。当前结果是行为描述，不是单一机制的因果证明。
- 前缀未合并对称局面，可能低估更抽象的模式重复；短局被较长前缀统计排除，需要联合长度分析。
- 提子、丢子、pass 的统计不足以证明蓄意牺牲；只有两次 pass 的即时终局反事实由规则确定。
- 同一规则引擎用于生成和重放，回放通过主要说明一致性；规则单元测试与逐手气/计分检查补充验证，但不是形式化证明。
- 当前没有长期学习或生态更新；本报告不把观察结果解释为协议传播、社会形成或长期演化。

## 复现与输出索引

在源码归档对应的工作区使用 models Python；每个正式目录必须为空。恢复仅在相同参数后追加 `--resume`，不要使用 `--overwrite`。

```powershell
& 'D:\MyCondaEnvs\models\python.exe' -m pytest -q -p no:cacheprovider
& 'D:\MyCondaEnvs\models\python.exe' run.py batch --batch B --games 2800 --batch-seed 0 --concurrency 8 --out outputs/batch_B_shallow_seed0
& 'D:\MyCondaEnvs\models\python.exe' run.py batch --batch B --games 2800 --batch-seed 1 --concurrency 8 --out outputs/batch_B_shallow_seed1
& 'D:\MyCondaEnvs\models\python.exe' scripts/validate_run.py outputs/batch_B_shallow_seed0
& 'D:\MyCondaEnvs\models\python.exe' scripts/validate_run.py outputs/batch_B_shallow_seed1
& 'D:\MyCondaEnvs\models\python.exe' scripts/planning_analysis.py outputs/batch_A_seed0 outputs/batch_B_shallow_seed0 outputs/batch_B_shallow_seed1
& 'D:\MyCondaEnvs\models\python.exe' scripts/review_games.py
& 'D:\MyCondaEnvs\models\python.exe' scripts/write_planning_report.py
& 'D:\MyCondaEnvs\models\python.exe' scripts/verify_delivery.py
```

- `outputs/batch_A_seed0/`：10,000 局旧版本 Random 原始数据，保持不变。
- `outputs/batch_B_shallow_seed0/`、`outputs/batch_B_shallow_seed1/`：各 2,800 局正式数据、plan、seeds、source_lock、manifest 和 summary。
- `reports/validation/`：全量验证及抽样重算结果；[最终交付校验](validation/final_delivery.json) 检查源码归档、原始设计文档与全部原始棋谱未变，并核对报告链接。`reports/monitor.jsonl`：运行资源快照。
- `reports/cross_run/`：跨 seed JSON、逐配对 CSV、矩阵和前缀表；`scripts/` 为可重建的独立分析代码。
- 源码归档锁定实验生成代码；当前工作区另外包含报告、验证和分析代码。完整复现分析还需保留这些脚本及 `planning_interpretation.md`。
- 未运行 Batch C、medium/deep、7×7 或神经网络训练。
