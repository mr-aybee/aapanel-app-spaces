"""Assemble aaPanel's self-contained index.html and a standalone fixture preview."""

from pathlib import Path

import re, json

root = Path(__file__).resolve().parents[1]

plugin = root / 'app_spaces'

css = (plugin / 'ui.css').read_text(encoding='utf-8')

markup = (plugin / 'ui.html').read_text(encoding='utf-8')

js = (plugin / 'editor_ui.js').read_text(encoding='utf-8') + '\n' + (plugin / 'ui.js').read_text(encoding='utf-8') + '\n' + (plugin / 'creation_ui.js').read_text(encoding='utf-8')

fragment = '<style>\n' + css + '\n</style>\n' + markup + '\n<script>\n' + js + '\n</script>\n'

version=json.loads((plugin/'info.json').read_text(encoding='utf-8'))['versions']

(plugin/'index.html').write_text((plugin/'launcher.html').read_text(encoding='utf-8').replace('__APP_SPACES_VERSION__',version),encoding='utf-8')

(plugin/'workspace.html').write_text('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>App Spaces</title><style>body{margin:0;background:#17191e}</style></head><body>'+fragment+'</body></html>',encoding='utf-8')

preview = root / 'preview'

preview.mkdir(exist_ok=True)

fixture = (preview / 'demo.js').read_text(encoding='utf-8')

(preview / 'index.html').write_text('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>App Spaces · source preview</title><style>body{margin:0;background:#17191e}</style></head><body><script>\n' + fixture + '\n</script>\n' + fragment + '</body></html>', encoding='utf-8')

print('Assembled plugin and standalone preview')

