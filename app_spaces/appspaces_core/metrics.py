"""On-demand cgroup sampling; no agent, sleeping subprocess, or proxy discovery."""
import hashlib
import json
import os
from pathlib import Path
import time

from .core import AppError, run, valid_unit

class Metrics:
    def __init__(self, store, runner=run, cgroups='/sys/fs/cgroup', proc='/proc', clock=time.monotonic):
        self.store, self.run = store, runner
        self.cgroups, self.proc, self.clock = Path(cgroups), Path(proc), clock

    def counters(self, group):
        # Resolve before reading: never let a kernel/fixture path escape the cgroup root.
        base = (self.cgroups / group.lstrip('/')).resolve()
        if not group or not base.is_relative_to(self.cgroups.resolve()):
            raise ValueError('Invalid cgroup')
        cpu = dict(line.split() for line in (base / 'cpu.stat').read_text().splitlines())
        memory = int((base / 'memory.current').read_text())
        return int(cpu['usage_usec']) * 1000, memory, str(base.stat().st_ino)

    def collect(self):
        import fcntl
        cache = self.store.root / 'metrics.json'
        lock = self.store.root / 'metrics.lock'
        fd = os.open(lock, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            # Multiple tabs/workers share one short-lived snapshot, not multiple collectors.
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                try:
                    response = json.loads(cache.read_text())['response']
                    if time.time() - response['at'] > 15:
                        raise AppError('Metrics snapshot is stale; collector busy')
                    return response
                except (OSError, ValueError, KeyError):
                    raise AppError('Metrics sampling in progress; retry shortly')
            now = self.clock()
            regs = self.store.registrations()
            # Extra uses the same cached identities as inventory, without rescanning hosts.
            known = {(r['runtime'], r['native']) for r in regs}
            for runtime in ('systemd', 'docker'):
                try:
                    discovered = json.loads((self.store.root / ('discovery-' + runtime + '.json')).read_text())
                    for item in discovered:
                        native = item['native']
                        application = runtime == 'docker' or native.startswith(('web-', 'appspaces-', 'zewar-')) or item.get('details', {}).get('WorkingDirectory', '').startswith(('/home/', '/srv/', '/opt/', '/www/', '/var/www/'))
                        if application and (runtime, native) not in known:
                            regs.append({'runtime': runtime, 'native': native, 'id': 'unassigned-' + hashlib.sha256((runtime + ':' + native).encode()).hexdigest()[:20]})
                            known.add((runtime, native))
                except (OSError, ValueError, KeyError, TypeError):
                    pass
            fingerprint = hashlib.sha256(json.dumps([(r['id'], r['runtime'], r['native']) for r in regs]).encode()).hexdigest()
            try:
                previous = json.loads(cache.read_text())
            except (OSError, ValueError):
                previous = {}
            elapsed = now - previous.get('at', now)
            if previous.get('fingerprint') == fingerprint and 0 <= elapsed < 4:
                return previous['response']
            raw, notes = {}, []
            units = [valid_unit(r['native']) for r in regs if r['runtime'] == 'systemd']
            if units:
                try:
                    for start in range(0, len(units), 100):
                        output = self.run(['systemctl', 'show', *units[start:start+100], '--property=Id,LoadState,ActiveState,ControlGroup,CPUUsageNSec,MemoryCurrent,InvocationID', '--no-pager'], timeout=8)
                        for block in output.strip().split('\n\n'):
                            data = dict(line.split('=', 1) for line in block.splitlines() if '=' in line)
                            identity = data.get('Id')
                            if identity not in units:
                                continue
                            if data.get('LoadState') == 'not-found':
                                raw[('systemd', identity)] = None
                            elif data.get('ActiveState') not in ('active', 'activating', 'reloading'):
                                raw[('systemd', identity)] = []
                            else:
                                try:
                                    counters = self.counters(data.get('ControlGroup', ''))
                                except (OSError, ValueError, KeyError):
                                    cpu, mem = data.get('CPUUsageNSec', ''), data.get('MemoryCurrent', '')
                                    invocation = data.get('InvocationID')
                                    counters = (int(cpu) if invocation and cpu.isdigit() and int(cpu)<2**63 else None, int(mem) if mem.isdigit() and int(mem)<2**63 else None, 'systemd:' + identity + ':' + str(invocation))
                                raw[('systemd', identity)] = [counters]
                except AppError:
                    notes.append('Systemd metrics unavailable')
            if any(r['runtime'] == 'docker' for r in regs):
                try:
                    # Only request identity, labels and PID; never collect container environments.
                    fmt = '{{json .Id}} {{json .Name}} {{.State.Pid}} {{json .State.Running}} {{json (index .Config.Labels "com.docker.compose.project")}} {{json (index .Config.Labels "com.docker.compose.service")}}'
                    ids = self.run(['docker', 'ps', '-aq', '--no-trunc'], timeout=5).split()
                    for start in range(0, len(ids), 50):
                        from .core import valid_container
                        output = self.run(['docker', 'inspect', '--type=container', '--format', fmt, *[valid_container(x) for x in ids[start:start+50]]], timeout=8)
                        decoder = json.JSONDecoder()
                        for line in output.splitlines():
                            parts = []
                            while line.strip():
                                value, end = decoder.raw_decode(line.lstrip())
                                parts.append(value)
                                line = line.lstrip()[end:]
                            cid, name, pid, running, project, service = parts
                            native = 'compose:'+project+'/'+service if project and service else 'container:'+name.lstrip('/')
                            members = raw.setdefault(('docker', native), [])
                            if running:
                                try:
                                    pid = int(pid)
                                    group = next(x.split(':', 2)[2] for x in (self.proc / str(pid) / 'cgroup').read_text().splitlines() if x.startswith('0::'))
                                    members.append(self.counters(group))
                                except (OSError, ValueError, KeyError, StopIteration):
                                    members.append((None, None, cid))
                except (AppError, ValueError, KeyError):
                    notes.append('Docker metrics unavailable')
            sampled = self.clock()
            samples, services = {}, []
            for reg in regs:
                members = raw.get((reg['runtime'], reg['native']))
                cpu, memory, status = None, None, 'unavailable'
                if members == []:
                    cpu, memory, status = 0.0, 0, 'inactive'
                elif members:
                    memory = sum(x[1] for x in members) if all(x[1] is not None for x in members) else None
                    if all(x[0] is not None for x in members):
                        total = sum(x[0] for x in members)
                        identity = sorted(x[2] for x in members)
                        samples[reg['id']] = {'total': total, 'identity': identity, 'at': sampled}
                        last = previous.get('samples', {}).get(reg['id'], {})
                        dt = sampled - last.get('at', sampled)
                        if last.get('identity') == identity and 0 < dt <= 120 and total >= last.get('total', total+1):
                            cpu = round((total-last['total']) / dt / 10000000, 2)
                        status = 'ok' if cpu is not None else 'sampling'
                services.append({'id': reg['id'], 'cpu': cpu, 'memory': memory, 'status': status})
            response = {'services': services, 'at': time.time(), 'warnings': notes, 'cpu_basis': '100% = one CPU core', 'interval_seconds': 5}
            temp = self.store.root / 'metrics.tmp'
            with open(temp, 'w', encoding='utf-8') as stream:
                os.chmod(temp, 0o600)
                json.dump({'at': sampled, 'fingerprint': fingerprint, 'samples': samples, 'response': response}, stream)
            os.replace(temp, cache)
            return response
        finally:
            os.close(fd)
