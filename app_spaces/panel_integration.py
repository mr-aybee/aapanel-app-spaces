"""Install only a static shell and a tiny navigation hook, preserving native bundles."""
from pathlib import Path
import shutil

PANEL = Path('/www/server/panel')
PLUGIN = Path(__file__).resolve().parent
TAG = '<script defer src="/static/app_spaces/panel_shortcut.js?v=0.0.1" data-app-spaces-integration></script>'
START = '# BEGIN APP SPACES ROUTE INTEGRATION'
END = '# END APP SPACES ROUTE INTEGRATION'
ROUTES = '''
# BEGIN APP SPACES ROUTE INTEGRATION
# Optional plugin route loader; the plugin owns its view implementation.
try:
    import importlib.util as _appspaces_import
    from pathlib import Path as _appspaces_Path
    _appspaces_file = _appspaces_Path('/www/server/panel/plugin/app_spaces/workspace_routes.py')
    if _appspaces_file.is_file():
        _appspaces_spec = _appspaces_import.spec_from_file_location('app_spaces_workspace_routes', _appspaces_file)
        _appspaces_routes = _appspaces_import.module_from_spec(_appspaces_spec)
        _appspaces_spec.loader.exec_module(_appspaces_routes)
        _appspaces_routes.register(app)
except Exception:
    app.logger.exception('App Spaces workspace route registration failed')
# END APP SPACES ROUTE INTEGRATION
'''


def strip_routes(text):
    import re
    return re.sub(r'\n?' + re.escape(START) + r'.*?' + re.escape(END) + r'\n?', '\n', text, flags=re.S)

def uninstall(panel=PANEL):
    import re
    template = panel / 'BTPanel/templates/default/index_new.html'
    if template.exists():
        text = template.read_text()
        template.write_text(re.sub(r'<script[^>]*data-app-spaces-integration[^>]*></script>\s*', '', text))
    for name in ('index.html', 'panel_shortcut.js'):
        (panel / 'BTPanel/static/app_spaces' / name).unlink(missing_ok=True)
    startup = panel / 'BTPanel/__init__.py'
    if startup.exists():
        startup.write_text(strip_routes(startup.read_text()))

def install(panel=PANEL):
    static = panel / 'BTPanel/static/app_spaces'
    static.mkdir(exist_ok=True, mode=0o755)
    for source, name in [('workspace.html', 'index.html'), ('panel_shortcut.js', 'panel_shortcut.js')]:
        target = static / name
        shutil.copyfile(PLUGIN / source, target)
        target.chmod(0o644)
    template = panel / 'BTPanel/templates/default/index_new.html'
    text = template.read_text()
    import re
    text = re.sub(r'<script[^>]*data-app-spaces-integration[^>]*></script>\s*', '', text)
    if '</body>' not in text:
        raise RuntimeError('Unsupported aaPanel template: no body closing tag')
    backup = PLUGIN / 'data/panel-index-before-integration.html'
    if not backup.exists():
        shutil.copyfile(template, backup)
        backup.chmod(0o600)
    template.write_text(text.replace('</body>', TAG + '\n</body>'))
    startup = panel / 'BTPanel/__init__.py'
    original = startup.read_text()
    backup = PLUGIN / 'data/panel-startup-before-integration.py'
    if not backup.exists():
        shutil.copyfile(startup, backup)
        backup.chmod(0o600)
    updated = strip_routes(original).rstrip() + '\n' + ROUTES
    compile(updated, str(startup), 'exec')
    startup.write_text(updated)

if __name__ == '__main__':
    import sys
    uninstall() if sys.argv[1:] == ['uninstall'] else install()
