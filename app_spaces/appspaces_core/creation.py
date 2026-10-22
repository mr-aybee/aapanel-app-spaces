"""Preview-first creation of local systemd units and plugin-owned Compose projects."""
import hashlib
import ipaddress
import json
import os
from pathlib import Path, PurePosixPath
import re
import secrets
import tempfile
import time

from .core import AppError, namespace_id, run

def string(value, label, maximum=4096):
    if not isinstance(value, str) or len(value) > maximum or any(c in value for c in '\x00\r\n'):
        raise AppError('Invalid ' + label)
    return value

def absolute(value, label):
    value = string(value, label)
    path = PurePosixPath(value)
    if not path.is_absolute() or '..' in path.parts or value.startswith('//'):
        raise AppError(label + ' must be an absolute Linux path without ..')
    return value

def argv(value, label):
    if not isinstance(value, list) or len(value) > 100:
        raise AppError(label + ' must be a JSON array of up to 100 arguments')
    return [string(x, label) for x in value]

def environment(value):
    if not isinstance(value, dict) or len(value) > 200:
        raise AppError('Environment must contain at most 200 name/value pairs')
    result = {}
    for key, item in value.items():
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,199}', key):
            raise AppError('Invalid environment variable name')
        result[key] = string(item, 'environment value', 16000)
    return result

def number(value, label, low, high):
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise AppError('Invalid ' + label) from exc
    if not low <= value <= high:
        raise AppError(label + ' is outside its allowed range')
    return value

def memory(value):
    value = string(value, 'memory limit', 30)
    if value and not re.fullmatch(r'[1-9][0-9]{0,8}[KMGTP]?', value):
        raise AppError('Memory limit must look like 512M or 2G')
    return value

def integer(value, label, low, high):
    value = number(value, label, low, high)
    if not value.is_integer():
        raise AppError(label + ' must be an integer')
    return int(value)

def unit_quote(value):
    # systemd C-style quoting; prevent specifier expansion. ExecStart uses : to disable $ expansion.
    return json.dumps(value.replace('%', '%%'), ensure_ascii=False)

def yaml_dump(value, depth=0):
    """Generate the limited Compose document we own, without a YAML dependency."""
    indent = '  ' * depth
    if isinstance(value, dict):
        lines = []
        for key, child in value.items():
            key = key if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]*', key) else json.dumps(key)
            if isinstance(child, (dict, list)) and child:
                lines.append(indent + key + ':\n' + yaml_dump(child, depth + 1))
            else:
                lines.append(indent + key + ': ' + json.dumps(child, ensure_ascii=False))
        return '\n'.join(lines)
    if isinstance(value, list):
        return '\n'.join(indent + '-\n' + yaml_dump(x, depth + 1) if isinstance(x, (dict, list)) else indent + '- ' + json.dumps(x, ensure_ascii=False) for x in value)
    raise AppError('Unsupported generated YAML value')

def compose_literal(value):
    if isinstance(value, str):
        return value.replace('$', '$$')
    if isinstance(value, list):
        return [compose_literal(x) for x in value]
    if isinstance(value, dict):
        return {k: compose_literal(v) for k, v in value.items()}
    return value

