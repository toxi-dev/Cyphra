/* This Source Code Form is subject to the Mozilla Public License, v. 2.0. */
package org.cyphra.browser;

import android.app.*;
import android.content.*;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.net.Uri;
import android.os.*;
import android.provider.MediaStore;
import android.text.InputType;
import android.view.*;
import android.view.inputmethod.InputMethodManager;
import android.widget.*;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.*;
import java.util.concurrent.*;
import org.json.*;
import org.mozilla.geckoview.*;

/** Native Android browser chrome. Work and Personal run in separate processes. */
public abstract class MainActivity extends Activity {
    static final int BG=0xff101113, PANEL=0xff191b1f, LINE=0xff2a2d33, TEXT=0xfff1f2f4, MUTED=0xff9298a2;
    private final ExecutorService jobs=Executors.newSingleThreadExecutor();
    private final ArrayList<Tab> tabs=new ArrayList<>();
    private BrowserStore store;
    private Engine engine;
    private UpdateClient updates;
    private SyncClient sync;
    private LinearLayout root, top, bottom;
    private FrameLayout content;
    private GeckoView gecko;
    private EditText address;
    private TextView modeLabel, tabCount, startup;
    private ProgressBar loading;
    private ImageButton back, forward, shield;
    private Tab current;
    private WebPrompts prompts;
    private String pendingUrl;
    private boolean ready, fullScreen;
    private AlertDialog activeShield;
    private LinearLayout shieldBody;
    private File pendingInstall;
    private UpdateClient.Offer pendingOffer;
    private boolean shuttingDown;
    private final BroadcastReceiver modeReceiver=new BroadcastReceiver(){
        @Override public void onReceive(Context context,Intent intent){if(mode().equals(intent.getStringExtra("mode")))shutdownProfile();}
    };

