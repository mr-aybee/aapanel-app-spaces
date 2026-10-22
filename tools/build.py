"""Build a reproducible aaPanel upload archive; excludes local data and test artifacts."""
from pathlib import Path
import json
import zipfile

root = Path(__file__).resolve().parents[1]
plugin = root / 'app_spaces'
version = json.loads((plugin / 'info.json').read_text())['versions']
out = root / 'dist'
out.mkdir(exist_ok=True)
archive = out / ('app_spaces-' + version + '.zip')
with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as stream:
    for file in sorted(plugin.rglob('*')):
        if not file.is_file() or any(x in ('data', '__pycache__') for x in file.relative_to(plugin).parts) or file.suffix == '.pyc':
            continue
        info = zipfile.ZipInfo(str(file.relative_to(root)).replace('\\', '/'), (2026, 10, 22, 0, 0, 0))
        info.external_attr = (0o100755 if file.suffix == '.sh' else 0o100644) << 16
        stream.writestr(info, file.read_bytes(), compress_type=zipfile.ZIP_DEFLATED)
print(archive)