def normalize(spec):
    if not isinstance(spec, dict):
        raise AppError('Expected a service definition')
    ns = namespace_id(spec.get('namespace', ''))
    name = namespace_id(spec.get('name', ''))
    if len(name) > 40:
        raise AppError('Service name must be at most 40 characters')
    runtime = spec.get('runtime')
    if runtime not in ('systemd', 'docker'):
        raise AppError('Choose systemd or Docker')
    result = {'namespace': ns, 'name': name, 'runtime': runtime,
              'description': string(spec.get('description', ''), 'description', 200),
              'environment': environment(spec.get('environment', {}))}
    if runtime == 'systemd':
        user = string(spec.get('user', ''), 'Linux user', 64)
        if not re.fullmatch(r'[a-z_][a-z0-9_-]*\$?', user):
            raise AppError('A valid existing Linux user is required')
        result.update(user=user, working_directory=absolute(spec.get('working_directory', ''), 'Working directory'),
                      executable=absolute(spec.get('executable', ''), 'Executable'), arguments=argv(spec.get('arguments', []), 'Arguments'),
                      restart=spec.get('restart', 'on-failure'), enable_at_boot=spec.get('enable_at_boot') is True,
                      restart_seconds=integer(spec.get('restart_seconds', 5), 'Restart delay', 0, 3600),
                      memory=memory(spec.get('memory', '')))
        if result['restart'] not in ('no', 'always', 'on-failure', 'on-abnormal'):
            raise AppError('Invalid systemd restart policy')
        if spec.get('cpus') not in ('', None):
            result['cpus'] = number(spec['cpus'], 'CPU limit', .01, 256)
        return result
    mode = spec.get('image_mode', 'image')
    if mode not in ('image', 'build'):
        raise AppError('Choose an existing image or a local Dockerfile build')
    image = string(spec.get('image', ''), 'Docker image', 256)
    if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9._/:@-]*', image):
        raise AppError('A valid image name/tag is required (also used to tag local builds)')
    result.update(image=image, image_mode=mode, command=argv(spec.get('command', []), 'Command'),
                  entrypoint=argv(spec.get('entrypoint', []), 'Entrypoint'),
                  working_directory=absolute(spec['working_directory'], 'Container working directory') if spec.get('working_directory') else '',
                  user=string(spec.get('user', ''), 'Container user', 100), restart=spec.get('restart', 'unless-stopped'),
                  memory=memory(spec.get('memory', '')), init=spec.get('init', True) is True,
                  read_only=spec.get('read_only') is True, no_new_privileges=spec.get('no_new_privileges', True) is True,
                  pids_limit=integer(spec.get('pids_limit', 256), 'PID limit', 16, 100000))
    if result['user'] and not re.fullmatch(r'[A-Za-z0-9_-]+(?::[A-Za-z0-9_-]+)?', result['user']):
        raise AppError('Container user must be username or UID[:GID]')
    if result['restart'] not in ('no', 'always', 'on-failure', 'unless-stopped'):
        raise AppError('Invalid Docker restart policy')
    if mode == 'build':
        result['build_context'] = absolute(spec.get('build_context', ''), 'Build context')
        dockerfile = string(spec.get('dockerfile', 'Dockerfile'), 'Dockerfile path', 200)
        if PurePosixPath(dockerfile).is_absolute() or '..' in PurePosixPath(dockerfile).parts or not dockerfile:
            raise AppError('Dockerfile must be relative to its build context')
        result['dockerfile'] = dockerfile
    if spec.get('cpus') not in ('', None):
        result['cpus'] = number(spec['cpus'], 'CPU limit', .01, 256)
    ports = spec.get('ports', [])
    if not isinstance(ports, list) or len(ports) > 30:
        raise AppError('At most 30 published ports are supported')
    result['ports'] = []
    occupied = set()
    for port in ports:
        host = string(port.get('host', '127.0.0.1'), 'Bind address', 100)
        try:
            ipaddress.ip_address(host)
        except ValueError as exc:
            raise AppError('Port bind address must be an IPv4 or IPv6 address') from exc
        published = integer(port.get('published'), 'Host port', 1, 65535)
        target = integer(port.get('target'), 'Container port', 1, 65535)
        protocol = port.get('protocol', 'tcp')
        if protocol not in ('tcp', 'udp'):
            raise AppError('Port protocol must be TCP or UDP')
        key = (host, published, protocol)
        if key in occupied or any(published == p and protocol == proto and (host in ('0.0.0.0','::') or h in ('0.0.0.0','::')) for h,p,proto in occupied):
            raise AppError('Duplicate published port mapping')
        occupied.add(key)
        result['ports'].append({'host': host, 'published': published, 'target': target, 'protocol': protocol})
    mounts = spec.get('mounts', [])
    if not isinstance(mounts, list) or len(mounts) > 30:
        raise AppError('At most 30 mounts are supported')
    result['mounts'] = []
    targets = set()
    for mount in mounts:
        kind = mount.get('type')
        if kind not in ('bind', 'volume'):
            raise AppError('Mount type must be bind or volume')
        source = absolute(mount.get('source', ''), 'Bind source') if kind == 'bind' else namespace_id(mount.get('source', ''))
        target = absolute(mount.get('target', ''), 'Mount target')
        if target in targets:
            raise AppError('Duplicate mount target')
        targets.add(target)
        result['mounts'].append({'type': kind, 'source': source, 'target': target, 'read_only': mount.get('read_only') is True})
    network = string(spec.get('network', ''), 'External network', 100)
    if network and not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', network):
        raise AppError('Invalid external Docker network name')
    result['network'] = network
    result['healthcheck'] = argv(spec.get('healthcheck', []), 'Healthcheck')
    if result['healthcheck'] and result['healthcheck'][0] != 'CMD':
        raise AppError('Healthcheck must use an explicit CMD argv array')
    return result

