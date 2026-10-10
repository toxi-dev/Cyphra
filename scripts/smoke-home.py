#!/usr/bin/env python3
"""Native trusted-input, bookmark and opt-in RSS qualification in a disposable profile."""
import base64
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import tempfile
import time
from marionette_driver.marionette import Marionette

ROOT = Path(__file__).resolve().parent.parent
EDITION = os.environ.get('CYPHRA_TEST_EDITION', json.loads((ROOT / 'cyphra.json').read_text()).get('edition', 'team'))
assert EDITION in ('team', 'public'), 'CYPHRA_TEST_EDITION must be team or public.'
METADATA = json.loads((ROOT / 'editions' / f'{EDITION}.json').read_text())
MODE = os.environ.get('CYPHRA_TEST_MODE', METADATA['defaultMode'])
assert MODE in ('work', 'personal'), 'CYPHRA_TEST_MODE must be work or personal.'
STAGE = ROOT / 'build/linux/Cyphra' if EDITION == 'team' else ROOT / 'build/public/linux/Cyphra'
LIVE_NEWS = os.environ.get('CYPHRA_LIVE_NEWS') == '1'
scratch = Path(tempfile.mkdtemp(prefix='cyphra-home-native-'))
child = None
driver = None

def wait(check, label, timeout=35):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        if child.poll() is not None:
            raise RuntimeError('Gecko exited during ' + label)
        time.sleep(.1)
    raise TimeoutError(label)

