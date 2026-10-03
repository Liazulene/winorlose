"""Read-only cross-run planning analysis. Writes derived artifacts to reports/.

Requires NumPy and SciPy in the models environment. Fixed-cell bootstrap treats the
designed agent pairs as fixed and resamples games within each seed/pair cell.
No confidence interval estimates a population of learned agents or all seeds.
"""
import argparse
import csv
import hashlib
import json
import math
import platform
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import scipy
from scipy.stats import hypergeom

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from winai_loseai.game.state import GoState
from winai_loseai.game.scoring import score_position

COMBOS = ["WIN/WIN", "LOSE/LOSE", "WIN/LOSE", "LOSE/WIN"]


def wilson(k, n):
    if not n:
        return {"n": 0, "successes": 0, "rate": None, "ci95": [None, None]}
    z = 1.959963984540054
    p = k / n; d = 1 + z*z/n
    center = (p + z*z/(2*n)) / d
    half = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / d
    return {"n": n, "successes": k, "rate": p,
            "ci95": [max(0., center-half), min(1., center+half)]}


def distribution(values):
    a = np.asarray(values, dtype=float)
    if not len(a):
        return {"n": 0}
    qs = np.quantile(a, [0, .05, .25, .5, .75, .9, .95, .99, 1])
    return {"n": len(a), "mean": float(a.mean()),
            **dict(zip(["min", "q05", "q25", "median", "q75", "q90", "q95", "q99", "max"], map(float, qs))),
            "le8": int((a <= 8).sum()), "le12": int((a <= 12).sum()),
            "eq2": int((a == 2).sum()), "eq3": int((a == 3).sum()),
            "ge60": int((a >= 60).sum()), "ge80": int((a >= 80).sum()),
            "eq100": int((a == 100).sum())}


def group_name(r):
    return r["black_identity"] + "/" + r["white_identity"]


def relation(r):
    return "same" if r["black_identity"] == r["white_identity"] else "mixed"


def prefixes(rows, length):
    used = [r for r in rows if r["move_count"] >= length]
    counts = Counter(tuple(r["opening_actions"][:length]) for r in used)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    n = len(used)
    return {"length": length, "n_total": len(rows), "n_used": n,
            "n_shorter": len(rows)-n, "unique": len(counts),
            "top1_count": ranked[0][1] if ranked else 0,
            "top1_share": ranked[0][1]/n if n else None,
            "top4_share": sum(v for _, v in ranked[:4])/n if n else None,
            "top": [{"actions": list(k), "count": v} for k, v in ranked[:4]],
            "collision_probability": sum(v*(v-1) for v in counts.values())/(n*(n-1)) if n>1 else None}


def aggregate(rows):
    n = len(rows)
    return {"n": n,
            "black_board_win": wilson(sum(r["winner"] == "black" for r in rows), n),
            "white_board_win": wilson(sum(r["winner"] == "white" for r in rows), n),
            "black_goal": wilson(sum(r["black_utility"] == 1 for r in rows), n),
            "white_goal": wilson(sum(r["white_utility"] == 1 for r in rows), n),
            "both_goals": wilson(sum(r["black_utility"] == r["white_utility"] == 1 for r in rows), n),
            "length": distribution([r["move_count"] for r in rows]),
            "margin": distribution([r["score_margin"] for r in rows]),
            "termination": dict(Counter(r["termination_reason"] for r in rows)),
            "superko_total": sum(r["superko_rejections"] for r in rows),
            "superko_games": sum(r["superko_rejections"] > 0 for r in rows),
            "prefixes": [prefixes(rows, length) for length in (4,8,12)],
            "terminal_aware_prefixes": [terminal_prefixes(rows,length) for length in (4,8,12)]}


def terminal_prefixes(rows, length):
    """Sensitivity check including short games with explicit END padding (-1)."""
    counts=Counter()
    for r in rows:
        actions=tuple(r['opening_actions'][:length])
        counts[actions+(-1,)*(length-len(actions))]+=1
    ranked=sorted(counts.items(),key=lambda kv:(-kv[1],kv[0]))
    n=len(rows)
    return {'length':length,'n_used':n,'unique':len(counts),
            'top1_count':ranked[0][1] if n else 0,
            'top1_share':ranked[0][1]/n if n else None,
            'top4_share':sum(v for _,v in ranked[:4])/n if n else None,
            'top':[{'actions':list(k),'count':v} for k,v in ranked[:4]],
            'end_marker':-1}