def identity(spec):
    stem = 'appspaces-' + spec['namespace'] + '-' + spec['name']
    project = stem if len(stem) <= 63 else stem[:48] + '-' + hashlib.sha256(stem.encode()).hexdigest()[:12]
    return stem + '.service' if spec['runtime'] == 'systemd' else 'compose:' + project + '/' + spec['name']

def render(spec):
    if spec['runtime'] == 'systemd':
        result = ['[Unit]', 'Description=' + spec['description'].replace('%', '%%'), 'After=network-online.target', 'Wants=network-online.target', '', '[Service]', 'Type=simple',
                  'User=' + spec['user'], 'WorkingDirectory=' + unit_quote(spec['working_directory']),
                  'ExecStart=:' + ' '.join(unit_quote(x) for x in [spec['executable']] + spec['arguments'])]
        result += ['Environment=' + unit_quote(k + '=' + v) for k, v in spec['environment'].items()]
        result += ['Restart=' + spec['restart'], 'RestartSec=' + str(spec['restart_seconds']), 'KillMode=control-group', 'TimeoutStopSec=30', 'StandardOutput=journal', 'StandardError=journal']
        if spec['memory']:
            result.append('MemoryMax=' + spec['memory'])
        if 'cpus' in spec:
            result.append('CPUQuota=' + str(spec['cpus'] * 100) + '%')
        return '\n'.join(result + ['', '[Install]', 'WantedBy=multi-user.target', ''])
    service = {'image': spec['image'], 'restart': spec['restart'], 'init': spec['init'], 'environment': spec['environment'],
               'pids_limit': spec['pids_limit'], 'read_only': spec['read_only'],
               'logging': {'driver': 'json-file', 'options': {'max-size': '10m', 'max-file': '3'}},
               'labels': {'com.orbyn.app-spaces.managed': 'true', 'com.orbyn.app-spaces.namespace': spec['namespace']}}
    if spec['image_mode'] == 'build':
        service['build'] = {'context': spec['build_context'], 'dockerfile': spec['dockerfile']}
    for key in ('command', 'entrypoint', 'user', 'working_directory'):
        if spec[key]:
            service['working_dir' if key == 'working_directory' else key] = spec[key]
    if spec['no_new_privileges']:
        service['security_opt'] = ['no-new-privileges:true']
    if spec['ports']:
        service['ports'] = [{'target': p['target'], 'published': str(p['published']), 'host_ip': p['host'], 'protocol': p['protocol']} for p in spec['ports']]
    if spec['mounts']:
        service['volumes'] = spec['mounts']
        for mount in service['volumes']:
            if mount['type'] == 'bind':
                mount['bind'] = {'create_host_path': False}
    if spec['memory']:
        service['mem_limit'] = spec['memory']
    if 'cpus' in spec:
        service['cpus'] = spec['cpus']
    if spec['healthcheck']:
        service['healthcheck'] = {'test': spec['healthcheck'], 'interval': '30s', 'timeout': '5s', 'retries': 3, 'start_period': '15s'}
    if spec['read_only']:
        service['tmpfs'] = ['/tmp']
    document = {'services': {spec['name']: service}}
    volumes = {m['source']: {} for m in spec['mounts'] if m['type'] == 'volume'}
    if volumes:
        document['volumes'] = volumes
    if spec['network']:
        document['networks'] = {'app_network': {'external': True, 'name': spec['network']}}
        service['networks'] = ['app_network']
    return '# Managed by App Spaces; no environment interpolation is intended.\n' + yaml_dump(compose_literal(document)) + '\n'

