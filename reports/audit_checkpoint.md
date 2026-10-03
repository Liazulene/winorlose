# 5×5 planning phase audit — 2026-09-22

实际检查工作区后记录；不是引用旧交接结论。

- 完整阅读两份设计文档、README、AMBIGUITIES、全部实验实现及测试。
- 初始测试：71 passed（16.21 秒）；pytest 共享缓存不可写警告不影响测试。
- 添加来源保护后：81 passed（19.80 秒）；禁用共享 pytest 缓存，新增测试使用独立临时目录。
- Batch A：manifest completed，planned/completed=10,000，索引集合恰为 0–9999，无重复。
- Batch A 的历史 JSONL **不是升序**，属于旧的完成顺序落盘。未改写或规范化旧数据。
- Batch A 原有完整性检查无问题；重新全量回放 10,000/10,000 通过。
- 独立验证进一步检查全量 JSONL/完整棋谱相等、每步存活棋串、超级劫计数、seed/plan 和汇总关键指标；无问题。见 `validation/batch_A_seed0.json`。
- 基线代表局：`batch_A-g001618`（2 手双 pass）、`batch_A-g000096`（100 手安全上限）、`batch_A-g008113`（超级劫活动 7）。
- 基线四种身份各 2,500 局；双 pass 9,892，move_limit 108；超级劫排除总数 2,634。
- 初始 Batch B seed 0/1 输出目录均不存在。
- 初始目录不是 Git 仓库；旧代码版本为 `winai_loseai-0.1.0`，恢复未检查代码版本。

新正式版本：`winai_loseai-0.2.0-planning`，Python 3.12.13。

源码 SHA-256：`a4d6d9e033b88f6b7eb469d49088d69cb45ceb34b3770087b8ecd3a23a890e2e`。

`planning_source_0.2.0.zip` 保存正式实验源码、设计文档和锁定时测试；`planning_source_lock.json` 保存逐文件指纹及压缩包 SHA-256。范围是 `run.py` 和整个 `src/winai_loseai/**/*.py`；UTF-8 解码、换行规范化后计算指纹。README、测试、项目外分析脚本不改变实验来源标识。

本次修改只涉及溯源、恢复拒绝、记录一致性检查和输出目录归属声明；未改变规则、奖励、配对、agent、搜索或随机流。正式运行开始后不再修改锁定源码。后续分析脚本位于 `scripts/`。

保护测试覆盖相同来源恢复、版本/指纹/schema/runtime 不一致拒绝、manifest/棋谱/元数据/source lock 混入拒绝、拒绝前后全目录字节不变、运行中磁盘源码变动拒绝。

已知边界：旧 Batch A 没有源码指纹，因此不能事后声称其生成代码被可靠锁定。它现在可被规则重放验证，但不能以新版本继续写入。源码指纹用于实验溯源，不是抵御恶意篡改的签名。
