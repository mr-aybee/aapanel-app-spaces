import importlib.util
import json
from pathlib import Path
import secrets
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'app_spaces'))
import app_spaces_main as module
from appspaces_core.core import Application, ProxyIndex
from test_core import FakeSystemd, FakeDocker

class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.session={'login':True,'uid':1}
        self.request=types.SimpleNamespace(method='POST')
        self.panel=types.SimpleNamespace(session=self.session,request=self.request,check_csrf=lambda:True)
        self.public=types.SimpleNamespace(get_csrf_sess_html_token_value=lambda:'fixture-token')
        self.modules=patch.dict(sys.modules,{'BTPanel':self.panel,'public':self.public})
        self.modules.start()
        self.plugin=patch.object(module,'PLUGIN',Path(self.temp.name));self.plugin.start()
        self.application=patch.object(module,'Application',lambda store: Application(store,FakeSystemd(),FakeDocker(),ProxyIndex(self.temp.name,[])));self.application.start()
        self.api=module.app_spaces_main()

    def tearDown(self):
        self.application.stop();self.plugin.stop();self.modules.stop();self.temp.cleanup()

    def call(self,payload):
        return self.api.api(types.SimpleNamespace(payload=json.dumps(payload)))

    def test_reject_other_user_and_get_and_csrf(self):
        self.session['uid']=2
        self.assertFalse(self.call({'operation':'inventory'})['status'])
        self.session['uid']=1;self.request.method='GET'
        self.assertFalse(self.call({'operation':'inventory'})['status'])
        self.request.method='POST';self.panel.check_csrf=lambda:False
        self.assertFalse(self.call({'operation':'inventory'})['status'])

    def test_bootstrap_and_metrics_keep_authentication(self):
        self.assertEqual(self.call({'operation':'bootstrap'})['data']['csrf'], 'fixture-token')
        with patch('appspaces_core.metrics.Metrics.collect', return_value={'services': []}):
            self.assertEqual(self.call({'operation':'metrics'})['data']['services'], [])
            for operation in ('bootstrap', 'metrics'):
                self.session['uid'] = 2
                self.assertFalse(self.call({'operation': operation})['status'])
                self.session['uid'] = 1
                self.panel.check_csrf = lambda: False
                self.assertFalse(self.call({'operation': operation})['status'])
                self.panel.check_csrf = lambda: True

    def test_reject_temporary_login(self):
        self.session['tmp_login_id']='1'
        self.assertFalse(self.call({'operation':'inventory'})['status'])

    def test_mutation_replay_rejected(self):
        payload={'operation':'namespaces','namespace_operation':'create','slug':'orbyn','request_id':secrets.token_hex(24)}
        self.assertTrue(self.call(payload)['status'])
        response=self.call(payload)
        self.assertFalse(response['status'])
        self.assertIn('already submitted',response['msg'])

    def test_explicit_confirmation_for_action(self):
        response=self.call({'operation':'action','id':'not-registered','verb':'restart','request_id':secrets.token_hex(24)})
        self.assertFalse(response['status'])
        self.assertIn('confirmation',response['msg'])

    def test_unknown_operation_and_malformed_payload(self):
        self.assertFalse(self.call({'operation':'shell','command':'reboot'})['status'])
        self.assertFalse(self.api.api(types.SimpleNamespace(payload='not json'))['status'])

    def test_empty_inventory(self):
        data=self.call({'operation':'inventory'})
        self.assertTrue(data['status'])
        self.assertEqual([],data['data']['services'])

    def test_creation_requires_confirmation(self):
        data=self.call({'operation':'create_service','token':'fake','request_id':secrets.token_hex(24)})
        self.assertFalse(data['status'])
        self.assertIn('confirmation',data['msg'])