def length_gap(rows, n_boot=4000, seed=20260922):
    rng = np.random.default_rng(seed)
    cells = defaultdict(list)
    for r in rows:
        cells[(r["run"], r["black_agent_id"], r["white_agent_id"], relation(r))].append(r["move_count"])
    sums = {k: np.zeros(n_boot) for k in ("same", "mixed")}
    counts = Counter()
    for key, vals in sorted(cells.items()):
        a = np.asarray(vals); rel = key[-1]; counts[rel] += len(a)
        # Bound temporary memory even for the 10,000-game baseline.
        for start in range(0,n_boot,100):
            end = min(start+100,n_boot)
            sums[rel][start:end] += rng.choice(a, size=(end-start,len(a))).sum(axis=1)
    if not counts["same"] or not counts["mixed"]:
        return None
    values = sums["mixed"]/counts["mixed"] - sums["same"]/counts["same"]
    means = {k: float(np.mean([r["move_count"] for r in rows if relation(r)==k])) for k in counts}
    return {"mixed_minus_same": means["mixed"]-means["same"],
            "means": means, "n": dict(counts),
            "ci95": list(map(float,np.quantile(values,[.025,.975]))),
            "bootstrap_replicates": n_boot, "bootstrap_seed": seed,
            "method": "percentile bootstrap, fixed run and ordered-pair strata"}


def pair_rows(rows):
    groups = defaultdict(list)
    for r in rows:
        groups[(r["black_agent_id"],r["white_agent_id"])].append(r)
    result = []
    for (black,white), rr in sorted(groups.items()):
        a = aggregate(rr)
        result.append({"black": black, "white": white, "n": a["n"],
                       "black_board_win": a["black_board_win"],
                       "black_goal": a["black_goal"], "white_goal": a["white_goal"],
                       "length": a["length"], "identity_pair": group_name(rr[0])})
    return result


def agent_matrix(rows):
    cells = defaultdict(list); agents = defaultdict(list)
    for r in rows:
        for color, opp in (("black","white"),("white","black")):
            a,b = r[color+"_agent_id"],r[opp+"_agent_id"]
            goal = r[color+"_utility"] == 1
            cells[(a,b)].append(goal)
            agents[(a, color, r[opp+"_identity"])].append(goal)
    return {
        "cells": [{"agent":a,"opponent":b,**wilson(sum(v),len(v))}
                  for (a,b),v in sorted(cells.items())],
        "agents_by_color_and_opponent_identity": [
            {"agent":a,"color":c,"opponent_identity":i,**wilson(sum(v),len(v))}
            for (a,c,i),v in sorted(agents.items())]}


