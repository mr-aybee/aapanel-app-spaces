import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app_spaces'))
from appspaces_core.core import Store
from appspaces_core.metrics import Metrics

class MetricsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = Store(self.root / 'data')
        self.store.db.execute("INSERT INTO namespaces VALUES ('demo','','')")
        self.store.db.execute("INSERT INTO registrations VALUES ('api','demo','systemd','demo.service','api',1,1)")
        self.store.db.execute("INSERT INTO registrations VALUES ('redis','demo','docker','compose:demo/redis','redis',1,0)")
        self.store.db.commit()
        self.now = 100.0
        self.calls = []
        self.cpu = 1000000
        self.active = True
        self.identity = 'group1'
        self.proc = self.root / 'proc/15'
        self.proc.mkdir(parents=True)
        (self.proc / 'cgroup').write_text('0::/docker/demo\n')
        self.flock = patch.dict(sys.modules, {'fcntl': types.SimpleNamespace(LOCK_EX=1, LOCK_NB=4, flock=lambda *args: None)})
        self.flock.start()

    def tearDown(self):
        self.flock.stop()
        self.store.close()
        self.temp.cleanup()

    def run_command(self, args, **kwargs):
        self.calls.append(args)
        if args[0] == 'systemctl':
            return 'Id=demo.service\nLoadState=loaded\nActiveState='+('active' if self.active else 'inactive')+'\nControlGroup=/system.slice/demo.service\n'
        if args[1] == 'ps':
            return 'a'*64
        return ' '.join(json.dumps(x) for x in ['a'*64, '/demo-redis', 15, self.active, 'demo', 'redis'])

    def collect(self):
        metrics = Metrics(self.store, self.run_command, proc=self.root / 'proc', clock=lambda: self.now)
        metrics.counters = lambda group: (self.cpu, 1024, self.identity + group)
        return metrics.collect()

    def test_delta_cache_and_all_runtimes(self):
        first = self.collect()
        self.assertTrue(all(x['status'] == 'sampling' and x['memory'] == 1024 for x in first['services']))
        count = len(self.calls)
        self.now += 2
        self.assertEqual(self.collect(), first)
        self.assertEqual(len(self.calls), count, 'Fresh shared cache must avoid all subprocesses')
        self.now += 3
        self.cpu += 2500000000
        second = self.collect()
        self.assertEqual([x['cpu'] for x in second['services']], [50.0, 50.0])
        self.assertTrue(all('proxy' not in str(call) and 'ss' not in call for call in self.calls))

    def test_restart_and_inactive(self):
        self.collect()
        self.now += 5
        self.identity = 'replacement'
        self.cpu = 0
        self.assertTrue(all(x['cpu'] is None for x in self.collect()['services']))
        self.now += 5
        self.active = False
        self.assertTrue(all(x['cpu'] == 0 and x['memory'] == 0 and x['status'] == 'inactive' for x in self.collect()['services']))

    def test_cgroup_traversal_refused(self):
        metrics = Metrics(self.store, cgroups=self.root / 'groups')
        with self.assertRaises(ValueError):
            metrics.counters('/../../outside')

    def test_unavailable_is_not_false_zero(self):
        def missing(*args):
            raise OSError('gone')
        metrics = Metrics(self.store, self.run_command, proc=self.root / 'proc', clock=lambda: self.now)
        metrics.counters = missing
        result = metrics.collect()
        self.assertTrue(all(x['cpu'] is None and x['memory'] is None for x in result['services']))

if __name__ == '__main__':
    unittest.main()
