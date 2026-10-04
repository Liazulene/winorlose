"""Independent numeric audit of complete paired fixed480 inference.
Uses direct binomial polynomial inversion, not scipy beta quantiles and no
production statistics imports. Mathematical applicability is separate review.
"""
import functools,math
from collections import Counter
DIRECTIONS=('WIN/WIN','LOSE/LOSE','WIN/LOSE','LOSE/WIN')
GOALS={d:('black_goals' if d in ('WIN/WIN','LOSE/LOSE') else 'joint_goals') for d in DIRECTIONS}
FAMILY_CONFIDENCE=1-.05/8
METHOD='paired_discordance_two_sided_CP_rectangle_Bonferroni'

def close(a,b,path='root'):
    problems=[]
    if isinstance(a,dict):
        if not isinstance(b,dict):return [path+': expected dictionary']
        if set(a)!=set(b):problems.append(path+': field set mismatch')
        for k in a.keys()&b.keys():problems+=close(a[k],b[k],path+'.'+k)
    elif isinstance(a,list):
        if not isinstance(b,list):return [path+': expected list']
        if len(a)!=len(b):problems.append(path+': length mismatch')
        for i,(x,y) in enumerate(zip(a,b)):problems+=close(x,y,f'{path}[{i}]')
    elif type(a) in (int,float):
        if type(b) not in (int,float) or not math.isfinite(b) or not math.isclose(a,b,rel_tol=1e-11,abs_tol=1e-9):problems.append(f'{path}: {a!r} != {b!r}')
    elif type(a)!=type(b) or a!=b:problems.append(f'{path}: value/type mismatch')
    return problems

def cdf(n,k,p):
    return math.fsum(math.comb(n,j)*p**j*(1-p)**(n-j) for j in range(k+1))

def solve_cdf(n,k,target):
    lo,hi=0.,1.
    for _ in range(90):
        mid=(lo+hi)/2
        if cdf(n,k,mid)>target:lo=mid
        else:hi=mid
    return (lo+hi)/2

@functools.lru_cache(None)
def cp(k,n,confidence=.95):
    tail=(1-confidence)/2
    return [0. if k==0 else solve_cdf(n,k-1,1-tail),1. if k==n else solve_cdf(n,k,tail)]

def dist(values):
    v=sorted(values);out={'n':len(v),'mean':math.fsum(v)/len(v)}
    for label,q in [('min',0),('q1',.25),('median',.5),('q3',.75),('p90',.9),('p95',.95),('max',1)]:
        pos=(len(v)-1)*q;i=int(pos);out[label]=v[i]+(v[min(i+1,len(v)-1)]-v[i])*(pos-i)
    return out

def endpoints(r):
    answer={'black_board_wins':r['winner']=='black','white_board_wins':r['winner']=='white','black_goals':r['black_utility']==1,'white_goals':r['white_utility']==1,'length_ge60':r['move_count']>=60,'move_limit':r['termination_reason']=='move_limit'}
    if r['black_identity']!=r['white_identity']:answer['joint_goals']=r['black_utility']==r['white_utility']==1
    return answer

def pair_rate(a,b,confidence=.95):
    n=len(a);count=Counter(zip(map(int,a),map(int,b)));plus,minus=count[0,1],count[1,0];c=1-(1-confidence)/2
    lp,up=cp(plus,n,c);lm,um=cp(minus,n,c);estimate=(plus-minus)/n;ci=[lp-um,up-lm]
    radius=(2*math.log(2/(1-confidence))/n)**.5;audit=[max(-1.,estimate-radius),min(1.,estimate+radius)]
    answer={'n':n,'baseline_successes':sum(a),'comparison_successes':sum(b),'n00':count[0,0],'n01':plus,'n10':minus,'n11':count[1,1],'discordant_pairs':plus+minus,'estimate':estimate,'confidence_level':confidence,'ci':ci,'component_confidence_level':c,'positive_probability_ci':[lp,up],'negative_probability_ci':[lm,um],'method':METHOD,'hoeffding_ci':audit,'hoeffding_radius':radius}
    if confidence==.95:answer.update(ci95=ci,ci95_hoeffding=audit)
    return answer

def mean_length(values,confidence=.95):
    estimate=math.fsum(values)/len(values);radius=188*math.sqrt(math.log(2/(1-confidence))/(2*len(values)))
    return {'n':len(values),'estimate':estimate,'confidence_level':confidence,'ci':[max(-90,estimate-radius),min(98,estimate+radius)],'support':[-90,98],'unclipped_radius':radius,'method':'Hoeffding_independent_bounded_mean','coverage_scope':'pointwise_for_this_fixed_estimand'}