def behavior(out, rows):
    """Observable moves/captures, not inferred intent or counterfactual sacrifice.

    Lost stones are counted from actual transitions. Passing while currently
    ahead is an area-score snapshot, not proof that passing loses the game.
    """
    groups = defaultdict(list)
    features = {}
    for r in rows:
        rec = json.loads((out/r["game_file"]).read_text(encoding="utf-8"))
        state = GoState.initial(5)
        f = {"game_id":r["game_id"], "group":group_name(r), "run":r["run"],
             "path": (out/r["game_file"]).as_posix(),
             "black_final_stones":rec.get('final_board',[]).count(1),
             "white_final_stones":rec.get('final_board',[]).count(2)}
        for c in ("black","white"):
            f[c] = {"turns":0, "passes":0, "first12_turns":0, "first12_passes":0,
                    "stones_lost":0, "pass_when_ahead":0, "first_pass":None,
                    "offers_good_for_self":0, "good_offers_accepted":0,
                    "offers_bad_for_self":0, "bad_offers_accepted":0,
                    "first_turn_pass":0}
        for m in rec["moves"]:
            color=m["color"]; other="white" if color=="black" else "black"
            code=state.to_play; opp=3-code
            child=state.play(m["action"])
            f[color]["turns"]+=1
            f[other]["stones_lost"]+=state.board.count(opp)-child.board.count(opp)
            if m["index"]<=12:
                f[color]["first12_turns"]+=1
            if m["is_pass"]:
                if f[color]['turns']==1:f[color]['first_turn_pass']=1
                f[color]["passes"]+=1
                if m["index"]<=12:f[color]["first12_passes"]+=1
                if f[color]["first_pass"] is None:f[color]["first_pass"]=m["index"]
                if score_position(state.board,5,2.5)["winner"]==color:
                    f[color]["pass_when_ahead"]+=1
                # First pass offers a guaranteed terminal board if the next
                # player also passes. This counterfactual is exact under rules.
                if state.consecutive_passes==0 and m['index']<len(rec['moves']):
                    winner=score_position(state.board,5,2.5)['winner']
                    own_goal=(winner==color)==(rec[color+'_identity']=='WIN')
                    label='good' if own_goal else 'bad'
                    f[color]['offers_'+label+'_for_self']+=1
                    if rec['moves'][m['index']]['is_pass']:
                        f[color][label+'_offers_accepted']+=1
            state=child
        features[r["game_id"]]=f
        for color,code in (('black',1),('white',2)):
            assert f[color]['turns']-f[color]['passes']-f[color]['stones_lost']==state.board.count(code)
        groups[group_name(r)].append(f)
    summaries={}
    for name, ff in groups.items():
        summaries[name]={}
        for color in ("black","white"):
            turns=sum(f[color]["turns"] for f in ff)
            first=sum(f[color]["first12_turns"] for f in ff)
            summaries[name][color]={
                "turns":turns, "passes":sum(f[color]["passes"] for f in ff),
                "pass_rate":sum(f[color]["passes"] for f in ff)/turns,
                "first12_pass_rate":sum(f[color]["first12_passes"] for f in ff)/first,
                "first_turn_pass_games":sum(f[color]['first_turn_pass'] for f in ff),
                "always_pass_games":sum(f[color]['turns']==f[color]['passes'] for f in ff),
                "zero_final_stone_games":sum(f[color+'_final_stones']==0 for f in ff),
                "placements":turns-sum(f[color]['passes'] for f in ff),
                "fraction_placed_stones_captured":sum(f[color]['stones_lost'] for f in ff)/max(1,turns-sum(f[color]['passes'] for f in ff)),
                "mean_stones_lost":float(np.mean([f[color]["stones_lost"] for f in ff])),
                "pass_when_ahead":sum(f[color]["pass_when_ahead"] for f in ff),
                "good_terminal_offers":wilson(sum(f[color]['good_offers_accepted'] for f in ff),sum(f[color]['offers_good_for_self'] for f in ff)),
                "bad_terminal_offers":wilson(sum(f[color]['bad_offers_accepted'] for f in ff),sum(f[color]['offers_bad_for_self'] for f in ff)),
                "first_pass":distribution([f[color]["first_pass"] for f in ff if f[color]["first_pass"] is not None])}
    return summaries,features


