#!/usr/bin/env python3
"""Exercise an installed APK through real native UI and loopback fixture (MPL-2.0)."""
import argparse
import json
from pathlib import Path
import re
import shlex
import subprocess
import time
import urllib.request
import xml.etree.ElementTree as ET

def adb(*args):
    return subprocess.check_output(['adb',*args],stderr=subprocess.STDOUT).decode().strip()

def shell(command):return adb('shell',command)

def nodes():
    shell('uiautomator dump /sdcard/cyphra-window.xml')
    return list(ET.fromstring(shell('cat /sdcard/cyphra-window.xml')).iter('node'))

def click(label):
    for attempt in range(2):
        tree=nodes()
        for node in tree:
            if node.get('text','').casefold()==label.casefold() or node.get('content-desc')==label or node.get('hint')==label:
                x1,y1,x2,y2=map(int,re.findall(r'\d+',node.get('bounds')))
                shell(f'input tap {(x1+x2)//2} {(y1+y2)//2}');time.sleep(.4);return
        if attempt==0:
            bounds=[tuple(map(int,re.findall(r'\d+',n.get('bounds')))) for n in tree]
            width=max(b[2] for b in bounds);height=max(b[3] for b in bounds)
            shell(f'input swipe {width//2} {int(height*.75)} {width//2} {int(height*.35)} 300')
            time.sleep(.3)
    raise AssertionError('Native control missing: '+label)

def ready():
    for _ in range(25):
        tree=nodes()
        failure=[n.get('text') for n in tree if 'Protection could not start' in n.get('text','')]
        if failure:raise AssertionError(failure)
        if any(n.get('content-desc')=='Address and Brave Search' and n.get('enabled')=='true' for n in tree):return
        time.sleep(1)
    raise AssertionError('Verified local protection did not become ready.')

def launch(package,mode,url=None):
    command=f'am start -W -n {package}/org.cyphra.browser.LauncherActivity --es mode {mode}'
    if url:command+=' -d '+shlex.quote(url)
    shell(command);ready()

def fixture(package,mode,run,shields='on',write=''):
    url=f'http://localhost:8765/?run={run}&mode={mode}&shields={shields}'
    if write:url+='&write='+write
    launch(package,mode,url)
    for _ in range(40):
        with urllib.request.urlopen('http://127.0.0.1:8765/api/results?run='+run,timeout=5) as response:results=json.load(response)
        if results:
            result=results[-1]['result']
            assert all(result['checks'].values()),result
            return result
        time.sleep(1)
    raise AssertionError('Actual browser fixture did not report: '+run)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--expect-restored',action='store_true')
    parser.add_argument('--expected-personal-marker',help='Known cookie/storage marker from an earlier upgrade fixture.')
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    adb('reverse','tcp:8765','tcp:8765')
    run='native-'+str(int(time.time()));proof={'package':args.package,'fixture':{},'checks':[]}
    work=fixture(args.package,'work',run+'-work',write='WORK_MARKER')
    proof['fixture']['work']=work
    click('Cyphra Shields');tree=nodes()
    assert any(n.get('text')=='3' for n in tree),'Actual Work cancellation total is not 3.'
    (args.output/'work-shields.xml').write_text(shell('cat /sdcard/cyphra-window.xml'))
    subprocess.run(['adb','exec-out','screencap','-p'],stdout=(args.output/'work-shields.png').open('wb'),check=True)
    shell('input keyevent 4')
    personal=fixture(args.package,'personal',run+'-personal',write='PERSONAL_MARKER')
    expected=args.expected_personal_marker if args.expected_personal_marker is not None else 'PERSONAL_MARKER' if args.expect_restored else None
    assert personal['storage']['localBefore']==expected and personal['storage']['cookieBefore']==expected,personal
    proof['fixture']['personal']=personal
    assert not shell('pidof '+args.package+':work || true'),'Old Work process did not exit.'
    click('Cyphra Shields');assert any(n.get('text')=='2' for n in nodes()),'Personal total is not 2.'
    click('Shields for this site');shell('input keyevent 4')
    exception=fixture(args.package,'personal',run+'-exception',shields='off')
    proof['fixture']['exception']=exception
    click('Cyphra Shields');assert any(n.get('text')=='1' for n in nodes()),'Exception must retain telemetry denial.'
    click('Shields for this site');shell('input keyevent 4')
    restored=fixture(args.package,'work',run+'-work-restored')
    assert restored['storage']['localBefore']=='WORK_MARKER' and restored['storage']['cookieBefore']=='WORK_MARKER',restored
    assert not shell('pidof '+args.package+':personal || true'),'Old Personal process did not exit.'
    proof['fixture']['workRestored']=restored
    proof['checks']=['Gecko startup policy and local blocker readiness gates passed in both modes',
        'Actual Work/Personal/exception server hits match actual native Shields cancellation counts',
        'Telemetry beacon never reached the loopback server, including the site exception',
        'WebAuthn API is disabled in a secure context without loading proprietary GMS',
        'Real process exit occurs before entering the other mode',
        'Cookie/localStorage values are isolated and survive returning to the original profile']
    click('Home');tree=nodes();assert any(n.get('text')=='Security reading' for n in tree)
    subprocess.run(['adb','exec-out','screencap','-p'],stdout=(args.output/'home.png').open('wb'),check=True)
    click('Cyphra Shields');assert any(n.get('text')=='No website in this tab' for n in nodes());shell('input keyevent 4')
    proof['checks'].append('Native Home closes the old document and shows no website statistics')
    proof['passed']=True;(args.output/'proof.json').write_text(json.dumps(proof,indent=2)+'\n')
    print('PASS native browsing, real blocking, mode isolation and guarded passkeys: '+args.package)

if __name__=='__main__':main()
