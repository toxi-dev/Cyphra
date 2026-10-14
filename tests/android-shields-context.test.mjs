import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { webcrypto } from 'node:crypto';

const assets = new URL('../android/app/src/main/assets/shields/', import.meta.url);
const extensionId = 'android-shields@cyphra.org';
const oldURL = 'http://localhost:8765/page';
const downloadURL = 'http://127.0.0.1:8765/download';
const oldId = 'a'.repeat(32), newId = 'b'.repeat(32);

async function harness() {
  const listeners = {}, events = [], live = new Map(), timers = new Map();
  let timerId = 0, contextReply;
  const event = name => ({addListener(fn) { listeners[name] = fn; }});
  const native = {onMessage:event('native'), onDisconnect:event('disconnect'), postMessage:value=>events.push(value)};
  const sandbox = vm.createContext({URL, TextEncoder, TextDecoder, crypto:webcrypto,
    setTimeout(fn) { const id=++timerId;timers.set(id,fn);return id; }, clearTimeout:id=>timers.delete(id),
    fetch:async url=>{const file=new URL(String(url).replace('moz-extension://fixture/', ''),assets);
      const bytes=fs.readFileSync(file);return {ok:true,json:async()=>JSON.parse(bytes),arrayBuffer:async()=>Uint8Array.from(bytes).buffer};},
    browser:{webNavigation:{onBeforeNavigate:event('navigate'),onHistoryStateUpdated:event('history'),onReferenceFragmentUpdated:event('fragment')},
      webRequest:{onBeforeRequest:event('request')}, tabs:{onRemoved:event('remove'),
        sendMessage:async(id,message)=>message.type==='document-context'?(contextReply?contextReply():live.get(id)):undefined},
      runtime:{id:extensionId,onMessage:event('message'),connectNative:()=>native,getURL:path=>'moz-extension://fixture/'+path}}});
  vm.runInContext(fs.readFileSync(new URL('vendor/adblock.js',assets),'utf8'),sandbox);
  vm.runInContext(fs.readFileSync(new URL('background.js',assets),'utf8'),sandbox);
  listeners.native({type:'configuration',work:true,disabledHosts:[]});
  const deadline=Date.now()+5000;
  while(!events.some(value=>value.type==='ready')) {
    assert.ok(Date.now()<deadline,'Actual bundled matcher did not verify/start.');
    await new Promise(resolve=>setImmediate(resolve));
  }
  let requestId=0;
  const request=(url,documentUrl,type='script')=>listeners.request({tabId:1,frameId:0,type,url,documentUrl,requestId:String(++requestId)});
  const navigate=url=>{listeners.navigate({tabId:1,frameId:0,url});return request(url,undefined,'main_frame');};
  const commit=async(url,documentId=oldId)=>{live.set(1,{url,documentId});
    await listeners.message({type:'snapshot',documentId},{id:extensionId,tab:{id:1},frameId:0,url});};
  const tick=async()=>{await new Promise(resolve=>setImmediate(resolve));for(const [id,fn] of [...timers]){timers.delete(id);fn();}};
  const snapshot=()=>JSON.parse(vm.runInContext('JSON.stringify(snapshot(1))',sandbox));
  const restore=async url=>{listeners.native({type:'restore-document',tabId:1,url});await tick();};
  return {listeners,events,live,request,navigate,commit,tick,snapshot,restore,
    configure:disabledHosts=>listeners.native({type:'configuration',work:true,disabledHosts}),
    hold:fn=>{contextReply=fn;}};
}

test('Android attachment retains real cancellations from the old live document',async()=>{
  const h=await harness();h.navigate(oldURL);await h.commit(oldURL);
  assert.equal(h.request('http://localhost:8765/ads/cbr.js',oldURL).cancel,true);
  h.navigate(downloadURL);
  assert.equal(h.request('http://localhost:8765/ads/cbr.js?pending=1',oldURL).cancel,true);
  assert.equal(h.request('http://localhost:8765/api/1/envelope?sentry_key=fixture',oldURL,'ping').cancel,true);
  await h.restore(oldURL);
  assert.equal(h.snapshot().host,'localhost');assert.equal(h.snapshot().blocked,3);
  assert.equal(h.snapshot().filters,2);assert.equal(h.snapshot().telemetry,1);
  await h.restore(oldURL);assert.equal(h.snapshot().blocked,3,'A duplicate restore must not clear or invent counters.');
  assert.equal(h.events.some(value=>value.type==='failure'),false);
  assert.equal(h.request('http://localhost:8765/ads/cbr.js?after=1',oldURL).cancel,true);
  assert.equal(h.snapshot().blocked,4);
});

