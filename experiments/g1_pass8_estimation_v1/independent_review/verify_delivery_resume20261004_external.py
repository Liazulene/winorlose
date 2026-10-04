"""Final read-only audit of source lock, unchanged raw data, and report links."""
import hashlib
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path('/workspace/scratch/50e0c7c6aca1/winorlose')
sys.path.insert(0,str(ROOT/'src'))
from winai_loseai.provenance import current_provenance, fingerprint, source_inventory


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    problems=[]
    lock=json.loads((ROOT/'reports/planning_source_lock.json').read_text(encoding='utf-8'))
    current=current_provenance()
    if current['source_fingerprint']!=lock['source_fingerprint']:
        problems.append('current source fingerprint changed')
    archive=ROOT/'reports/planning_source_0.2.0.zip'
    if sha(archive)!=lock['archive_sha256']:problems.append('source archive changed')
    design_unchanged=True
    with zipfile.ZipFile(archive) as z:
        for name,digest in source_inventory().items():
            text=z.read(name).decode('utf-8').replace('\r\n','\n').replace('\r','\n')
            if hashlib.sha256(text.encode('utf-8')).hexdigest()!=digest:
                problems.append('archive source mismatch: '+name)
        for name in ('5x5_mvp_spec.md','winai_loseai_go_experiment_notes_v2.md'):
            if z.read(name)!=(ROOT/name).read_bytes():
                design_unchanged=False
                problems.append('original design document modified: '+name)
    checked=[]
    for name in ('batch_A_seed0','batch_B_shallow_seed0','batch_B_shallow_seed1'):
        out=ROOT/'outputs'/name
        evidence=json.loads((ROOT/'reports/validation'/f'{name}.json').read_text(encoding='utf-8'))
        hashes={p.name:sha(p) for p in sorted((out/'games').glob('*.json'))}
        same=(fingerprint(hashes)==evidence['raw_game_hashes_sha256']
              and sha(out/'games.jsonl')==evidence['metadata_sha256']
              and sha(out/'manifest.json')==evidence['manifest_sha256'])
        if not same:problems.append('raw data changed since full validation: '+name)
        if evidence['problems'] or evidence['replay_ok']!=evidence['planned']:
            problems.append('full validation failed: '+name)
        checked.append({'run':name,'raw_files':len(hashes),'unchanged_since_validation':same})
    data=json.loads((ROOT/'reports/cross_run/analysis.json').read_text(encoding='utf-8'))
    tests=json.loads((ROOT/'reports/validation/final_tests.json').read_text(encoding='utf-8'))
    if tests['exit_code']!=0 or tests['failed']!=0:problems.append('test suite failed')
    for name,digest in tests['file_hashes'].items():
        if sha(ROOT/name)!=digest:problems.append('tested file changed: '+name)
    if sha(ROOT/'scripts/planning_analysis.py')!=data['analysis_script_sha256']:
        problems.append('analysis script changed since analysis')
    for name,source in data['sources'].items():
        if sha(ROOT/'outputs'/name/'games.jsonl')!=source['metadata_sha256']:
            problems.append('analysis input changed: '+name)
    report=ROOT/'reports/5x5_planning_phase_report.md'
    for target in re.findall(r'\]\(([^)]+)\)',report.read_text(encoding='utf-8')):
        if target.startswith(('http:','https:','#')):continue
        # This evidence file is created below, after the checks finish.
        if target=='validation/final_delivery.json':continue
        if not (report.parent/target.split('#')[0]).exists():
            problems.append('broken report link: '+target)
    result={'checked_at':datetime.now(timezone.utc).isoformat(),
            'source':current,'runs':checked,'original_design_documents_unchanged':design_unchanged,
            'tests_passed':tests['passed'],'report_sha256':sha(report),'problems':problems}
    (Path('/workspace/scratch/50e0c7c6aca1/winorlose_g1_pass8_estimation_v1/experiments/g1_pass8_estimation_v1/independent_review/resume20261004_delivery_result.json')).write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
    return bool(problems)


if __name__=='__main__':raise SystemExit(main())
