"""Small, dependency-free backend shared by aaPanel and fixture tests."""
import contextlib
import datetime
import difflib
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import socket
import sqlite3
import subprocess
import tempfile
import time

class AppError(Exception):
    pass

def run(argv, timeout=25):
    """Never invoke a shell; command errors do not echo potentially secret output."""
    try:
        p = subprocess.run(argv, capture_output=True, timeout=timeout, check=False,
                           env={**os.environ, 'LC_ALL': 'C', 'SYSTEMD_COLORS': '0'})
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AppError('Command unavailable or timed out: ' + argv[0]) from exc
    if p.returncode:
        raise AppError('%s failed (exit %s)' % (argv[0], p.returncode))
    if len(p.stdout) > 4 * 1024 * 1024:
        raise AppError('Command output exceeded 4 MB; narrow the request')
    return p.stdout.decode('utf-8', 'replace')

def valid_unit(value):
    if not re.fullmatch(r'[A-Za-z0-9_@:.\\-]{1,200}\.service', value) or value.startswith('-'):
        raise AppError('Invalid systemd service identifier')
    return value

def valid_container(value):
    if not re.fullmatch(r'[a-f0-9]{12,64}', value):
        raise AppError('Expected a Docker container ID')
    return value

def namespace_id(value):
    if not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', value) or len(value) > 64:
        raise AppError('Use a lowercase namespace slug, maximum 64 characters')
    return value

def secret_key(key):
    return bool(re.search(r'password|secret|token|credential|connectionstrings|private.?key|api.?key|access.?key', key, re.I))

def redact(text):
    """Conservative masking for logs/config diffs, not a guarantee for arbitrary app logs."""
    text = re.sub(r'(?im)^.*(?:Environment\s*=|password|secret|token|credential|connectionstrings|private.?key|api.?key|access.?key).*$', '[sensitive line hidden]', text)
    text = re.sub(r'(https?://)[^\s/@]+:[^\s/@]+@', r'\1[hidden]@', text)
    return text

def revision(text):
    return hashlib.sha256(text.encode()).hexdigest()

