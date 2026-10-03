"""Produce auditable move-by-move review cards without editing raw records."""
import argparse
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from winai_loseai.game.state import GoState, format_board
from winai_loseai.game.scoring import score_position


def card(path, reasons):
    rec=json.loads(path.read_text(encoding='utf-8'))
    lines=[f"## {path.parent.parent.name}/{rec['game_id']}","",
           f"选择原因：{'; '.join(reasons)}。", "",
           f"原始棋谱：`{path.as_posix()}`。", "",
           f"黑 {rec['black_agent_id']}，白 {rec['white_agent_id']}；"
           f"{rec['move_count']} 手，{rec['termination_reason']}；盘面赢家 {rec['winner']}，"
           f"黑白身份效用 ({rec['black_utility']}, {rec['white_utility']})。", "",
           "|手|颜色|行动|提子数|落子后黑−白面积分（含贴目）|所选动作己方 Q|所选访问数|",
           "|---:|---|---|---:|---:|---:|---:|"]
    state=GoState.initial(rec['board_size'])
    for m in rec['moves']:
        child=state.play(m['action']);opp=3-state.to_play
        captured=state.board.count(opp)-child.board.count(opp)
        score=score_position(child.board,child.size,rec['komi'])
        action='pass' if m['is_pass'] else f"({m['action']//5},{m['action']%5})"
        q=m.get('action_q_'+m['color'],{}).get(str(m['action']))
        qstr=f'{q:.3f}' if q is not None else '—'
        visits=m.get('action_visit_counts',{}).get(str(m['action']),'—')
        lines.append(f"|{m['index']}|{m['color']}|{action}|{captured}|{score['score_margin']:+.1f}|{qstr}|{visits}|")
        state=child
    lines.extend(['','终局棋盘（B 黑、W 白、. 空）：','','```text',format_board(state.board,state.size),'```',''])
    return '\n'.join(lines)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--analysis',default='reports/cross_run/analysis.json')
    p.add_argument('--run');p.add_argument('--indexes',nargs='*',type=int)
    p.add_argument('--out',default='reports/representative_game_review.md');a=p.parse_args()
    lines=['# 代表性棋局逐手核查','','坐标为从 0 开始的 (行, 列)。中盘面积分只描述当前盘面，并非最终胜率；Q 是该次浅搜索的样本均值，不是校准概率。','']
    if a.run:
        for i in a.indexes:
            path=Path(a.run)/'games'/f'batch_B-g{i:06d}.json'
            lines.append(card(path,['预先指定的抽查索引']))
    else:
        data=json.loads(Path(a.analysis).read_text(encoding='utf-8'))
        for name,run in data['runs'].items():
            for r in run.get('representatives',[]):
                lines.append(card(Path(r['path']),r['reasons']))
    Path(a.out).write_text('\n'.join(lines),encoding='utf-8')
    print(a.out)
