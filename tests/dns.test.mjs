import test from 'node:test';
import assert from 'node:assert/strict';
import { makeQuery, readResponse } from '../browser/modules/dns.sys.mjs';

test('DNS diagnostic uses a real DNS question with a matching transaction ID', () => {
  const q=makeQuery('example.com', 0x1234);
  assert.equal(q.host,'example.com');
  assert.deepEqual([...q.bytes.slice(0,12)],[0x12,0x34,1,0,0,1,0,0,0,0,0,0]);
  const answer=Uint8Array.from([...q.bytes,192,12,0,1,0,1,0,0,0,60,0,4,192,0,2,1]);
  answer[2]=0x81;answer[3]=0x80;answer[7]=1;
  assert.deepEqual(readResponse(answer,0x1234),['192.0.2.1']);
  assert.throws(()=>readResponse(answer,0x4321),/match/);
  answer[3]=0x83;
  assert.throws(()=>readResponse(answer,0x1234),/NXDOMAIN/);
});
test('DNS diagnostic rejects invalid names and malformed DNS responses', () => {
  for (const name of ['bad..example','-bad.example','a'.repeat(64)+'.example','[::1]']) assert.throws(()=>makeQuery(name,1));
  assert.throws(()=>readResponse(new Uint8Array(2),1),/invalid/);
  const q=makeQuery('example.com',1);q.bytes[2]=0x81;q.bytes[7]=1;
  assert.throws(()=>readResponse(q.bytes,1),/malformed/);
});

test('DNS choices require explicit system mode or a complete credential-free HTTPS endpoint', async () => {
  const {validateDNSChoice,DNS} = await import('../browser/modules/dns.sys.mjs');
  assert.deepEqual(validateDNSChoice({selection:'system'}),{selection:'system',mode:5,uri:''});
  assert.equal(validateDNSChoice({selection:'quad9'}).uri,'https://dns.quad9.net/dns-query');
  assert.equal(validateDNSChoice({selection:'cloudflare'}).mode,3);
  assert.equal(validateDNSChoice({selection:'toxitech'}).uri,'https://dns.toxitechnetwork.org/dns-query');
  for (const uri of ['http://dns.example/dns-query','https://user:secret@dns.example/dns-query','https://dns.example/','https://dns.example/dns-query?token=secret','https://dns.example/dns-query#x',' https://dns.example/dns-query']) {
    assert.throws(()=>validateDNSChoice({selection:'custom',uri}));
  }
  const values = new Map([['network.trr.mode',3],['network.trr.uri','https://dns.toxitechnetwork.org/dns-query']]);
  globalThis.Services={prefs:{prefIsLocked:()=>false,setStringPref:(k,v)=>values.set(k,v),setIntPref:(k,v)=>values.set(k,v),getStringPref:(k,d)=>values.get(k)??d,getIntPref:(k,d)=>values.get(k)??d},dns:{clearCache(){}}};
  assert.equal(DNS.configure({selection:'system'}).mode,5);
  assert.equal(values.get('network.trr.uri'),'');
  assert.equal(DNS.configure({selection:'custom',uri:'https://resolver.example/dns-query'}).mode,3);
  assert.equal(DNS.configure({selection:'custom',uri:'https://dns.toxitechnetwork.org/dns-query'}).selection,'custom');
  values.set('cyphra.dns.selection','quad9');
  assert.equal(DNS.info().selection,'toxitech','A stale choice must not misreport the active resolver.');
  const saved=[...values]; assert.throws(()=>DNS.configure({selection:'custom',uri:'http://unsafe.example/dns-query'}));
  assert.deepEqual([...values],saved);
});
