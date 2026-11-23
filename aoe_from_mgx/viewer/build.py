"""Build an offline AoE overview from roster-enabled JSONL or ZIP; stdlib only."""
import argparse,contextlib,json,zipfile
from pathlib import Path
@contextlib.contextmanager
def source(p):
 if p.suffix.lower()=='.zip':
  with zipfile.ZipFile(p) as z:
   names=[n for n in z.namelist() if n.lower().endswith('.jsonl')]
   if len(names)!=1:raise ValueError('Expected one JSONL')
   with z.open(names[0]) as f:yield f
 else:
  with p.open('rb') as f:yield f

def main():
 ap=argparse.ArgumentParser();ap.add_argument('input',type=Path);ap.add_argument('--out',type=Path,default=Path('overview.html'));ap.add_argument('--sample-seconds',type=int,default=1);a=ap.parse_args()
 if a.sample_seconds<1:ap.error('--sample-seconds must be positive')
 frames=[];pending={};actions={};errors=[];stop=[];run=0;last=None
 with source(a.input) as f:
  for line in f:
   r=json.loads(line);k=r.get('kind')
   if k=='gather_action_sample':
    leaf=r.get('task_tree',{}).get('root')
    while leaf and leaf.get('children') and leaf['children'][0].get('task'):leaf=leaf['children'][0]['task']
    if leaf:leaf={k:leaf.get(k) for k in ('type_code','state_code','target_id_1')}
    actions[(r['slot'],r['unit_id'])]=[r['time_ms'],r['state_before'],leaf]
   elif k=='roster':
    if last is not None and r['time_ms']<last:run+=1;actions.clear()
    last=r['time_ms'];frame={'t':last,'run':run,'players':r['players']}
    for p in frame['players']:
     keep=('id','type_id','class_id','struct_type','state','hp','x','y','resource_type_candidate','resource_amount_candidate','nearest_own_tc_candidate','container_id_candidate')
     p['objects']=[{k:o.get(k) for k in keep} for o in p['objects']]
     for o in p['objects']:
      aa=actions.get((p['slot'],o['id']))
      if aa and aa[0]<=last:o['observed_action']=aa
    # Keep the first snapshot and the last snapshot in each time bucket.
    bucket=last//(a.sample_seconds*1000)
    if a.sample_seconds>1 and len(frames)>1 and frames[-1]['run']==run and frames[-2]['run']==run and frames[-1]['t']//(a.sample_seconds*1000)==bucket:
     frames[-1]=frame
    else:frames.append(frame)
    pending[r['step_id']]=frame
   elif k=='call':
    frame=pending.pop(r['id'],None)
    if frame:
     lookup={p['slot']:p for p in r['after']['players']}
     for p in frame['players']:
      q=lookup.get(p['slot'],{});p['resources']={n:q.get(n) for n in ['food','wood','gold','stone']}
   elif k in ('error','agent_error','cleanup_error'):errors.append(r)
   elif k=='stop':stop.append(r)
 if not frames:raise ValueError('No roster snapshots: use a roster-enabled log')
 names=json.loads(Path(__file__).with_name('names.json').read_text(encoding='utf-8'))
 data=json.dumps({'frames':frames,'sample_seconds':a.sample_seconds,'names':names,'errors':len(errors),'stop':stop,'missing_resource_frames':len(pending)},ensure_ascii=False,allow_nan=False,separators=(',',':')).replace('<','\\u003c')
 with a.out.open('x',encoding='utf-8') as f:f.write(Path(__file__).with_name('viewer.html').read_text(encoding='utf-8').replace('__DATA__',data))
 print('Created',a.out,'frames',len(frames),'unmatched',len(pending),'errors',len(errors))
if __name__=='__main__':main()
