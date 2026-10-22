import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('panel_integration', Path(__file__).resolve().parents[1] / 'app_spaces/panel_integration.py')
integration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(integration)


class IntegrationTests(unittest.TestCase):
    def test_install_update_and_uninstall_preserve_panel_changes(self):
        with tempfile.TemporaryDirectory() as folder:
            panel = Path(folder)
            (panel / 'BTPanel/static').mkdir(parents=True)
            template = panel / 'BTPanel/templates/default/index_new.html'
            template.parent.mkdir(parents=True)
            template.write_text('<html><body>native</body></html>')
            (panel / 'BTPanel/__init__.py').write_text('# panel startup\n')
            plugin = panel / 'plugin'
            (plugin / 'data').mkdir(parents=True)
            (plugin / 'workspace.html').write_text('public shell')
            (plugin / 'panel_shortcut.js').write_text('shortcut')
            original = integration.PLUGIN
            integration.PLUGIN = plugin
            try:
                integration.install(panel)
                integration.install(panel)
                self.assertEqual(template.read_text().count('data-app-spaces-integration'), 1)
                self.assertEqual((panel/'BTPanel/__init__.py').read_text().count(integration.START),1)
                template.write_text(template.read_text().replace('native', 'updated-native'))
                integration.uninstall(panel)
                self.assertEqual(template.read_text(), '<html><body>updated-native</body></html>')
                self.assertFalse((panel / 'BTPanel/static/app_spaces/index.html').exists())
                self.assertNotIn(integration.START,(panel/'BTPanel/__init__.py').read_text())
                self.assertTrue((plugin / 'data/panel-index-before-integration.html').exists())
            finally:
                integration.PLUGIN = original
