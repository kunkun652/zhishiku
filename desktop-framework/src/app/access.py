"""Single-owner desktop sessions and explicitly scoped, revocable agent tokens.

This is an application boundary, not isolation from the same Windows account.
No anonymous API reads; the native launcher exchanges a one-use bootstrap token.
"""
import hashlib
import re
import secrets
import threading
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse


class Access:
    def __init__(self):
        self.bootstrap = secrets.token_urlsafe(32)
        self.owner_token = secrets.token_urlsafe(32)
        self.lock = threading.Lock()
        self.agents = {}

    def role(self, request):
        auth = request.headers.get('authorization', '')
        # An explicit invalid credential must not fall back to an owner cookie.
        token = auth[7:] if auth.startswith('Bearer ') else ''
        if not auth:
            token = request.cookies.get('zh_session', '')
        if token and secrets.compare_digest(token, self.owner_token):
            return 'owner'
        return self.agents.get(hashlib.sha256(token.encode()).hexdigest()) if token else None

    def allowed(self, role, method, path):
        if role == 'owner':
            return True
        if role not in ('reader', 'processor'):
            return False
        if path.startswith('/api/security') or path == '/api/workbench/settings':
            return False
        if method in ('GET', 'HEAD'):
            return True
        if method == 'POST' and path in ('/api/retrieve', '/api/agent/ask', '/api/workbench/ask'):
            return True
        return role == 'processor' and method == 'POST' and (
            path == '/api/assistant/ingest' or
            re.fullmatch(r'/api/assistant/files/[^/]+/process', path) is not None)


def install(core):
    app, access = core.app, Access()
    app.state.access = access

    @app.middleware('http')
    async def authenticate(request, call_next):
        path = request.url.path
        host = request.headers.get('host', '')
        origin = request.headers.get('origin')
        if not re.fullmatch(r'(127\.0\.0\.1|localhost|testserver)(:\d+)?', host):
            return JSONResponse({'detail': 'Invalid host'}, status_code=400)
        if origin and origin not in ('http://' + host, 'https://' + host):
            return JSONResponse({'detail': 'Cross-origin access denied'}, status_code=403)
        if path.startswith('/api/') and path not in ('/api/ping', '/api/session'):
            role = access.role(request)
            if not access.allowed(role, request.method, path):
                return JSONResponse({'detail': '请从知识库快捷方式启动，或使用授权的 Agent 凭据' if not role else '此 Agent 无权执行该操作'},
                                    status_code=401 if not role else 403)
            request.state.role = role
        response = await call_next(request)
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        if path.startswith('/api/'):
            response.headers['Cache-Control'] = 'no-store'
        if re.fullmatch(r'/api/model-assets/[^/]+/file', path) and not response.headers.get('content-type','').startswith('application/pdf'):
            # Browser PDF viewers need their built-in viewer; other originals
            # remain sandboxed, and active HTML/SVG are served as attachments.
            response.headers['Content-Security-Policy'] = "sandbox"
        return response

    @app.get('/api/ping')
    def ping():
        return {'status': 'ready', 'build': '1.6.0-trusted-workbench'}

    @app.post('/api/session')
    def session(body: dict):
        token = body.get('token')
        with access.lock:
            if not isinstance(token, str) or not access.bootstrap or not secrets.compare_digest(token, access.bootstrap):
                raise HTTPException(401, '启动凭据已失效，请重新启动桌面应用')
            access.bootstrap = ''
        result = JSONResponse({'role': 'owner'})
        result.set_cookie('zh_session', access.owner_token, httponly=True, samesite='strict', path='/')
        return result

    @app.post('/api/security/agent-token')
    def create_token(body: dict):
        role = body.get('role', 'reader')
        if role not in ('reader', 'processor'):
            raise HTTPException(422, '只能签发只读或资料处理凭据')
        token = secrets.token_urlsafe(32)
        key = hashlib.sha256(token.encode()).hexdigest()
        access.agents[key] = role
        return {'token': token, 'id': key, 'role': role, 'expires': '应用关闭或撤销时失效'}

    @app.delete('/api/security/agent-token/{token_id}')
    def revoke(token_id: str):
        access.agents.pop(token_id, None)
        return {'revoked': True}