def add_family(target,adjusted,label):
    target.update(simultaneous_family_ci95=adjusted['ci'],simultaneous_family_interval_confidence_level=FAMILY_CONFIDENCE,simultaneous_family_size=8,simultaneous_family_endpoint=label)
    if 'component_confidence_level' in adjusted:
        target.update(simultaneous_family_component_confidence_level=adjusted['component_confidence_level'],simultaneous_family_positive_probability_ci=adjusted['positive_probability_ci'],simultaneous_family_negative_probability_ci=adjusted['negative_probability_ci'],simultaneous_family_hoeffding_audit_ci=adjusted['hoeffding_ci'])
    else:target['simultaneous_family_unclipped_radius']=adjusted['unclipped_radius']

def group(rows,direction,family=False):
    key=lambda r:(r['batch_seed'],r['black_seed'],r['white_seed'],r['replicate'])
    arms={rule:sorted([r for r in rows if r['pass_min_ply']==rule],key=key) for rule in (0,8)}
    assert [key(r) for r in arms[0]]==[key(r) for r in arms[8]]
    rule_stats={};vectors={}
    for rule,arm in arms.items():
        vectors[rule]={name:[endpoints(r)[name] for r in arm] for name in endpoints(arm[0])}
        rates={name:{'successes':sum(v),'n':len(v),'estimate':sum(v)/len(v),'confidence_level':.95,'ci':cp(sum(v),len(v)), 'method':'two_sided_Clopper_Pearson_average_probability','coverage_scope':'pointwise_95_not_family_adjusted'} for name,v in vectors[rule].items()}
        rule_stats['G0' if rule==0 else 'G1-pass8']={'n':len(arm),'rates':rates,'length':dist([r['move_count'] for r in arm]),'extra_length':dist([r['move_count']-rule-2 for r in arm])}
    rates={}
    for name in vectors[0]:
        a,b=vectors[0][name],vectors[8][name];rates[name]=pair_rate(a,b);rates[name]['coverage_scope']='pointwise_95_not_family_adjusted'
        if family and name==GOALS[direction]:add_family(rates[name],pair_rate(a,b,FAMILY_CONFIDENCE),direction+':'+name)
    lengths=[r8['move_count']-r0['move_count'] for r0,r8 in zip(arms[0],arms[8])];raw=mean_length(lengths);raw['distribution']=dist(lengths)
    if family:add_family(raw,mean_length(lengths,FAMILY_CONFIDENCE),direction+':raw_length')
    extra=dict(raw);extra['estimate']-=8
    for k in ('ci','support','simultaneous_family_ci95'):
        if k in extra:extra[k]=[x-8 for x in extra[k]]
    extra['distribution']={k:v if k=='n' else v-8 for k,v in raw['distribution'].items()}
    extra.update(derived_from='raw_length_delta_minus_8',is_additional_family_member=False,interpretation='Mechanical translation only; not a causal adjustment or coordination estimate.')
    return {'identity_direction':direction,'primary_goal_endpoint':GOALS[direction],'n_pairs':len(arms[0]),'rules':rule_stats,'contrast':{'comparison':'G1-pass8','baseline':'G0','direction':'G1-pass8_minus_G0','rates':rates,'raw_length':raw,'extra_length':extra}}

def verify(rows,saved):
    problems=[];expected={'pooled':{},'per_seed':{}}
    for direction in DIRECTIONS:
        subset=[r for r in rows if r['black_identity']+'/'+r['white_identity']==direction]
        expected['pooled'][direction]=group(subset,direction,True)
        for seed in (11,12,13):expected['per_seed'].setdefault(str(seed),{})[direction]=group([r for r in subset if r['batch_seed']==seed],direction)
    for k,v in expected.items():problems+=close(v,saved.get(k),'inference.'+k)
    wanted={'analysis_version':'g1-pass8-fixed-paired-cp-hoeffding-v1','estimation_only':True,'complete_registered_sample':True,'n_records':480,'n_paired_blocks':240}
    for k,v in wanted.items():problems+=close(v,saved.get(k),'inference.'+k)
    intervals=saved.get('intervals',{})
    for k,v in {'raw_length_support':[-90,98],'simultaneous_family_confidence_level':.95,'simultaneous_family_size':8,'per_family_interval_confidence_level':FAMILY_CONFIDENCE,'family':[{'direction':d,'endpoint':endpoint} for d in DIRECTIONS for endpoint in (GOALS[d],'raw_length')]}.items():problems+=close(v,intervals.get(k),'inference.intervals.'+k)
    return {'passed':not problems,'problems':problems,'checked_groups':16,'joint_family_size':8,'method':'Independent direct binomial-polynomial inversion with90bisections; no scipy or production stats imports','tolerance':'abs1e-9 or relative1e-11; ignores insignificant outward one-ULP differences','coverage':['All raw paired2x2counts/rates/denominators and armwise pointwise CP','Pointwise paired CP-rectangle and separate Hoeffding audits','Eight pooled family simultaneous bounds at alpha.05/8','Hoeffding raw-length support[-90,98] and derived minus8 point/bound/quantile translations','Pooled60pairs/direction and seed20pairs/direction; strict result structure'],'limitations':['Numerical arithmetic verification does not establish PRNG independence or mathematical theorem applicability.']},expected