    protected abstract boolean workMode();
    public String mode(){return workMode()?"work":"personal";}
    private class Tab {
        GeckoSession session;
        String url="about:blank",title="New tab";
        final boolean privateTab;
        boolean canBack,canForward,desktop;
        GeckoSession.ProgressDelegate.SecurityInformation security;
        Tab(boolean privateTab){this.privateTab=privateTab;}
    }
    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        store=new BrowserStore(this,mode(),BuildConfig.EDITION);
        updates=new UpdateClient(this,store,new UpdateClient.Config(BuildConfig.EDITION,BuildConfig.REPOSITORY,
            BuildConfig.UPDATE_KEY_ID,BuildConfig.UPDATE_KEY_SPKI,BuildConfig.ASSET_PREFIX,BuildConfig.VERSION_NAME,
            BuildConfig.VERSION_CODE,getPackageName()));
        sync=new SyncClient(this,store);
        prompts=new WebPrompts(this,s->{for(Tab t:tabs)if(t.session==s)return t.url;return "";});
        pendingUrl=getIntent().getStringExtra("url");
        buildChrome();
        engine=Engine.get(this,workMode(),BuildConfig.TEAM,new Engine.Listener(){
            @Override public void onReady(){runOnUiThread(()->engineReady());}
            @Override public void onStats(GeckoSession s,Engine.Stats stats){runOnUiThread(()->{
                if(activeShield!=null && activeShield.isShowing() && current!=null && current.session==s) renderShields();
            });}
            @Override public void onFailure(String message){runOnUiThread(()->{
                startup.setText("Protection could not start. "+message); startup.setVisibility(View.VISIBLE);
                ready=false; address.setEnabled(false);
            });}
        });
        if(engine.isReady()) engineReady();
        IntentFilter closeFilter=new IntentFilter(getPackageName()+".CLOSE_MODE");
        if(Build.VERSION.SDK_INT>=33)registerReceiver(modeReceiver,closeFilter,Context.RECEIVER_NOT_EXPORTED);else registerReceiver(modeReceiver,closeFilter,getPackageName()+".permission.INTERNAL",null);
        if(Build.VERSION.SDK_INT>=33)getOnBackInvokedDispatcher().registerOnBackInvokedCallback(0,this::backAction);
    }
    private void buildChrome(){
        root=new LinearLayout(this); root.setOrientation(LinearLayout.VERTICAL);root.setBackgroundColor(BG);
        root.setOnApplyWindowInsetsListener((v,insets)->{
            if(Build.VERSION.SDK_INT>=30){
                android.graphics.Insets bars=insets.getInsets(WindowInsets.Type.systemBars()|WindowInsets.Type.displayCutout());
                android.graphics.Insets ime=insets.getInsets(WindowInsets.Type.ime());
                v.setPadding(bars.left,bars.top,bars.right,Math.max(bars.bottom,ime.bottom));
            }else v.setPadding(insets.getSystemWindowInsetLeft(),insets.getSystemWindowInsetTop(),insets.getSystemWindowInsetRight(),insets.getSystemWindowInsetBottom());
            return insets;
        });
        top=new LinearLayout(this);top.setGravity(Gravity.CENTER_VERTICAL);top.setPadding(dp(8),dp(6),dp(6),dp(6));
        ImageButton home=iconButton("home","Home",()->showHome());
        home.setImageResource(R.drawable.ic_logo);top.addView(home,new LinearLayout.LayoutParams(dp(42),dp(44)));
        address=input("Search Brave or enter address");address.setSingleLine(true);address.setTextSize(15);
        address.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_URI);
        address.setImeOptions(android.view.inputmethod.EditorInfo.IME_ACTION_GO);
        address.setPadding(dp(14),0,dp(10),0);address.setBackground(shape(PANEL,12,LINE));
        address.setSelectAllOnFocus(true);address.setEnabled(false);address.setContentDescription("Address and Brave Search");
        address.setOnEditorActionListener((v,action,event)->{navigateInput(address.getText().toString());return true;});
        top.addView(address,new LinearLayout.LayoutParams(0,dp(44),1));
        shield=iconButton("shield","Cyphra Shields",this::showShields);top.addView(shield,new LinearLayout.LayoutParams(dp(46),dp(44)));
        root.addView(top);
        loading=new ProgressBar(this,null,android.R.attr.progressBarStyleHorizontal);loading.setIndeterminate(true);
        loading.setVisibility(View.GONE);root.addView(loading,new LinearLayout.LayoutParams(-1,dp(2)));
        startup=text("Starting local protections…",13,MUTED);startup.setPadding(dp(20),dp(8),dp(20),dp(8));root.addView(startup);
        content=new FrameLayout(this);root.addView(content,new LinearLayout.LayoutParams(-1,0,1));
        gecko=new GeckoView(this);gecko.setBackgroundColor(BG);
        View divider=new View(this);divider.setBackgroundColor(LINE);root.addView(divider,new LinearLayout.LayoutParams(-1,dp(1)));
        bottom=new LinearLayout(this);bottom.setGravity(Gravity.CENTER_VERTICAL);bottom.setPadding(dp(4),0,dp(4),0);
        back=iconButton("back","Back",this::backAction);forward=iconButton("forward","Forward",()->{if(current!=null&&current.session!=null)current.session.goForward();});
        bottom.addView(back,new LinearLayout.LayoutParams(0,dp(54),1));bottom.addView(forward,new LinearLayout.LayoutParams(0,dp(54),1));
        modeLabel=text(workMode()?"Work":"Personal",12,TEXT);modeLabel.setGravity(Gravity.CENTER);modeLabel.setTypeface(null,Typeface.BOLD);
        modeLabel.setContentDescription("Switch Work or Personal profile");modeLabel.setOnClickListener(v->showModes());bottom.addView(modeLabel,new LinearLayout.LayoutParams(0,dp(54),1.5f));
        tabCount=text("1",13,TEXT);tabCount.setGravity(Gravity.CENTER);tabCount.setBackground(new IconDrawable("tabs",MUTED));
        FrameLayout tabButton=new FrameLayout(this);tabButton.setContentDescription("Tabs");tabButton.setOnClickListener(v->showTabs());
        FrameLayout.LayoutParams countLayout=new FrameLayout.LayoutParams(dp(25),dp(25),Gravity.CENTER);tabButton.addView(tabCount,countLayout);
        bottom.addView(tabButton,new LinearLayout.LayoutParams(0,dp(54),1));
        bottom.addView(iconButton("menu","Menu",this::showMenu),new LinearLayout.LayoutParams(0,dp(54),1));root.addView(bottom);
        setContentView(root);showHomeView();
    }
    private void engineReady(){
        if(ready||isFinishing())return;ready=true;address.setEnabled(true);startup.setVisibility(View.GONE);
        JSONArray stored=store.tabs();
        for(int i=0;i<stored.length()&&tabs.size()<20;i++){
            JSONObject entry=stored.optJSONObject(i);String url=entry==null?stored.optString(i):entry.optString("url");
            if(BrowserStore.isWebURL(url)){Tab tab=new Tab(false);tab.url=url;tab.title=entry==null?host(url):entry.optString("title",host(url));tabs.add(tab);}
        }
        if(tabs.isEmpty())tabs.add(new Tab(false));
        Tab initial=tabs.get(0);
        // Choose the incoming destination before opening Gecko. Loading a saved
        // URI and then another URI during startup can reorder native load events.
        if(BrowserStore.isWebURL(pendingUrl)){
            if(tabs.size()==1&&"about:blank".equals(initial.url))initial.url=pendingUrl;
            else if(tabs.size()<20){initial=new Tab(false);initial.url=pendingUrl;tabs.add(initial);}
            else initial.url=pendingUrl;
        }
        pendingUrl=null;select(initial);
    }
    private void prepare(Tab tab){prepare(tab,true);}
    private void prepare(Tab tab,boolean open){
        if(tab.session!=null)return;
        tab.session=engine.newSession(tab.privateTab,open);
        tab.session.setNavigationDelegate(new GeckoSession.NavigationDelegate(){
            @Override public void onLocationChange(GeckoSession s,String uri,List<GeckoSession.PermissionDelegate.ContentPermission> permissions,Boolean gesture){
                if(uri!=null){tab.url=uri;if(tab==current){address.setText(uri.equals("about:blank")?"":uri);refreshButtons();}saveTabs();}
            }
            @Override public void onCanGoBack(GeckoSession s,boolean value){tab.canBack=value;refreshButtons();}
            @Override public void onCanGoForward(GeckoSession s,boolean value){tab.canForward=value;refreshButtons();}
            @Override public GeckoResult<AllowOrDeny> onLoadRequest(GeckoSession s,LoadRequest request){
                String uri=request.uri;
                if(BrowserStore.isWebURL(uri)||"about:blank".equals(uri)||uri.startsWith("blob:")||uri.startsWith("view-source:http"))return GeckoResult.fromValue(AllowOrDeny.ALLOW);
                // App links never silently hand a page's request to another application.
                if(request.hasUserGesture&&(uri.startsWith("mailto:")||uri.startsWith("tel:"))){
                    new AlertDialog.Builder(MainActivity.this).setTitle("Open another app?").setMessage(uri)
                        .setPositiveButton("Open",(d,w)->{try{startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse(uri)));}catch(Exception e){toast("No app can open this link.");}})
                        .setNegativeButton("Cancel",null).show();
                }
                return GeckoResult.fromValue(AllowOrDeny.DENY);
            }
            @Override public GeckoResult<GeckoSession> onNewSession(GeckoSession s,String uri){
                if((!BrowserStore.isWebURL(uri)&&!"about:blank".equals(uri))||tabs.size()>=20)return GeckoResult.fromValue(null);
                Tab child=new Tab(tab.privateTab);child.url=uri;tabs.add(child);prepare(child,false);
                selectPopup(child);return GeckoResult.fromValue(child.session);
            }
            @Override public GeckoResult<String> onLoadError(GeckoSession s,String uri,WebRequestError error){
                if(tab==current){loading.setVisibility(View.GONE);showLoadError(uri,error);}
                return GeckoResult.fromValue(null);
            }
        });
        tab.session.setProgressDelegate(new GeckoSession.ProgressDelegate(){
            @Override public void onPageStart(GeckoSession s,String uri){prompts.dismissPending();engine.onPageStart(s,uri);if(tab==current)loading.setVisibility(View.VISIBLE);}
            @Override public void onPageStop(GeckoSession s,boolean success){
                if(tab==current)loading.setVisibility(View.GONE);
                if(success&&!tab.privateTab)store.recordVisit(tab.title,tab.url);saveTabs();
            }
            @Override public void onSecurityChange(GeckoSession s,SecurityInformation info){tab.security=info;}
        });
        tab.session.setContentDelegate(new GeckoSession.ContentDelegate(){
            @Override public void onTitleChange(GeckoSession s,String title){if(title!=null)tab.title=title;saveTabs();}
            @Override public void onFullScreen(GeckoSession s,boolean value){
                if(tab!=current)return;fullScreen=value;top.setVisibility(value?View.GONE:View.VISIBLE);bottom.setVisibility(value?View.GONE:View.VISIBLE);
            }
            @Override public void onContextMenu(GeckoSession s,int x,int y,ContextElement element){
                String url=element.linkUri;if(url==null||!BrowserStore.isWebURL(url))return;
                new AlertDialog.Builder(MainActivity.this).setTitle(host(url)).setItems(new String[]{"Open in new tab","Copy link"},(d,w)->{
                    if(w==0)newTab(tab.privateTab,url);else copy(url);
                }).show();
            }
            @Override public void onExternalResponse(GeckoSession s,WebResponse response){download(response);}
            @Override public void onCrash(GeckoSession s){tab.session=null;toast("This tab stopped. Reload to open it again.");}
            @Override public void onKill(GeckoSession s){tab.session=null;}
        });
        tab.session.setPromptDelegate(prompts);
        tab.session.setPermissionDelegate(prompts);
        BasicSelectionActionDelegate selections = new BasicSelectionActionDelegate(this);
        selections.enableExternalActions(false);
        tab.session.setSelectionActionDelegate(selections);
    }
    private void selectPopup(Tab tab){
        prompts.dismissPending();
        if(current!=null&&current.session!=null)current.session.setActive(false);
        current=tab;showGecko();gecko.setSession(tab.session);tab.session.setActive(true);refreshButtons();saveTabs();
    }
    private void select(Tab tab){
        prompts.dismissPending();
        if(current!=null&&current.session!=null)current.session.setActive(false);
        current=tab;tabCount.setText(Integer.toString(tabs.size()));
        address.setText("about:blank".equals(tab.url)?"":tab.url);
        if("about:blank".equals(tab.url))showHomeView();else{
            boolean fresh=tab.session==null;prepare(tab);showGecko();gecko.setSession(tab.session);tab.session.setActive(true);
            if(fresh)tab.session.loadUri(tab.url);
        }
        refreshButtons();saveTabs();
    }
    private void navigateInput(String raw){try{navigate(BrowserStore.navigation(raw));}catch(Exception e){toast(e.getMessage());}}
    private void navigate(String url){
        if(!ready){pendingUrl=url;return;}
        if(current==null)newTab(false,null);
        current.url=url;prepare(current);showGecko();gecko.setSession(current.session);current.session.setActive(true);current.session.loadUri(url);
        address.clearFocus();((InputMethodManager)getSystemService(INPUT_METHOD_SERVICE)).hideSoftInputFromWindow(address.getWindowToken(),0);
        address.setText(url);saveTabs();
    }
    private void newTab(boolean privateTab,String url){
        if(!ready){toast("Local protections are still starting.");return;}if(tabs.size()>=20){toast("Close a tab before opening another.");return;}
        Tab tab=new Tab(privateTab);tabs.add(tab);select(tab);if(url!=null)navigate(url);
    }
    private void close(Tab tab){
        if(tab.session!=null)tab.session.close();tabs.remove(tab);if(tabs.isEmpty())tabs.add(new Tab(false));
        if(current==tab)select(tabs.get(Math.max(0,tabs.size()-1)));tabCount.setText(Integer.toString(tabs.size()));saveTabs();
    }
    private void showGecko(){content.removeAllViews();if(gecko.getParent()!=null)((android.view.ViewGroup)gecko.getParent()).removeView(gecko);content.addView(gecko,new FrameLayout.LayoutParams(-1,-1));}
    private void showHome(){
        if(current==null){showHomeView();return;}
        prompts.dismissPending();
        if(current.session!=null){gecko.releaseSession();current.session.close();current.session=null;}
        current.canBack=false;current.canForward=false;current.security=null;current.url="about:blank";current.title="New tab";
        loading.setVisibility(View.GONE);address.setText("");showHomeView();saveTabs();
    }
    private void showHomeView(){
        content.removeAllViews();ScrollView scroll=new ScrollView(this);scroll.setFillViewport(true);LinearLayout body=column();body.setPadding(dp(28),dp(42),dp(28),dp(24));scroll.addView(body);
        LinearLayout identity=new LinearLayout(this);identity.setGravity(Gravity.CENTER_VERTICAL);
        ImageView logo=new ImageView(this);logo.setImageResource(R.drawable.ic_logo);identity.addView(logo,new LinearLayout.LayoutParams(dp(34),dp(34)));
        TextView title=text("Cyphra",32,TEXT);title.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));title.setPadding(dp(13),0,0,0);identity.addView(title);body.addView(identity);
        TextView profile=text(current!=null&&current.privateTab?"Private tab · "+mode():workMode()?"Work profile":"Personal profile",13,MUTED);profile.setPadding(0,dp(12),0,dp(30));body.addView(profile);
        LinearLayout search=new LinearLayout(this);search.setGravity(Gravity.CENTER_VERTICAL);search.setPadding(dp(14),0,dp(4),0);search.setBackground(shape(PANEL,14,LINE));
        ImageView searchIcon=new ImageView(this);searchIcon.setImageDrawable(new IconDrawable("search",MUTED));search.addView(searchIcon,new LinearLayout.LayoutParams(dp(20),dp(20)));
        EditText query=input("Search with Brave");query.setSingleLine(true);query.setTextSize(16);query.setBackgroundColor(Color.TRANSPARENT);query.setPadding(dp(12),0,0,0);
        query.setImeOptions(android.view.inputmethod.EditorInfo.IME_ACTION_SEARCH);query.setOnEditorActionListener((v,a,e)->{navigateInput(query.getText().toString());return true;});
        search.addView(query,new LinearLayout.LayoutParams(0,dp(58),1));search.addView(iconButton("search","Search with Brave",()->navigateInput(query.getText().toString())),new LinearLayout.LayoutParams(dp(46),dp(48)));body.addView(search);
        JSONArray bookmarks=store==null?new JSONArray():store.bookmarks();
        if(bookmarks.length()>0){section(body,"Bookmarks");for(int i=0;i<Math.min(4,bookmarks.length());i++){JSONObject b=bookmarks.optJSONObject(i);if(b!=null)row(body,b.optString("title",host(b.optString("url"))),host(b.optString("url")),()->navigate(b.optString("url")));}}
        section(body,"Security reading");
        row(body,"CISA","Alerts and advisories",()->navigate("https://www.cisa.gov/news-events/cybersecurity-advisories"));
        row(body,"PortSwigger","Research and web security",()->navigate("https://portswigger.net/research"));
        row(body,"NCSC","Guidance and news",()->navigate("https://www.ncsc.gov.uk/section/keep-up-to-date/all-blogs"));
        TextView offline=text("Nothing on this page loads until you open it.",12,MUTED);offline.setPadding(0,dp(24),0,0);body.addView(offline);
        content.addView(scroll,new FrameLayout.LayoutParams(-1,-1));refreshButtons();
    }
    private void refreshButtons(){
        if(back==null)return;back.setAlpha(current!=null&&current.canBack?.9f:.35f);forward.setAlpha(current!=null&&current.canForward?.9f:.35f);
        modeLabel.setText(current!=null&&current.privateTab?"Private":workMode()?"Work":"Personal");
        if(current!=null&&current.privateTab)getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);else getWindow().clearFlags(WindowManager.LayoutParams.FLAG_SECURE);
        if(Build.VERSION.SDK_INT>=33)setRecentsScreenshotEnabled(!workMode()&&(current==null||!current.privateTab));
        if(tabCount!=null)tabCount.setText(Integer.toString(Math.max(1,tabs.size())));
    }
    private void saveTabs(){if(store==null)return;JSONArray saved=new JSONArray();for(Tab tab:tabs)if(!tab.privateTab){JSONObject o=new JSONObject();try{o.put("url",tab.url);o.put("title",tab.title);}catch(JSONException ignored){}saved.put(o);}store.saveTabs(saved);}
    private void backAction(){if(fullScreen&&current!=null&&current.session!=null){current.session.exitFullScreen();return;}if(current!=null&&current.canBack&&current.session!=null){current.session.goBack();return;}if(current!=null&&!current.url.equals("about:blank")){showHome();return;}moveTaskToBack(true);}
    private void showTabs(){
        LinearLayout body=column();row(body,"New tab","",()->{newTab(false,null);dismissDialog(body);});row(body,"New private tab","Not saved to history or restored",()->{newTab(true,null);dismissDialog(body);});
        for(Tab tab:new ArrayList<>(tabs)){
            LinearLayout item=new LinearLayout(this);item.setGravity(Gravity.CENTER_VERTICAL);
            TextView label=text((tab.privateTab?"Private · ":"")+tab.title,15,TEXT);label.setMaxLines(2);label.setPadding(dp(16),dp(15),dp(8),dp(15));label.setOnClickListener(v->{select(tab);dismissDialog(body);});item.addView(label,new LinearLayout.LayoutParams(0,-2,1));
            item.addView(iconButton("close","Close tab",()->{close(tab);dismissDialog(body);showTabs();}),new LinearLayout.LayoutParams(dp(48),dp(48)));body.addView(item);
        }dialog("Tabs · "+(workMode()?"Work":"Personal"),body);
    }
    private void showModes(){new AlertDialog.Builder(this).setTitle("Profiles").setMessage("Work and Personal keep separate cookies, bookmarks and settings. Switching closes the current profile; its ordinary tabs are restored next time.")
        .setItems(new String[]{"Work · stricter protection","Personal · everyday browsing"},(d,w)->{
            if((w==0)==workMode())return;Intent intent=new Intent(this,LauncherActivity.class).putExtra("mode",w==0?"work":"personal").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);startActivity(intent);
        }).show();}
    private void showMenu(){
        final String[] actions={"New tab","New private tab","Reload","Bookmarks","History","Save bookmark","Desktop site","Share page","Site information","Tools","Settings"};
        new AlertDialog.Builder(this).setTitle("Cyphra").setItems(actions,(d,w)->{switch(w){
            case 0:newTab(false,null);break;case 1:newTab(true,null);break;case 2:if(current!=null&&!current.url.equals("about:blank")){if(current.session==null)navigate(current.url);else current.session.reload();}break;
            case 3:showSaved(false);break;case 4:showSaved(true);break;case 5:bookmark();break;
            case 6:if(current!=null&&current.session!=null){current.desktop=!current.desktop;current.session.getSettings().setUserAgentMode(current.desktop?GeckoSessionSettings.USER_AGENT_MODE_DESKTOP:GeckoSessionSettings.USER_AGENT_MODE_MOBILE);current.session.reload();}break;
            case 7:if(current!=null&&BrowserStore.isWebURL(current.url))startActivity(Intent.createChooser(new Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT,current.url),"Share page"));break;
            case 8:siteInfo();break;case 9:showTools();break;case 10:showSettings();break;
        }}).show();
    }
    private void showSaved(boolean history){
        JSONArray entries=history?store.history():store.bookmarks();LinearLayout body=column();
        if(entries.length()==0)row(body,history?"No saved history":"No bookmarks yet",history?"History is off by default in Work.":"Save a page from the menu.",null);
        for(int i=0;i<entries.length();i++){JSONObject item=entries.optJSONObject(i);if(item==null)continue;String url=item.optString("url");View entry=row(body,item.optString("title",host(url)),host(url),()->{navigate(url);dismissDialog(body);});
            if(!history)entry.setOnLongClickListener(v->{new AlertDialog.Builder(this).setTitle("Remove bookmark?").setMessage(item.optString("title",url)).setPositiveButton("Remove",(d,w)->{store.removeBookmark(url);dismissDialog(body);showSaved(false);}).setNegativeButton("Cancel",null).show();return true;});}
        if(history&&entries.length()>0)row(body,"Clear history","",()->{store.clearHistory();dismissDialog(body);showSaved(true);});dialog(history?"History":"Bookmarks",body);
    }
    private void bookmark(){if(current==null||!BrowserStore.isWebURL(current.url)){toast("Open a website to save it.");return;}if(current.privateTab){toast("Bookmarks are disabled in private tabs.");return;}store.addBookmark(current.title,current.url);toast("Bookmark saved in "+mode()+".");}
    private void showShields(){if(engine==null){toast("Protections are starting.");return;}shieldBody=column();activeShield=dialog("Cyphra Shields",shieldBody);activeShield.setOnDismissListener(d->{activeShield=null;shieldBody=null;});renderShields();}
    private void renderShields(){
        if(shieldBody==null)return;shieldBody.removeAllViews();String site=current==null?"":host(current.url);Engine.Stats stats=current==null||current.session==null?null:engine.snapshot(current.session);
        TextView domain=text(site.isEmpty()?"No website in this tab":site,20,TEXT);domain.setPadding(dp(16),dp(12),dp(16),dp(16));shieldBody.addView(domain);
        if(!site.isEmpty()){Switch enabled=new Switch(this);enabled.setText("Shields for this site");enabled.setTextColor(TEXT);enabled.setPadding(dp(16),dp(8),dp(16),dp(8));enabled.setChecked(engine.shieldsEnabled(site));enabled.setOnCheckedChangeListener((v,value)->{engine.setShieldsForHost(site,value);if(current!=null&&current.session!=null)current.session.reload();});shieldBody.addView(enabled);}
        TextView count=text(Integer.toString(stats==null?0:stats.blocked),44,TEXT);count.setTypeface(Typeface.create("sans-serif-light",Typeface.NORMAL));count.setPadding(dp(16),dp(8),dp(16),0);shieldBody.addView(count);
        row(shieldBody,"Requests blocked in this page",stats==null?"No page requests recorded":"Ads, trackers and telemetry: actual cancellations",null);
        if(stats!=null){row(shieldBody,"Telemetry blocked",Integer.toString(stats.telemetry),null);row(shieldBody,"Native tracking protection events",Integer.toString(stats.nativeBlocked)+" · counted separately",null);
            if(!stats.hosts.isEmpty()){section(shieldBody,"Blocked destinations");for(String destination:stats.hosts)row(shieldBody,destination,"",null);}}
        row(shieldBody,"DNS",engine.dnsChoice().equals("system")?"System DNS":engine.dnsUri(),null);
        row(shieldBody,workMode()?"Work defaults":"Personal defaults",workMode()?"Stricter filtering · WebGL off":"Balanced filtering · WebGL available",null);
    }
    private void siteInfo(){
        if(current==null||!BrowserStore.isWebURL(current.url)){toast("Open a website first.");return;}String info=current.url;
        if(current.security!=null){info+="\n\n"+(current.security.isSecure?"Encrypted HTTPS connection":"Connection is not verified HTTPS");if(current.security.certificate!=null)info+="\n\nCertificate issuer:\n"+current.security.certificate.getIssuerX500Principal().getName();}
        new AlertDialog.Builder(this).setTitle("Site information").setMessage(info).setPositiveButton("Done",null).show();
    }
    private void showLoadError(String uri,WebRequestError error){
        LinearLayout body=column();body.setPadding(dp(28),dp(44),dp(28),dp(24));body.addView(text("This page could not load",24,TEXT));row(body,host(uri),"",null);
        row(body,"Connection error",Integer.toString(error.code),null);
        if(engine!=null&&!engine.dnsChoice().equals("system"))row(body,"Encrypted DNS",engine.dnsUri()+"\nNo silent fallback to System DNS.",null);
        row(body,"Retry","",()->navigate(uri));row(body,"DNS settings","",this::showDns);content.removeAllViews();content.addView(body);
    }
    private void showSettings(){
        LinearLayout body=column();row(body,"Profiles",workMode()?"Work":"Personal",this::showModes);row(body,"DNS",engine.dnsChoice(),this::showDns);
        row(body,"Default browser","Choose Cyphra in Android settings",()->{
            android.app.role.RoleManager roles=(android.app.role.RoleManager)getSystemService(ROLE_SERVICE);
            if(roles!=null&&roles.isRoleAvailable(android.app.role.RoleManager.ROLE_BROWSER))startActivityForResult(roles.createRequestRoleIntent(android.app.role.RoleManager.ROLE_BROWSER),53);
        });
        Switch history=new Switch(this);history.setText("Save browsing history");history.setTextColor(TEXT);history.setPadding(dp(16),dp(16),dp(16),dp(16));history.setChecked(store.booleanPref("save-history",!workMode()));history.setOnCheckedChangeListener((v,on)->store.setBooleanPref("save-history",on));body.addView(history);
        row(body,"Encrypted sync",sync.isPaired()?"Paired · manual sync":"Not paired",this::showSync);
        row(body,"Updates","Manual checks · "+BuildConfig.VERSION_NAME,this::showUpdates);
        row(body,"Clear browsing data","Cookies, website storage, cache and local history",()->new AlertDialog.Builder(this).setTitle("Clear "+mode()+" browsing data?").setMessage("Bookmarks and settings are kept. This signs you out of websites in this profile.")
            .setPositiveButton("Clear",(d,w)->engine.runtime.getStorageController().clearData(StorageController.ClearFlags.ALL).accept(v->{store.clearHistory();toast("Browsing data cleared.");},e->toast("Could not clear browsing data."))).setNegativeButton("Cancel",null).show());
        row(body,"About Cyphra","GeckoView · MPL-2.0 · no analytics SDK",()->new AlertDialog.Builder(this).setTitle("Cyphra "+BuildConfig.VERSION_NAME).setMessage((BuildConfig.TEAM?"Byte Team edition":"Public edition")+"\nGeckoView 157.0.20261005135250\n\nTelemetry and background update checks are disabled. Optional sync and updates contact only their configured services when requested.\n\nAndroid source and license notices are in the release.").setPositiveButton("Done",null).show());dialog("Settings",body);
    }
    private void showDns(){
        String[] choices={"toxitech","system","quad9","cloudflare","custom"};String[] labels={"Toxitech · encrypted","System DNS","Quad9 · encrypted","Cloudflare · encrypted","Custom HTTPS"};int selected=Arrays.asList(choices).indexOf(engine.dnsChoice());
        new AlertDialog.Builder(this).setTitle("DNS for "+mode()).setSingleChoiceItems(labels,selected,(d,w)->{
            d.dismiss();if(w==4){EditText custom=input("https://resolver.example/dns-query");custom.setText(engine.dnsChoice().equals("custom")?engine.dnsUri():"");LinearLayout body=column();body.setPadding(dp(16),0,dp(16),0);body.addView(custom);
                AlertDialog dialog=new AlertDialog.Builder(this).setTitle("Custom encrypted DNS").setView(body).setPositiveButton("Save",null).setNegativeButton("Cancel",null).create();dialog.setOnShowListener(x->dialog.getButton(-1).setOnClickListener(v->{try{engine.setDns("custom",custom.getText().toString());toast("Custom DNS saved.");dialog.dismiss();}catch(Exception e){custom.setError(e.getMessage());}}));dialog.show();
            }else{try{engine.setDns(choices[w],"");toast("DNS saved for "+mode()+".");}catch(Exception e){toast(e.getMessage());}}
        }).setNegativeButton("Cancel",null).show();
    }
    private void showUpdates(){
        if(current!=null&&current.privateTab){toast("Updates are disabled in private tabs.");return;}
        LinearLayout body=column();row(body,"Installed version",BuildConfig.VERSION_NAME+" · "+BuildConfig.EDITION,null);row(body,"Check GitHub","No automatic checks or silent installs",this::checkUpdates);
        if(BuildConfig.TEAM){row(body,"Repository read token",updates.hasToken()?"Stored with Android Keystore":"Required for private releases",()->{EditText token=input("GitHub repository read token");token.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD);LinearLayout holder=column();holder.setPadding(dp(16),0,dp(16),0);holder.addView(token);
            AlertDialog d=new AlertDialog.Builder(this).setTitle("Private GitHub updates").setMessage("Use a token limited to Cyphra-Browser, Contents: read.").setView(holder).setPositiveButton("Save",null).setNegativeButton("Cancel",null).create();d.setOnShowListener(x->d.getButton(-1).setOnClickListener(v->{try{updates.configureToken(token.getText().toString());token.setText("");d.dismiss();toast("Token saved.");}catch(Exception e){token.setError(e.getMessage());}}));d.show();});
            if(updates.hasToken())row(body,"Remove token","",()->{try{updates.forgetToken();toast("Token removed.");}catch(Exception e){toast("Could not remove token.");}});}dialog("Updates",body);
    }
    private void checkUpdates(){busy("Checking GitHub…",()->{
        UpdateClient.Offer offer=updates.check();return offer;
    },value->{UpdateClient.Offer offer=(UpdateClient.Offer)value;if(offer==null||!offer.newer){toast("Cyphra is up to date.");return;}
        new AlertDialog.Builder(this).setTitle("Cyphra "+offer.version).setMessage("Download the signed release and verify it before opening Android's installer?")
            .setPositiveButton("Download",(d,w)->busy("Downloading and verifying update…",()->{File file=updates.download(offer);updates.verifyForInstall(file,offer);return file;},file->{pendingInstall=(File)file;pendingOffer=offer;installUpdate();}))
            .setNegativeButton("Later",null).show();});}
    private void installUpdate(){
        if(pendingInstall==null)return;
        if(!getPackageManager().canRequestPackageInstalls()){
            new AlertDialog.Builder(this).setTitle("Allow Cyphra updates").setMessage("Android needs permission for Cyphra to open its package installer. Return here after allowing it.")
                .setPositiveButton("Open settings",(d,w)->startActivityForResult(new Intent(android.provider.Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,Uri.parse("package:"+getPackageName())),52)).setNegativeButton("Cancel",null).show();return;
        }
        busy("Verifying APK…",()->{updates.verifyForInstall(pendingInstall,pendingOffer);return pendingInstall;},value->{
            Uri uri=UpdateProvider.uri(this,(File)value);Intent intent=new Intent(Intent.ACTION_VIEW).setDataAndType(uri,"application/vnd.android.package-archive").addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);try{startActivity(intent);}catch(Exception e){toast("Android's installer is unavailable.");}
        });
    }
    private void showSync(){
        if(current!=null&&current.privateTab){toast("Sync is disabled in private tabs.");return;}LinearLayout body=column();
        if(sync.isPaired()){row(body,"Server",sync.endpoint(),null);row(body,"Sync now","Bookmarks and selected settings only",()->busy("Syncing encrypted bookmarks…",()->sync.sync(),result->toast(result.toString())));row(body,"Disconnect","Local data stays on this device",()->{sync.disconnect();toast("Sync disconnected.");});}
        else{row(body,"Create a vault","Invitation required",()->syncSetup(true));row(body,"Pair this device","Use your existing pairing code",()->syncSetup(false));}
        row(body,"Separate vaults",workMode()?"Work vault · "+BuildConfig.EDITION:"Personal vault · "+BuildConfig.EDITION,null);dialog("Encrypted sync",body);
    }
    private void syncSetup(boolean create){
        LinearLayout body=column();body.setPadding(dp(18),0,dp(18),0);EditText endpoint=input("HTTPS sync server");endpoint.setText(BuildConfig.TEAM?"https://dns.toxitechnetwork.org/cyphra-sync":"");body.addView(endpoint);
        EditText secret=input(create?"Creation invitation":"Pairing code");secret.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD);body.addView(secret);
        AlertDialog d=new AlertDialog.Builder(this).setTitle(create?"Create encrypted vault":"Pair encrypted vault").setView(body).setPositiveButton(create?"Create":"Pair",null).setNegativeButton("Cancel",null).create();
        d.setOnShowListener(x->d.getButton(-1).setOnClickListener(v->{String server=endpoint.getText().toString(),code=secret.getText().toString();d.dismiss();busy(create?"Creating encrypted vault…":"Pairing device…",()->{if(create)return sync.create(server,code);sync.pair(server,code);return null;},result->{secret.setText("");if(create){String pairing=(String)result;new AlertDialog.Builder(this).setTitle("Pairing code").setMessage("Keep this secret. It gives access to your "+mode()+" vault.\n\n"+pairing).setPositiveButton("Copy",(dialog,w)->copy(pairing)).setNegativeButton("Done",null).show();}else toast("Device paired. Use Sync now to merge bookmarks.");});}));d.show();
    }
    private void showTools(){new AlertDialog.Builder(this).setTitle("Tools").setItems(new String[]{"JSON format","Base64 encode","Base64 decode","URL encode","URL decode","SHA-256","Page source"},(d,w)->{if(w==6){if(current!=null&&BrowserStore.isWebURL(current.url))navigate("view-source:"+current.url);return;}tool(w);}).show();}
    private void tool(int operation){
        LinearLayout body=column();body.setPadding(dp(16),0,dp(16),0);EditText input=input("Input");input.setMinLines(3);input.setMaxLines(6);body.addView(input);TextView output=text("",14,TEXT);output.setTextIsSelectable(true);body.addView(output);
        AlertDialog d=new AlertDialog.Builder(this).setTitle(new String[]{"JSON format","Base64 encode","Base64 decode","URL encode","URL decode","SHA-256"}[operation]).setView(body).setPositiveButton("Run",null).setNegativeButton("Close",null).setNeutralButton("Copy output",(x,w)->copy(output.getText().toString())).create();
        d.setOnShowListener(x->d.getButton(-1).setOnClickListener(v->{try{String value=input.getText().toString();if(value.length()>1024*1024)throw new IllegalArgumentException("Input is too large.");String result;
            switch(operation){case 0:result=value.trim().startsWith("[")?new JSONArray(value).toString(2):new JSONObject(value).toString(2);break;case 1:result=android.util.Base64.encodeToString(value.getBytes(StandardCharsets.UTF_8),android.util.Base64.NO_WRAP);break;case 2:result=new String(android.util.Base64.decode(value,android.util.Base64.DEFAULT),StandardCharsets.UTF_8);break;case 3:result=URLEncoder.encode(value,"UTF-8");break;case 4:result=URLDecoder.decode(value,"UTF-8");break;default:byte[] bytes=MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8));StringBuilder hex=new StringBuilder();for(byte b:bytes)hex.append(String.format(Locale.ROOT,"%02x",b&255));result=hex.toString();}output.setText(result);
        }catch(Exception error){output.setText("Could not process this input: "+error.getMessage());}}));d.show();
    }
    private void download(WebResponse response){
        if(response.body==null)return;String path=Uri.parse(response.uri).getLastPathSegment();String name=path==null||path.isEmpty()?"download":path.replaceAll("[^a-zA-Z0-9._-]","_");if(name.length()>100)name=name.substring(0,100);final String filename=name;
        new AlertDialog.Builder(this).setTitle("Save download?").setMessage(filename+"\n\n"+host(response.uri)).setPositiveButton("Save",(d,w)->busy("Saving download…",()->{
            ContentValues values=new ContentValues();values.put(MediaStore.Downloads.DISPLAY_NAME,filename);values.put(MediaStore.Downloads.MIME_TYPE,"application/octet-stream");values.put(MediaStore.Downloads.RELATIVE_PATH,Environment.DIRECTORY_DOWNLOADS+"/Cyphra");values.put(MediaStore.Downloads.IS_PENDING,1);
            Uri dest=getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI,values);if(dest==null)throw new IOException("Could not create download.");
            try(InputStream in=response.body;OutputStream out=getContentResolver().openOutputStream(dest)){if(out==null)throw new IOException("Could not write download.");byte[] b=new byte[32768];int n;while((n=in.read(b))!=-1)out.write(b,0,n);}catch(Exception e){getContentResolver().delete(dest,null,null);throw e;}
            ContentValues finished=new ContentValues();finished.put(MediaStore.Downloads.IS_PENDING,0);getContentResolver().update(dest,finished,null,null);return filename;
        },value->toast("Saved to Downloads/Cyphra."))).setNegativeButton("Cancel",(d,w)->{try{response.body.close();}catch(IOException ignored){}}).setOnCancelListener(d->{try{response.body.close();}catch(IOException ignored){}}).show();
    }
    private interface Task{Object run() throws Exception;}
    private void busy(String label,Task task,java.util.function.Consumer<Object> done){
        ProgressDialog dialog=new ProgressDialog(this);dialog.setMessage(label);dialog.setCancelable(false);dialog.show();
        jobs.submit(()->{try{Object value=task.run();runOnUiThread(()->{if(!isFinishing()){dialog.dismiss();done.accept(value);}});}catch(Exception e){runOnUiThread(()->{if(!isFinishing()){dialog.dismiss();new AlertDialog.Builder(this).setTitle("Could not complete this action").setMessage(e.getMessage()==null?"Please try again.":e.getMessage()).setPositiveButton("Done",null).show();}});}});
    }
    private AlertDialog dialog(String title,LinearLayout body){ScrollView scroll=new ScrollView(this);scroll.addView(body);AlertDialog d=new AlertDialog.Builder(this).setTitle(title).setView(scroll).setNegativeButton("Done",null).create();body.setTag(d);d.show();return d;}
    private void dismissDialog(View body){Object tag=body.getTag();if(tag instanceof Dialog)((Dialog)tag).dismiss();}
    private LinearLayout column(){LinearLayout v=new LinearLayout(this);v.setOrientation(LinearLayout.VERTICAL);return v;}
    private TextView text(String value,float size,int color){TextView v=new TextView(this);v.setText(value);v.setTextSize(size);v.setTextColor(color);return v;}
    private EditText input(String hint){EditText v=new EditText(this);v.setHint(hint);v.setTextColor(TEXT);v.setHintTextColor(MUTED);v.setTextSize(15);return v;}
    private void section(LinearLayout body,String label){TextView v=text(label,12,MUTED);v.setTypeface(null,Typeface.BOLD);v.setPadding(0,dp(30),0,dp(10));body.addView(v);}
    private View row(LinearLayout body,String title,String detail,Runnable action){LinearLayout item=column();item.setPadding(dp(16),dp(13),dp(16),dp(13));item.addView(text(title,15,TEXT));if(detail!=null&&!detail.isEmpty()){TextView sub=text(detail,12,MUTED);sub.setPadding(0,dp(5),0,0);item.addView(sub);}if(action!=null){item.setBackground(selectable());item.setOnClickListener(v->action.run());}body.addView(item,new LinearLayout.LayoutParams(-1,-2));return item;}
    private android.graphics.drawable.Drawable selectable(){android.util.TypedValue value=new android.util.TypedValue();getTheme().resolveAttribute(android.R.attr.selectableItemBackground,value,true);return getDrawable(value.resourceId);}
    private ImageButton iconButton(String icon,String label,Runnable action){ImageButton v=new ImageButton(this);v.setImageDrawable(new IconDrawable(icon,TEXT));v.setPadding(dp(12),dp(12),dp(12),dp(12));v.setBackground(selectable());v.setContentDescription(label);v.setOnClickListener(w->action.run());return v;}
    private GradientDrawable shape(int color,int radius,int border){GradientDrawable d=new GradientDrawable();d.setColor(color);d.setCornerRadius(dp(radius));d.setStroke(dp(1),border);return d;}
    private int dp(int n){return Math.round(n*getResources().getDisplayMetrics().density);}
    private String host(String url){try{String host=Uri.parse(url).getHost();return host==null?"":host;}catch(Exception e){return "";}}
    private void toast(String message){Toast.makeText(this,message==null?"Could not complete the action.":message,Toast.LENGTH_SHORT).show();}
    private void copy(String value){((ClipboardManager)getSystemService(CLIPBOARD_SERVICE)).setPrimaryClip(ClipData.newPlainText("Cyphra",value));toast("Copied.");}
    @Override protected void onNewIntent(Intent intent){super.onNewIntent(intent);setIntent(intent);String url=intent.getStringExtra("url");if(BrowserStore.isWebURL(url))navigate(url);}
    @Override protected void onPause(){saveTabs();if(current!=null&&current.session!=null)current.session.setActive(false);super.onPause();}
    @Override protected void onResume(){super.onResume();if(current!=null&&current.session!=null)current.session.setActive(true);}
    // API 33+ uses the native OnBackInvokedDispatcher registered above.
    // This override is the required fallback only on Android 10–12.
    @android.annotation.SuppressLint("GestureBackNavigation")
    @Override public void onBackPressed(){if(Build.VERSION.SDK_INT<33)backAction();}
    private void shutdownProfile(){
        if(shuttingDown||engine==null)return;shuttingDown=true;ready=false;saveTabs();prompts.dismissPending();
        engine.shutdownGracefully(()->{finishAndRemoveTask();android.os.Process.killProcess(android.os.Process.myPid());});
    }
    @Override protected void onDestroy(){try{unregisterReceiver(modeReceiver);}catch(Exception ignored){}if(engine!=null){engine.setListener(null);if(!shuttingDown)shutdownProfile();}if(prompts!=null)prompts.dismissPending();jobs.shutdown();super.onDestroy();}
    @Override protected void onActivityResult(int request,int result,Intent data){super.onActivityResult(request,result,data);if(request==52){if(getPackageManager().canRequestPackageInstalls())installUpdate();}else prompts.onActivityResult(request,result,data);}
    @Override public void onRequestPermissionsResult(int request,String[] permissions,int[] results){super.onRequestPermissionsResult(request,permissions,results);prompts.onRequestPermissionsResult(request,results);}
}
