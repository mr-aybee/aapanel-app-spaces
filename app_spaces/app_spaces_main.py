"""aaPanel entry point. All browser operations go through the authenticated api method."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

PLUGIN = Path(__file__).resolve().parent
if str(PLUGIN) not in sys.path:
    sys.path.insert(0, str(PLUGIN))
from appspaces_core.core import AppError, Application, Configuration, Store, redact, namespace_id
from appspaces_core.creation import Creator

class app_spaces_main:
    def api(self, args):
        store = None
        try:
            from BTPanel import session, request, check_csrf
            import public
            # Primary panel administrator only. Temporary links and API-key-only access are rejected.
            if request.method != 'POST' or session.get('login') is not True or str(session.get('uid')) != '1' or session.get('tmp_login_id'):
                raise AppError('A normal primary-administrator aaPanel session is required')
            if not check_csrf():
                raise AppError('Invalid aaPanel request token; reload the panel')
            actor = str(session['uid']) + ':' + hashlib.sha256(public.get_csrf_sess_html_token_value().encode()).hexdigest()[:16]
            payload = json.loads(getattr(args, 'payload', '{}'))
            if not isinstance(payload, dict):
                raise AppError('Expected a JSON object')
            operation = payload.get('operation', 'inventory')
            if operation == 'bootstrap':
                return {'status': True, 'data': {'csrf': public.get_csrf_sess_html_token_value()}}
            store = Store(PLUGIN / 'data')
            # A retry of a mutation must not issue a second restart or duplicate write.
            if operation in ('namespaces', 'register', 'move', 'unregister', 'action', 'apply', 'create_service'):
                request_id = str(payload.get('request_id', ''))
                import re
                if not re.fullmatch(r'[a-f0-9-]{32,64}', request_id):
                    raise AppError('A unique operation request ID is required')
                try:
                    store.db.execute('DELETE FROM requests WHERE at < strftime("%s","now") - 86400')
                    import time
                    store.db.execute('INSERT INTO requests VALUES (?,?,?,?)', (request_id, actor, operation, time.time()))
                    store.db.commit()
                except sqlite3.IntegrityError as exc:
                    raise AppError('This operation was already submitted; refresh before trying again') from exc
            if operation == "metrics":
                from appspaces_core.metrics import Metrics
                return {"status": True, "data": Metrics(store).collect()}
            app = Application(store)
            if operation in ('inventory', 'discover'):
                data = app.inventory(operation == 'discover', include_unassigned=operation == 'inventory')
            elif operation == 'creation_preview':
                data = Creator(store).preview(payload.get('spec'), actor)
            elif operation == 'create_service':
                if payload.get('confirmed') is not True:
                    raise AppError('Explicit creation confirmation is required')
                data = Creator(store).create(payload.get('token'), actor, payload.get('start') is True)
            elif operation == 'namespaces':
                data = app.namespace({**payload, 'operation': payload.get('namespace_operation')})
            elif operation == 'register':
                data = app.register(payload)
            elif operation == 'move':
                reg = store.get(payload.get('id'))
                target = namespace_id(payload.get('namespace', ''))
                if not any(x['slug'] == target for x in store.namespaces()):
                    raise AppError('Namespace does not exist')
                store.db.execute('UPDATE registrations SET namespace=? WHERE id=?', (target, reg['id']))
                store.db.commit()
                data = {'moved': True}
            elif operation == 'unregister':
                reg = store.get(payload.get('id'))
                if payload.get('confirmation') != reg['label']:
                    raise AppError('Type the workload label to unregister it')
                store.db.execute('DELETE FROM registrations WHERE id=?', (reg['id'],))
                store.db.commit()
                data = {'unregistered': True, 'runtime_untouched': True}
            elif operation == 'action':
                if payload.get('confirmed') is not True:
                    raise AppError('Explicit action confirmation is required')
                data = app.action(payload.get('id'), payload.get('verb'))
            elif operation in ('logs', 'environment', 'configuration', 'preview', 'apply'):
                reg = store.get(payload.get('id'))
                adapter = app.adapters[reg['runtime']]
                if operation == 'logs':
                    data = {'text': redact(adapter.logs(reg['native'], payload.get('lines', 100))), 'note': 'Common secret patterns masked; app logs may contain other sensitive information.'}
                elif operation == 'environment':
                    values = adapter.environment(reg['native'])
                    if reg['runtime'] == 'systemd':
                        values = {reg['native']: values}
                    # Environment values are hidden by default regardless of variable name.
                    reveal = payload.get('reveal') is True
                    data = {'instances': {instance: [{'key': k, 'value': v if reveal else '••••••', 'masked': not reveal} for k, v in env.items()] for instance, env in values.items()},
                            'note': 'Configured unit environment only; EnvironmentFile, manager inheritance and application configuration may add or override values.' if reg['runtime'] == 'systemd' else 'Effective container environment. Configuration changes require recreation by its deployment owner.'}
                else:
                    config = Configuration(store, app.adapters['systemd'])
                    if operation == 'configuration':
                        data = config.read(reg, payload.get('reveal') is True)
                    elif operation == 'preview':
                        data = config.preview(reg, payload.get('content', ''), payload.get('revision'), actor)
                    else:
                        if not reg['lifecycle'] or payload.get('confirmed') is not True:
                            raise AppError('Lifecycle capability and explicit restart confirmation are required')
                        data = config.apply(reg, payload.get('token'), actor)
            elif operation == 'audit':
                data = [dict(x) for x in store.db.execute('SELECT * FROM audit ORDER BY id DESC LIMIT 200')]
            elif operation == 'export':
                data = {'schema': 1, 'namespaces': store.namespaces(), 'registrations': store.registrations()}
            else:
                raise AppError('Unknown operation')
            if operation not in ('inventory', 'discover', 'audit', 'logs'):
                store.audit(actor, operation, str(payload.get('id', payload.get('slug', '')))[:200], 'ok')
            return {'status': True, 'data': data}
        except (AppError, ValueError, TypeError, KeyError, sqlite3.IntegrityError) as exc:
            # Do not echo payloads, unit content, or subprocess diagnostics.
            message = str(exc) if isinstance(exc, AppError) else 'Invalid request or duplicate registration/namespace'
            if store:
                store.audit(locals().get('actor', 'unknown'), locals().get('operation', 'request'), '', 'failed')
            return {'status': False, 'msg': message}
        except Exception:
            return {'status': False, 'msg': 'Operation failed. Check runtime availability and plugin data permissions.'}
        finally:
            if store:
                store.close()