class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / 'state.db'
        self.db = sqlite3.connect(str(self.path), timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS namespaces (slug TEXT PRIMARY KEY, description TEXT NOT NULL, environment TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS registrations (id TEXT PRIMARY KEY, namespace TEXT NOT NULL REFERENCES namespaces(slug), runtime TEXT NOT NULL, native TEXT NOT NULL, label TEXT NOT NULL, lifecycle INTEGER NOT NULL DEFAULT 0, config INTEGER NOT NULL DEFAULT 0, UNIQUE(runtime,native));
        CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY, at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, actor TEXT NOT NULL, operation TEXT NOT NULL, target TEXT NOT NULL, outcome TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tickets (token TEXT PRIMARY KEY, registration TEXT NOT NULL, actor TEXT NOT NULL, expires REAL NOT NULL, revision TEXT NOT NULL, content TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS requests (token TEXT PRIMARY KEY, actor TEXT NOT NULL, operation TEXT NOT NULL, at REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS creation_tickets (token TEXT PRIMARY KEY, actor TEXT NOT NULL, expires REAL NOT NULL, spec TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS managed_workloads (registration TEXT PRIMARY KEY REFERENCES registrations(id) ON DELETE CASCADE, path TEXT NOT NULL, spec TEXT NOT NULL, status TEXT NOT NULL);
        PRAGMA user_version=2;
        ''')
        self.db.commit()
        self.path.chmod(0o600)

    def close(self):
        self.db.close()

    def namespaces(self):
        return [dict(x) for x in self.db.execute("SELECT * FROM namespaces ORDER BY CASE WHEN slug='extra' THEN 1 ELSE 0 END, slug")]

    def registrations(self):
        return [dict(x) for x in self.db.execute('SELECT * FROM registrations ORDER BY label')]

    def get(self, key):
        row = self.db.execute('SELECT * FROM registrations WHERE id=?', (key,)).fetchone()
        if not row:
            raise AppError('Registered workload not found')
        return dict(row)

    def audit(self, actor, operation, target, outcome):
        self.db.execute('INSERT INTO audit(actor,operation,target,outcome) VALUES (?,?,?,?)',
                        (actor, operation, target, outcome))
        self.db.commit()

    @contextlib.contextmanager
    def lock(self, key):
        # Advisory locks coordinate all aaPanel worker processes; Linux target only.
        import fcntl
        lockfile = self.root / (hashlib.sha256(key.encode()).hexdigest() + '.lock')
        with open(lockfile, 'a', encoding='utf-8') as stream:
            os.chmod(lockfile, 0o600)
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise AppError('Another operation is already running for this workload') from exc
            try:
                yield
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

class Systemd:
    def __init__(self, runner=run):
        self.run = runner
        self._properties = {}
        self._sockets = None

    PROPERTIES = 'Id,LoadState,ActiveState,SubState,UnitFileState,FragmentPath,DropInPaths,MainPID,ControlGroup,MemoryCurrent,CPUUsageNSec,NRestarts,ActiveEnterTimestampMonotonic,User,WorkingDirectory'

    def prime(self, names):
        names = [valid_unit(n) for n in names if n not in self._properties and not n.endswith('@.service')]
        for start in range(0, len(names), 100):
            group = names[start:start + 100]
            try:
                raw = self.run(['systemctl', 'show', *group, '--property=' + self.PROPERTIES, '--no-pager'])
                for block in re.split(r'\n\s*\n', raw.strip()):
                    data = dict(line.split('=', 1) for line in block.splitlines() if '=' in line)
                    if data.get('Id') in group:
                        self._properties[data['Id']] = data
            except AppError:
                pass  # Fall back to isolated inspection for failed batches.

    def discover(self):
        names = set()
        for args in (['list-units', '--all', '--type=service', '--no-legend', '--plain'],
                     ['list-unit-files', '--type=service', '--no-legend', '--no-pager']):
            for line in self.run(['systemctl'] + args).splitlines():
                parts = line.split()
                if parts and parts[0].endswith('.service'):
                    try:
                        names.add(valid_unit(parts[0]))
                    except AppError:
                        pass
        # Avoid collecting sockets/cgroups for every OS unit during discovery.
        self.prime(sorted(names))
        items = []
        for name in sorted(names):
            if name.endswith('@.service'):
                continue  # A template is not a runnable instance.
            try:
                items.append(self.inspect(name, listeners=False))
            except AppError:
                continue  # One unsupported/transient unit must not hide every app.
        return items

    def inspect(self, native, listeners=True):
        native = valid_unit(native)
        data = self._properties.get(native)
        if data is None:
            raw = self.run(['systemctl', 'show', native, '--property=' + self.PROPERTIES, '--no-pager'])
            data = dict(line.split('=', 1) for line in raw.splitlines() if '=' in line)
        state = {'active': 'Running', 'inactive': 'Stopped', 'failed': 'Failed', 'activating': 'Starting', 'deactivating': 'Stopping', 'reloading': 'Reloading'}.get(data.get('ActiveState'), 'Unknown')
        if data.get('LoadState') == 'not-found':
            state = 'Unavailable'
        pid = int(data.get('MainPID') or 0)
        endpoints = []
        if pid and listeners:
            try:
                # Include descendant cgroup processes where proc/cgroup information is available.
                cgroup = data.get('ControlGroup', '')
                pids = {str(pid)}
                if cgroup.startswith('/') and '..' not in Path(cgroup).parts:
                    root = Path('/sys/fs/cgroup') / cgroup.lstrip('/')
                    if root.is_dir():
                        for file in list(root.rglob('cgroup.procs'))[:100]:
                            pids.update(file.read_text().split())
                if self._sockets is None:
                    self._sockets = self.run(['ss', '-H', '-lntp'])
                sockets = self._sockets
                for line in sockets.splitlines():
                    if not any(re.search(r'pid=' + re.escape(p) + r'[,)]', line) for p in pids):
                        continue
                    parts = line.split()
                    host, port = parts[3].rsplit(':', 1)
                    endpoints.append({'host': host.strip('[]'), 'port': int(port), 'protocol': 'tcp'})
            except (AppError, OSError, ValueError, IndexError):
                pass
        mem = data.get('MemoryCurrent', '')
        uptime = None
        if state == 'Running':
            try:
                uptime = max(0, int(float(Path('/proc/uptime').read_text().split()[0]) - int(data['ActiveEnterTimestampMonotonic']) / 1000000))
            except (OSError, ValueError, KeyError):
                pass
        return {'native': native, 'name': native.removesuffix('.service'), 'runtime': 'systemd', 'source': native,
                'state': state, 'native_state': data.get('SubState'), 'health': None, 'endpoints': endpoints,
                'memory': int(mem) if mem.isdigit() and int(mem) < 2**63 else None, 'cpu': None,
                'uptime': uptime, 'restarts': int(data.get('NRestarts') or 0), 'details': data,
                'instances': [], 'config_supported': bool(data.get('FragmentPath', '').startswith('/etc/systemd/system/'))}

    def action(self, native, operation):
        if operation not in ('start', 'stop', 'restart'):
            raise AppError('Unsupported operation')
        self.run(['systemctl', operation, valid_unit(native)], timeout=60)
        self._properties.pop(native, None)
        self._sockets = None
        return self.inspect(native)

    def logs(self, native, lines=100):
        return self.run(['journalctl', '--unit=' + valid_unit(native), '-n', str(min(500, max(1, int(lines)))), '--no-pager', '-o', 'short-iso'], timeout=15)

    def environment(self, native):
        raw = self.run(['systemctl', 'show', valid_unit(native), '--property=Environment', '--value'])
        try:
            return dict(x.split('=', 1) for x in shlex.split(raw) if '=' in x)
        except ValueError:
            raise AppError('Environment contains syntax not supported by this viewer')

class Docker:
    def __init__(self, runner=run):
        self.run = runner
        self._snapshot = None

    def _inspect_ids(self, ids):
        return json.loads(self.run(['docker', 'inspect', '--type=container'] + [valid_container(x) for x in ids])) if ids else []

    def discover(self):
        if self._snapshot is not None:
            return self._snapshot
        ids = self.run(['docker', 'ps', '-aq', '--no-trunc']).split()
        containers = []
        for start in range(0, len(ids), 50):
            containers.extend(self._inspect_ids(ids[start:start + 50]))
        groups = {}
        for c in containers:
            labels = c.get('Config', {}).get('Labels') or {}
            project, service = labels.get('com.docker.compose.project'), labels.get('com.docker.compose.service')
            # Group replicas using stable Compose labels; standalone name survives replacement.
            native = 'compose:' + project + '/' + service if project and service else 'container:' + c['Name'].lstrip('/')
            groups.setdefault(native, []).append(c)
        self._snapshot = [self._dto(native, members) for native, members in sorted(groups.items())]
        return self._snapshot

    def inspect(self, native):
        matches = [x for x in self.discover() if x['native'] == native]
        if not matches:
            raise AppError('Docker workload is unavailable or its identity changed')
        return matches[0]

    def _dto(self, native, members):
        c = members[0]
        instances, endpoints = [], []
        for item in members:
            state = item.get('State', {})
            status = state.get('Status', 'unknown')
            mapped = {'running': 'Running', 'exited': 'Stopped', 'created': 'Stopped', 'dead': 'Failed', 'restarting': 'Restarting', 'paused': 'Paused'}.get(status, 'Unknown')
            if status == 'exited' and state.get('ExitCode', 0):
                mapped = 'Failed'
            instances.append({'id': item['Id'], 'name': item['Name'].lstrip('/'), 'state': mapped, 'health': (state.get('Health') or {}).get('Status')})
            for internal, bindings in (item.get('NetworkSettings', {}).get('Ports') or {}).items():
                inside, protocol = internal.split('/')
                for binding in bindings or []:
                    endpoints.append({'host': binding['HostIp'], 'port': int(binding['HostPort']), 'container_port': int(inside), 'protocol': protocol})
        states = {x['state'] for x in instances}
        state = next(iter(states)) if len(states) == 1 else 'Mixed'
        labels = c.get('Config', {}).get('Labels') or {}
        uptimes = []
        for member in members:
            status = member.get('State', {})
            if status.get('Status') != 'running':
                continue
            try:
                started = datetime.datetime.fromisoformat(status['StartedAt'].replace('Z', '+00:00'))
                uptimes.append(max(0, int(time.time() - started.timestamp())))
            except (KeyError, ValueError, OverflowError):
                pass
        # Do not return inspect's full Config.Env to the listing.
        return {'native': native, 'name': native.split(':', 1)[1], 'runtime': 'docker', 'source': c['Config']['Image'],
                'state': state, 'health': [x['health'] for x in instances], 'endpoints': endpoints,
                'instances': instances, 'cpu': None, 'memory': None, 'uptime': min(uptimes) if uptimes else None,
                'details': {'project': labels.get('com.docker.compose.project'), 'service': labels.get('com.docker.compose.service'),
                            'restart_policy': c.get('HostConfig', {}).get('RestartPolicy', {}).get('Name')},
                'config_supported': False}

    def action(self, native, operation):
        if operation not in ('start', 'stop', 'restart'):
            raise AppError('Unsupported operation')
        workload = self.inspect(native)
        results = []
        for instance in workload['instances']:
            try:
                self.run(['docker', operation, valid_container(instance['id'])], timeout=60)
                results.append({'instance': instance['name'], 'ok': True})
            except AppError as exc:
                results.append({'instance': instance['name'], 'ok': False, 'error': str(exc)})
        self._snapshot = None
        return {'instances': results, 'workload': self.inspect(native), 'ok': all(x['ok'] for x in results)}

    def logs(self, native, lines=100, instance=None):
        workload = self.inspect(native)
        allowed = [x['id'] for x in workload['instances']]
        instance = instance or allowed[0]
        if instance not in allowed:
            raise AppError('Instance does not belong to the registered workload')
        # Docker writes container stderr to CLI stderr; collect both, preserving a bounded tail.
        try:
            p = subprocess.run(['docker', 'logs', '--tail', str(min(500, max(1, int(lines)))), '--timestamps', instance],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=15, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise AppError('Container logs unavailable') from exc
        if p.returncode:
            raise AppError('Container logs unavailable')
        return p.stdout[-512000:].decode('utf-8', 'replace')

    def environment(self, native):
        workload = self.inspect(native)
        containers = self._inspect_ids([x['id'] for x in workload['instances']])
        return {item['Name'].lstrip('/'): dict(x.split('=', 1) for x in item['Config'].get('Env', []) if '=' in x) for item in containers}

def nginx_tokens(text):
    # Preserve quoted strings while ignoring comments; unsupported dynamic targets remain unresolved.
    pattern = r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|\#[^\n]*|[{};]|[^\s{};#]+'''
    return [x[1:-1] if x[:1] in ('"', "'") else x for x in re.findall(pattern, text) if not x.startswith('#')]

def nginx_tree(text):
    tokens, pos = nginx_tokens(text), 0
    def block(nested=False):
        nonlocal pos
        result, words = [], []
        while pos < len(tokens):
            token = tokens[pos]
            pos += 1
            if token == '}':
                if not nested:
                    raise AppError('Unbalanced Nginx block')
                return result
            if token == '{':
                result.append((words, block(True)))
                words = []
            elif token == ';':
                if words:
                    result.append((words, None))
                words = []
            else:
                words.append(token)
        if nested:
            raise AppError('Unclosed Nginx block')
        return result
    return block()

class ProxyIndex:
    def __init__(self, root='/www/server/panel/vhost/nginx', local_ips=None):
        self.root = Path(root)
        self.local_ips = set(local_ips or ['127.0.0.1', '::1']) | {'127.0.0.1', '::1'}
        if local_ips is None:
            try:
                for iface in json.loads(run(['ip', '-j', 'address', 'show'])):
                    self.local_ips.update(a['local'] for a in iface.get('addr_info', []))
            except (AppError, ValueError, KeyError):
                pass

    def local(self, host):
        if host.lower() == 'localhost':
            return True
        try:
            return ipaddress.ip_address(host).is_loopback or host in self.local_ips
        except ValueError:
            return False  # Unresolved DNS is not silently treated as local.

    def read(self):
        routes, warnings = [], []
        if not self.root.is_dir():
            return [], ['aaPanel Nginx configuration directory unavailable']
        for file in sorted(self.root.glob('*.conf')):
            if file.is_symlink():
                continue
            try:
                tree = nginx_tree(file.read_text(errors='replace'))
                upstreams = {}
                for words, children in tree:
                    if words[:1] == ['upstream'] and len(words) > 1:
                        upstreams[words[1]] = [w[1] for w, c in children if w[:1] == ['server'] and len(w) > 1]
                for words, children in tree:
                    if words[:1] != ['server'] or children is None:
                        continue
                    domains = [d for w, c in children if w[:1] == ['server_name'] for d in w[1:]]
                    def walk(nodes, location='/'):
                        for w, child in nodes:
                            if not w:
                                continue
                            if w[0] == 'include':
                                warnings.append(file.name + ': included configuration not resolved; mappings may be incomplete')
                            if child is not None:
                                walk(child, ' '.join(w[1:]) if w[0] == 'location' else location)
                            elif w[0] == 'proxy_pass' and len(w) > 1:
                                target = w[1]
                                match = re.match(r'^(https?)://(\[[^]]+\]|[^/:]+)(?::(\d+))?(/.*)?$', target)
                                route = {'project': file.stem, 'domains': domains, 'location': location, 'target': target,
                                         'file': str(file), 'origin': 'nginx-config', 'confidence': 'unresolved', 'targets': []}
                                if match and '$' not in target:
                                    scheme, host, port, _ = match.groups()
                                    host = host.strip('[]')
                                    candidates = upstreams.get(host, [host + ':' + (port or ('443' if scheme == 'https' else '80'))])
                                    for candidate in candidates:
                                        try:
                                            h, p = candidate.rsplit(':', 1)
                                            h = h.strip('[]')
                                            route['targets'].append({'host': h, 'port': int(p), 'local': self.local(h)})
                                        except (ValueError, TypeError):
                                            pass
                                    route['confidence'] = 'parsed' if route['targets'] else 'unresolved'
                                routes.append(route)
                    walk(children)
            except (OSError, AppError):
                warnings.append(file.name + ': could not parse configuration')
        return routes, sorted(set(warnings))

    def match(self, endpoints, routes):
        matches = []
        for route in routes:
            for target in route['targets']:
                if not target['local']:
                    continue
                if any(e['protocol'] == 'tcp' and e['port'] == target['port'] and
                       (e['host'] in ('*', '', '0.0.0.0', '::') or e['host'] == target['host'] or
                        (target['host'] == 'localhost' and e['host'] in ('127.0.0.1', '::1'))) for e in endpoints):
                    matches.append({k: v for k, v in route.items() if k != 'targets'} | {'confidence': 'inferred-local-port'})
                    break
        return matches

class Configuration:
    """Admin-only, registered local systemd unit editing. Docker source adoption is explicit future work."""
    def __init__(self, store, adapter, roots=None):
        self.store, self.adapter = store, adapter
        self.roots = [Path(x).resolve() for x in (roots or ['/etc/systemd/system'])]

    def path(self, reg):
        if reg['runtime'] != 'systemd' or not reg['config']:
            raise AppError('Configuration editing is not enabled for this registered systemd unit')
        dto = self.adapter.inspect(reg['native'])
        path = Path(dto['details'].get('FragmentPath') or '')
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise AppError('Only regular local service files may be edited')
        resolved = path.resolve()
        if path != resolved or not any(resolved.is_relative_to(root) for root in self.roots):
            raise AppError('Service file is outside allowed roots or traverses a symlink')
        if resolved.name != valid_unit(reg['native']):
            raise AppError('Service fragment identity does not match registration')
        if resolved.stat().st_size > 256000:
            raise AppError('Service file exceeds editor limit')
        return resolved

    def read(self, reg, reveal=False):
        path = self.path(reg)
        content = path.read_text()
        dto = self.adapter.inspect(reg['native'])
        return {'path': str(path), 'content': content if reveal else redact(content), 'revision': revision(content),
                'editable': reveal, 'dropins': dto['details'].get('DropInPaths', ''),
                'note': 'Editing this fragment does not overwrite drop-ins or referenced environment files.'}

    def preview(self, reg, content, expected, actor):
        path = self.path(reg)
        original = path.read_text()
        if revision(original) != expected:
            raise AppError('Configuration changed externally. Reload before editing.')
        if not content or len(content.encode()) > 256000 or '\x00' in content:
            raise AppError('Invalid configuration size or content')
        with tempfile.TemporaryDirectory(prefix='app-spaces-') as folder:
            os.chmod(folder, 0o700)
            temp = Path(folder) / path.name
            temp.write_text(content)
            temp.chmod(0o600)
            self.adapter.run(['systemd-analyze', 'verify', str(temp)], timeout=25)
        if not reg['lifecycle']:
            raise AppError('Enable lifecycle control before previewing a restart-based configuration change')
        token = secrets.token_urlsafe(32)
        self.store.db.execute('DELETE FROM tickets WHERE expires<?', (time.time(),))
        self.store.db.execute('INSERT INTO tickets VALUES (?,?,?,?,?,?)', (token, reg['id'], actor, time.time() + 300, expected, content))
        self.store.db.commit()
        diff = '\n'.join(difflib.unified_diff(redact(original).splitlines(), redact(content).splitlines(), fromfile='current', tofile='proposed', lineterm=''))
        return {'token': token, 'diff': diff or 'Only hidden values changed, or no visible changes.', 'expires_in': 300,
                'notice': 'Secrets and Environment lines are hidden in this diff. Applying restarts this service.'}

    def apply(self, reg, token, actor):
        with self.store.lock(reg['id']):
            ticket = self.store.db.execute('SELECT * FROM tickets WHERE token=? AND registration=? AND actor=?', (token, reg['id'], actor)).fetchone()
            if not ticket or ticket['expires'] < time.time():
                raise AppError('Preview expired, already consumed, or belongs to another session')
            path = self.path(reg)
            original = path.read_text()
            if revision(original) != ticket['revision']:
                raise AppError('Configuration changed since preview. Reload and preview again.')
            self.store.db.execute('DELETE FROM tickets WHERE token=?', (token,))
            self.store.db.commit()
            backup = self.store.root / ('backup-' + reg['id'] + '-' + str(time.time_ns()) + '.service')
            backup.write_text(original)
            backup.chmod(0o600)
            stat = path.stat()
            def write(content):
                fd, temporary = tempfile.mkstemp(prefix='.app-spaces-', dir=str(path.parent))
                try:
                    with os.fdopen(fd, 'w') as stream:
                        stream.write(content)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.chmod(temporary, stat.st_mode & 0o777)
                    os.chown(temporary, stat.st_uid, stat.st_gid)
                    os.replace(temporary, path)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
            try:
                write(ticket['content'])
                self.adapter.run(['systemctl', 'daemon-reload'])
                dto = self.adapter.action(reg['native'], 'restart')
                if dto['state'] not in ('Running', 'Starting'):
                    raise AppError('Service did not start after applying configuration')
            except Exception as exc:
                write(original)
                self.adapter.run(['systemctl', 'daemon-reload'])
                try:
                    self.adapter.action(reg['native'], 'restart')
                except AppError:
                    raise AppError('Apply failed; original file restored but service recovery failed. Check systemd logs.') from exc
                raise AppError('Apply failed; original configuration restored and restart attempted. Check service state.') from exc
            return {'backup': str(backup), 'state': dto['state'], 'note': 'Process state verified; application readiness was not tested.'}

class Application:
    def __init__(self, store, systemd=None, docker=None, proxies=None):
        self.store = store
        self.adapters = {'systemd': systemd or Systemd(), 'docker': docker or Docker()}
        self.proxies = proxies or ProxyIndex()

    def inventory(self, discover=False, include_unassigned=False):
        warnings, items = [], []
        routes, proxy_warnings = self.proxies.read()
        warnings.extend(proxy_warnings)
        regs = self.store.registrations()
        if not discover and hasattr(self.adapters['systemd'], 'prime'):
            self.adapters['systemd'].prime([r['native'] for r in regs if r['runtime'] == 'systemd'])
        if discover:
            for runtime, adapter in self.adapters.items():
                try:
                    cache = self.store.root / ('discovery-' + runtime + '.json')
                    try:
                        if time.time() - cache.stat().st_mtime > 30:
                            raise ValueError('Expired cache')
                        discovered = json.loads(cache.read_text(encoding='utf-8'))
                    except (OSError, ValueError):
                        discovered = adapter.discover()
                        cache.write_text(json.dumps(discovered), encoding='utf-8')
                        cache.chmod(0o600)
                    for item in discovered:
                        if not any(r['runtime'] == runtime and r['native'] == item['native'] for r in regs):
                            items.append(item)
                except AppError as exc:
                    warnings.append(runtime + ': ' + str(exc))
        else:
            # Resolve Docker inventory once per refresh, not once per registration.
            docker = {}
            docker_error = None
            if any(r['runtime'] == 'docker' for r in regs):
                try:
                    docker = {x['native']: x for x in self.adapters['docker'].discover()}
                except AppError as exc:
                    docker_error = str(exc)
            for reg in regs:
                managed = self.store.db.execute('SELECT * FROM managed_workloads WHERE registration=?', (reg['id'],)).fetchone()
                try:
                    item = self.adapters['systemd'].inspect(reg['native']) if reg['runtime'] == 'systemd' else docker.get(reg['native'])
                    if not item:
                        raise AppError(docker_error or 'Docker workload unavailable')
                except AppError as exc:
                    item = {'native': reg['native'], 'source': reg['native'], 'runtime': reg['runtime'], 'state': 'Unavailable', 'endpoints': [], 'memory': None, 'cpu': None, 'uptime': None, 'error': str(exc), 'instances': [], 'config_supported': False}
                    if managed and reg['runtime'] == 'docker' and not docker_error:
                        item.update(state='Defined', error='Compose definition exists; start this workload to create its containers.')
                item = {**item, 'id': reg['id'], 'namespace': reg['namespace'], 'name': reg['label'],
                        'managed': bool(managed), 'definition': managed['path'] if managed else None,
                        'capabilities': {'lifecycle': bool(reg['lifecycle']), 'config': bool(reg['config']) and item.get('config_supported', False)}}
                items.append(item)
        for item in items:
            item['proxies'] = self.proxies.match(item.get('endpoints', []), routes)
        if include_unassigned and not discover:
            unassigned = self.inventory(discover=True)
            warnings.extend(unassigned['warnings'])
            for item in unassigned['services']:
                application = item['runtime'] == 'docker' or item['native'].startswith(('web-', 'appspaces-', 'zewar-')) or item.get('details', {}).get('WorkingDirectory', '').startswith(('/home/', '/srv/', '/opt/', '/www/', '/var/www/'))
                if not application:
                    continue
                if item['runtime'] == 'systemd':
                    try:
                        item = self.adapters['systemd'].inspect(item['native'])
                    except AppError:
                        continue
                item.update(id='unassigned-' + hashlib.sha256((item['runtime'] + ':' + item['native']).encode()).hexdigest()[:20], namespace='extra', unregistered=True, capabilities={'lifecycle':False,'config':False})
                item['proxies'] = self.proxies.match(item.get('endpoints', []), routes)
                items.append(item)
        # Same port may belong to multiple listeners/replicas. Do not claim an exact identity.
        for item in items:
            for proxy in item['proxies']:
                if sum(any(p['file'] == proxy['file'] and p['location'] == proxy['location'] for p in other['proxies']) for other in items) > 1:
                    proxy['confidence'] = 'ambiguous'
        namespaces = self.store.namespaces()
        if any(x.get('unregistered') for x in items) and not any(n['slug']=='extra' for n in namespaces):
            namespaces.append({'slug':'extra','description':'Other workloads · click to register under an app namespace','environment':'Read-only','virtual':True})
        return {'namespaces': namespaces, 'services': items, 'warnings': sorted(set(warnings)), 'at': datetime.datetime.now(datetime.timezone.utc).isoformat()}

    def namespace(self, payload):
        op, slug = payload.get('operation'), namespace_id(payload.get('slug', ''))
        if op == 'create':
            self.store.db.execute('INSERT INTO namespaces VALUES (?,?,?)', (slug, str(payload.get('description', ''))[:200], str(payload.get('environment', ''))[:40]))
        elif op == 'delete':
            if self.store.db.execute('SELECT 1 FROM registrations WHERE namespace=?', (slug,)).fetchone():
                raise AppError('Move or unregister workloads before deleting this namespace')
            self.store.db.execute('DELETE FROM namespaces WHERE slug=?', (slug,))
        else:
            raise AppError('Unsupported namespace operation')
        self.store.db.commit()
        return self.store.namespaces()

    def register(self, payload):
        runtime = payload.get('runtime')
        if runtime not in self.adapters:
            raise AppError('Unsupported runtime')
        native = str(payload.get('native', ''))
        item = self.adapters[runtime].inspect(native)
        slug = namespace_id(payload.get('namespace', ''))
        if not any(n['slug'] == slug for n in self.store.namespaces()):
            raise AppError('Namespace does not exist')
        label = str(payload.get('label') or item['name'])[:120]
        lifecycle, config = bool(payload.get('lifecycle')), bool(payload.get('config'))
        if config and (runtime != 'systemd' or not item.get('config_supported')):
            raise AppError('Only local systemd configuration is editable in this release')
        key = secrets.token_hex(12)
        self.store.db.execute('INSERT INTO registrations VALUES (?,?,?,?,?,?,?)', (key, slug, runtime, native, label, int(lifecycle), int(config)))
        self.store.db.commit()
        return self.store.get(key)

    def action(self, key, operation):
        reg = self.store.get(key)
        if not reg['lifecycle']:
            raise AppError('Lifecycle control was not enabled when registering this workload')
        with self.store.lock(key):
            managed = self.store.db.execute('SELECT 1 FROM managed_workloads WHERE registration=?', (key,)).fetchone()
            if managed and reg['runtime'] == 'docker':
                from .creation import Creator
                return Creator(self.store).lifecycle(reg, operation)
            return self.adapters[reg['runtime']].action(reg['native'], operation)