try:
    scratch.chmod(0o755)
    app = scratch / 'Cyphra'
    shutil.copytree(STAGE, app, symlinks=True)
    profile = scratch / 'profile'
    profile.mkdir(mode=0o777)
    profile.chmod(0o777)
    if os.getuid() == 0:
        os.chown(profile, 65534, 65534)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0)); port = sock.getsockname()[1]
    (profile / 'user.js').write_text(f'user_pref("marionette.port",{port});\nuser_pref("browser.sessionstore.resume_from_crash",false);\n')
    (profile / 'user.js').chmod(0o644)
    environment = dict(os.environ)
    environment['CYPHRA_MODE'] = MODE
    for key in list(environment):
        if key.startswith('MOZ_DISABLE_'):
            del environment[key]
    environment['MOZ_CRASHREPORTER_DISABLE'] = '1'
    environment['MOZ_LOG'] = 'nsHttp:3,nsHostResolver:3'
    environment['MOZ_LOG_FILE'] = str(profile / 'network.log')
    environment['DBUS_SESSION_BUS_ADDRESS'] = ''
    for name, variable in [('config', 'XDG_CONFIG_HOME'), ('cache', 'XDG_CACHE_HOME')]:
        directory = scratch / name
        directory.mkdir(mode=0o777)
        directory.chmod(0o777)
        if os.getuid() == 0:
            os.chown(directory, 65534, 65534)
        environment[variable] = str(directory)
    command = ['xvfb-run', '-a', '-s', '-screen 0 1440x940x24', str(app / 'runtime/librewolf'), '-app', str(app / 'runtime/browser/application.ini'), '-no-remote', '-profile', str(profile), '--marionette', '-remote-allow-system-access', '--width', '1440', '--height', '940']
    if os.getuid() == 0:
        command = ['runuser', '-u', 'nobody', '--'] + command
    with (scratch / 'process.log').open('wb') as log:
        child = subprocess.Popen(command, cwd=scratch, env=environment, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    def connected():
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=.1): return True
        except OSError: return False
    wait(connected, 'Marionette startup')
    driver = Marionette(host='127.0.0.1', port=port, socket_timeout=30)
    driver.start_session()
    driver.set_context(driver.CONTEXT_CHROME)
    wait(lambda: driver.execute_script('return Services.prefs.getBoolPref("cyphra.ready",false)&&!!document.getElementById("cyphra-mode");'), 'full staged Cyphra startup')
    assert driver.execute_script('return Services.appinfo.version;') == json.loads((ROOT / 'engine-lock.json').read_text())['geckoVersion']
    assert driver.execute_script('return CyphraModes.info();') == {'mode': MODE, 'edition': EDITION, 'profileIsolation': True}
    inserted = driver.execute_async_script('''
      const done=arguments[arguments.length-1];
      const { PlacesUtils }=ChromeUtils.importESModule('resource://gre/modules/PlacesUtils.sys.mjs');
      (async()=>{
        for (const entry of [{title:'Actual team bookmark',url:'https://example.com/team'}, {title:'Unsafe bookmarklet',url:'javascript:alert(1)'}, {title:'Credential bookmark',url:'https://secret@example.com/'}]) {
          await PlacesUtils.bookmarks.insert({...entry,parentGuid:PlacesUtils.bookmarks.toolbarGuid});
        }
        done(true);
      })().catch(error=>done({error:String(error)}));
    ''')
    assert inserted is True, inserted
    driver.set_context(driver.CONTEXT_CONTENT)
    driver.navigate('resource://cyphra-home/newtab.xhtml')
    driver.set_context(driver.CONTEXT_CHROME)
    print('Home actor:', json.dumps(driver.execute_script('''
      const b=gBrowser.selectedBrowser, g=b.browsingContext.currentWindowGlobal;
      try { const actor=g.getActor('CyphraHome'),bc=actor.browsingContext,embed=bc.top.embedderElement,win=embed?.ownerDocument?.defaultView; return {uri:g.documentURI.spec,managerURI:actor.manager.documentURI?.spec,remote:b.remoteType,actor:!!actor,bc:bc.id,top:bc.top.id,same:bc===bc.top,embed:!!embed,owner:!!win,windowtype:win?.document.documentElement.getAttribute('windowtype')}; }
      catch(error){return {error:String(error),uri:g.documentURI.spec,remote:b.remoteType};}
    ''')), flush=True)
    print('Home native bookmarks:', json.dumps(driver.execute_async_script('''
      const done=arguments[arguments.length-1];
      const {PlacesUtils}=ChromeUtils.importESModule('resource://gre/modules/PlacesUtils.sys.mjs');
      const entries=[];PlacesUtils.bookmarks.fetch({parentGuid:PlacesUtils.bookmarks.toolbarGuid},b=>entries.push({title:b.title,url:b.url?.href,type:b.type})).then(()=>done(entries)).catch(e=>done({error:String(e)}));
    ''')), flush=True)
    print('Home parent state:', json.dumps(driver.execute_async_script('''
      const done=arguments[arguments.length-1];
      try {gBrowser.selectedBrowser.browsingContext.currentWindowGlobal.getActor('CyphraHome').receiveMessage({name:'Cyphra:GetHome'}).then(done).catch(e=>done({error:String(e)}));}catch(error){done({error:String(error)});}
    ''')), flush=True)
    driver.set_context(driver.CONTEXT_CONTENT)
    print('Home content initial:', json.dumps(driver.execute_script('return {uri:document.documentURI,text:document.body.innerText.slice(-600)};')), flush=True)
    wait(lambda: driver.execute_script('return document.getElementById("cyphra-home-pins").children.length;'), 'native bookmark rendering')
    # XHTML is parsed as XML: an unqualified <svg> can exist without painting.
    rendering = driver.execute_async_script('''
      const done=arguments[arguments.length-1];
      (async()=>{
        const icons=['.search-leading svg','.search-submit svg','#cyphra-home-refresh svg'].map(selector=>{
          const icon=document.querySelector(selector);
          if (!icon || !(icon instanceof SVGSVGElement)) return {selector,rendered:false};
          const box=icon.getBBox(),rect=icon.getBoundingClientRect(),style=getComputedStyle(icon);
          return {selector,namespace:icon.namespaceURI,
            rendered:box.width>0&&box.height>0&&rect.width>0&&rect.height>0
              &&style.display!=='none'&&style.visibility==='visible'&&Number(style.opacity)>0
              &&style.stroke!=='none'&&parseFloat(style.strokeWidth)>0,
            geometry:{width:box.width,height:box.height}};
        });
        const logo=document.querySelector('.brand img');
        await logo.decode();
        const canvas=document.createElement('canvas');canvas.width=24;canvas.height=24;
        const context=canvas.getContext('2d');context.drawImage(logo,0,0,24,24);
        const pixels=context.getImageData(0,0,24,24).data;
        let paintedPixels=0;for(let i=3;i<pixels.length;i+=4) if(pixels[i]>0) paintedPixels++;
        done({icons,logo:{loaded:logo.complete&&logo.naturalWidth>0&&logo.naturalHeight>0,paintedPixels}});
      })().catch(error=>done({error:String(error)}));
    ''')
    assert 'error' not in rendering, rendering
    assert len(rendering['icons']) == 3 and all(icon.get('rendered') and icon['namespace'] == 'http://www.w3.org/2000/svg' for icon in rendering['icons']), rendering
    assert rendering['logo']['loaded'] and rendering['logo']['paintedPixels'] > 0, rendering
    print('PASS: both search magnifiers and briefing refresh have native SVG geometry; the unchanged logo paints.', json.dumps(rendering), flush=True)
    state = driver.execute_script('return {scripts:document.scripts.length,bridge:typeof window.cyphra,search:document.querySelector("form").action,submit:document.querySelector(".search-submit").textContent.trim(),icon:!!document.querySelector(".search-submit svg"),pins:[...document.querySelectorAll("#cyphra-home-pins a")].map(a=>({title:a.textContent,url:a.href})),news:document.getElementById("cyphra-home-articles").children.length,status:document.getElementById("cyphra-home-news-status").textContent};')
    assert state['scripts'] == 0 and state['bridge'] == 'undefined' and state['search'] == 'https://search.brave.com/search' and not state['submit'] and state['icon'], state
    assert any(pin['url'] == 'https://example.com/team' for pin in state['pins']), state
    assert all(not pin['url'].startswith('javascript:') and 'secret@' not in pin['url'] for pin in state['pins']), state
    assert state['news'] == 0, state
    assert driver.execute_script('return document.getElementById("cyphra-home-context").textContent;') == MODE.capitalize() + ' profile'
    assert driver.execute_script('return document.getElementById("cyphra-home-edition").textContent;') == METADATA['displayName']
    if EDITION == 'public':
        assert not driver.execute_script('return document.body.textContent.includes("Byte Team") || document.body.textContent.includes("Team DNS");')
    driver.execute_script('document.getElementById("cyphra-home-bookmarks").click(); document.getElementById("cyphra-home-refresh").click();')
    time.sleep(3)
    network = '\n'.join(p.read_text(errors='replace') for p in profile.glob('network.log*'))
    assert not any(host in network for host in ['www.cisa.gov','www.ncsc.gov.uk','portswigger.net']), 'Opening the page must not fetch news.'
    driver.set_context(driver.CONTEXT_CHROME)
    assert driver.execute_script('return !SidebarController.isOpen;'), 'Synthetic clicks must not invoke privileged controls.'
    assert driver.execute_script('''
      const {News}=ChromeUtils.importESModule('resource://cyphra/modules/news.sys.mjs');
      const {NEWS_FEEDS}=ChromeUtils.importESModule('resource://cyphra/modules/news-policy.sys.mjs');
      return NEWS_FEEDS.every(feed=>!News.isActiveFeedRequest(feed.url,'GET'))
        && !News.isActiveFeedRequest('https://www.cisa.gov/another-path','GET');
    '''), 'No permanent privileged feed exemption may exist.'
    driver.set_context(driver.CONTEXT_CONTENT)
    print('PASS: script-free Brave-only home, magnifying glass, sanitized real bookmarks and no automatic feed request.', flush=True)
    print('PASS: synthetic clicks cannot invoke the privileged home controls.', flush=True)
    # Native Marionette element clicks produce trusted user input, unlike DOM click().
    driver.find_element('id','cyphra-home-bookmarks').click()
    driver.set_context(driver.CONTEXT_CHROME)
    wait(lambda: driver.execute_script('return SidebarController.isOpen && SidebarController.currentID==="viewBookmarksSidebar";'), 'trusted bookmark control')
    driver.execute_script('SidebarController.hide();')
    driver.set_context(driver.CONTEXT_CONTENT)
    if LIVE_NEWS:
        # Exercise the SVG target inside the button, including actor delegation.
        driver.find_element('css selector','#cyphra-home-refresh svg').click()
        wait(lambda: driver.execute_script('return document.getElementById("cyphra-home-news-status").textContent.startsWith("Last refreshed ");'), 'actual RSS refresh', timeout=40)
        news = driver.execute_script('return {articles:[...document.querySelectorAll("#cyphra-home-articles a")].map(a=>({title:a.querySelector(".article-title").textContent,url:a.href})),status:document.getElementById("cyphra-home-news-status").textContent,errors:document.getElementById("cyphra-home-news-errors").textContent,scripts:document.scripts.length};')
        assert news['articles'] and len(news['articles']) <= 8 and news['scripts'] == 0, news
        assert not news['errors'], news
        cache = json.loads((profile / 'cyphra-news.json').read_text())
        assert {article['source'] for article in cache['articles']} == {'cisa','ncsc','portswigger'}, cache
        assert len(cache['articles']) <= 18 and isinstance(cache['updated'], int), cache
        assert (profile / 'cyphra-news.json').stat().st_mode & 0o777 == 0o600
        driver.set_context(driver.CONTEXT_CHROME)
        assert driver.execute_script('''
          const {News}=ChromeUtils.importESModule('resource://cyphra/modules/news.sys.mjs');
          const {NEWS_FEEDS}=ChromeUtils.importESModule('resource://cyphra/modules/news-policy.sys.mjs');
          return NEWS_FEEDS.every(feed=>!News.isActiveFeedRequest(feed.url,'GET')&&!News.isActiveFeedRequest(feed.url,'POST'));
        '''), 'Request exemptions must be removed after the user-requested fetch.'
        driver.set_context(driver.CONTEXT_CONTENT)
        print('PASS: trusted click fetched and sanitized real CISA, NCSC and PortSwigger RSS with actual dates.', flush=True)
        (ROOT / 'artifacts').mkdir(exist_ok=True)
        (ROOT / f'artifacts/cyphra-{EDITION}-{MODE}-home-news-native.png').write_bytes(base64.b64decode(driver.screenshot()))
        driver.refresh()
        wait(lambda: driver.execute_script('return document.getElementById("cyphra-home-articles").children.length;'), 'saved news rendering')
    else:
        print('SKIP: live RSS refresh; enable CYPHRA_LIVE_NEWS=1 for publisher qualification.', flush=True)
    driver.set_context(driver.CONTEXT_CHROME)
    normal_window = driver.current_chrome_window_handle
    old_windows = set(driver.chrome_window_handles)
    driver.execute_script('OpenBrowserWindow({private:true});')
    private_window = wait(lambda: list(set(driver.chrome_window_handles)-old_windows), 'private window')[0]
    driver.switch_to_window(private_window)
    wait(lambda: driver.execute_script('return !!document.getElementById("cyphra-rail");'), 'private UI installation')
    private_tab = driver.execute_script('return gBrowser.selectedBrowser.browsingContext.id;')
    # New windows have their own selected content context.
    driver.set_context(driver.CONTEXT_CONTENT)
    driver.navigate('resource://cyphra-home/newtab.xhtml')
    wait(lambda: driver.execute_script('return document.getElementById("cyphra-home-refresh").disabled;'), 'private refresh disabled')
    assert 'Private window' in driver.execute_script('return document.getElementById("cyphra-home-news-status").textContent;')
    assert 'Private window' in driver.execute_script('return document.getElementById("cyphra-home-context").textContent;')
    if LIVE_NEWS:
        assert driver.execute_script('return document.getElementById("cyphra-home-articles").children.length;') > 0
    driver.set_context(driver.CONTEXT_CHROME)
    result = driver.execute_async_script('''
      const done=arguments[arguments.length-1];
      gBrowser.selectedBrowser.browsingContext.currentWindowGlobal.getActor('CyphraHome')
        .receiveMessage({name:'Cyphra:RefreshNews',data:{isPrivate:false,url:'https://example.com/'}}).then(done).catch(e=>done({error:String(e)}));
    ''')
    assert result['isPrivate'] is True and 'normal window' in result['error'], result
    print('PASS: private windows cannot trigger news fetches; profile identity is accurate.', flush=True)
    print('PASS: native Cyphra home qualification.', flush=True)
except Exception:
    if driver:
        try:
            driver.set_context(driver.CONTEXT_CHROME)
            print('Native console:', json.dumps(driver.execute_script('return Services.console.getMessageArray().map(m=>m.message).slice(-20);')), flush=True)
        except Exception: pass
    print((scratch / 'process.log').read_text(errors='replace')[-10000:], flush=True)
    raise
finally:
    if driver:
        try: driver.quit()
        except Exception: pass
    if child and child.poll() is None:
        os.killpg(child.pid,signal.SIGTERM)
        try: child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid,signal.SIGKILL); child.wait(timeout=5)
    shutil.rmtree(scratch,ignore_errors=True)
