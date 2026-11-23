"""Streaming, evidence-based review of roster-enabled AoE JSONL/ZIP logs."""
import argparse
from collections import Counter, deque
from contextlib import contextmanager
import html
import json
import math
from pathlib import Path
import zipfile

RES = ('food', 'wood', 'gold', 'stone')
LABELS = {'food':'еда','wood':'дерево','gold':'золото','stone':'камень',
          'workers':'жители','land':'сухопутные боевые','ships':'боевые корабли'}

@contextmanager
def source(path):
    if path.suffix.lower() == '.zip':
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if n.lower().endswith('.jsonl')]
            if len(names) != 1:
                raise ValueError('ZIP должен содержать ровно один JSONL')
            with z.open(names[0]) as f:
                yield f
    else:
        with path.open('rb') as f:
            yield f

def finite(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)

def summarize(player):
    counts = Counter()
    for obj in player.get('objects', []):
        if obj.get('state') != 2:
            continue
        cls = obj.get('class_id')
        if cls == 4: counts['workers'] += 1
        elif cls == 22: counts['ships'] += 1
        elif cls in (0, 6, 12, 47, 13, 35, 51, 54): counts['land'] += 1
        elif cls not in (18,43,59,21,2,19,20,9,10,58) and obj.get('struct_type') != 80:
            counts['unknown'] += 1
    return dict(slot=player['slot'], score=player.get('score'),
                **{k:counts[k] for k in ('workers','land','ships','unknown')}, resources=None)

def read_frames(path, diag):
    """Retain only one pending aggregate, never historical unit objects."""
    pending = None
    with source(path) as f:
        for line_no, line in enumerate(f, 1):
            try:
                r = json.loads(line)
            except (ValueError, UnicodeError):
                raise ValueError(f'Повреждён JSON в строке {line_no}; отчёт не создан') from None
            k = r.get('kind')
            if k == 'roster':
                if pending is not None:
                    diag['unmatched'] += 1
                    yield pending
                pending = {'t':r['time_ms'], 'step':r['step_id'],
                           'players':{p['slot']:summarize(p) for p in r['players']}}
            elif k == 'call' and pending is not None and r.get('id') == pending['step']:
                for p in r.get('after', {}).get('players', []):
                    if p['slot'] in pending['players']:
                        pending['players'][p['slot']]['resources'] = {
                            key:p.get(key) if finite(p.get(key)) else None for key in RES}
                yield pending
                pending = None
            elif k in ('error','agent_error','cleanup_error'):
                diag['errors'] += 1
            elif k == 'stop':
                diag['stop'] = r
    if pending is not None:
        diag['unmatched'] += 1
        yield pending

