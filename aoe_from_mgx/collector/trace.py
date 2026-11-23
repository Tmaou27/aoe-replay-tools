"""Experimental Frida boundary trace. Run only against an offline AoC replay."""
import argparse, hashlib, json, os, sys, threading, time, traceback
from pathlib import Path
EXPECTED='4ffd2e0aa42871b0d1812b994e8b98af0cae489eb89e947c592d034ef317e7fc'

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--pid',type=int)
    p.add_argument('--seconds',type=int,default=120,choices=range(5,86401),metavar='5..86400')
    p.add_argument('--max-calls',type=int,default=1000000,choices=range(1,10000001),metavar='1..10000000')
    p.add_argument('--out',default='aoe_tasks.jsonl')
    a=p.parse_args()
    if os.name!='nt':p.error('Requires Windows and the original running game.')
    import frida
    device=frida.get_local_device()
    if a.pid is None:
        found=[x for x in device.enumerate_processes() if x.name.lower()=='age2_x1.exe']
        if len(found)!=1:raise RuntimeError('Expected one age2_x1.exe; use --pid.')
        a.pid=found[0].pid
    session=None;script=None;started=False;lock=threading.Lock();lost=threading.Event();write_error=[]; received=[0]
    # Refuse overwrites before attaching to the process.
    with Path(a.out).open('x',encoding='utf-8') as out:
        def emit(item):
            with lock:
                out.write(json.dumps(item,ensure_ascii=False,allow_nan=False)+'\n');out.flush()
        def message(msg,data):
            try:
                if msg['type']=='send':
                    payload=msg['payload']
                    if payload.get('type')=='batch':
                        for r in payload['records']:
                            emit(r); received[0]+=1
                    else:emit({'kind':'agent_message','payload':payload})
                else:
                    emit({'kind':'agent_error','message':msg});lost.set()
            except Exception as e:write_error.append(str(e));lost.set()
        def detached(*details):
            lost.set()
            try:emit({'kind':'detached','details':[str(x) for x in details]})
            except Exception:pass
        try:
            session=device.attach(a.pid);session.on('detached',detached)
            script=session.create_script(Path(__file__).with_name('agent.js').read_text(encoding='utf-8'))
            script.on('message',message);script.load()
            info=script.exports_sync.inspect()
            digest=hashlib.sha256(Path(info['path']).read_bytes()).hexdigest()
            if digest!=EXPECTED:raise RuntimeError('Loaded executable fingerprint mismatch. No hooks started.')
            emit({'kind':'metadata','schema':1,'pid':a.pid,'exe_sha256':digest,'frida_version':frida.__version__,
                  'module':info,'precision':'boundary_candidates_only_not_complete_resource_events'})
            print('Запись должна быть на паузе. Frida уже подключена; перехваты ещё не установлены.')
            input('Нажмите Enter для начала трассировки: ')
            result=script.exports_sync.start(a.max_calls);started=True
            emit({'kind':'start','result':result,'host_monotonic_ns':time.monotonic_ns()})
            print(f'Снимите паузу записи. Лимит: {a.seconds} реальных секунд. После конца записи вернитесь сюда и нажмите Ctrl+C. Не запускайте другую запись в этом сеансе.')
            until=time.monotonic()+a.seconds
            while time.monotonic()<until and not lost.wait(0.5):
                status=script.exports_sync.status()
                if not status['active']:
                    print('Сбор остановлен агентом:',status.get('stop_reason') or 'ошибка; см. лог')
                    break
        except KeyboardInterrupt:print('Остановка по Ctrl+C.')
        finally:
            if script is not None:
                if started and not lost.is_set():
                    try:
                        stopped=script.exports_sync.stop()
                        deadline=time.monotonic()+3
                        while received[0]<stopped['records_sent'] and time.monotonic()<deadline:
                            time.sleep(0.01)
                        emit({'kind':'stop','result':stopped,'records_received':received[0],
                              'all_sent_records_received':received[0]==stopped['records_sent']})
                    except Exception as e:emit({'kind':'cleanup_error','error':str(e)})
                try:script.unload()
                except Exception:pass
            if session is not None:
                try:session.detach()
                except Exception:pass
        if write_error:raise RuntimeError('Output write error: '+repr(write_error))
    print('Сохранён',a.out)

if __name__=='__main__':
    try:main()
    except Exception:traceback.print_exc();sys.exit(1)
