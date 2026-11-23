"""MGX -> manual game playback -> checked log -> offline overview (Windows)."""
import argparse,hashlib,importlib.util,json,os,sys,time,uuid,zipfile,webbrowser
from pathlib import Path
BASE=Path(__file__).resolve().parent

def digest(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()

def invoke(path,argv):
 spec=importlib.util.spec_from_file_location('aoe_stage_'+uuid.uuid4().hex,path)
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
 old=sys.argv
 try:sys.argv=[str(path),*map(str,argv)];module.main()
 finally:sys.argv=old

def inspect_log(path):
 counts={};issues=[];stop=None;last=None;first=None;resets=0
 with path.open(encoding='utf-8') as f:
  for number,line in enumerate(f,1):
   try:r=json.loads(line)
   except ValueError:issues.append('Invalid JSON line '+str(number));break
   k=r.get('kind');counts[k]=counts.get(k,0)+1
   if k in ('error','agent_error','cleanup_error'):issues.append(str(r)[:500])
   if k=='stop':stop=r
   if k=='roster':
    t=r['time_ms']
    if first is None:first=t
    if last is not None and t<last:resets+=1
    last=t
 if not stop:issues.append('Missing stop record')
 else:
  r=stop['result']
  if not stop.get('all_sent_records_received'):issues.append('Record delivery not confirmed')
  for k in ['capped','resource_cap','errors','pending_calls_at_stop','resource_pending','context_pending','action_pending']:
   if r.get(k):issues.append(k+'='+str(r[k]))
  if r.get('stop_reason'):issues.append('stop_reason='+str(r['stop_reason']))
 if not counts.get('roster'):issues.append('No object snapshots')
 if resets:issues.append('Game clock reset: '+str(resets))
 return dict(record_counts=counts,issues=issues,first_snapshot_ms=first,last_snapshot_ms=last,clock_resets=resets,stop=stop)

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('mgx',type=Path);p.add_argument('--pid',type=int)
 p.add_argument('--seconds',type=int,default=14400)
 p.add_argument('--output-dir',type=Path)
 p.add_argument('--log',type=Path,help='Build from an existing JSONL instead of recording')
 p.add_argument('--sample-seconds',type=int,default=1,help='HTML sampling interval; raw log remains unchanged')
 p.add_argument('--no-open',action='store_true')
 a=p.parse_args()
 if a.sample_seconds<1:p.error('--sample-seconds must be positive')
 if not a.mgx.is_file():p.error('MGX file does not exist')
 if not 5<=a.seconds<=86400:p.error('--seconds must be 5..86400')
 if a.log is None and os.name!='nt':p.error('Recording requires Windows')
 if a.log is not None and not a.log.is_file():p.error('--log does not exist')
 folder=a.output_dir or Path.cwd()/('aoe_result_'+time.strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:6])
 folder=folder.resolve();folder.mkdir(parents=True,exist_ok=False)
 manifest={'overview_sample_seconds':a.sample_seconds,'mgx_path':str(a.mgx.resolve()),'mgx_sha256':digest(a.mgx),'opened_replay_identity_verified':False,'full_replay_completion_verified':False}
 manifest_path=folder/'manifest.json'
 def save():manifest_path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
 save();log=a.log.resolve() if a.log else folder/'capture.jsonl'
 try:
  if not a.log:
   print('Откройте в игре именно:',a.mgx.resolve())
   print('Поставьте запись на паузу как можно ближе к началу. Не снимайте паузу до приглашения сборщика.')
   print('После окончания записи: не закрывайте игру, нажмите Ctrl+C ОДИН раз в этой консоли и дождитесь HTML.')
   print('Результаты:',folder)
   args=['--seconds',a.seconds,'--max-calls',1000000,'--out',log]
   if a.pid is not None:args+=['--pid',a.pid]
   invoke(BASE/'collector'/'trace.py',args)
  report=inspect_log(log);manifest['validation']=report;manifest['source_log']=str(log);save()
  with zipfile.ZipFile(folder/'capture.zip','w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:z.write(log,'capture.jsonl')
  if report['issues']:
   print('Обнаружены ограничения:',*report['issues'],sep='\n')
  if not report['record_counts'].get('roster'):raise RuntimeError('Нет снимков для обзора. Лог и диагностика сохранены.')
  print('Построение обзора. Для длинного лога потребуется свободная память.')
  overview=folder/'overview.html';invoke(BASE/'viewer'/'build.py',[log,'--out',overview,'--sample-seconds',a.sample_seconds])
  manifest['overview']=str(overview);manifest['status']='partial_or_warning' if report['issues'] else 'captured_interval_checked';save()
  print('Готово:',overview)
  print('Проверен записанный интервал; полнота партии и совпадение MGX автоматически не подтверждаются.')
  if not a.no_open:webbrowser.open(overview.as_uri())
 except BaseException as e:
  manifest['status']='failed_or_interrupted';manifest['failure']=str(e);save()
  print('Сбор/обработка не завершены. Сохранённые файлы:',folder)
  raise
if __name__=='__main__':main()
