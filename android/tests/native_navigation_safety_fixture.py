#!/usr/bin/env python3
"""Owned loopback fixture for scoped GeckoView navigation safety (MPL-2.0).

This fixture is separate from the original download/context fixtures. The only
unbounded script requires an explicit button click by the supervised native
test; never expose it on a non-loopback listener.
"""
from datetime import datetime, timezone
import http.server
import json
from pathlib import Path
import secrets
import threading
import time
import urllib.parse

DOWNLOAD_BYTES = b'Cyphra scoped navigation safety fixture\n'
TIMER_INTERVAL_MS = 1000
TIMER_BUSY_MS = 800
TIMER_MAX_CALLBACKS = 36

STYLE = '<style>body{font:16px system-ui;padding:20px}button{font:18px system-ui;padding:16px;margin:12px 0;display:block}</style>'
TIMER = r'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Cyphra bounded navigation timer</title>__STYLE__</head>
<body><h1>Bounded navigation timer</h1><p>Static document; at most 36 callbacks.</p><button id="inspect">Inspect timer identity</button>
<script>
'use strict';
const run=__RUN__,token=__TOKEN__;let ticks=0,completed=0;
function report(kind){return fetch('/event?run='+encodeURIComponent(run),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind,token,ticks,completed,url:location.href,title:document.title})});}
function pulse(){
 ++ticks;report('tick-start');
 const deadline=performance.now()+800;while(performance.now()<deadline){}
 ++completed;report('tick-complete');
 if(ticks>=36)clearInterval(timer);
}
const timer=setInterval(pulse,1000);
document.getElementById('inspect').addEventListener('click',()=>report('inspect'));
report('ready');
</script></body></html>'''

SENTINEL = r'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Cyphra native Back sentinel</title>__STYLE__</head>
<body><h1>Native Back sentinel</h1><button id="inspect">Inspect recovered document</button><script>
'use strict';const run=__RUN__,token=__TOKEN__;
function report(kind){return fetch('/event?run='+encodeURIComponent(run),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind,token,url:location.href,title:document.title})});}
document.getElementById('inspect').addEventListener('click',()=>report('sentinel-inspect'));
addEventListener('pageshow',()=>report('sentinel-pageshow'));report('sentinel-ready');
</script></body></html>'''

LOOP = r'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Cyphra supervised looping script</title>__STYLE__</head>
<body><h1>Supervised looping script</h1><p>Only the native safety runner should arm this local page.</p><button id="arm">Start supervised loop</button><script>
'use strict';const run=__RUN__,token=__TOKEN__;
function report(kind){return fetch('/event?run='+encodeURIComponent(run),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind,token,url:location.href,title:document.title})});}
document.getElementById('arm').addEventListener('click',async()=>{
 await report('loop-start');
 // Intentionally infinite. The host supervisor has a strict deadline and
 // failure-only force-stop cleanup. No auto-navigation or timer repairs.
 for(;;){}
});report('loop-ready');
</script></body></html>'''


def render_document(kind, run, token):
    template = {'timer': TIMER, 'sentinel': SENTINEL, 'loop': LOOP}[kind]
    return template.replace('__STYLE__', STYLE).replace('__RUN__', json.dumps(run)).replace('__TOKEN__', json.dumps(token))


class Fixture:
    def __init__(self, log):
        self.log = Path(log)
        self.events = []
        self.lock = threading.Lock()
        self.server = None
        self.thread = None

    def record(self, method, path, run, body=None):
        event = {'at': datetime.now(timezone.utc).isoformat(), 'monotonicNs': time.monotonic_ns(),
                 'method': method, 'path': path, 'run': run}
        if body is not None:
            event['body'] = body
        with self.lock:
            self.events.append(event)
            with self.log.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(event, sort_keys=True) + '\n')
        return event

    def snapshot(self, run):
        with self.lock:
            return [event.copy() for event in self.events if event['run'] == run]

    def start(self):
        fixture = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass

            def send(self, data, content_type='application/json', status=200, download=None):
                if not isinstance(data, bytes):
                    data = (data if isinstance(data, str) else json.dumps(data)).encode('utf-8')
                self.send_response(status)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; object-src 'none'")
                if download:
                    self.send_header('Content-Disposition', 'attachment; filename="' + download + '"')
                self.end_headers()
                self.wfile.write(data)

            def parse(self):
                parsed = urllib.parse.urlsplit(self.path)
                run = urllib.parse.parse_qs(parsed.query).get('run', [''])[0]
                if not run or len(run) > 100 or not all(c.isalnum() or c in '-_' for c in run):
                    return parsed.path, None
                return parsed.path, run

            def do_GET(self):
                path, run = self.parse()
                if run is None:
                    return self.send({'error': 'Invalid fixture run'}, status=400)
                fixture.record('GET', path, run)
                if path in ('/timer', '/sentinel', '/loop'):
                    return self.send(render_document(path[1:], run, secrets.token_hex(16)), 'text/html; charset=utf-8')
                if path == '/attachment':
                    return self.send(DOWNLOAD_BYTES, 'text/plain', download='cyphra-safety-' + run + '.txt')
                return self.send({'error': 'Unknown fixture endpoint'}, status=404)

            def do_POST(self):
                path, run = self.parse()
                try:
                    size = int(self.headers.get('Content-Length', '0'))
                    if path != '/event' or run is None or not 0 < size <= 4096:
                        raise ValueError('Invalid event')
                    body = json.loads(self.rfile.read(size))
                    if not isinstance(body, dict) or body.get('kind') not in {
                        'ready', 'tick-start', 'tick-complete', 'inspect', 'sentinel-ready',
                        'sentinel-pageshow', 'sentinel-inspect', 'loop-ready', 'loop-start',
                    }:
                        raise ValueError('Invalid event kind')
                except (ValueError, UnicodeError):
                    return self.send({'error': 'Invalid fixture event'}, status=400)
                fixture.record('POST', path, run, body)
                return self.send({'received': True})

        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .1}, daemon=True)
        self.thread.start()
        return self.server.server_port

    def close(self):
        if self.server:
            self.server.shutdown()
            self.server.server_close()
        if self.thread:
            self.thread.join(timeout=2)