test('Android cross-host attachment exceptions keep the actual document policy in both directions',async()=>{
  for(const disabled of ['localhost','127.0.0.1']) {
    const h=await harness();h.configure([disabled]);h.navigate(oldURL);await h.commit(oldURL);h.navigate(downloadURL);
    const expected=disabled==='localhost'?undefined:true;
    assert.equal(h.request('http://localhost:8765/ads/cbr.js',oldURL).cancel,expected,'Pending attachment must not supply the site exception.');
    assert.equal(h.request('http://127.0.0.1:8765/third-party/probe.js',oldURL).cancel,expected);
    assert.equal(h.request('http://localhost:8765/api/1/envelope?sentry_key=fixture',oldURL,'ping').cancel,true);
    await h.restore(oldURL);
    assert.equal(h.request('http://localhost:8765/ads/cbr.js?after=1',oldURL).cancel,expected);
    assert.equal(h.snapshot().blocked,disabled==='localhost'?1:4);
    assert.equal(h.snapshot().telemetry,1);
  }
});

test('An asynchronous attachment restore cannot overwrite a newer committed document',async()=>{
  const h=await harness();h.navigate(oldURL);await h.commit(oldURL);h.navigate(downloadURL);
  let resolve;h.hold(()=>new Promise(done=>{resolve=done;}));
  h.listeners.native({type:'restore-document',tabId:1,url:oldURL});
  h.navigate('https://new.example.org/page');await h.commit('https://new.example.org/page',newId);
  resolve({url:oldURL,documentId:oldId});await h.tick();
  assert.equal(h.snapshot().host,'new.example.org');assert.equal(h.snapshot().blocked,0);
  assert.equal(h.events.some(value=>value.type==='failure'),false,'Superseded replies are ignored, not turned into browser failures.');
});

test('Trusted same-document history changes retain identity and genuine counts across an attachment',async()=>{
  const h=await harness();h.navigate(oldURL);await h.commit(oldURL);
  h.request('http://localhost:8765/ads/cbr.js',oldURL);
  const changed='http://localhost:8765/updated-route#section';h.live.set(1,{url:changed,documentId:oldId});
  h.listeners.history({tabId:1,frameId:0,url:changed});await h.tick();h.navigate(downloadURL);
  await h.restore(changed);assert.equal(h.snapshot().host,'localhost');assert.equal(h.snapshot().blocked,1);
  assert.equal(h.events.some(value=>value.type==='failure'),false);
});

test('Website messages cannot assert a document identity or restore counters',async()=>{
  const h=await harness();h.navigate(oldURL);await h.commit(oldURL);h.navigate(downloadURL);
  await h.listeners.message({type:'snapshot',documentId:oldId},{id:'website.example',tab:{id:1},frameId:0,url:oldURL});
  await h.listeners.message({type:'restore-document',tabId:1,url:oldURL},{id:extensionId,tab:{id:1},frameId:0,url:oldURL});
  assert.equal(h.snapshot().host,'127.0.0.1');
});

test('The isolated document identity works on ordinary HTTP without the secure-context randomUUID API',async()=>{
  let listener;const native=[];
  const sandbox=vm.createContext({crypto:{getRandomValues:array=>webcrypto.getRandomValues(array)},location:{href:'http://ordinary.example/page'},
    document:{readyState:'loading',addEventListener(){}},window:{addEventListener(){}},
    browser:{runtime:{onMessage:{addListener:value=>{listener=value;}},sendMessage:async()=>({tabId:1,snapshot:{ready:true}}),
      sendNativeMessage:async(_name,message)=>native.push(message)}}});
  vm.runInContext(fs.readFileSync(new URL('content.js',assets),'utf8'),sandbox);
  const context=await listener({type:'document-context'});await new Promise(resolve=>setImmediate(resolve));
  assert.match(context.documentId,/^[a-f0-9]{32}$/);assert.equal(context.url,'http://ordinary.example/page');
  assert.equal(native[0].documentId,context.documentId);assert.equal(vm.runInContext('window.documentId',sandbox),undefined);
});
