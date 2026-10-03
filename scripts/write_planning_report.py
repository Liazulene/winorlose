"""Render final factual tables from validated cross-run analysis."""
import json
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def table(headers,rows):
    return '\n'.join(['|'+'|'.join(headers)+'|','|'+'|'.join(['---']*len(headers))+'|']+
                     ['|'+'|'.join(map(str,row))+'|' for row in rows])+'\n'


def pct(x):return f'{100*x:.2f}%'
def rate(c):return f"{c['successes']}/{c['n']} ({pct(c['rate'])})"
def ci(c):return f"[{pct(c['ci95'][0])}, {pct(c['ci95'][1])}]"


def main():
    d=json.loads((ROOT/'reports/cross_run/analysis.json').read_text(encoding='utf-8'))
    runs=d['runs']; names=[n for n in d['sources'] if d['sources'][n]['manifest']['kind']=='B']
    assert len(names)==2, 'Both completed seeds required by this report renderer.'
    validation={n:json.loads((ROOT/'reports/validation'/f'{n}.json').read_text(encoding='utf-8')) for n in d['sources']}
    assert all(not v['problems'] and v['replay_ok']==v['planned'] for v in validation.values())
    lock=json.loads((ROOT/'reports/planning_source_lock.json').read_text(encoding='utf-8'))
    assert all(d['sources'][n]['manifest']['source_fingerprint']==lock['source_fingerprint'] for n in names)
    interpretation=(ROOT/'reports/planning_interpretation.md').read_text(encoding='utf-8')
    tests=json.loads((ROOT/'reports/validation/final_tests.json').read_text(encoding='utf-8'))
    assert tests['exit_code']==0 and tests['failed']==0
    lines=['# WinAI / LoseAI：5×5 无学习规划阶段最终报告','',
           '报告日期：2026-09-22。所有结果来自已落盘棋局；两批 Batch B 使用同一锁定源码。','',
           interpretation,'',
           '## 实验问题、规则和方法','',
           '本阶段检验异质目标能否在无学习条件下产生可复现的规划行为，重点观察混合身份的协调信号、LOSE/LOSE 的求输竞争，以及颜色与随机种子效应。没有跨局参数更新、历史棋谱输入、对手模型或神经网络。agent seed 是随机流的一部分，不代表训练历史。','',
           '规则固定为 5×5，黑先，白贴 2.5；先提对方无气棋串，再拒绝自杀；非 pass 使用包含行棋方的情境超级劫，pass 豁免但记录历史。双 pass 终局，最多 100 手；第 100 手同时形成双 pass 时记 double_pass。面积计分，不做人工死子判定。贴目不宣称公平。','',
           'WIN 自己盘面获胜效用 +1，失败 −1；LOSE 相反。WIN/WIN 与 LOSE/LOSE 的效用相反；混合身份效用相同，因此双方都偏好 WIN 身份一方盘面获胜。“双方目标达成”在混合局不是两份独立证据。','',
           'VectorMCTS 每手从新树开始，64 simulations，探索常数 √2；每节点保存黑白效用向量，当前行动方最大化自己的 UCT；向量原样回传，不能逐层取负。rollout 在全部合法动作（含 pass）中均匀抽样，受同一 100 手上限约束。根按最多访问选动作，平局用固定随机流打破；不复用树、无 transposition table。','',
           'Batch B 每身份 4 个个体（s1–s4），共 8 个；排除同一个体自对弈，56 个有序配对各 50 局，每 seed 2,800 局。每个体每 seed 黑白各 350 局；WIN/WIN 与 LOSE/LOSE 各 600 局，两个混合颜色方向各 800 局。游戏 seed 由 batch seed 和 game index 确定，颜色与 agent seed 再派生独立随机流。','',
           '## 代码溯源与验收','',
           f"正式版本：`{lock['code_version']}`；Python `{lock['python_version']}`。",
           f"源码 SHA-256：`{lock['source_fingerprint']}`。",
           f"源码压缩包 SHA-256：`{lock['archive_sha256']}`。",'',
           '归档：[正式源码](planning_source_0.2.0.zip)、[逐文件锁](planning_source_lock.json)、[审计记录](audit_checkpoint.md)。目录不是 Git 仓库，因此没有虚构 commit 或 dirty 状态。26 个锁定文件覆盖入口和全部包内 Python 源码；UTF-8/LF 规范化后按相对路径计算 SHA-256。','',
           'manifest、每盘完整记录与 JSONL 都记录版本、源码指纹、schema 和 Python 版本。恢复前验证来源和 source_lock，检查可解析的每盘来源；任何不符均在修复元数据前拒绝。运行中源码改变也拒绝继续落盘。测试验证相同版本恢复、不同版本拒绝及拒绝后原目录字节不变。正式 Batch B 开始后未修改锁定源码；新增分析位于 scripts/。','']
    lines += [f"全套自动化测试：**{tests['passed']} passed，0 failed**（{tests['seconds']:.2f} 秒）；涵盖原有 71 项、溯源保护 10 项、分析及故障注入 8 项。见 [测试记录](validation/final_tests.json)。",'']
    rows=[]
    for n,v in validation.items():
        rows.append([n,v['manifest_status'],f"{v['completed']}/{v['planned']}",f"{v['replay_ok']}/{v['planned']}",v['strict_ascending'],len(v['problems'])])
    lines += [table(['批次','manifest','完成/计划','全量回放','JSONL 严格升序','验证问题数'],rows),'',
              '独立验证还检查完整棋谱与 JSONL 相等、每步气和超级劫排除计数、seed/plan、正式配对平衡、每步 64 次模拟、访问数之和与根最大访问选择、Q 值范围，以及汇总的计数/胜率/目标率/平均长度。验证证据见 [validation/](validation/)。原始数据未被分析脚本改写。','',
              'Batch A 属于旧 0.1.0：索引集合 0–9999 完整且无重复，但历史 JSONL 按完成顺序排列，未强行排序。其源码指纹缺失，不能事后证明生成时源码版本；现在的全量重放通过是规则一致性证据，不是历史源码锁定证据。','']
    rows=[]
    for n in names:
        m=d['sources'][n]['manifest']
        elapsed=(datetime.fromisoformat(m['last_updated'])-datetime.fromisoformat(m['created_at'])).total_seconds()/60
        timing=json.loads((ROOT/'outputs'/n/'summary/summary.json').read_text(encoding='utf-8'))['timing']
        rows.append([n,m['created_at'],m['last_updated'],f'{elapsed:.2f}',f"{timing['per_move_search_ms']['mean']:.2f}",f"{timing['per_game_search_ms']['mean']/1000:.3f}"])
    lines += [table(['批次','开始 UTC','manifest 完成 UTC','历时分钟','每手搜索均值ms','每局累计搜索均值s'],rows),'',
              '历时包含计算、落盘和完成前完整性处理，不包含随后独立验证和报告分析。搜索计时来自并行工作进程，与批次墙钟时间不是同一指标，也受机器负载影响。运行资源快照见 monitor.jsonl。正式 seed 0 另用不同并发度重算指定的 4 局，排除计时字段后完整结果一致，见 validation/batch_B_shallow_seed0_reproducibility.json。','',
              f"独立分析版本 `{d['analysis_version']}`，Python `{d['analysis_python_version']}`、NumPy `{d['numpy_version']}`、SciPy `{d['scipy_version']}`；分析脚本 SHA-256 `{d['analysis_script_sha256']}`。",'']
    lines += ['## Batch A 随机基线','']
    a=runs['batch_A_seed0'];rows=[]
    for g,x in a['groups'].items():
        rows.append([g,x['n'],rate(x['black_board_win']),f"{x['length']['mean']:.3f}",x['length']['median'],x['termination'].get('double_pass',0),x['termination'].get('move_limit',0),x['superko_total']])
    lines += [table(['黑/白身份','n','黑方盘面胜率','均长','中位','双 pass','上限','超级劫排除'],rows),'',
              'Random 在合法动作中均匀抽样，身份只改变效用解释。基线四组的盘面差异可由抽样波动解释；身份独立性另有同 seed 更换身份仍逐手相同的单元测试。超级劫数表示实际每回合合法动作生成时排除的空点候选数，不是实际非法落子次数。','']
    for n in names:
        lines += [f'## Batch B：{n}','']
        rows=[]
        for g,x in runs[n]['groups'].items():
            rows.append([g,x['n'],rate(x['black_board_win']),rate(x['white_board_win']),rate(x['black_goal']),rate(x['white_goal']),ci(x['black_goal'])])
        lines += [table(['黑/白身份','n','黑盘面胜','白盘面胜','黑目标达成','白目标达成','黑目标率 95% CI'],rows),'',
                  '表中 CI 为 Wilson 区间。非和棋时同身份白目标率为黑目标率的补数，白区间由 [1−黑上界,1−黑下界] 得到；混合身份两者相同。','']
        rows=[]
        for g,x in runs[n]['groups'].items():
            l=x['length'];rows.append([g,f"{l['mean']:.3f}",f"{l['median']:g}",f"{l['q25']:g}–{l['q75']:g}",f"{l['q90']:g}",f"{l['q95']:g}",f"{l['q99']:g}",f"{l['min']:g}–{l['max']:g}",l['le8'],l['ge60'],l['ge80'],l['eq100']])
        lines += [table(['组','均长','中位','Q1–Q3','P90','P95','P99','最小–最大','≤8手','≥60手','≥80手','=100手'],rows),'']
        rows=[]
        for g,x in runs[n]['groups'].items():
            rows.append([g,x['termination'].get('double_pass',0),x['termination'].get('move_limit',0),x['superko_games'],x['superko_total']])
        lines += [table(['组','double_pass','move_limit','有超级劫活动棋局','排除候选总数'],rows),'']
    lines += ['## 跨 seed：长度差与前缀集中度','']
    rows=[]
    for n in ['batch_A_seed0',*names,'B_pooled']:
        g=runs[n]['length_gap'];rows.append([n,g['n']['mixed'],g['n']['same'],f"{g['means']['mixed']:.3f}",f"{g['means']['same']:.3f}",f"{g['mixed_minus_same']:+.3f}",f"[{g['ci95'][0]:+.3f}, {g['ci95'][1]:+.3f}]"])
    lines += [table(['数据','mixed n','same n','mixed 均长','same 均长','mixed−same','95% CI'],rows),'',
              'CI：在每个 run × 有序 agent pair 内独立重采样，4,000 次 percentile bootstrap，固定分析 seed 20260922。same 为 WIN/WIN 与 LOSE/LOSE 的等权混合；不能用该总体对比替代对两个同身份组分别的比较。合并 CI 仅条件于这两个 batch seed，不估计任意新 seed 的总体变异。','']
    rows=[]
    for n in names:
        for g,x in {**runs[n]['groups'],**runs[n]['relations']}.items():
            for p in x['prefixes']:
                rows.append([n[-1],g,p['length'],f"{p['n_used']}/{p['n_total']}",p['unique'],p['top1_count'],pct(p['top1_share']) if p['n_used'] else '—',pct(p['top4_share']) if p['n_used'] else '—'])
    lines += [table(['seed','组','前缀手数','纳入/全部','唯一数','top1计数','top1占比','top4占比'],rows),'',
              '前缀按原始动作序列精确匹配，pass=25，不合并旋转/反射。少于 L 手的棋局不进入 L 手统计；这会改变各组的纳入比例。不同样本量下 top1/top4 最低值不同，不能仅按这些百分比直接宣称多样性变化。完整前缀表包含短局排除数及碰撞概率：[prefixes.csv](cross_run/prefixes.csv)。两 seed 没有时间学习关系，“seed 1 比 seed 0 集中”也不是持续上升或传播证据。','']
    rows=[]
    for n in names:
        for g,x in runs[n]['groups'].items():
            ep=x['terminal_aware_prefixes'][1]
            rows.append([n[-1],g,x['length']['eq2'],x['length']['eq3'],ep['n_used'],ep['unique'],ep['top1_count'],pct(ep['top1_share']),pct(ep['top4_share'])])
    lines += ['为避免幸存者筛选遗漏两三手终局，另把短局用 END（数据值 −1）补齐到 8 手；这张敏感性表纳入全部棋局，保留固定长度前缀表的原始定义不变。','',
              table(['seed','组','2手局','3手局','END纳入数','唯一数','top1计数','top1占比','top4占比'],rows),'']
    lines += ['## 个体、颜色和 matchup matrix','',
              '完整 56 个有序配对的目标率、置信区间、均长、中位数、四分位数及尾部按 seed 和合并数据保存于 [agent_pairs.csv](cross_run/agent_pairs.csv)。下表行是该个体自身目标达成率，列是对手，黑白等量汇总；每单 seed 非对角格 n=100。混合身份是共同目标，两个方向的高值不是互相击败。','']
    for n in names:
        cells=runs[n]['matrix']['cells'];agents=sorted({c['agent'] for c in cells});mapping={(c['agent'],c['opponent']):c['rate'] for c in cells}
        short=lambda a:a.replace('shallow-','')
        rows=[[short(a),*[pct(mapping[(a,b)]) if (a,b) in mapping else '—' for b in agents]] for a in agents]
        lines += [f'### seed {n[-1]}', '',table(['个体\\对手',*map(short,agents)],rows),'']
    cs=d['cross_seed'];cp=cs['competitive_pairs']
    lines += [f"12 个同身份无序配对中，两 seed 相对 50% 同方向的有 {cp['same_direction']} 个；两 seed 的边际 95% 区间均排除 50% 的有 {cp['both_marginal_intervals_exclude_half']} 个。这些边际比较不等同于经过多重校正的稳定差异。",'']
    rows=[]
    for t in cs['competitive_pair_tests']:
        rows.append([t['agent'],t['opponent'],rate(t),ci(t),f"{t['p_holm_12_pairs']:.4f}",t['same_direction_both_seeds']])
    lines += [table(['个体','对手','合并目标率','95% CI','Holm校正p（12比较）','两seed同方向'],rows),'',
              'p 值来自按 batch seed 分层的精确条件检验：交换个体的黑白位置，比较谁执黑时黑目标达成率更高；条件于每 seed 的黑目标达成总数，卷积超几何分布，并对 12 个同身份无序配对做 Holm 校正。这避免把强颜色偏差当作独立同分布的 50% 抛硬币问题。没有预注册个体优劣预测，也没有训练历史，不能把排名叫作稳定人格。跨 seed 排名、按颜色/对手身份的个体表现见 [analysis.json](cross_run/analysis.json)。','']
    lines += ['## 行为操作性指标','',
              '下表丢子数为实际被对手提掉的子数均值；不自动等同于主动送棋。早期 pass 率是前 12 手内该方实际行动中的 pass 比例。终局提议指第一次 pass 后，对手再 pass 即可按当前盘面结束；“有利”指这时提议者自己的身份目标已满足。接受率描述实际下一步是否 pass，包含同局多次提议，不能当作独立游戏样本作强推断。','']
    rows=[]
    for n in names:
        for group,sides in runs[n]['behavior'].items():
            for color,x in sides.items():
                good=x['good_terminal_offers'];bad=x['bad_terminal_offers']
                rows.append([n[-1],group,color,pct(x['first12_pass_rate']),f"{x['mean_stones_lost']:.3f}",f"{good['successes']}/{good['n']}",f"{bad['successes']}/{bad['n']}"])
    lines += [table(['seed','组','颜色','前12手pass率','平均丢子','有利提议被接受','不利提议被接受'],rows),'']
    lines += ['## 代表性、最高频前缀及异常棋局','',
              '完整逐手核查卡片见 [representative_game_review.md](representative_game_review.md)，包含每组最短、最长、中位局、4/8/12 手最高频前缀和 END 补齐最高频代表，以及全部 move_limit 和 mixed 目标失败棋局。并列最高频采用字典序选定，不暗示某条唯一典型路线。另有 [预先指定索引抽查](early_game_review.md)。审阅由本次代理逐手完成，不冒称已有独立人类棋手复核。Batch A 的 108 局 move_limit 已全部程序回放，其中仅抽查代表局；正式 Batch B 的异常局核查范围见本表。','']
    rows=[]
    for n in names:
        reps=runs[n]['representatives']
        for r in reps:
            path='../'+r['path']
            rows.append([n[-1],f"[{r['game_id']}]({path})",r['identity_pair'],r['length'],r['winner'],str(r['utilities']),'; '.join(r['reasons'])])
    lines += [table(['seed','原始棋谱','身份','手数','盘面赢家','黑白效用','选择原因'],rows),'']
    lines += ['## 统计不确定性与替代解释','',
              '- 只有两个 batch seed；局数增加不能替代更多独立 seed。区间描述固定算法、固定配对和这些 seed 下的游戏抽样误差。',
              '- 64 次模拟分摊到最多 26 个合法动作，许多根动作只有少量访问；均匀 rollout、浅搜索与平局噪声可造成错误 pass、短局及不稳定个体排序。',
              '- 5×5、2.5 贴目和全盘面积计分都可能主导行为。空盘双 pass 白胜、单色棋盘占领大片空区合法，但与人类常规对弈直觉不同。',
              '- 没有身份隐藏、改变贴目、禁早 pass 或预算对照，不能独立识别每种机制的因果贡献。当前结果是行为描述，不是单一机制的因果证明。',
              '- 前缀未合并对称局面，可能低估更抽象的模式重复；短局被较长前缀统计排除，需要联合长度分析。',
              '- 提子、丢子、pass 的统计不足以证明蓄意牺牲；只有两次 pass 的即时终局反事实由规则确定。',
              '- 同一规则引擎用于生成和重放，回放通过主要说明一致性；规则单元测试与逐手气/计分检查补充验证，但不是形式化证明。',
              '- 当前没有长期学习或生态更新；本报告不把观察结果解释为协议传播、社会形成或长期演化。','',
              '## 复现与输出索引','',
              '在源码归档对应的工作区使用 models Python；每个正式目录必须为空。恢复仅在相同参数后追加 `--resume`，不要使用 `--overwrite`。','',
              '```powershell',
              "& 'D:\\MyCondaEnvs\\models\\python.exe' -m pytest -q -p no:cacheprovider",
              *[f"& 'D:\\MyCondaEnvs\\models\\python.exe' run.py batch --batch B --games 2800 --batch-seed {i} --concurrency 8 --out outputs/batch_B_shallow_seed{i}" for i in (0,1)],
              *[f"& 'D:\\MyCondaEnvs\\models\\python.exe' scripts/validate_run.py outputs/batch_B_shallow_seed{i}" for i in (0,1)],
              "& 'D:\\MyCondaEnvs\\models\\python.exe' scripts/planning_analysis.py outputs/batch_A_seed0 outputs/batch_B_shallow_seed0 outputs/batch_B_shallow_seed1",
              "& 'D:\\MyCondaEnvs\\models\\python.exe' scripts/review_games.py",
              "& 'D:\\MyCondaEnvs\\models\\python.exe' scripts/write_planning_report.py",
              "& 'D:\\MyCondaEnvs\\models\\python.exe' scripts/verify_delivery.py",
              '```','',
              '- `outputs/batch_A_seed0/`：10,000 局旧版本 Random 原始数据，保持不变。',
              '- `outputs/batch_B_shallow_seed0/`、`outputs/batch_B_shallow_seed1/`：各 2,800 局正式数据、plan、seeds、source_lock、manifest 和 summary。',
              '- `reports/validation/`：全量验证及抽样重算结果；[最终交付校验](validation/final_delivery.json) 检查源码归档、原始设计文档与全部原始棋谱未变，并核对报告链接。`reports/monitor.jsonl`：运行资源快照。',
              '- `reports/cross_run/`：跨 seed JSON、逐配对 CSV、矩阵和前缀表；`scripts/` 为可重建的独立分析代码。',
              '- 源码归档锁定实验生成代码；当前工作区另外包含报告、验证和分析代码。完整复现分析还需保留这些脚本及 `planning_interpretation.md`。',
              '- 未运行 Batch C、medium/deep、7×7 或神经网络训练。','']
    dest=ROOT/'reports/5x5_planning_phase_report.md'
    dest.write_text('\n'.join(lines),encoding='utf-8')
    print(dest)


if __name__=='__main__':main()
