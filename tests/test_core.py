import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app_spaces'))
from appspaces_core.core import AppError, Application, Configuration, Docker, ProxyIndex, Store, Systemd, redact, valid_unit, namespace_id

class FakeSystemd:
    def __init__(self, path=None):
        self.path = path
        self.calls = []
        self.fail_restart = False

    def inspect(self, native):
        return {'native': native, 'name': native, 'runtime': 'systemd', 'source': native, 'state': 'Running', 'endpoints': [{'host':'0.0.0.0','port':9810,'protocol':'tcp'}], 'details':{'FragmentPath': str(self.path or '/etc/systemd/system/demo.service')}, 'instances': [], 'config_supported':True}

    def discover(self):
        return [self.inspect('demo.service')]

    def run(self, args, **kwargs):
        self.calls.append(args)
        return ''

    def action(self, native, operation):
        self.calls.append([native, operation])
        if self.fail_restart:
            self.fail_restart = False
            raise AppError('Simulated startup failure')
        return self.inspect(native)

class FakeDocker:
    def discover(self):
        raise AppError('Docker daemon unavailable')

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(self.temp.name)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_namespace_survives_reopen(self):
        app = Application(self.store, FakeSystemd(), FakeDocker(), ProxyIndex(self.temp.name, []))
        app.namespace({'operation':'create','slug':'orbyn-prod','description':'Production'})
        self.store.close()
        self.store = Store(self.temp.name)
        self.assertEqual('orbyn-prod',self.store.namespaces()[0]['slug'])

    def test_registration_does_not_run_service(self):
        adapter = FakeSystemd()
        app = Application(self.store, adapter, FakeDocker(), ProxyIndex(self.temp.name, []))
        app.namespace({'operation':'create','slug':'orbyn'})
        reg = app.register({'runtime':'systemd','native':'demo.service','namespace':'orbyn'})
        self.assertEqual([],adapter.calls)
        with self.assertRaises(AppError): app.action(reg['id'],'restart')

    def test_namespace_delete_cannot_orphan_registration(self):
        app = Application(self.store, FakeSystemd(), FakeDocker(), ProxyIndex(self.temp.name, []))
        app.namespace({'operation':'create','slug':'orbyn'})
        app.register({'runtime':'systemd','native':'demo.service','namespace':'orbyn'})
        with self.assertRaises(AppError): app.namespace({'operation':'delete','slug':'orbyn'})

    def test_discovery_docker_failure_does_not_hide_systemd(self):
        app = Application(self.store, FakeSystemd(), FakeDocker(), ProxyIndex(self.temp.name, []))
        data = app.inventory(discover=True)
        self.assertEqual(1,len(data['services']))
        self.assertTrue(any('Docker' in x for x in data['warnings']))

    def test_register_duplicate_rejected(self):
        app = Application(self.store, FakeSystemd(), FakeDocker(), ProxyIndex(self.temp.name, []))
        app.namespace({'operation':'create','slug':'orbyn'})
        payload={'runtime':'systemd','native':'demo.service','namespace':'orbyn'}
        app.register(payload)
        with self.assertRaises(sqlite3.IntegrityError): app.register(payload)

    def test_existing_app_visible_unassigned_without_registration(self):
        adapter=FakeSystemd()
        adapter.discover=lambda:[adapter.inspect('web-api.service')]
        app=Application(self.store,adapter,FakeDocker(),ProxyIndex(self.temp.name,[]))
        data=app.inventory(include_unassigned=True)
        self.assertEqual('extra',data['services'][0]['namespace'])
        self.assertTrue(data['services'][0]['unregistered'])
        self.assertFalse(data['services'][0]['capabilities']['lifecycle'])
        self.assertEqual([],self.store.registrations())
        self.assertTrue(data['namespaces'][0]['virtual'])

class ProxyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name)
        self.index = ProxyIndex(self.path, ['46.62.193.88'])

    def tearDown(self): self.temp.cleanup()

    def test_many_routes_and_remote_same_port(self):
        (self.path/'orbyn.conf').write_text('''server {
          server_name orbyntech.com www.orbyntech.com;
          location / { proxy_pass http://localhost:9811; }
          location /api/ { proxy_pass http://127.0.0.1:9810; }
          location /hubs/ { proxy_pass http://46.62.193.88:9810; }
          location /remote/ { proxy_pass http://203.0.113.2:9810; }
        }''')
        routes,_=self.index.read()
        matches=self.index.match([{'host':'0.0.0.0','port':9810,'protocol':'tcp'}],routes)
        self.assertEqual(['/api/','/hubs/'],[x['location'] for x in matches])
        self.assertEqual(2,len(matches[0]['domains']))

    def test_ipv6_named_upstream_and_default_port(self):
        (self.path/'test.conf').write_text('''upstream app { server [::1]:9810; }
        server { server_name example.com; location / { proxy_pass http://app; } location /default { proxy_pass http://127.0.0.1; } }''')
        routes,_=self.index.read()
        self.assertEqual(1,len(self.index.match([{'host':'::1','port':9810,'protocol':'tcp'}],routes)))
        self.assertEqual(1,len(self.index.match([{'host':'127.0.0.1','port':80,'protocol':'tcp'}],routes)))

    def test_includes_and_dynamic_targets_not_claimed_exact(self):
        (self.path/'test.conf').write_text('server { server_name a; include /tmp/*.conf; location / { proxy_pass http://$backend; } }')
        routes,warnings=self.index.read()
        self.assertTrue(warnings)
        self.assertEqual('unresolved', routes[0]['confidence'])
        self.assertEqual([],self.index.match([{'host':'0.0.0.0','port':80,'protocol':'tcp'}],routes))

    def test_loopback_listener_not_mapped_to_public_address(self):
        (self.path/'test.conf').write_text('server { server_name a; proxy_pass http://46.62.193.88:9810; }')
        routes,_=self.index.read()
        self.assertEqual([],self.index.match([{'host':'127.0.0.1','port':9810,'protocol':'tcp'}],routes))

class ValidationTests(unittest.TestCase):
    def test_discovery_skips_templates_and_individual_unit_failures(self):
        def runner(args, **kwargs):
            if args[1]=='list-units':return ''
            if args[1]=='list-unit-files':return 'demo@.service disabled\nweb-api.service enabled\nbroken.service enabled'
            if args[2]=='broken.service':raise AppError('Unavailable unit')
            if args[2]=='demo@.service':raise AssertionError('Template should never be inspected')
            return 'Id=web-api.service\nMainPID=0\nActiveState=active\n'
        items=Systemd(runner).discover()
        self.assertEqual(['web-api.service'],[x['native'] for x in items])
    def test_invalid_unit_and_namespace(self):
        for value in ('../../demo.service','--help.service','demo.service;reboot','demo\n.service'):
            with self.assertRaises(AppError): valid_unit(value)
        with self.assertRaises(AppError): namespace_id('../root')
        self.assertEqual('web-api@demo.service',valid_unit('web-api@demo.service'))

    def test_redaction(self):
        text = 'Description=hello\nEnvironment="NORMAL=value"\nPassword=super-secret\nurl=https://user:pass@example.com'
        value = redact(text)
        self.assertNotIn('super-secret',value)
        self.assertNotIn('NORMAL=value',value)
        self.assertNotIn('user:pass',value)
        self.assertIn('Description=hello',value)

    def test_docker_replicas_stable_group(self):
        def container(cid,name):
            return {'Id':cid*64,'Name':'/'+name,'State':{'Status':'running'},'Config':{'Image':'example:v1','Labels':{'com.docker.compose.project':'orbyn','com.docker.compose.service':'api'}},'NetworkSettings':{'Ports':{'8080/tcp':[{'HostIp':'0.0.0.0','HostPort':'9810'}]}},'HostConfig':{}}
        def runner(args, **kwargs):
            return 'a'*64+'\n'+'b'*64 if args[1]=='ps' else json.dumps([container('a','api-1'),container('b','api-2')])
        adapter=Docker(runner)
        data=adapter.discover()
        self.assertEqual('compose:orbyn/api',data[0]['native'])
        self.assertEqual(2,len(data[0]['instances']))
        self.assertEqual(8080,data[0]['endpoints'][0]['container_port'])
        self.assertIsNone(data[0]['memory'])

    def test_stopped_nonzero_docker_is_failed(self):
        item={'Id':'a'*64,'Name':'/app','State':{'Status':'exited','ExitCode':1},'Config':{'Image':'example'},'NetworkSettings':{},'HostConfig':{}}
        self.assertEqual('Failed',Docker()._dto('container:app',[item])['state'])

