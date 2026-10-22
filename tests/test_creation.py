import contextlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'app_spaces'))
from appspaces_core.core import AppError, Store
from appspaces_core.creation import Creator, identity, normalize, render

def native_spec(**overrides):
    return {'runtime':'systemd','namespace':'orbyn','name':'api','description':'Example API','executable':'/usr/bin/dotnet','working_directory':'/srv/app','user':'deploy','arguments':['App.dll'], 'environment':{'ASPNETCORE_ENVIRONMENT':'Production'}, **overrides}

def docker_spec(**overrides):
    return {'runtime':'docker','namespace':'orbyn','name':'web','image':'nginx:stable-alpine','environment':{},'ports':[{'host':'127.0.0.1','published':9830,'target':80,'protocol':'tcp'}],**overrides}

class CreationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.units=self.root/'units';self.units.mkdir()
        self.store=Store(self.root/'data')
        self.store.db.execute('INSERT INTO namespaces VALUES (?,?,?)',('orbyn','Example','Production'));self.store.db.commit()
        self.calls=[]
        def runner(args,**kwargs):
            self.calls.append(args)
            if args[:2]==['systemctl','show']:return 'not-found\n'
            return ''
        self.runner=runner
        self.creator=Creator(self.store,runner,self.units,False)
        self.lock=patch.object(self.store,'lock',lambda key:contextlib.nullcontext());self.lock.start()

    def tearDown(self):
        self.lock.stop();self.store.close();self.temp.cleanup()

    def test_systemd_render_has_readable_env_and_literal_arguments(self):
        source=render(normalize(native_spec(environment={'NORMAL':'hello world','PERCENT':'%n','PRICE':'$5'},arguments=['App.dll','$(touch /tmp/no)','100%'])))
        self.assertIn('ExecStart=:',source)
        self.assertIn('Environment="NORMAL=hello world"',source)
        self.assertIn('Environment="PERCENT=%%n"',source)
        self.assertIn('Environment="PRICE=$5"',source)
        self.assertIn('"100%%"',source)

    def test_env_newline_directive_injection_rejected(self):
        with self.assertRaises(AppError):normalize(native_spec(environment={'VAR':'x\nExecStart=/bin/sh'}))
        with self.assertRaises(AppError):normalize(native_spec(user='root\nExecStart=/bin/sh'))

    def test_windows_and_parent_paths_rejected(self):
        for path in ('D:\\Repos\\app','/srv/../etc','relative/path'):
            with self.assertRaises(AppError):normalize(native_spec(working_directory=path))

    def test_preview_masks_all_env_values_and_does_not_create_unit(self):
        data=self.creator.preview(native_spec(environment={'NORMAL':'private-value'}),'admin')
        self.assertNotIn('private-value',data['content'])
        self.assertIn('[hidden]',data['content'])
        self.assertEqual([],list(self.units.iterdir()))
        self.assertFalse(any(x[:2]==['systemctl','start'] for x in self.calls))

    def test_create_only_and_single_use_ticket(self):
        preview=self.creator.preview(native_spec(),'admin')
        result=self.creator.create(preview['token'],'admin')
        self.assertTrue(result['created']);self.assertFalse(result['started'])
        self.assertTrue(Path(result['path']).is_file())
        self.assertEqual('api',self.store.get(result['id'])['label'])
        with self.assertRaises(AppError):self.creator.create(preview['token'],'admin')

    def test_create_start_and_boot_are_explicit(self):
        preview=self.creator.preview(native_spec(enable_at_boot=True),'admin')
        result=self.creator.create(preview['token'],'admin',True)
        native=result['identity']
        self.assertIn(['systemctl','enable',native],self.calls)
        self.assertIn(['systemctl','start',native],self.calls)

    def test_existing_unit_never_overwritten(self):
        name=identity(normalize(native_spec()))
        (self.units/name).write_text('original')
        with self.assertRaises(AppError):self.creator.preview(native_spec(),'admin')
        self.assertEqual('original',(self.units/name).read_text())

    def test_collision_between_preview_and_creation(self):
        preview=self.creator.preview(native_spec(),'admin')
        target=self.units/preview['identity'];target.write_text('external')
        with self.assertRaises(AppError):self.creator.create(preview['token'],'admin')
        self.assertEqual('external',target.read_text())

    def test_preview_bound_to_actor_and_expiry(self):
        preview=self.creator.preview(native_spec(),'admin')
        with self.assertRaises(AppError):self.creator.create(preview['token'],'other')
        self.store.db.execute('UPDATE creation_tickets SET expires=0');self.store.db.commit()
        with self.assertRaises(AppError):self.creator.create(preview['token'],'admin')

    def test_start_failure_retains_registered_definition(self):
        preview=self.creator.preview(native_spec(),'admin')
        original=self.creator.run
        def failure(args,**kwargs):
            if args[:2]==['systemctl','start']:raise AppError('Simulated startup error')
            return original(args,**kwargs)
        self.creator.run=failure
        result=self.creator.create(preview['token'],'admin',True)
        self.assertTrue(result['created']);self.assertFalse(result['started'])
        self.assertIn('error',result)
        self.assertTrue(Path(result['path']).exists())
        self.assertTrue(self.store.get(result['id']))

    def test_compose_options_and_literal_environment(self):
        spec=normalize(docker_spec(environment={'VALUE':'${DO_NOT_EXPAND}'},command=['nginx','-g','daemon off;'],
            mounts=[{'type':'volume','source':'app-data','target':'/data','read_only':False}],network='shared',cpus='1.5',memory='512M',read_only=True,
            healthcheck=['CMD','wget','-q','http://localhost/']))
        source=render(spec)
        for expected in ('127.0.0.1','host_ip','app-data','external: true','cpus: 1.5','mem_limit: "512M"','read_only: true','healthcheck:','logging:','$${DO_NOT_EXPAND}'):
            self.assertIn(expected,source)

    def test_create_docker_definition_without_containers(self):
        preview=self.creator.preview(docker_spec(),'admin')
        result=self.creator.create(preview['token'],'admin')
        self.assertTrue(Path(result['path']).is_file())
        self.assertEqual('Defined',result['state'])
        self.assertFalse(any('up' in x for x in self.calls))
        self.creator.lifecycle(self.store.get(result['id']),'start')
        self.assertTrue(any('up' in x and '-d' in x for x in self.calls))

    def test_local_dockerfile_build_and_start_flags(self):
        spec=docker_spec(image_mode='build',image='local/app:v1',build_context='/srv/app',dockerfile='docker/Dockerfile')
        preview=self.creator.preview(spec,'admin');result=self.creator.create(preview['token'],'admin',True)
        self.assertTrue(result['started'])
        self.assertTrue(any('--build' in x for x in self.calls))
        with self.assertRaises(AppError):normalize({**spec,'dockerfile':'../Dockerfile'})

    def test_invalid_port_and_volume_rejected(self):
        for ports in ([{'published':70000,'target':80}],[{'published':1.2,'target':80}],[{'host':'example.com','published':80,'target':80}]):
            with self.assertRaises(AppError):normalize(docker_spec(ports=ports))
        with self.assertRaises(AppError):normalize(docker_spec(mounts=[{'type':'volume','source':'../../root','target':'/data'}]))

    def test_listening_port_conflict_prevents_creation(self):
        self.creator.run=lambda args,**kwargs:'LISTEN 0 512 0.0.0.0:9830 0.0.0.0:*' if args[0]=='ss' else ''
        with self.assertRaises(AppError):self.creator.preview(docker_spec(),'admin')

    def test_healthcheck_shell_mode_not_implicitly_enabled(self):
        with self.assertRaises(AppError):normalize(docker_spec(healthcheck=['CMD-SHELL','curl localhost']))

    def test_missing_namespace_rejected(self):
        with self.assertRaises(AppError):self.creator.preview(native_spec(namespace='missing'),'admin')
