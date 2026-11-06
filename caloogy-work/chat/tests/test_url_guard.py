"""The token must only ever go to Caloogy: python3 -m pytest or python3 chat/tests/test_url_guard.py"""
import http.server, os, sys, tempfile, threading, urllib.request
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from caloogy_chat import cli
bad = ['https://evil.com', 'http://work.caloogy.com', 'https://caloogy.com.evil.com', 'https://evilcaloogy.com', 'https://work.caloogy.com@evil.com', 'file:///etc/passwd', 'ftp://caloogy.com']
good = ['https://work.caloogy.com', 'https://caloogy.com', 'http://localhost:5192', 'http://127.0.0.1:5192']
for u in bad:
    try: cli.checked_url(u); raise SystemExit(f'FAIL allowed {u}')
    except cli.Fail: print('PASS refused', u)
for u in good: assert cli.checked_url(u) == u; print('PASS allowed', u)
seen = {}
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def do_GET(self):
        if self.path == '/away':
            self.send_response(302); self.send_header('Location', f'http://127.0.0.1:{self.server.server_address[1]}/there'); self.end_headers(); return
        if self.path == '/far':
            self.send_response(302); self.send_header('Location', 'https://evil.com/steal'); self.end_headers(); return
        seen['auth'] = self.headers.get('Authorization'); self.send_response(200); self.send_header('Content-Length', '2'); self.end_headers(); self.wfile.write(b'{}')
srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), H); threading.Thread(target=srv.serve_forever, daemon=True).start()
port = srv.server_address[1]
r = urllib.request.Request(f'http://localhost:{port}/away', headers={'Authorization': 'Bearer secret'})
cli._OPENER.open(r, timeout=5); assert seen.get('auth') is None, seen; print('PASS Authorization dropped on a cross-host redirect')
try:
    cli._OPENER.open(urllib.request.Request(f'http://localhost:{port}/far', headers={'Authorization': 'Bearer secret'}), timeout=5); raise SystemExit('FAIL followed')
except cli.Fail: print('PASS redirect to another site refused')
os.environ['CALOOGY_CHAT_URL'] = 'https://evil.com'; os.environ['CALOOGY_CHAT_TOKEN'] = 'x'
class A: url = None
try: cli.base_url(A()); raise SystemExit('FAIL env url accepted')
except cli.Fail: print('PASS env URL refused')
print('OK')
