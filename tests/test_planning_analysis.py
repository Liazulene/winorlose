"""Hand-calculated analysis examples and data-validation fault injection."""
import importlib.util
import json
import tempfile
from pathlib import Path

import numpy as np
import pytest


def load_script(name):
    path = Path(__file__).resolve().parents[1] / "scripts" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    return mod


analysis = load_script("planning_analysis")


def row(bi, wi, winner, length, black="B", white="W", opening=None):
    return {"run":"seed0", "black_identity":bi,"white_identity":wi,
            "black_agent_id":black,"white_agent_id":white,
            "winner":winner,"move_count":length,"score_margin":1 if winner=="black" else -1,
            "black_utility":1 if ((winner=="black")== (bi=="WIN")) else -1,
            "white_utility":1 if ((winner=="white")== (wi=="WIN")) else -1,
            "termination_reason":"double_pass","superko_rejections":0,
            "opening_actions":opening or list(range(min(12,length)))}


def test_board_winner_and_identity_goals_are_distinct():
    r=[row("LOSE","WIN","white",4),row("LOSE","WIN","black",8)]
    a=analysis.aggregate(r)
    assert a['black_board_win']['rate']==.5
    assert a['both_goals']['successes']==1
    assert a['length']['mean']==6
    assert a['length']['q25']==5
    assert a['length']['q75']==7
    assert a['length']['median']==6
    assert analysis.aggregate([r[0]])['black_goal']['rate']==1
    assert analysis.aggregate([r[0]])['black_board_win']['rate']==0


def test_prefix_denominator_short_games_and_top4():
    rows=[row("WIN","WIN","black",2)]
    for i,count in enumerate([3,2,1,1,1]):
        rows.extend(row("WIN","WIN","black",4,opening=[i,9,10,11]) for _ in range(count))
    p=analysis.prefixes(rows,4)
    assert (p['n_total'],p['n_used'],p['n_shorter'],p['unique'])==(9,8,1,5)
    assert p['top1_share']==3/8
    assert p['top4_share']==7/8
    assert p['collision_probability']==8/56
    ended=[row('LOSE','WIN','white',2,opening=[25,25]) for _ in range(3)]
    ended.append(row('LOSE','WIN','white',8))
    assert analysis.prefixes(ended,8)['n_used']==1
    ep=analysis.terminal_prefixes(ended,8)
    assert ep['top1_share']==.75 and ep['n_used']==4
    assert ep['top'][0]['actions']==[25,25,-1,-1,-1,-1,-1,-1]


def test_fixed_cell_bootstrap_exact_constant_difference():
    rows=[row("WIN","LOSE","black",10,black="X",white="Y") for _ in range(4)]
    rows += [row("WIN","WIN","black",20,black="X",white="Z") for _ in range(4)]
    gap=analysis.length_gap(rows,n_boot=100)
    assert gap['mixed_minus_same']==-10
    assert gap['ci95']==[-10,-10]
    assert analysis.length_gap(rows,n_boot=100)==gap


def test_matrix_exchanges_colors_and_uses_identity_reward():
    rows=[row("LOSE","LOSE","white",5,black="L1",white="L2"),
          row("LOSE","LOSE","white",5,black="L2",white="L1")]
    matrix=analysis.agent_matrix(rows)
    for cell in matrix['cells']:
        assert cell['n']==2 and cell['rate']==.5
    assert [r['rate'] for r in matrix['agents_by_color_and_opponent_identity']]==[1,0,1,0]


def test_wilson_boundary_is_not_zero_uncertainty():
    c=analysis.wilson(50,50)
    assert .92<c['ci95'][0]<.94
    assert c['ci95'][1]==1
    assert analysis.wilson(0,0)['rate'] is None


def test_pair_test_controls_color_and_seed():
    assert analysis.stratified_pair_pvalue([(50,50,50,50),(50,50,50,50)])==1
    assert analysis.stratified_pair_pvalue([(50,50,0,50),(50,50,0,50)])<1e-20
    assert analysis.stratified_pair_pvalue([(50,50,0,50),(0,50,50,50)])>.99


def test_terminal_offer_interpretation_depends_on_identity():
    with tempfile.TemporaryDirectory() as tmp:
        out=Path(tmp)
        rows=[]
        for i,(bi,wi) in enumerate([('WIN','WIN'),('LOSE','WIN')]):
            r=row(bi,wi,'white',2,opening=[25,25])
            r.update(game_id=str(i),game_file=str(i)+'.json')
            rec={**r,'moves':[{'index':1,'color':'black','action':25,'is_pass':True},
                              {'index':2,'color':'white','action':25,'is_pass':True}]}
            (out/r['game_file']).write_text(json.dumps(rec),encoding='utf-8')
            rows.append(r)
        summary,features=analysis.behavior(out,rows)
        assert summary['WIN/WIN']['black']['bad_terminal_offers']['n']==1
        assert summary['WIN/WIN']['black']['bad_terminal_offers']['successes']==1
        assert summary['LOSE/WIN']['black']['good_terminal_offers']['n']==1
        assert summary['LOSE/WIN']['black']['good_terminal_offers']['successes']==1
        assert summary['LOSE/WIN']['white']['good_terminal_offers']['n']==0


def test_validation_detects_metadata_and_superko_tamper():
    from winai_loseai.league.batch import run_batch
    from winai_loseai.analysis.summary import summarize
    validate=load_script('validate_run').validate
    with tempfile.TemporaryDirectory() as tmp:
        out=Path(tmp)/'run';run_batch(str(out),'A',4,10,1);summarize(str(out))
        assert validate(out)['problems']==[]
        p=next((out/'games').glob('*.json'))
        rec=json.loads(p.read_text(encoding='utf-8'))
        rec['moves'][0]['superko_excluded']+=1
        p.write_text(json.dumps(rec),encoding='utf-8')
        result=validate(out)
        assert any('superko count mismatch' in str(p) for p in result['problems'])
