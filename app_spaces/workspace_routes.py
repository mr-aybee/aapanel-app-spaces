"""Exact workspace routes, separate from aaPanel's catch-all dashboard router."""
from pathlib import Path


def register(app):
    if 'app_spaces_workspace' in app.view_functions:
        return
    from flask import make_response, send_file

    def workspace():
        # This shell contains no session token or workload data. All data stays in
        # the existing primary-admin + CSRF protected POST API.
        response = make_response(send_file(Path(__file__).resolve().parent / 'workspace.html', conditional=False))
        response.headers['Content-Type'] = 'text/html; charset=utf-8'
        response.headers['Cache-Control'] = 'no-store, max-age=0'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response

    app.add_url_rule('/app-spaces', 'app_spaces_workspace', workspace, methods=['GET'])
    app.add_url_rule('/static/app_spaces/index.html', 'app_spaces_workspace_legacy', workspace, methods=['GET'])