class Creator:
    def __init__(self, store, runner=run, units='/etc/systemd/system', validate_paths=True):
        self.store, self.run = store, runner
        self.units = Path(units)
        self.projects = store.root / 'projects'
        self.validate_paths = validate_paths

    def _namespace(self, spec):
        if not any(n['slug'] == spec['namespace'] for n in self.store.namespaces()):
            raise AppError('Create or select an existing namespace first')

    def _unused(self, spec):
        native = identity(spec)
        if self.store.db.execute('SELECT 1 FROM registrations WHERE runtime=? AND native=?', (spec['runtime'], native)).fetchone():
            raise AppError('This workload identity is already registered')
        if spec['runtime'] == 'systemd':
            target = self.units / native
            if target.exists() or target.is_symlink():
                raise AppError('A service file already exists; nothing will be overwritten')
            if self.run(['systemctl', 'show', native, '--property=LoadState', '--value']).strip() != 'not-found':
                raise AppError('A systemd unit with this identity already exists')
        else:
            project = native.split(':', 1)[1].split('/')[0]
            if (self.projects / project).exists():
                raise AppError('A managed project definition already exists')
            if self.run(['docker', 'ps', '-aq', '--filter', 'label=com.docker.compose.project=' + project]).strip():
                raise AppError('A Docker project with this identity already exists')

    def _paths(self, spec):
        if not self.validate_paths:
            return
        if spec['runtime'] == 'systemd':
            import pwd
            try:
                pwd.getpwnam(spec['user'])
            except KeyError as exc:
                raise AppError('Linux user does not exist') from exc
            if not Path(spec['working_directory']).is_dir():
                raise AppError('Working directory does not exist on the server')
            if not Path(spec['executable']).is_file() or not os.access(spec['executable'], os.X_OK):
                raise AppError('Executable is missing or not executable on the server')
            self.run(['runuser', '-u', spec['user'], '--', 'test', '-x', spec['working_directory']])
            self.run(['runuser', '-u', spec['user'], '--', 'test', '-x', spec['executable']])
        else:
            if spec['image_mode'] == 'build':
                context = Path(spec['build_context'])
                if not context.is_dir() or not (context / spec['dockerfile']).is_file():
                    raise AppError('Build context or Dockerfile does not exist on the server')
            for mount in spec['mounts']:
                if mount['type'] == 'bind' and not Path(mount['source']).exists():
                    raise AppError('Bind source must already exist; missing host paths are not auto-created')
            if spec['network']:
                self.run(['docker', 'network', 'inspect', spec['network']])

    def validate(self, spec, content):
        self._namespace(spec)
        self._unused(spec)
        self._paths(spec)
        if spec['runtime'] == 'docker':
            for protocol in {p['protocol'] for p in spec['ports']}:
                listeners = self.run(['ss', '-H', '-lnt' if protocol == 'tcp' else '-lnu'])
                for line in listeners.splitlines():
                    columns = line.split()
                    if len(columns) < 4 or ':' not in columns[3]:
                        continue
                    address, port = columns[3].rsplit(':', 1)
                    address = address.strip('[]')
                    for mapping in spec['ports']:
                        wildcard = address in ('*', '0.0.0.0', '::') or mapping['host'] in ('0.0.0.0', '::')
                        if mapping['protocol'] == protocol and str(mapping['published']) == port and (wildcard or mapping['host'] == address):
                            raise AppError('A requested host port is already listening; choose a different port')
        with tempfile.TemporaryDirectory(prefix='app-spaces-create-') as folder:
            os.chmod(folder, 0o700)
            path = Path(folder) / (identity(spec) if spec['runtime'] == 'systemd' else 'compose.yaml')
            path.write_text(content, encoding='utf-8')
            path.chmod(0o600)
            if spec['runtime'] == 'systemd':
                self.run(['systemd-analyze', 'verify', str(path)])
            else:
                project = identity(spec).split(':', 1)[1].split('/')[0]
                self.run(['docker', 'compose', '--project-name', project, '-f', str(path), 'config', '--quiet'])

    def preview(self, raw, actor):
        spec = normalize(raw)
        if len(json.dumps(spec).encode('utf-8')) > 256000:
            raise AppError('Service definition exceeds 256 KB')
        content = render(spec)
        self.validate(spec, content)
        token = secrets.token_urlsafe(32)
        self.store.db.execute('DELETE FROM creation_tickets WHERE expires<?', (time.time(),))
        self.store.db.execute('INSERT INTO creation_tickets VALUES (?,?,?,?)', (token, actor, time.time() + 300, json.dumps(spec)))
        self.store.db.commit()
        visible = json.loads(json.dumps(spec))
        visible['environment'] = {key: '[hidden]' for key in spec['environment']}
        return {'token': token, 'content': render(visible), 'identity': identity(spec), 'expires_in': 300,
                'note': 'Environment values are hidden in this generated preview. Creation revalidates identity and server paths. Nothing has been started.'}

    def create(self, token, actor, start=False):
        row = self.store.db.execute('SELECT * FROM creation_tickets WHERE token=? AND actor=?', (token, actor)).fetchone()
        if not row or row['expires'] < time.time():
            raise AppError('Creation preview expired, consumed, or belongs to another session')
        spec = json.loads(row['spec'])
        native = identity(spec)
        with self.store.lock('create:' + native):
            row = self.store.db.execute('SELECT * FROM creation_tickets WHERE token=? AND actor=?', (token, actor)).fetchone()
            if not row or row['expires'] < time.time():
                raise AppError('Creation preview is no longer valid')
            content = render(spec)
            self.validate(spec, content)
            self.store.db.execute('DELETE FROM creation_tickets WHERE token=?', (token,))
            self.store.db.commit()
            if spec['runtime'] == 'systemd':
                path = self.units / native
            else:
                project = native.split(':', 1)[1].split('/')[0]
                self.projects.mkdir(exist_ok=True, mode=0o700)
                if self.projects.resolve() != self.projects:
                    raise AppError('Managed projects directory traverses a symlink')
                project_root = self.projects / project
                project_root.mkdir(mode=0o700)  # exclusive project ownership
                path = project_root / 'compose.yaml'
            if path.parent.resolve() != path.parent or path.is_symlink():
                raise AppError('Creation path traverses a symlink')
            fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as stream:
                stream.write(content)
                stream.flush()
                os.fsync(stream.fileno())
            key = secrets.token_hex(12)
            try:
                self.store.db.execute('INSERT INTO registrations VALUES (?,?,?,?,?,?,?)', (key, spec['namespace'], spec['runtime'], native, spec['name'], 1, int(spec['runtime'] == 'systemd')))
                self.store.db.execute('INSERT INTO managed_workloads VALUES (?,?,?,?)', (key, str(path), json.dumps({'runtime':spec['runtime'],'image_mode':spec.get('image_mode')}), 'defined'))
                self.store.db.commit()
            except Exception:
                self.store.db.rollback()
                path.unlink()  # only the exclusively created file; no containers or volumes exist yet
                raise
            result = {'id':key, 'created':True, 'started':False, 'path':str(path), 'identity':native, 'state':'Defined'}
            try:
                if spec['runtime'] == 'systemd':
                    self.run(['systemctl', 'daemon-reload'])
                    if spec['enable_at_boot']:
                        self.run(['systemctl', 'enable', native])
                    result['state'] = 'Stopped'
                if start:
                    self.lifecycle(self.store.get(key), 'start')
                    result.update(started=True, state='Starting')
            except AppError as exc:
                result.update(state='Needs attention', error=str(exc))
            # Retain failed definitions for inspection/retry; never delete volumes as failure cleanup.
            self.store.db.execute('UPDATE managed_workloads SET status=? WHERE registration=?', (result['state'],key))
            self.store.db.commit()
            return result

    def managed(self, key):
        row = self.store.db.execute('SELECT * FROM managed_workloads WHERE registration=?', (key,)).fetchone()
        return dict(row) if row else None

    def lifecycle(self, reg, operation):
        if operation not in ('start', 'stop', 'restart'):
            raise AppError('Unsupported operation')
        record = self.managed(reg['id'])
        if not record or reg['runtime'] != 'docker':
            self.run(['systemctl', operation, reg['native']], timeout=60)
            return {'ok':True}
        path = Path(record['path'])
        if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(self.projects.resolve()):
            raise AppError('Managed Compose source is missing or outside the project directory')
        project = reg['native'].split(':', 1)[1].split('/')[0]
        service = reg['native'].split('/', 1)[1]
        command = ['docker','compose','--project-name',project,'-f',str(path)]
        if operation == 'start':
            command += ['up','-d']
            if json.loads(record['spec']).get('image_mode') == 'build':
                command += ['--build']
            command += [service]
        else:
            command += [operation, service]
        self.run(command, timeout=600 if operation == 'start' else 90)
        return {'ok':True,'note':'Compose command completed; check state and health in inventory.'}