class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.unit=self.root/'demo.service'
        self.unit.write_text('[Service]\nExecStart=/usr/bin/true\nEnvironment="PASSWORD=example"\n')
        self.store=Store(self.root/'data')
        self.adapter=FakeSystemd(self.unit)
        self.config=Configuration(self.store,self.adapter,[self.root])
        self.reg={'id':'abc','runtime':'systemd','native':'demo.service','config':1,'lifecycle':1}

    def tearDown(self): self.store.close(); self.temp.cleanup()

    def test_hidden_read_not_editable(self):
        data=self.config.read(self.reg)
        self.assertFalse(data['editable'])
        self.assertNotIn('PASSWORD=example',data['content'])

    def test_external_edit_rejects_preview(self):
        data=self.config.read(self.reg,True)
        self.unit.write_text('[Service]\nExecStart=/usr/bin/false\n')
        with self.assertRaises(AppError): self.config.preview(self.reg,data['content'],data['revision'],'admin')

    def test_path_outside_allowed_roots(self):
        config=Configuration(self.store,self.adapter,[self.root/'another'])
        with self.assertRaises(AppError): config.read(self.reg)

    def test_preview_hides_secrets_and_binds_actor(self):
        data=self.config.read(self.reg,True)
        preview=self.config.preview(self.reg,data['content'].replace('example','replacement'),data['revision'],'admin')
        self.assertNotIn('replacement',preview['diff'])
        import contextlib
        with patch.object(self.store, 'lock', lambda key: contextlib.nullcontext()):
            with self.assertRaises(AppError): self.config.apply(self.reg,preview['token'],'another-session')

    def test_apply_replay_and_rollback(self):
        data=self.config.read(self.reg,True)
        preview=self.config.preview(self.reg,data['content'].replace('/usr/bin/true','/usr/bin/false'),data['revision'],'admin')
        self.adapter.fail_restart=True
        import contextlib
        with patch.object(self.store, 'lock', lambda key: contextlib.nullcontext()), patch('os.chown', create=True):
            with self.assertRaises(AppError): self.config.apply(self.reg,preview['token'],'admin')
            self.assertEqual(data['content'],self.unit.read_text())
            with self.assertRaises(AppError): self.config.apply(self.reg,preview['token'],'admin')

    def test_apply_success_and_conflict_after_preview(self):
        import contextlib
        data=self.config.read(self.reg,True)
        preview=self.config.preview(self.reg,data['content'].replace('/usr/bin/true','/usr/bin/false'),data['revision'],'admin')
        with patch.object(self.store, 'lock', lambda key: contextlib.nullcontext()), patch('os.chown', create=True):
            result=self.config.apply(self.reg,preview['token'],'admin')
            self.assertEqual('Running',result['state'])
            self.assertIn('/usr/bin/false',self.unit.read_text())
            with self.assertRaises(AppError): self.config.apply(self.reg,preview['token'],'admin')
        data=self.config.read(self.reg,True)
        preview=self.config.preview(self.reg,data['content'],data['revision'],'admin')
        self.unit.write_text(data['content']+'# external edit\n')
        with patch.object(self.store, 'lock', lambda key: contextlib.nullcontext()):
            with self.assertRaises(AppError): self.config.apply(self.reg,preview['token'],'admin')

if __name__=='__main__': unittest.main()


class DockerUptimeTests(unittest.TestCase):
    def test_docker_uptime_uses_actual_start(self):
        import datetime
        started=(datetime.datetime.now(datetime.timezone.utc)-datetime.timedelta(hours=2)).isoformat()
        item={'Id':'a'*64,'Name':'/demo','State':{'Status':'running','StartedAt':started},'Config':{'Image':'demo'},'NetworkSettings':{'Ports':{}}}
        result=Docker()._dto('container:demo',[item])
        self.assertTrue(7195 <= result['uptime'] <= 7205)
        item['State']['StartedAt']='invalid'
        self.assertIsNone(Docker()._dto('container:demo',[item])['uptime'])
