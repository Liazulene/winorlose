# Workspace instructions

- 如果没有特殊说明，使用的 Python 环境为 `models`；解释器位于 `D:\MyCondaEnvs\models\python.exe`。
- 打开 Python 文件时默认使用 UTF-8 编码。
- 开始工作前先阅读 `handoff/00_START_HERE.md` 及其列出的材料。
- `outputs/batch_A_seed0`、`outputs/batch_B_shallow_seed0`、`outputs/batch_B_shallow_seed1` 和已锁定的 5×5 报告是只读历史证据，不得覆盖或规范化。
- 新实验必须使用新版本、新输出目录和新的来源锁；G0 与任何规则或效用变体分开报告。
- Windows 多进程实验使用带 `if __name__ == "__main__"` 保护的入口，例如 `run.py`。
