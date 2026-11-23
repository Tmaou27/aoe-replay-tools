import json
from pathlib import Path
import tempfile
import unittest
import zipfile
from analyze import analyze, render

class ReviewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.path=Path(self.tmp.name)/'log.jsonl'
    def tearDown(self): self.tmp.cleanup()
    def write(self,times,drop=False,missing=False):
        records=[]
        for i,t in enumerate(times):
            end=i==len(times)-1
            objects=[{'state':2,'class_id':4} for _ in range(10-(3 if end and drop else 0))]
            objects += [{'state':2,'class_id':6} for _ in range(10-(5 if end and drop else 0))]
            enemy=[{'state':2,'class_id':6} for _ in range(10+(10 if end else 0))]
            records.append(dict(kind='roster',time_ms=t,step_id=i,players=[dict(slot=1,objects=objects),dict(slot=2,objects=enemy)]))
            if not missing or i!=30:
                records.append(dict(kind='call',id=i,after=dict(players=[dict(slot=1,wood=500+10*i,food=0,gold=0,stone=0),dict(slot=2,wood=0,food=0,gold=0,stone=0)])))
        records.append(dict(kind='stop',all_sent_records_received=True,result={}))
        self.path.write_text('\n'.join(json.dumps(r) for r in records))
    def test_evidence(self):
        self.write(range(0,61000,1000),drop=True)
        r=analyze(self.path,player=1,opponents=[2])
        kinds={e['kind'] for e in r['events']}
        self.assertEqual(kinds,{'stock_wood','decrease_workers','decrease_land','relative_land'})
        self.assertTrue(all(e['end']==60000 for e in r['events']))
        self.assertEqual(r['events'][0]['before'][0]['workers'],10)
        self.assertIn('Факт.',render(r))
    def test_gap_and_reset(self):
        for times in ([0,60000], [0,1000,0,1000]):
            self.write(times,drop=True)
            r=analyze(self.path,player=1,opponents=[2])
            self.assertEqual(r['events'],[])
            self.assertEqual(r['diagnostics']['segments'],2)
    def test_missing_balance(self):
        self.write(range(0,61000,1000),missing=True)
        r=analyze(self.path,player=1)
        self.assertFalse(any(e['kind'].startswith('stock') for e in r['events']))
        self.assertEqual(r['diagnostics']['unmatched'],1)
    def test_zip_matches(self):
        self.write(range(0,61000,1000),drop=True)
        zpath=self.path.with_suffix('.zip')
        with zipfile.ZipFile(zpath,'w') as z:z.write(self.path,'log.jsonl')
        self.assertEqual(analyze(self.path),analyze(zpath))
    def test_invalid_json(self):
        self.path.write_text('{bad')
        with self.assertRaises(ValueError):analyze(self.path)

if __name__=='__main__':unittest.main()
