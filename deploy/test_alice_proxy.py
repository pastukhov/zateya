"""Real nginx integration test; requires Docker, no secrets or vault."""
import json
from pathlib import Path
import subprocess
import time
import urllib.error
import urllib.request
import uuid


def docker(*args):
    return subprocess.check_output(['docker', *args], text=True).strip()


def test_proxy_boundary(tmp_path):
    root = Path(__file__).resolve().parents[1]
    template = root / 'deploy/alice.nginx.conf.template'
    assert template.exists(), 'Alice proxy config is missing'
    name = 'alice-test-' + uuid.uuid4().hex[:10]
    mock = tmp_path / 'mock.py'
    mock.write_text('''from http.server import BaseHTTPRequestHandler, HTTPServer
import json
class Handler(BaseHTTPRequestHandler):
 def do_POST(self):
  body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
  result = json.dumps(dict(path=self.path, auth=self.headers.get('Authorization'), body=body.decode())).encode()
  self.send_response(200); self.end_headers(); self.wfile.write(result)
 def log_message(self, *args): pass
HTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
''')
    docker('network', 'create', name)
    try:
        docker('run', '-d', '--name', name+'-backend', '--network', name,
               '--network-alias', 'backend', '-v', f'{mock}:/mock.py:ro',
               'python:3.12-slim', 'python', '/mock.py')
        docker('run', '-d', '--name', name+'-proxy', '--network', name,
               '-p', '127.0.0.1::8080', '-e', 'VOICE_BIND_PORT=8080',
               '-v', f'{template}:/etc/nginx/templates/default.conf.template:ro',
               'nginx:stable-alpine')
        port = docker('port', name+'-proxy', '8080/tcp').rsplit(':', 1)[1]
        base = f'http://127.0.0.1:{port}'
        def request(path, method='GET', body=None):
            req = urllib.request.Request(base+path, data=body, method=method,
                                         headers={'Authorization': 'Bearer test-marker',
                                                  'Content-Type': 'application/json'})
            try:
                with urllib.request.urlopen(req, timeout=3) as response:
                    return response.status, response.read()
            except urllib.error.HTTPError as error:
                return error.code, error.read()
        for _ in range(50):
            try:
                if request('/')[0] == 404:
                    break
            except OSError:
                pass
            time.sleep(.1)
        for path in ['/', '/docs', '/metrics', '/health/live', '/data/foo',
                     '/api/voice/turns', '/api/alice/webhook/extra']:
            assert request(path)[0] == 404, path
        assert request('/api/alice/webhook')[0] == 405
        payload = '{"request":{"original_utterance":"тест"}}'.encode()
        status, body = request('/api/alice/webhook', 'POST', payload)
        assert status == 200, body
        assert json.loads(body) == dict(path='/api/alice/webhook',
                                        auth='Bearer test-marker', body=payload.decode())
        assert request('/api/alice/webhook', 'POST', b'x'*65537)[0] == 413
        logs = docker('logs', name+'-proxy')
        assert 'test-marker' not in logs
        assert 'original_utterance' not in logs
    finally:
        subprocess.run(['docker', 'rm', '-f', name+'-proxy', name+'-backend'], capture_output=True)
        subprocess.run(['docker', 'network', 'rm', name], capture_output=True)
