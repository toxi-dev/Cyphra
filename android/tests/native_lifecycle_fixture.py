#!/usr/bin/env python3
"""Loopback-only live-document fixture for native lifecycle qualification (MPL-2.0)."""
import argparse
import http.server
import json
import os
from pathlib import Path
import re
import secrets
import threading
import urllib.parse

LOCK = threading.Lock()
DOCUMENTS = {}
LOG = None
PAGE = r'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Lifecycle __KIND__ document</title></head><body>
<h1>Lifecycle __KIND__ document</h1><label>Runtime form input <input id="form"></label>
<p id="sequence"></p><script>
'use strict';
const token=__TOKEN__, run=__RUN__, kind=__KIND_JSON__;
window.cyphraLifecycleToken=token;
document.getElementById('form').value='input-'+token;
history.replaceState({token,step:0},'',location.pathname+location.search+'#zero');
history.pushState({token,step:1},'','#one');history.pushState({token,step:2},'','#two');
let sequence=0,busy=false;
async function pulse(){
 if(busy)return;busy=true;
 try{
  const state={token:window.cyphraLifecycleToken,sequence:++sequence,
   form:document.getElementById('form').value,href:location.href,historyLength:history.length,
   stateToken:history.state?.token,stateStep:history.state?.step,visibility:document.visibilityState};
  document.getElementById('sequence').textContent='Live sequence '+sequence;
  await fetch('/state?run='+encodeURIComponent(run)+'&kind='+kind,{method:'POST',
   headers:{'Content-Type':'application/json'},body:JSON.stringify(state)});
 }finally{busy=false;}
}
pulse();setInterval(pulse,250);addEventListener('popstate',pulse);
</script></body></html>'''


def page(run, kind, token):
    return (PAGE.replace('__KIND__', kind).replace('__TOKEN__', json.dumps(token))
            .replace('__RUN__', json.dumps(run)).replace('__KIND_JSON__', json.dumps(kind)))


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def request_key(self):
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        run = query.get('run', [''])[0]
        kind = query.get('kind', [''])[0]
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', run) or kind not in ('ordinary', 'private'):
            raise ValueError('A bounded run ID and document kind are required.')
        return parsed.path, (run, kind)

    def send(self, body, content_type='application/json', status=200):
        data = (body if isinstance(body, str) else json.dumps(body)).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type+'; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == '/health':
            self.send({'fixture': 'cyphra-native-lifecycle-v1', 'pid': os.getpid()});return
        try:
            path, key = self.request_key()
            with LOCK:
                document = DOCUMENTS.setdefault(key, {'pageRequests': 0, 'tokens': [], 'latest': None})
                if path == '/page':
                    token = secrets.token_hex(16)
                    document['pageRequests'] += 1
                    document['tokens'].append(token)
                    body = page(*key, token)
                elif path == '/snapshot':
                    body = json.loads(json.dumps(document))
                else:
                    self.send({'error': 'Unknown fixture path.'}, status=404);return
            self.send(body, 'text/html' if path == '/page' else 'application/json')
        except ValueError as error:
            self.send({'error': str(error)}, status=400)

    def do_POST(self):
        try:
            path, key = self.request_key()
            if path != '/state':
                self.send({'error': 'Unknown fixture path.'}, status=404);return
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 8192:
                raise ValueError('Invalid state size.')
            state = json.loads(self.rfile.read(size))
            with LOCK:
                document = DOCUMENTS.get(key)
                if not document or state.get('token') not in document['tokens']:
                    raise ValueError('State has no matching document request.')
                document['latest'] = state
                if LOG:
                    with LOG.open('a', encoding='utf-8') as stream:
                        stream.write(json.dumps({'run': key[0], 'kind': key[1], 'state': state})+'\n')
            self.send({'accepted': True})
        except (ValueError, TypeError) as error:
            self.send({'error': str(error)}, status=400)


def main():
    global LOG
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--log', type=Path)
    args = parser.parse_args()
    LOG = args.log
    if LOG:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        # A new invocation must never overwrite the reports from an earlier one.
        with LOG.open('x', encoding='utf-8'):
            pass
    server = http.server.ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'Lifecycle fixture ready at http://127.0.0.1:{args.port}', flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
