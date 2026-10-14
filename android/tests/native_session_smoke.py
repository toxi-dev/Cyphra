#!/usr/bin/env python3
"""Test actual native tab restoration on a disposable rooted emulator (MPL-2.0).

Requires native_browser_fixture.py on host loopback port 8765 and an installed
APK. Closes existing Personal tabs through the UI; other profile data stays.
Root reads inspect only the ordinary-tab preference and its selected index.
"""
import argparse
import json
from pathlib import Path
import re
import shlex
import time
import urllib.request
import xml.etree.ElementTree as ET

from native_ui_smoke import adb, click, launch, nodes, shell


def session(package):
    path=f'/data/user/0/{package}/shared_prefs/cyphra-data-personal.xml'
    tree=ET.fromstring(shell('cat '+shlex.quote(path)))
    serialized=next((n.text for n in tree if n.get('name')=='tabs'),'[]')
    selected=next((int(n.get('value')) for n in tree if n.get('name')=='tabs-selected'),0)
    return {'tabs':json.loads(serialized or '[]'),'selected':selected}


def tab_url(tab):
    return tab.get('url','') if isinstance(tab,dict) else tab


def selected_url(state):
    assert state['tabs'],'No ordinary tabs were saved.'
    assert 0<=state['selected']<len(state['tabs']),state
    return tab_url(state['tabs'][state['selected']])


def tab_count():
    for node in nodes():
        if node.get('content-desc')=='Tabs':
            for child in node.iter('node'):
                value=child.get('text','')
                if value.isdecimal():return int(value)
    raise AssertionError('The native tab counter is missing.')


def assert_displayed(url):
    for _ in range(15):
        tree=nodes()
        address=next((n for n in tree if n.get('content-desc')=='Address and Brave Search'),None)
        displayed=address.get('text','') if address is not None else None
        if url=='about:blank':
            # Android's accessibility node exposes an empty EditText's hint as
            # its text on some releases. The native Home content is also checked.
            empty=displayed=='' or address is not None and displayed==address.get('hint')
            if empty and any(n.get('text')=='Security reading' for n in tree):return
        elif displayed==url:return
        time.sleep(.4)
    raise AssertionError(f'Expected native address {url!r}, saw {displayed!r}.')


def fixture_results(run):
    with urllib.request.urlopen('http://127.0.0.1:8765/api/results?run='+run,timeout=5) as response:
        return json.load(response)


def await_visit(run,previous):
    # Revisited URLs intentionally accumulate request counts. We require a new
    # actual page report, rather than reuse first-visit blocking expectations.
    for _ in range(35):
        results=fixture_results(run)
        if len(results)>previous:
            result=results[-1]['result']
            assert result['run']==run and result['secureContext'] is True,result
            return result
        time.sleep(1)
    raise AssertionError('Restored Gecko document did not report a new visit: '+run)


def restart(package,url=None):
    shell('am force-stop '+shlex.quote(package))
    launch(package,'personal',url)


def new_tab(private=False):
    click('Tabs');click('New private tab' if private else 'New tab')


def close_at(index):
    buttons=[n for n in nodes() if n.get('content-desc')=='Close tab']
    assert 0<=index<len(buttons),(index,len(buttons))
    x1,y1,x2,y2=map(int,re.findall(r'\d+',buttons[index].get('bounds')))
    assert y2>y1 and x2>x1,'The target close button is not visible.'
    shell(f'input tap {(x1+x2)//2} {(y1+y2)//2}');time.sleep(.5)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--package',required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if not re.fullmatch(r'org\.cyphra\.browser\.(team|public)(\.debug)?',args.package):
        parser.error('Use an installed Cyphra Team or Public package.')
    assert shell('id -u')=='0','Run adb root and adb wait-for-device before this disposable-emulator test.'
    args.output.mkdir(parents=True,exist_ok=True)
    adb('reverse','tcp:8765','tcp:8765')
    run='session-'+str(time.time_ns())
    urls={name:f'http://localhost:8765/?run={run}-{name}&mode=personal&shields=on'
          for name in ('first','second','private','incoming','private-close')}
    proof={'package':args.package,'mode':'personal','checks':[],'observed':{}}

    launch(args.package,'personal')
    original_count=tab_count()
    click('Tabs')
    for _ in range(original_count):click('Close tab')
    click('Done');assert_displayed('about:blank');assert tab_count()==1

    launch(args.package,'personal',urls['first']);await_visit(run+'-first',0)
    assert_displayed(urls['first'])
    new_tab();launch(args.package,'personal',urls['second']);await_visit(run+'-second',0)
    state=session(args.package)
    assert len(state['tabs'])==2 and selected_url(state)==urls['second'],state
    previous=len(fixture_results(run+'-second'))
    restart(args.package);assert_displayed(urls['second']);await_visit(run+'-second',previous)
    assert session(args.package)['selected']==1
    proof['checks'].append('Selected second ordinary page survives force-stop and relaunch; Gecko reports a new document visit')

    new_tab();assert_displayed('about:blank')
    state=session(args.package)
    assert len(state['tabs'])==3 and selected_url(state)=='about:blank',state
    restart(args.package);assert_displayed('about:blank');assert tab_count()==3
    assert selected_url(session(args.package))=='about:blank'
    proof['checks'].append('Selected native Home tab and the ordinary tab count survive restart')

    new_tab(True);launch(args.package,'personal',urls['private']);private=await_visit(run+'-private',0)
    assert all(private['checks'].values()),private
    assert private['storage']['localBefore'] is None and private['storage']['cookieBefore'] is None,private
    assert_displayed(urls['private']);assert tab_count()==4
    state=session(args.package)
    assert len(state['tabs'])==3 and selected_url(state)=='about:blank',state
    assert urls['private'] not in [tab_url(t) for t in state['tabs']]
    restart(args.package);assert_displayed('about:blank');assert tab_count()==3
    proof['checks'].append('A private page has isolated cookies/storage and real request filtering; it is excluded from saved tabs and restart returns to the last ordinary Home tab')

    restart(args.package,urls['incoming']);assert_displayed(urls['incoming'])
    await_visit(run+'-incoming',0)
    state=session(args.package)
    assert len(state['tabs'])==4 and state['selected']==3 and selected_url(state)==urls['incoming'],state
    assert [tab_url(t) for t in state['tabs'][:3]]==[urls['first'],urls['second'],'about:blank'],state
    proof['checks'].append('Incoming URI wins during startup without replacing the existing ordinary session')

    new_tab(True);launch(args.package,'personal',urls['private-close']);await_visit(run+'-private-close',0)
    click('Tabs');close_at(3);click('Done');assert_displayed(urls['private-close'])
    state=session(args.package)
    assert len(state['tabs'])==3 and selected_url(state)==urls['first'],state
    assert urls['incoming'] not in [tab_url(t) for t in state['tabs']]
    assert urls['private-close'] not in [tab_url(t) for t in state['tabs']]
    previous=len(fixture_results(run+'-first'))
    restart(args.package);assert_displayed(urls['first']);await_visit(run+'-first',previous)
    assert tab_count()==3
    proof['checks'].append('Closing the remembered ordinary tab while private stays active leaves a valid ordinary restart selection')

    proof['observed']={'ordinaryURLs':[tab_url(t) for t in session(args.package)['tabs']],
                       'selectedIndex':session(args.package)['selected'],'finalNativeTabCount':tab_count()}
    proof['passed']=True
    (args.output/'proof.json').write_text(json.dumps(proof,indent=2)+'\n')
    print('PASS native session restoration, Home, private exclusion and incoming URI: '+args.package)


if __name__=='__main__':main()
