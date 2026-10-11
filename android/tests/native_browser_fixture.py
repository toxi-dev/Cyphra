#!/usr/bin/env python3
"""Loopback-only native Gecko fixture. No DNS, certificates, or host changes."""
import argparse
import collections
import datetime
import http.server
import json
import pathlib
import re
import threading
import urllib.parse

ROOT = pathlib.Path(__file__).resolve().parent
EVENTS = []
RESULTS = []
LOCK = threading.Lock()
LOG = pathlib.Path("/tmp/cyphra-native-fixture-requests.jsonl")
TRACKED = {
    "/normal/probe.js": "normal",
    "/ads/cbr.js": "ads",
    "/third-party/probe.js": "thirdParty",
    "/api/1/envelope": "telemetry",
}

HTML = r'''<!doctype html>
<html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Cyphra native privacy fixture</title>
<style>html{color-scheme:dark}body{background:#101113;color:#f1f2f3;font:16px system-ui;margin:20px;line-height:1.6}h1{font-size:22px}p{margin:8px 0}code{font-size:14px;color:#b9c6d6}pre{white-space:pre-wrap;border-top:1px solid #444;padding-top:14px}button{background:#25292e;color:#fff;padding:10px;border:1px solid #555;border-radius:6px}</style>
</head><body>
<h1>Cyphra native privacy fixture</h1>
<p id="label"></p><p id="status">Running actual browser probes…</p>
<pre id="results">Waiting for scripts and request log.</pre>
<button onclick="location.reload()">Repeat this visit</button>
<script>
'use strict';
const config = __CONFIG__;
document.getElementById('label').textContent = 'Run: '+config.run+' · Test label: '+config.mode+' · Expected Shields: '+config.shields;
const observed = {run:config.run, modeLabel:config.mode, shieldsLabel:config.shields,
  secureContext:isSecureContext, publicKeyCredential:typeof PublicKeyCredential,
  userAgent:navigator.userAgent, scripts:{}, storage:{}, webAuthn:{}};
const query = '?run='+encodeURIComponent(config.run);
const cookieMarker = () => document.cookie.split('; ').find(v=>v.startsWith('cyphraFixture='))?.slice('cyphraFixture='.length) || null;
try {
  observed.storage.localBefore=localStorage.getItem('cyphraFixture');
  observed.storage.cookieBefore=cookieMarker();
  if(config.write){localStorage.setItem('cyphraFixture',config.write);document.cookie='cyphraFixture='+encodeURIComponent(config.write)+'; Path=/; Max-Age=604800; SameSite=Strict';}
  observed.storage.localAfter=localStorage.getItem('cyphraFixture');
  observed.storage.cookieAfter=cookieMarker();
}catch(error){observed.storage.error=error.name;}
function script(name,url){return new Promise(resolve=>{
  const node=document.createElement('script');
  let finished=false;
  function finish(state){if(finished)return;finished=true;observed.scripts[name]=state;resolve();}
  node.onload=()=>finish('loaded');node.onerror=()=>finish('error');
  setTimeout(()=>finish('timed out'),6000);node.src=url+query;document.head.appendChild(node);
});}
async function webAuthn(method){
  if(!isSecureContext)return 'not a secure context';
  if(!navigator.credentials)return 'credentials API unavailable';
  try{return await Promise.race([
    navigator.credentials[method]({publicKey:{}}).then(()=> 'unexpected success',error=>error.name),
    new Promise(resolve=>setTimeout(()=>resolve('timed out'),3000))
  ]);}catch(error){return error.name;}
}
(async()=>{
  // This path is explicitly recognized as telemetry by the shipping extension.
  // sendBeacon's boolean is only queue acceptance, never proof of delivery.
  observed.beaconQueued=navigator.sendBeacon('/api/1/envelope'+query+'&sentry_key=fixture','fixture-only');
  await Promise.all([
    script('normal',location.origin+'/normal/probe.js'),
    script('ads',location.origin+'/ads/cbr.js'),
    script('thirdParty','http://127.0.0.1:__PORT__/third-party/probe.js'),
    webAuthn('create').then(v=>observed.webAuthn.create=v),
    webAuthn('get').then(v=>observed.webAuthn.get=v)
  ]);
  await new Promise(resolve=>setTimeout(resolve,1200));
  try{observed.serverHits=await(await fetch('/api/hits'+query,{cache:'no-store'})).json();}catch(error){observed.serverHitsError=error.name;}
  const counts=observed.serverHits?.counts;
  observed.checks={
    secureContext:observed.secureContext===true,
    publicKeyAPIHidden:observed.publicKeyCredential==='undefined',
    webAuthnCreateGuard:['NotSupportedError','credentials API unavailable'].includes(observed.webAuthn.create),
    webAuthnGetGuard:['NotSupportedError','credentials API unavailable'].includes(observed.webAuthn.get),
    normalReachedServer:counts?.normal===1,
    telemetryDidNotReachServer:counts?.telemetry===0,
    adsExpected:counts?.ads===(config.shields==='off'?1:0),
    thirdPartyExpected:counts?.thirdParty===((config.shields==='off'||config.mode==='personal')?1:0)
  };
  const passed=Object.values(observed.checks).every(v=>v===true);
  document.getElementById('status').textContent=passed?'All measured checks passed':'Check results below';
  document.getElementById('results').textContent=JSON.stringify(observed,null,2);
  await fetch('/result'+query,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(observed)});
})().catch(error=>{document.getElementById('status').textContent='Fixture error: '+error.name;});
</script></body></html>'''


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def event(self, body=None):
        parsed = urllib.parse.urlsplit(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        run = query.get("run", [""])[0][:64]
        event = {"at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                 "method": self.command, "host": self.headers.get("Host", ""),
                 "path": parsed.path, "run": run}
        with LOCK:
            EVENTS.append(event)
            if body is not None:
                RESULTS.append({"run": run, "result": body})
            with LOG.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({**event, **({"result": body} if body is not None else {})}) + "\n")
        return parsed, query, run

    def send(self, payload, content_type="application/json", status=200):
        data = payload.encode("utf-8") if isinstance(payload, str) else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type + "; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline' http://localhost:"+str(self.server.server_port)+" http://127.0.0.1:"+str(self.server.server_port)+"; style-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'; object-src 'none'")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        parsed, query, run = self.event()
        if parsed.path == "/health":
            return self.send({"ready": True, "bind": "127.0.0.1", "port": self.server.server_port})
        if parsed.path == "/api/hits":
            with LOCK:
                counts = collections.Counter(TRACKED[e["path"]] for e in EVENTS if e["run"] == run and e["path"] in TRACKED)
            return self.send({"run": run, "counts": {name: counts[name] for name in TRACKED.values()}})
        if parsed.path == "/api/results":
            with LOCK:
                found = [e for e in RESULTS if not run or e["run"] == run]
            return self.send(found)
        if parsed.path in ("/normal/probe.js", "/ads/cbr.js", "/third-party/probe.js"):
            return self.send("window.cyphraFixtureDelivered=(window.cyphraFixtureDelivered||[]);window.cyphraFixtureDelivered.push("+json.dumps(parsed.path)+");", "text/javascript")
        if parsed.path == "/":
            safe = lambda name, default: re.sub(r"[^A-Za-z0-9_.-]", "_", query.get(name, [default])[0])[:64]
            config = {"run": safe("run", "visit"), "mode": safe("mode", "personal"), "shields": safe("shields", "on"), "write": safe("write", "")}
            return self.send(HTML.replace("__CONFIG__", json.dumps(config)).replace("__PORT__", str(self.server.server_port)), "text/html")
        return self.send({"error": "No fixture endpoint"}, status=404)

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.send({"error": "Invalid length"}, status=400)
        if length < 0 or length > 16384:
            return self.send({"error": "Fixture body too large"}, status=413)
        payload = self.rfile.read(length)
        parsed = urllib.parse.urlsplit(self.path)
        body = None
        if parsed.path == "/result":
            try:
                body = json.loads(payload)
            except (ValueError, UnicodeError):
                return self.send({"error": "Invalid result"}, status=400)
        self.event(body)
        return self.send({"received": True})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = http.server.ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print("Cyphra fixture listening only on http://127.0.0.1:"+str(args.port), flush=True)
    server.serve_forever()
