"""Read-only fixed48 M7 checkpoint validator; optional create-only evidence."""
import argparse
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from winai_loseai.experiments import komi_pass_estimation as g


def checkpoint(out):
    out=g.assert_output_allowed(out)
    p=g.protocol()
    manifest=json.loads((out/'manifest.json').read_text(encoding='utf-8'))
    n=manifest['completed_game_count'];size=p['resource_policy']['checkpoint_games']
    if type(n) is not int or n<1 or n>p['planned_games'] or n%size:
        raise ValueError('Expected a registered 48-game checkpoint')
    result=g.validate(out,require_complete=n==p['planned_games'])
    if result['problems'] or result['game_count']!=n or result['replay_and_search_ok']!=n:
        raise ValueError(result)
    expected='completed' if n==p['planned_games'] else 'interrupted'
    if result['manifest_status']!=expected:raise ValueError('Unexpected checkpoint status')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',default=str(ROOT/'outputs/komi_pass_estimation_v1'))
    parser.add_argument('--evidence')
    args=parser.parse_args()
    gate=g.verify_preexecution();result=checkpoint(args.out)
    report={'pre_execution_gate':gate,**result}
    if args.evidence:
        dest=g.assert_output_allowed(args.evidence)
        dest.parent.mkdir(parents=True,exist_ok=True)
        with dest.open('x',encoding='utf-8') as f:
            json.dump(report,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    return 0

if __name__=='__main__':raise SystemExit(main())