def clock(t):
    seconds = int(t // 1000)
    return f'{seconds//3600:02}:{seconds//60%60:02}:{seconds%60:02}'

def analyze(path, window=60, player=None, opponents=(), max_gap=5):
    diag = dict(errors=0, unmatched=0, stop=None, frames=0, segments=0, gaps=0, resets=0)
    history = deque()
    last = None
    events = []
    summaries = {}
    cooldown = {}
    segment = 0
    def add(kind, slot, start, end, fact, check, exercise, comparison=None):
        key = (segment,slot,kind,comparison)
        if end['t'] - cooldown.get(key, -10**15) < window*1000:
            return
        cooldown[key] = end['t']
        events.append(dict(kind=kind, player=slot, segment=segment, start=start['t'],
                           end=end['t'], fact=fact, check=check, exercise=exercise,
                           comparison=comparison, before=list(start['players'].values()),
                           after=list(end['players'].values())))
    for frame in read_frames(path, diag):
        diag['frames'] += 1
        if last is None or frame['t'] <= last or frame['t']-last > max_gap*1000:
            if last is not None:
                diag['resets' if frame['t'] <= last else 'gaps'] += 1
            segment += 1
            history.clear()
        last = frame['t']
        for slot, p in frame['players'].items():
            key = (segment,slot)
            entry = summaries.setdefault(key,dict(segment=segment,player=slot,start=last,end=last,
                                                   first=p,last=p,unknown_max=0))
            entry.update(end=last,last=p,unknown_max=max(entry['unknown_max'],p['unknown']))
        history.append(frame)
        target = frame['t'] - window*1000
        while len(history)>1 and history[1]['t'] <= target:
            history.popleft()
        before = history[0]
        if before['t'] > target:
            continue
        for slot, p in frame['players'].items():
            if player is not None and slot != player:
                continue
            a = before['players'].get(slot)
            # Missing player observations inside the window invalidate its comparisons.
            if a is None or any(slot not in fr['players'] for fr in history):
                continue
            for metric, threshold in [('workers',3),('land',5),('ships',5)]:
                delta = p[metric]-a[metric]
                if delta <= -threshold:
                    add('decrease_'+metric,slot,before,frame,
                        f'{LABELS[metric]}: {a[metric]} → {p[metric]} ({delta:+d}). Это чистое изменение состава, не число погибших.',
                        'Проверь столкновения, обращения, гарнизоны и полноту списка. По одним снимкам причина не установлена.',
                        'Если повтор подтвердит невыгодный бой — отметь момент, когда ещё можно было отступить или дождаться подкрепления.' if metric!='workers' else
                        'Если подтвердится налёт — проверь, когда его можно было заметить и куда увести жителей.')
            if a['resources'] and p['resources']:
                for resource in RES:
                    x,y = a['resources'][resource],p['resources'][resource]
                    # Require complete balances throughout the observation window.
                    known = all(fr['players'][slot]['resources'] is not None and
                                fr['players'][slot]['resources'][resource] is not None for fr in history)
                    if known and x is not None and y is not None and y>=1000 and y-x>=500 and p['land']+p['ships']<=a['land']+a['ships']:
                        add('stock_'+resource,slot,before,frame,
                            f'{LABELS[resource]}: {x:.0f} → {y:.0f}; боевые юниты: {a["land"]+a["ships"]} → {p["land"]+p["ships"]}. Рост запаса без чистого роста армии.',
                            'Проверь цель накопления, остальные ресурсы, население, очереди и потери. Производство могло работать; простой не доказан.',
                            'Если запас оказался незапланированным — заранее выбери, на какие войска, здания или исследования его тратить.')
            for other in opponents:
                if other == slot or any(other not in fr['players'] for fr in history):
                    continue
                q,b = frame['players'][other],before['players'][other]
                for metric in ('land','ships'):
                    old,new = a[metric]-b[metric],p[metric]-q[metric]
                    if new-old <= -10:
                        add('relative_'+metric,slot,before,frame,
                            f'{LABELS[metric]}, разница с игроком {other}: {old:+d} → {new:+d}. У тебя {a[metric]} → {p[metric]}, у него {b[metric]} → {q[metric]}.',
                            'Это изменение соотношения численности, не боевой силы. Проверь типы, улучшения, положение и доступную тебе разведку.',
                            'Если разведка позволяла увидеть усиление — проверь, стоило ли отложить атаку, усилить производство или сменить состав.',other)
    if not diag['frames']:
        raise ValueError('В логе нет roster-снимков; ресурсного лога недостаточно')
    if player is not None and not any(k[1]==player for k in summaries):
        raise ValueError(f'Игрок {player} не найден')
    unknown_opponents = set(opponents) - {k[1] for k in summaries}
    if unknown_opponents:
        raise ValueError(f'Указанные соперники не найдены: {sorted(unknown_opponents)}')
    diag['segments'] = segment
    stop = diag['stop'] or {}
    result = stop.get('result', {})
    diag['delivery_ok'] = bool(stop.get('all_sent_records_received'))
    diag['limits_or_pending'] = {k:result[k] for k in ('capped','resource_cap','errors','stop_reason',
        'pending_calls_at_stop','resource_pending','context_pending','action_pending') if result.get(k)}
    return dict(diagnostics=diag,window_seconds=window,max_gap_seconds=max_gap,
                player=player,opponents=list(opponents),summaries=list(summaries.values()),events=events)

def render(report):
    esc = lambda x: html.escape(str(x))
    d = report['diagnostics']
    parts = ['<!doctype html><html lang="ru"><meta charset="utf-8"><title>Разбор AoE</title>',
        '<style>body{max-width:1150px;margin:32px auto;padding:0 20px;background:#111827;color:#e5e7eb;font:16px/1.6 system-ui}section{background:#1e293b;padding:20px;border-radius:12px;margin:18px 0}td,th{padding:7px;text-align:left;border-bottom:1px solid #475569}table{border-collapse:collapse;width:100%}.muted{color:#b9c6da}select{font:inherit}summary{cursor:pointer}h2{font-size:20px}</style>',
        '<h1>Эпизоды для разбора партии</h1><p>Наблюдения из снимков и вопросы для просмотра повтора. Это не доказательство причин поражения и не оценка качества игры.</p>',
        f'<p>Снимков: {d["frames"]}; непрерывных участков: {d["segments"]}; разрывов: {d["gaps"]}; сбросов/повторов времени: {d["resets"]}; ошибок: {d["errors"]}; несвязанных снимков: {d["unmatched"]}. Доставка подтверждена: {"да" if d["delivery_ok"] else "нет"}. Ограничения: {esc(d["limits_or_pending"] or "не отмечены")}.</p>',
        f'<p class="muted">Окно сравнения: {report["window_seconds"]} с. Порог разрыва: {report["max_gap_seconds"]} с. Пороги сигналов: −3 жителя, −5 боевых одной среды; рост одного запаса ≥500 до ≥1000 без чистого роста армии; ухудшение разницы численности ≥10. Это эвристические ориентиры анализа, не оптимальные игровые нормативы. Повтор одного сигнала подавляется на длину окна.</p>',
        '<p class="muted">Считаются объекты состояния 2. Гарнизоны и улучшения не подтверждены. Монахи, короли и хозяйственные суда не входят в боевой итог. Запасы не равны доходу. Нет данных о видимости, очередях, победителе и причинах исчезновения объектов. Сухопутные и морские сравнения разделены. Союзы не угадываются.</p>',
        '<label>Показать игрока <select id="player"><option value="all">Всех</option>']
    for slot in sorted({s['player'] for s in report['summaries']}):
        parts.append(f'<option value="{slot}">{slot}</option>')
    parts.append('</select></label><h2>Записанные интервалы</h2>')
    for s in report['summaries']:
        a,b = s['first'],s['last']
        parts.append(f'<section data-player="{s["player"]}"><b>Игрок {s["player"]} · участок {s["segment"]} · {clock(s["start"])}–{clock(s["end"])}</b><p>Жители: {a["workers"]} → {b["workers"]}; сухопутные: {a["land"]} → {b["land"]}; корабли: {a["ships"]} → {b["ships"]}. Максимум неклассифицированных активных объектов: {s["unknown_max"]}.</p></section>')
    parts.append(f'<h2>Эпизоды: {len(report["events"])}</h2>')
    if not report['events']:
        parts.append('<p>Пороги не сработали. Это не означает отсутствие ошибок: участок мог быть коротким или данных недостаточно.</p>')
    for e in report['events']:
        parts.append(f'<section data-player="{e["player"]}"><h2>Игрок {e["player"]} · участок {e["segment"]} · {clock(e["start"])}–{clock(e["end"])}</h2><p><b>Факт.</b> {esc(e["fact"])}</p><p><b>Проверить в повторе.</b> {esc(e["check"])}</p><p><b>Условный вывод для следующей игры.</b> {esc(e["exercise"])}</p><details><summary>Числа всех записанных игроков до и после</summary><table><tr><th>Момент</th><th>Игрок</th><th>Жители</th><th>Суша</th><th>Корабли</th><th>Е / Д / З / К</th></tr>')
        for key, label in [('before','До'),('after','После')]:
            for p in e[key]:
                resources = ' / '.join('—' if not p['resources'] or p['resources'][r] is None else f'{p["resources"][r]:.0f}' for r in RES)
                parts.append(f'<tr><td>{label}</td><td>{p["slot"]}</td><td>{p["workers"]}</td><td>{p["land"]}</td><td>{p["ships"]}</td><td>{resources}</td></tr>')
        parts.append('</table></details></section>')
    parts.append('<script>document.getElementById("player").onchange=function(){document.querySelectorAll("[data-player]").forEach(e=>e.hidden=this.value!=="all"&&e.dataset.player!==this.value)}</script></html>')
    return '\n'.join(parts)

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('input',type=Path)
    p.add_argument('--out',type=Path,default=Path('coach.html'))
    p.add_argument('--player',type=int)
    p.add_argument('--opponents',type=int,nargs='+',default=[])
    p.add_argument('--window',type=int,default=60)
    p.add_argument('--max-gap',type=float,default=5)
    a = p.parse_args()
    if a.window<1 or a.max_gap<=0: p.error('window/max-gap must be positive')
    if a.opponents and a.player is None:p.error('--opponents requires --player')
    if a.player in a.opponents:p.error('Игрок не может быть собственным соперником')
    target = a.out.with_suffix('.json')
    if a.out.exists() or target.exists():p.error('Выходные файлы уже существуют; выбери новое --out')
    if a.out.suffix.lower() != '.html':p.error('--out должен иметь расширение .html')
    report = analyze(a.input,a.window,a.player,a.opponents,a.max_gap)
    with a.out.open('x',encoding='utf-8') as f:f.write(render(report))
    with target.open('x',encoding='utf-8') as f:json.dump(report,f,ensure_ascii=False,indent=2,allow_nan=False)
    print(f'Готово: {a.out}; снимков {report["diagnostics"]["frames"]}, эпизодов {len(report["events"])}')

if __name__ == '__main__':
    main()