def representatives(out, rows, features):
    selected={}
    def add(r,reason):selected.setdefault(r["game_id"],{"row":r,"reasons":[]})["reasons"].append(reason)
    for group in COMBOS:
        rr=[r for r in rows if group_name(r)==group]
        if not rr:continue
        ordered=sorted(rr,key=lambda r:(r["move_count"],r["game_index"]))
        for r in ordered[:2]:add(r,group+" shortest")
        for r in ordered[-2:]:add(r,group+" longest")
        add(ordered[len(ordered)//2],group+" median length")
        for length in (4,8,12):
            p=prefixes(rr,length)
            if p["top"]:
                pref=p["top"][0]["actions"]
                matching=[r for r in rr if r["move_count"]>=length and r["opening_actions"][:length]==pref]
                add(matching[0],f"{group} top prefix L={length}, count={p['top1_count']}")
        ep=terminal_prefixes(rr,8)
        if ep['top']:
            target=ep['top'][0]['actions']
            matching=[r for r in rr if (r['opening_actions'][:8]+[-1]*max(0,8-len(r['opening_actions'])))==target]
            add(matching[0],f"{group} top END-padded prefix L=8, count={ep['top1_count']}")
    for r in rows:
        if r["termination_reason"]=="move_limit":add(r,"all move_limit games")
        if relation(r)=="mixed" and r["black_utility"]!=1:add(r,"mixed goal failure")
    for r in sorted(rows,key=lambda r:-r["superko_rejections"])[:3]:add(r,"highest superko activity")
    return [{"game_id":gid,"path":(out/v['row']['game_file']).as_posix(),
             "reasons":v["reasons"],"identity_pair":group_name(v["row"]),
             "length":v["row"]["move_count"],"winner":v["row"]["winner"],
             "utilities":[v["row"]["black_utility"],v["row"]["white_utility"]],
             "behavior":features.get(gid)} for gid,v in sorted(selected.items())]


def write_csv(path, rows):
    if not rows:return
    with path.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)


def stratified_pair_pvalue(seed_counts):
    """Exact conditional test of which individual holds black, within seed.

    Each tuple is (A-black goal successes, A-black n, B-black successes,
    B-black n). Condition on each seed's total black-goal count. The null
    distribution is a convolution of hypergeometrics, avoiding an iid .5
    assumption when the same identity has a strong color advantage.
    """
    probabilities=np.array([1.]);observed=0
    for ka,na,kb,nb in seed_counts:
        probabilities=np.convolve(probabilities,hypergeom.pmf(np.arange(na+1),na+nb,ka+kb,na))
        observed+=ka
    return float(min(1.,probabilities[probabilities<=probabilities[observed]*(1+1e-10)].sum()))


def compare_seeds(runs, names):
    if len(names)!=2:return {"available_seeds":len(names)}
    left,right=[runs[n] for n in names]
    comparison={"names":names,"groups":{},"matrix":[]}
    for group in COMBOS:
        a,b=left['groups'][group],right['groups'][group]
        comparison['groups'][group]={
            "length_mean_seed0":a['length']['mean'],"length_mean_seed1":b['length']['mean'],
            "length_delta_seed1_minus_seed0":b['length']['mean']-a['length']['mean'],
            "black_goal_delta_seed1_minus_seed0":b['black_goal']['rate']-a['black_goal']['rate'],
            "black_board_win_delta_seed1_minus_seed0":b['black_board_win']['rate']-a['black_board_win']['rate']}
    maps=[{(r['agent'],r['opponent']):r for r in x['matrix']['cells']} for x in (left,right)]
    for key in sorted(maps[0]):
        a,b=maps[0][key],maps[1][key]
        comparison['matrix'].append({"agent":key[0],"opponent":key[1],
                                    "rate_seed0":a['rate'],"rate_seed1":b['rate'],
                                    "same_direction_vs_half":(a['rate']-.5)*(b['rate']-.5)>0,
                                    "both_marginal_ci_above_half":a['ci95'][0]>.5 and b['ci95'][0]>.5,
                                    "both_marginal_ci_below_half":a['ci95'][1]<.5 and b['ci95'][1]<.5})
    # Same-identity unordered pairs only: mixed rows share aligned rewards and
    # cannot be interpreted as a competitive dominance relation.
    competitive=[r for r in comparison['matrix'] if r['agent']<r['opponent']
                 and r['agent'].split('-')[0]==r['opponent'].split('-')[0]]
    comparison['competitive_pairs']={
        'n':len(competitive),'same_direction':sum(r['same_direction_vs_half'] for r in competitive),
        'both_marginal_intervals_exclude_half':sum(r['both_marginal_ci_above_half'] or r['both_marginal_ci_below_half'] for r in competitive),
        'warning':'Exploratory, uncorrected multiple comparisons; no stable specialization claim.'}
    tests=[]
    ordered_maps=[{(p['black'],p['white']):p for p in runs[name]['pairs']} for name in names]
    for r in competitive:
        key=(r['agent'],r['opponent']);a,b=maps[0][key],maps[1][key]
        k=a['successes']+b['successes'];n=a['n']+b['n']
        strata=[]
        for pairs in ordered_maps:
            ab=pairs[key];ba=pairs[(key[1],key[0])]
            strata.append((ab['black_goal']['successes'],ab['n'],ba['black_goal']['successes'],ba['n']))
        tests.append({'agent':key[0],'opponent':key[1],**wilson(k,n),
                      'p_two_sided_equal_goal':stratified_pair_pvalue(strata),
                      'same_direction_both_seeds':r['same_direction_vs_half']})
    order=sorted(range(len(tests)),key=lambda i:tests[i]['p_two_sided_equal_goal'])
    last=0.
    for rank,i in enumerate(order):
        last=max(last,min(1.,tests[i]['p_two_sided_equal_goal']*(len(tests)-rank)))
        tests[i]['p_holm_12_pairs']=last
    comparison['competitive_pair_tests']=tests
    comparison['competitive_test_scope']='12 same-identity unordered pairs; exact conditional hypergeometric convolution stratified by batch seed, comparing black goal rates under exchanged individual assignments; Holm correction.'
    def individual_rates(data,identity):
        rr=data['matrix']['agents_by_color_and_opponent_identity']
        agents=sorted({r['agent'] for r in rr if r['agent'].startswith(identity+'-')})
        result=[]
        for agent in agents:
            own=[r for r in rr if r['agent']==agent and r['opponent_identity']==identity]
            result.append({'agent':agent,**wilson(sum(r['successes'] for r in own),sum(r['n'] for r in own))})
        return sorted(result,key=lambda r:(-r['rate'],r['agent']))
    comparison['individual_same_identity_rankings']={
        identity:{name:individual_rates(runs[name],identity) for name in names} for identity in ('WIN','LOSE')}
    comparison['length_gap_same_sign']=left['length_gap']['mixed_minus_same']*right['length_gap']['mixed_minus_same']>0
    return comparison


def analyze(paths, destination):
    destination.mkdir(parents=True,exist_ok=True)
    all_rows=[]; runs={}; sources={}; mcts=[]
    for path in paths:
        out=Path(path); name=out.name
        manifest=json.loads((out/'manifest.json').read_text(encoding='utf-8'))
        if manifest['status']!='completed':raise ValueError(f'{name} incomplete')
        rows=[json.loads(x) for x in (out/'games.jsonl').read_text(encoding='utf-8').splitlines()]
        for r in rows:r['run']=name
        rows.sort(key=lambda r:r['game_index'])
        sources[name]={"manifest":manifest,"metadata_sha256":hashlib.sha256((out/'games.jsonl').read_bytes()).hexdigest()}
        sources[name]['manifest'].pop('completed_indexes',None)
        result={"groups":{k:aggregate([r for r in rows if group_name(r)==k]) for k in COMBOS},
                "relations":{k:aggregate([r for r in rows if relation(r)==k]) for k in ('mixed','same')},
                "length_gap":length_gap(rows),"pairs":pair_rows(rows),"matrix":agent_matrix(rows)}
        if manifest['kind']=='B':
            behavior_summary,features=behavior(out,rows)
            result['behavior']=behavior_summary
            result['representatives']=representatives(out,rows,features)
            mcts.extend(rows)
        runs[name]=result;all_rows.extend(rows)
    if mcts:
        runs['B_pooled']={"groups":{k:aggregate([r for r in mcts if group_name(r)==k]) for k in COMBOS},
                          "relations":{k:aggregate([r for r in mcts if relation(r)==k]) for k in ('mixed','same')},
                          "length_gap":length_gap(mcts),"pairs":pair_rows(mcts),"matrix":agent_matrix(mcts)}
    bnames=[n for n in sources if sources[n]['manifest']['kind']=='B']
    result={"analysis_version":"1.1", "numpy_version":np.__version__, "scipy_version":scipy.__version__, "sources":sources,"runs":runs,
            "analysis_python_version":platform.python_version(),
            "analysis_script_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "cross_seed":compare_seeds(runs,bnames),
            "cautions":["Fixed agents and two batch seeds; no cross-game learning.",
                        "Wilson intervals are marginal game-level intervals, not multiplicity corrected.",
                        "Pair-stratified bootstrap conditions on observed seed/pair cells.",
                        "Prefix denominators exclude shorter games; exact orientation, no symmetry reduction.",
                        "Captures and passes are descriptive; deliberate sacrifice needs counterfactual analysis."]}
    (destination/'analysis.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    pair_table=[];prefix_table=[];matrix_table=[]
    for run,data in runs.items():
        for pair in data['pairs']:
            pair_table.append({"run":run,"black":pair['black'],"white":pair['white'],"identity_pair":pair['identity_pair'],"n":pair['n'],
                               "black_win_rate":pair['black_board_win']['rate'],
                               "black_goal_rate":pair['black_goal']['rate'],"white_goal_rate":pair['white_goal']['rate'],
                               "black_goal_low":pair['black_goal']['ci95'][0],"black_goal_high":pair['black_goal']['ci95'][1],
                               **{"length_"+k:v for k,v in pair['length'].items() if k!='n'}})
        for group,stats in {**data['groups'],**data['relations']}.items():
            for p in stats['prefixes']:
                prefix_table.append({"run":run,"group":group,**{k:v for k,v in p.items() if k!='top'}})
        for row in data['matrix']['cells']:
            matrix_table.append({"run":run,**{k:v for k,v in row.items() if k!='ci95'},"low":row['ci95'][0],"high":row['ci95'][1]})
    write_csv(destination/'agent_pairs.csv',pair_table)
    write_csv(destination/'prefixes.csv',prefix_table)
    write_csv(destination/'matrix_cells.csv',matrix_table)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('runs',nargs='+');p.add_argument('--out',default='reports/cross_run')
    a=p.parse_args();r=analyze(a.runs,Path(a.out))
    print(json.dumps({k:v['length_gap'] for k,v in r['runs'].items()},ensure_ascii=False,indent=2))
