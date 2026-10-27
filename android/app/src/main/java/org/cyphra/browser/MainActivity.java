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
    // Keep Gecko's progress module enabled while ownership crosses Activities.
    // Re-enabling it emits an initial about:blank event even for a live tab.
    // This inert delegate holds no Activity or private-document references.
    private static final GeckoSession.ProgressDelegate RETAINED_PROGRESS = new GeckoSession.ProgressDelegate() {};
    private int BG,PANEL,LINE,TEXT,MUTED;
    private final ExecutorService jobs=Executors.newSingleThreadExecutor();
    private final ArrayList<Tab> tabs=new ArrayList<>();
    private final Set<Dialog> dialogs=Collections.newSetFromMap(new WeakHashMap<>());
    private BrowserStore store;
    private Appearance appearance;
    private AppearancePanel appearancePanel;
    private Engine engine;
    private Engine.Listener engineListener;
    private final Object sessionOwner=new Object();
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
    private Tab lastOrdinary;
    private WebPrompts prompts;
    private String pendingUrl;
    private String loadErrorUri;
    private WebRequestError lastLoadError;
    private boolean ready, fullScreen;
    private boolean tabsRestored;
    private boolean restoredLoading;
    private ShieldsPanel activeShield;
    private File pendingInstall;
    private UpdateClient.Offer pendingOffer;
    private boolean shuttingDown,destroyed;
    private final BroadcastReceiver modeReceiver=new BroadcastReceiver(){
        @Override public void onReceive(Context context,Intent intent){if(mode().equals(intent.getStringExtra("mode")))shutdownProfile();}
    };

    protected abstract boolean workMode();
    public String mode(){return workMode()?"work":"personal";}
    private static final class Tab {
        GeckoSession session;
        Object delegateOwner;
        String url="about:blank",title="New tab";
        final NavigationMemory navigation=new NavigationMemory();
        final boolean privateTab;
        boolean canBack,canForward,desktop;
        GeckoSession.ProgressDelegate.SecurityInformation security;
        GeckoSession.ProgressDelegate.SecurityInformation previousSecurity;
        Tab(boolean privateTab){this.privateTab=privateTab;}
    }
    /** Process-local handoff only: private tabs and live documents never enter saved state. */
    private static final class RetainedTabs {
        final ArrayList<Tab> tabs;
        final Tab current,lastOrdinary;
        final String pendingUrl,loadErrorUri;
        final WebRequestError loadError;
        final WebPrompts.PendingAndroidRequests androidRequests;
        final File pendingInstall;
        final UpdateClient.Offer pendingOffer;
        final boolean restored,loading,fullScreen;
        RetainedTabs(MainActivity activity){
            tabs=new ArrayList<>(activity.tabs);current=activity.current;lastOrdinary=activity.lastOrdinary;
            pendingUrl=activity.pendingUrl;loadErrorUri=activity.loadErrorUri;loadError=activity.lastLoadError;
            androidRequests=activity.prompts.pendingAndroidRequests();
            pendingInstall=activity.pendingInstall;pendingOffer=activity.pendingOffer;
            restored=activity.tabsRestored;loading=activity.loading.getVisibility()==View.VISIBLE;fullScreen=activity.fullScreen;
        }
    }
    @Override public void onCreate(Bundle saved) {
        super.onCreate(saved);
        if(!EditionPolicy.allowsMode(BuildConfig.EDITION,mode())){finish();return;}
        RetainedTabs retained=(RetainedTabs)getLastNonConfigurationInstance();
        if(retained!=null){
            tabs.addAll(retained.tabs);current=retained.current;lastOrdinary=retained.lastOrdinary;
            pendingUrl=retained.pendingUrl;loadErrorUri=retained.loadErrorUri;lastLoadError=retained.loadError;
            pendingInstall=retained.pendingInstall;pendingOffer=retained.pendingOffer;
            tabsRestored=retained.restored;restoredLoading=retained.loading;fullScreen=retained.fullScreen;
        }else pendingUrl=getIntent().getStringExtra("url");
        store=new BrowserStore(this,mode(),BuildConfig.EDITION);
        loadAppearance();
        updates=new UpdateClient(this,store,new UpdateClient.Config(BuildConfig.EDITION,BuildConfig.REPOSITORY,
            BuildConfig.UPDATE_KEY_ID,BuildConfig.UPDATE_KEY_SPKI,BuildConfig.ASSET_PREFIX,BuildConfig.VERSION_NAME,
            BuildConfig.VERSION_CODE,getPackageName()));
        sync=new SyncClient(this,store);
        prompts=new WebPrompts(this,appearance,s->{for(Tab t:tabs)if(t.session==s)return t.url;return "";});
        if(retained!=null)prompts.inheritPendingAndroidRequests(retained.androidRequests);
        buildChrome();
        engineListener=new Engine.Listener(){
            @Override public void onReady(){runOnUiThread(()->engineReady());}
            @Override public void onStats(GeckoSession s,Engine.Stats stats){runOnUiThread(()->{
                if(!destroyed && activeShield!=null && activeShield.isShowing() && current!=null && current.session==s) renderShields();
            });}
            @Override public void onFailure(String message){runOnUiThread(()->{
                if(destroyed)return;
                startup.setText("Protection could not start. "+message); startup.setVisibility(View.VISIBLE);
                ready=false; address.setEnabled(false);
            });}
        };
        engine=Engine.get(this,workMode(),BuildConfig.TEAM,engineListener);
        for(Tab tab:tabs)if(tab.session!=null)bindSession(tab);
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
        home.setImageResource(R.drawable.ic_logo);home.setImageTintList(android.content.res.ColorStateList.valueOf(TEXT));top.addView(home,new LinearLayout.LayoutParams(dp(48),dp(48)));
        address=input("Search Brave or enter address");address.setSingleLine(true);address.setTextSize(appearance.sp(15));
        address.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_URI);
        address.setImeOptions(android.view.inputmethod.EditorInfo.IME_ACTION_GO);
        address.setPadding(dp(14),0,dp(10),0);address.setBackground(shape(PANEL,12,LINE));
        address.setSelectAllOnFocus(true);address.setEnabled(false);address.setContentDescription("Address and Brave Search");
        address.setOnEditorActionListener((v,action,event)->{navigateInput(address.getText().toString());return true;});
        top.addView(address,new LinearLayout.LayoutParams(0,dp(48),1));
        shield=iconButton("shield","Cyphra Shields",this::showShields);top.addView(shield,new LinearLayout.LayoutParams(dp(48),dp(48)));
        root.addView(top);
        loading=new ProgressBar(this,null,android.R.attr.progressBarStyleHorizontal);loading.setIndeterminate(true);
        loading.setIndeterminateTintList(android.content.res.ColorStateList.valueOf(appearance.accentColor));loading.setVisibility(View.GONE);root.addView(loading,new LinearLayout.LayoutParams(-1,dp(2)));
        startup=text("Starting local protections…",13,MUTED);startup.setPadding(dp(20),dp(8),dp(20),dp(8));root.addView(startup);
        content=new FrameLayout(this);root.addView(content,new LinearLayout.LayoutParams(-1,0,1));
        if(gecko==null)gecko=new GeckoView(this){
            @Override public void onAttachedToWindow(){super.onAttachedToWindow();if(BuildConfig.DEBUG)android.util.Log.d("CyphraViewLifecycle","event=view-attached");}
            @Override public void onDetachedFromWindow(){if(BuildConfig.DEBUG)android.util.Log.d("CyphraViewLifecycle","event=view-detaching");super.onDetachedFromWindow();}
            @Override public void onWindowFocusChanged(boolean focused){super.onWindowFocusChanged(focused);if(BuildConfig.DEBUG)android.util.Log.d("CyphraViewLifecycle",focused?"event=view-focused":"event=view-unfocused");}
        };gecko.setBackgroundColor(BG);
        View divider=new View(this);divider.setBackgroundColor(LINE);root.addView(divider,new LinearLayout.LayoutParams(-1,dp(1)));
        bottom=new LinearLayout(this);bottom.setGravity(Gravity.CENTER_VERTICAL);bottom.setPadding(dp(4),0,dp(4),0);
        back=iconButton("back","Back",this::backAction);forward=iconButton("forward","Forward",()->{if(current!=null&&current.session!=null)current.session.goForward();});
        bottom.addView(back,new LinearLayout.LayoutParams(0,dp(appearance.toolbarHeight()),1));
        if(appearance.forward)bottom.addView(forward,new LinearLayout.LayoutParams(0,dp(appearance.toolbarHeight()),1));
        if(appearance.reload)bottom.addView(iconButton("refresh","Reload",this::reloadPage),new LinearLayout.LayoutParams(0,dp(appearance.toolbarHeight()),1));
        modeLabel=text(workMode()?"Work":"Personal",12,TEXT);modeLabel.setGravity(Gravity.CENTER);modeLabel.setTypeface(null,Typeface.BOLD);
        modeLabel.setContentDescription("Switch Work or Personal profile");modeLabel.setBackground(selectable());modeLabel.setOnClickListener(v->showModes());
        if(BuildConfig.HOME)bottom.addView(iconButton("bookmark","Bookmarks",()->showSaved(false)),new LinearLayout.LayoutParams(0,dp(appearance.toolbarHeight()),1));
        else bottom.addView(modeLabel,new LinearLayout.LayoutParams(0,dp(appearance.toolbarHeight()),1.5f));
        tabCount=text("1",13,TEXT);tabCount.setGravity(Gravity.CENTER);tabCount.setBackground(new IconDrawable("tabs",MUTED));
        FrameLayout tabButton=new FrameLayout(this);tabButton.setContentDescription("Tabs");tabButton.setOnClickListener(v->showTabs());
        FrameLayout.LayoutParams countLayout=new FrameLayout.LayoutParams(dp(25),dp(25),Gravity.CENTER);tabButton.addView(tabCount,countLayout);
        tabButton.setBackground(selectable());bottom.addView(tabButton,new LinearLayout.LayoutParams(0,dp(appearance.toolbarHeight()),1));
        bottom.addView(iconButton("menu","Menu",this::showMenu),new LinearLayout.LayoutParams(0,dp(appearance.toolbarHeight()),1));root.addView(bottom);
        setContentView(root);appearance.applyWindow(getWindow());showHomeView();
    }
    private void loadAppearance(){appearance=new Appearance(this,store);appearance.apply(this);BG=appearance.background;PANEL=appearance.panel;LINE=appearance.line;TEXT=appearance.text;MUTED=appearance.muted;}
    private void applyAppearance(){
        boolean wasLoading=loading!=null&&loading.getVisibility()==View.VISIBLE;CharSequence notice=startup==null?"":startup.getText();
        if(activeShield!=null)activeShield.dismiss();loadAppearance();if(prompts!=null)prompts.setAppearance(appearance);buildChrome();
        address.setEnabled(ready);startup.setVisibility(ready?View.GONE:View.VISIBLE);if(!ready)startup.setText(notice);loading.setVisibility(wasLoading?View.VISIBLE:View.GONE);
        if(current!=null&&!"about:blank".equals(current.url)){
            address.setText(current.url);
            if(lastLoadError!=null)showLoadError(loadErrorUri,lastLoadError);
            else{showGecko();if(current.session!=null)gecko.setSession(current.session);}
        }
        top.setVisibility(fullScreen?View.GONE:View.VISIBLE);bottom.setVisibility(fullScreen?View.GONE:View.VISIBLE);refreshButtons();
        if(appearancePanel!=null)appearancePanel.refresh();
    }
    private void showAppearance(){if(appearancePanel!=null&&appearancePanel.isShowing())return;appearancePanel=new AppearancePanel(this,store,this::applyAppearance,()->appearancePanel=null);appearancePanel.show();}
    private void reloadPage(){if(current!=null&&!"about:blank".equals(current.url)){if(current.session==null)navigate(current.url);else current.session.reload();}}
    private void engineReady(){
        if(ready||shuttingDown||destroyed||isFinishing())return;ready=true;address.setEnabled(true);startup.setVisibility(View.GONE);
        if(tabsRestored){
            // Reattach the same document/session, including private tabs. Reusing
            // the launch Intent or disk URLs here would create a second load.
            if(current!=null){
                address.setText("about:blank".equals(current.url)?"":current.url);
                if(lastLoadError!=null)showLoadError(loadErrorUri,lastLoadError);
                else if(!"about:blank".equals(current.url)){
                    boolean fresh=current.session==null;prepare(current);showGecko();gecko.setSession(current.session);current.session.setActive(true);
                    if(fresh)current.session.loadUri(current.url);
                }
            }
            loading.setVisibility(restoredLoading?View.VISIBLE:View.GONE);
            top.setVisibility(fullScreen?View.GONE:View.VISIBLE);bottom.setVisibility(fullScreen?View.GONE:View.VISIBLE);refreshButtons();
            String destination=pendingUrl;pendingUrl=null;if(BrowserStore.isWebURL(destination))navigate(destination);
            return;
        }
        JSONArray stored=store.tabs();
        for(int i=0;i<stored.length()&&tabs.size()<20;i++){
            JSONObject entry=stored.optJSONObject(i);String url=entry==null?stored.optString(i):entry.optString("url");
            if(BrowserStore.isWebURL(url)||"about:blank".equals(url)){Tab tab=new Tab(false);tab.url=url;tab.title="about:blank".equals(url)?"New tab":entry==null?host(url):entry.optString("title",host(url));tabs.add(tab);}
        }
        if(tabs.isEmpty())tabs.add(new Tab(false));
        Tab initial=tabs.get(Math.max(0,Math.min(store.selectedTab(),tabs.size()-1)));
        // Choose the incoming destination before opening Gecko. Loading a saved
        // URI and then another URI during startup can reorder native load events.
        if(BrowserStore.isWebURL(pendingUrl)){
            if(tabs.size()==1&&"about:blank".equals(initial.url))initial.url=pendingUrl;
            else if(tabs.size()<20){initial=new Tab(false);initial.url=pendingUrl;tabs.add(initial);}
            else initial.url=pendingUrl;
        }
        pendingUrl=null;tabsRestored=true;select(initial);
    }
    private void prepare(Tab tab){prepare(tab,true);}
    private void prepare(Tab tab,boolean open){
        if(tab.session!=null)return;
        tab.session=engine.newSession(tab.privateTab,open);
        bindSession(tab);
    }
    private void bindSession(Tab tab){
        tab.delegateOwner=sessionOwner;
        tab.session.setNavigationDelegate(new GeckoSession.NavigationDelegate(){
            @Override public void onLocationChange(GeckoSession s,String uri,List<GeckoSession.PermissionDelegate.ContentPermission> permissions,Boolean gesture){
                if(!ownsSession(tab,s,"location-stale"))return;
                if(uri!=null&&tab.navigation.location(uri)){tab.url=uri;if(tab==current){address.setText(uri.equals("about:blank")?"":uri);refreshButtons();}saveTabs();}
            }
            @Override public void onCanGoBack(GeckoSession s,boolean value){if(ownsSession(tab,s,"back-state-stale")){tab.canBack=value;refreshButtons();}}
            @Override public void onCanGoForward(GeckoSession s,boolean value){if(ownsSession(tab,s,"forward-state-stale")){tab.canForward=value;refreshButtons();}}
            @Override public GeckoResult<AllowOrDeny> onLoadRequest(GeckoSession s,LoadRequest request){
                if(!ownsSession(tab,s,"load-request-stale"))return GeckoResult.fromValue(AllowOrDeny.DENY);
                String uri=request.uri;
                if(BrowserStore.isWebURL(uri)||"about:blank".equals(uri)||uri.startsWith("blob:")||uri.startsWith("view-source:http")){
                    if(request.target==TARGET_WINDOW_CURRENT){long previous=tab.navigation.serial;tab.navigation.request(uri,request.isRedirect);if(previous!=tab.navigation.serial)tab.previousSecurity=tab.security;}
                    return GeckoResult.fromValue(AllowOrDeny.ALLOW);
                }
                // App links never silently hand a page's request to another application.
                if(request.hasUserGesture&&(uri.startsWith("mailto:")||uri.startsWith("tel:"))){
                    dialogBuilder().setTitle("Open another app?").setMessage(uri)
                        .setPositiveButton("Open",(d,w)->{try{startActivity(new Intent(Intent.ACTION_VIEW,Uri.parse(uri)));}catch(Exception e){toast("No app can open this link.");}})
                        .setNegativeButton("Cancel",null).show();
                }
                return GeckoResult.fromValue(AllowOrDeny.DENY);
            }
            @Override public GeckoResult<GeckoSession> onNewSession(GeckoSession s,String uri){
                if(!ownsSession(tab,s,"new-session-stale"))return GeckoResult.fromValue(null);
                if((!BrowserStore.isWebURL(uri)&&!"about:blank".equals(uri))||tabs.size()>=20)return GeckoResult.fromValue(null);
                Tab child=new Tab(tab.privateTab);child.url=uri;tabs.add(child);prepare(child,false);
                selectPopup(child);return GeckoResult.fromValue(child.session);
            }
            @Override public GeckoResult<String> onLoadError(GeckoSession s,String uri,WebRequestError error){
                if(!ownsSession(tab,s,"load-error-stale"))return GeckoResult.fromValue(null);
                if(tab==current){loading.setVisibility(View.GONE);showLoadError(uri,error);}
                return GeckoResult.fromValue(null);
            }
        });
        tab.session.setProgressDelegate(new GeckoSession.ProgressDelegate(){
            @Override public void onPageStart(GeckoSession s,String uri){
                if(!ownsSession(tab,s,"page-start-stale"))return;
                if(!tab.navigation.acceptsPageStart(uri)){traceNavigation("page-start-ignored",tab);return;}
                traceNavigation("page-start-before",tab);prompts.dismissPending();engine.onPageStart(s,uri);traceNavigation("page-start-after",tab);
                if(tab==current){boolean errorView=lastLoadError!=null;lastLoadError=null;loadErrorUri=null;if(errorView)showGecko();loading.setVisibility(View.VISIBLE);}
            }
            @Override public void onPageStop(GeckoSession s,boolean success){
                if(!ownsSession(tab,s,"page-stop-stale"))return;
                traceNavigation("page-stop",tab);
                if(tab==current)loading.setVisibility(View.GONE);
                if(success&&!tab.privateTab)store.recordVisit(tab.title,tab.url);saveTabs();
            }
            @Override public void onSecurityChange(GeckoSession s,SecurityInformation info){if(ownsSession(tab,s,"security-change-stale"))tab.security=info;}
        });
        tab.session.setContentDelegate(new GeckoSession.ContentDelegate(){
            @Override public void onTitleChange(GeckoSession s,String title){if(!ownsSession(tab,s,"title-change-stale"))return;traceNavigation("title-change",tab);if(title!=null){tab.title=title;tab.navigation.title(title);}saveTabs();}
            @Override public void onFullScreen(GeckoSession s,boolean value){
                if(!ownsSession(tab,s,"full-screen-stale")||tab!=current)return;fullScreen=value;top.setVisibility(value?View.GONE:View.VISIBLE);bottom.setVisibility(value?View.GONE:View.VISIBLE);
            }
            @Override public void onContextMenu(GeckoSession s,int x,int y,ContextElement element){
                if(!ownsSession(tab,s,"context-menu-stale"))return;
                String url=element.linkUri;if(url==null||!BrowserStore.isWebURL(url))return;
                dialogBuilder().setTitle(host(url)).setItems(new String[]{"Open in new tab","Copy link"},(d,w)->{
                    if(w==0)newTab(tab.privateTab,url);else copy(url);
                }).show();
            }
            @Override public void onExternalResponse(GeckoSession s,WebResponse response){download(tab,s,response);}
            @Override public void onCrash(GeckoSession s){
                traceNavigation(tab.session==s?"session-crash-current":"session-crash-stale",tab);
                if(!ownsSession(tab,s,"session-crash-stale"))return;tab.session=null;toast("This tab stopped. Reload to open it again.");
            }
            @Override public void onKill(GeckoSession s){
                traceNavigation(tab.session==s?"session-kill-current":"session-kill-stale",tab);
                if(!ownsSession(tab,s,"session-kill-stale"))return;tab.session=null;
            }
        });
        tab.session.setPromptDelegate(prompts);
        tab.session.setPermissionDelegate(prompts);
        BasicSelectionActionDelegate selections = new BasicSelectionActionDelegate(this);
        selections.enableExternalActions(false);
        tab.session.setSelectionActionDelegate(selections);
    }
    private void detachSessions(){
        if(gecko!=null)gecko.releaseSession();
        for(Tab tab:tabs)if(tab.session!=null&&tab.delegateOwner==sessionOwner){
            tab.delegateOwner=null;
            tab.session.setNavigationDelegate(null);
            tab.session.setProgressDelegate(isChangingConfigurations()&&!shuttingDown?RETAINED_PROGRESS:null);
            tab.session.setContentDelegate(null);
            tab.session.setPromptDelegate(null);tab.session.setPermissionDelegate(null);tab.session.setSelectionActionDelegate(null);
        }
    }
    private void selectPopup(Tab tab){
        prompts.dismissPending();
        lastLoadError=null;loadErrorUri=null;
        if(current!=null&&current.session!=null)current.session.setActive(false);
        current=tab;if(!tab.privateTab)lastOrdinary=tab;showGecko();gecko.setSession(tab.session);tab.session.setActive(true);refreshButtons();saveTabs();
    }
    private void select(Tab tab){
        prompts.dismissPending();
        lastLoadError=null;loadErrorUri=null;
        if(current!=null&&current.session!=null)current.session.setActive(false);
        current=tab;if(!tab.privateTab)lastOrdinary=tab;tabCount.setText(Integer.toString(tabs.size()));
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
        lastLoadError=null;loadErrorUri=null;current.previousSecurity=current.security;current.navigation.prepare(url);current.url=url;prepare(current);showGecko();gecko.setSession(current.session);current.session.setActive(true);current.session.loadUri(url);
        address.clearFocus();((InputMethodManager)getSystemService(INPUT_METHOD_SERVICE)).hideSoftInputFromWindow(address.getWindowToken(),0);
        address.setText(url);saveTabs();
    }
    private void newTab(boolean privateTab,String url){
        if(!ready){toast("Local protections are still starting.");return;}if(tabs.size()>=20){toast("Close a tab before opening another.");return;}
        Tab tab=new Tab(privateTab);tabs.add(tab);select(tab);if(url!=null)navigate(url);
    }
    private void close(Tab tab){
        if(tab.session!=null)tab.session.close();tabs.remove(tab);if(tabs.isEmpty())tabs.add(new Tab(false));
        if(lastOrdinary==tab)lastOrdinary=null;
        if(current==tab)select(tabs.get(Math.max(0,tabs.size()-1)));tabCount.setText(Integer.toString(tabs.size()));saveTabs();
    }
    private void showGecko(){
        // Ordinary navigation keeps the same view/session. Detaching it destroys
        // the display surface and deactivates Gecko before reattaching it.
        if(gecko.getParent()==content&&content.getChildCount()==1&&content.getChildAt(0)==gecko){
            if(current!=null)traceNavigation("view-host-retained",current);return;
        }
        if(current!=null)traceNavigation("view-host-attach",current);
        content.removeAllViews();if(gecko.getParent()!=null)((android.view.ViewGroup)gecko.getParent()).removeView(gecko);content.addView(gecko,new FrameLayout.LayoutParams(-1,-1));
    }
    private void showHome(){
        lastLoadError=null;loadErrorUri=null;
        if(current==null){showHomeView();return;}
        prompts.dismissPending();
        if(current.session!=null){gecko.releaseSession();current.session.close();current.session=null;}
        current.canBack=false;current.canForward=false;current.security=null;current.url="about:blank";current.title="New tab";current.navigation.home();
        loading.setVisibility(View.GONE);address.setText("");showHomeView();saveTabs();
    }
    private void showHomeView(){
        content.removeAllViews();
        ScrollView scroll=new ScrollView(this);scroll.setFillViewport(true);scroll.setVerticalScrollBarEnabled(false);
        FrameLayout canvas=new FrameLayout(this);scroll.addView(canvas);
        LinearLayout body=column();body.setPadding(dp(24),dp(appearance.compact()?28:42),dp(24),dp(24));
        int available=getResources().getDisplayMetrics().widthPixels;
        FrameLayout.LayoutParams page=new FrameLayout.LayoutParams(Math.min(available,dp(640)),-2,Gravity.TOP|Gravity.CENTER_HORIZONTAL);canvas.addView(body,page);
        boolean centered="center".equals(appearance.homeAlignment),privateTab=current!=null&&current.privateTab;
        LinearLayout identity=new LinearLayout(this);identity.setGravity(Gravity.CENTER_VERTICAL|(centered?Gravity.CENTER_HORIZONTAL:Gravity.START));
        ImageView logo=new ImageView(this);logo.setContentDescription("Cyphra new tab");logo.setImageResource(R.drawable.ic_logo);logo.setImageTintList(android.content.res.ColorStateList.valueOf(TEXT));identity.addView(logo,new LinearLayout.LayoutParams(dp(34),dp(34)));
        TextView title=text(BuildConfig.HOME?"Cyphra Home":"Cyphra",34,TEXT);title.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));title.setLetterSpacing(-.035f);title.setPadding(dp(12),0,0,0);identity.addView(title);body.addView(identity);
        String context=privateTab?"Private tab":BuildConfig.HOME?"Everyday browsing":BuildConfig.TEAM?"Byte Team · "+(workMode()?"Work":"Personal"):(workMode()?"Work profile":"Personal profile");
        TextView profile=text(context,13,MUTED);profile.setGravity(centered?Gravity.CENTER_HORIZONTAL:Gravity.START);profile.setPadding(0,dp(10),0,dp(appearance.compact()?22:30));body.addView(profile);
        LinearLayout search=new LinearLayout(this);search.setGravity(Gravity.CENTER_VERTICAL);search.setPadding(dp(16),0,dp(4),0);search.setBackground(shape(PANEL,18,LINE));
        EditText query=input("Search with Brave");query.setSingleLine(true);query.setTextSize(appearance.sp(16));query.setBackgroundColor(Color.TRANSPARENT);query.setPadding(0,0,dp(8),0);
        query.setImeOptions(android.view.inputmethod.EditorInfo.IME_ACTION_SEARCH);query.setOnEditorActionListener((v,a,e)->{navigateInput(query.getText().toString());return true;});
        search.addView(query,new LinearLayout.LayoutParams(0,dp(appearance.compact()?52:60),1));search.addView(iconButton("search","Search with Brave",()->navigateInput(query.getText().toString())),new LinearLayout.LayoutParams(dp(48),dp(48)));body.addView(search);
        if(appearance.quickActions){
            LinearLayout actions=new LinearLayout(this);actions.setGravity(Gravity.CENTER_VERTICAL);LinearLayout.LayoutParams actionLayout=new LinearLayout.LayoutParams(-1,-2);actionLayout.topMargin=dp(14);body.addView(actions,actionLayout);
            homeAction(actions,"bookmark","Bookmarks",()->showSaved(false));homeAction(actions,"private","Private tab",()->newTab(true,null));
        }
        JSONArray bookmarks=store==null?new JSONArray():store.bookmarks();
        if(appearance.bookmarks){
            section(body,"Bookmarks");LinearLayout gridRow=null;int shown=0;
            if(bookmarks.length()==0){
                TextView empty=text("Your saved pages will appear here.",13,MUTED);empty.setPadding(0,dp(4),0,dp(12));body.addView(empty);
                TextView save=text("Save a page from the menu while browsing.",12,MUTED);body.addView(save);
            }
            for(int i=0;i<Math.min(appearance.bookmarkCount,bookmarks.length());i++){
                JSONObject bookmark=bookmarks.optJSONObject(i);if(bookmark==null)continue;String url=bookmark.optString("url");
                if("grid".equals(appearance.homeLayout)){
                    if(shown%2==0){gridRow=new LinearLayout(this);LinearLayout.LayoutParams layout=new LinearLayout.LayoutParams(-1,-2);layout.bottomMargin=dp(8);body.addView(gridRow,layout);}
                    View shortcut=homeShortcut(bookmark.optString("title",host(url)),host(url),()->navigate(url));
                    LinearLayout.LayoutParams layout=new LinearLayout.LayoutParams(0,-1,1);if(shown%2==0)layout.rightMargin=dp(8);gridRow.addView(shortcut,layout);shown++;
                }else row(body,bookmark.optString("title",host(url)),host(url),()->navigate(url));
            }
            if(gridRow!=null&&shown%2==1)gridRow.addView(new View(this),new LinearLayout.LayoutParams(0,0,1));
        }
        if(appearance.reading){
            section(body,"Security reading");
            row(body,"CISA","Alerts and advisories",()->navigate("https://www.cisa.gov/news-events/cybersecurity-advisories"));
            row(body,"PortSwigger","Research and web security",()->navigate("https://portswigger.net/research"));
            row(body,"NCSC","Guidance and news",()->navigate("https://www.ncsc.gov.uk/section/keep-up-to-date/all-blogs"));
        }
        TextView offline=text(privateTab?"Private tabs close when Cyphra exits.":"Nothing on this page loads until you open it.",12,MUTED);offline.setPadding(0,dp(28),0,dp(2));body.addView(offline);
        TextView customize=text("Customize Home",13,appearance.accentColor);customize.setMinimumHeight(dp(48));customize.setGravity(Gravity.CENTER_VERTICAL);customize.setBackground(selectable());customize.setOnClickListener(v->showAppearance());body.addView(customize);
        content.addView(scroll,new FrameLayout.LayoutParams(-1,-1));refreshButtons();
    }
    private void homeAction(LinearLayout parent,String icon,String label,Runnable action){
        LinearLayout item=new LinearLayout(this);item.setGravity(Gravity.CENTER);item.setMinimumHeight(dp(48));item.setPadding(dp(6),0,dp(6),0);item.setBackground(selectable());
        ImageView image=new ImageView(this);image.setImageDrawable(new IconDrawable(icon,MUTED));item.addView(image,new LinearLayout.LayoutParams(dp(18),dp(18)));
        TextView title=text(label,13,TEXT);title.setPadding(dp(8),0,0,0);item.addView(title);item.setOnClickListener(v->action.run());parent.addView(item,new LinearLayout.LayoutParams(0,-2,1));
    }
    private View homeShortcut(String title,String domain,Runnable action){
        LinearLayout item=column();item.setPadding(dp(14),dp(14),dp(14),dp(14));item.setMinimumHeight(dp(82));item.setBackground(shape(PANEL,12,LINE));item.setForeground(selectable());
        TextView label=text(title,14,TEXT);label.setMaxLines(2);label.setEllipsize(android.text.TextUtils.TruncateAt.END);item.addView(label);
        TextView detail=text(domain,11,MUTED);detail.setSingleLine(true);detail.setEllipsize(android.text.TextUtils.TruncateAt.END);detail.setPadding(0,dp(5),0,0);item.addView(detail);item.setOnClickListener(v->action.run());return item;
    }
    private void refreshButtons(){
        if(back==null)return;back.setAlpha(current!=null&&current.canBack?.9f:.35f);forward.setAlpha(current!=null&&current.canForward?.9f:.35f);
        modeLabel.setText(current!=null&&current.privateTab?"Private":workMode()?"Work":"Personal");
        if(current!=null&&current.privateTab)getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);else getWindow().clearFlags(WindowManager.LayoutParams.FLAG_SECURE);
        if(Build.VERSION.SDK_INT>=33)setRecentsScreenshotEnabled(!workMode()&&(current==null||!current.privateTab));
        if(tabCount!=null)tabCount.setText(Integer.toString(Math.max(1,tabs.size())));
    }
    private void saveTabs(){
        if(store==null||!tabsRestored)return;
        JSONArray saved=new JSONArray();int selected=0;
        for(Tab tab:tabs)if(!tab.privateTab){
            if(tab==lastOrdinary)selected=saved.length();
            JSONObject o=new JSONObject();try{o.put("url",tab.url);o.put("title",tab.title);}catch(JSONException ignored){}saved.put(o);
        }
        store.saveTabs(saved,selected);
    }
    private void backAction(){if(fullScreen&&current!=null&&current.session!=null){current.session.exitFullScreen();return;}if(current!=null&&current.canBack&&current.session!=null){current.session.goBack();return;}if(current!=null&&!current.url.equals("about:blank")){showHome();return;}moveTaskToBack(true);}
    private void showTabs(){
        LinearLayout body=column();row(body,"New tab","",()->{newTab(false,null);dismissDialog(body);});row(body,"New private tab","Not saved to history or restored",()->{newTab(true,null);dismissDialog(body);});
        for(Tab tab:new ArrayList<>(tabs)){
            LinearLayout item=new LinearLayout(this);item.setGravity(Gravity.CENTER_VERTICAL);
            TextView label=text((tab.privateTab?"Private · ":"")+tab.title,15,TEXT);label.setMaxLines(2);label.setPadding(dp(16),dp(15),dp(8),dp(15));label.setOnClickListener(v->{select(tab);dismissDialog(body);});item.addView(label,new LinearLayout.LayoutParams(0,-2,1));
            item.addView(iconButton("close","Close tab",()->{close(tab);dismissDialog(body);showTabs();}),new LinearLayout.LayoutParams(dp(48),dp(48)));body.addView(item);
        }dialog("Tabs · "+(workMode()?"Work":"Personal"),body);
    }
    private void showModes(){if(BuildConfig.HOME)return;dialogBuilder().setTitle("Profiles").setMessage("Work and Personal keep separate cookies, bookmarks and settings. Switching closes the current profile; its ordinary tabs are restored next time.")
        .setItems(new String[]{"Work · stricter protection","Personal · everyday browsing"},(d,w)->{
            if((w==0)==workMode())return;Intent intent=new Intent(this,LauncherActivity.class).putExtra("mode",w==0?"work":"personal").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);startActivity(intent);
        }).show();}
    private void showMenu(){
        ArrayList<String> actions=new ArrayList<>(Arrays.asList("New tab","New private tab","Reload","Forward","Bookmarks","History","Downloads","Save bookmark","Desktop site","Share page","Site information"));
        if(!BuildConfig.HOME)actions.add("Tools");actions.add("Settings");
        dialogBuilder().setTitle(getString(R.string.app_name)).setItems(actions.toArray(new String[0]),(d,w)->{switch(actions.get(w)){
            case "New tab":newTab(false,null);break;case "New private tab":newTab(true,null);break;case "Reload":reloadPage();break;
            case "Forward":if(current!=null&&current.session!=null)current.session.goForward();break;case "Bookmarks":showSaved(false);break;case "History":showSaved(true);break;case "Save bookmark":bookmark();break;
            case "Desktop site":if(current!=null&&current.session!=null){current.desktop=!current.desktop;current.session.getSettings().setUserAgentMode(current.desktop?GeckoSessionSettings.USER_AGENT_MODE_DESKTOP:GeckoSessionSettings.USER_AGENT_MODE_MOBILE);current.session.reload();}break;
            case "Downloads":try{startActivity(new Intent(DownloadManager.ACTION_VIEW_DOWNLOADS));}catch(ActivityNotFoundException e){toast("Your Android system does not provide a Downloads screen.");}break;
            case "Share page":if(current!=null&&BrowserStore.isWebURL(current.url))startActivity(Intent.createChooser(new Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT,current.url),"Share page"));break;
            case "Site information":siteInfo();break;case "Tools":showTools();break;case "Settings":showSettings();break;
        }}).show();
    }
    private void showSaved(boolean history){
        JSONArray entries=history?store.history():store.bookmarks();LinearLayout body=column();
        if(entries.length()==0)row(body,history?"No saved history":"No bookmarks yet",history?(workMode()?"History is off by default in Work.":"The pages you visit will appear here when history is on."):"Save a page from the menu.",null);
        for(int i=0;i<entries.length();i++){JSONObject item=entries.optJSONObject(i);if(item==null)continue;String url=item.optString("url");View entry=row(body,item.optString("title",host(url)),host(url),()->{navigate(url);dismissDialog(body);});
            if(!history)entry.setOnLongClickListener(v->{dialogBuilder().setTitle("Remove bookmark?").setMessage(item.optString("title",url)).setPositiveButton("Remove",(d,w)->{store.removeBookmark(url);dismissDialog(body);showSaved(false);}).setNegativeButton("Cancel",null).show();return true;});}
        if(history&&entries.length()>0)row(body,"Clear history","",()->{store.clearHistory();dismissDialog(body);showSaved(true);});dialog(history?"History":"Bookmarks",body);
    }
    private void bookmark(){if(current==null||!BrowserStore.isWebURL(current.url)){toast("Open a website to save it.");return;}if(current.privateTab){toast("Bookmarks are disabled in private tabs.");return;}store.addBookmark(current.title,current.url);toast(BuildConfig.HOME?"Bookmark saved.":"Bookmark saved in "+mode()+".");}
    private void showShields(){
        if(engine==null){toast("Protections are starting.");return;}
        if(activeShield!=null&&activeShield.isShowing()){renderShields();return;}
        activeShield=new ShieldsPanel(this,workMode(),appearance,value->{
            String site=current==null?"":host(current.url);if(site.isEmpty())return;
            engine.setShieldsForHost(site,value);renderShields();if(current!=null&&current.session!=null)current.session.reload();
        },()->activeShield=null);
        renderShields();activeShield.show();
    }
    private void renderShields(){
        if(activeShield==null||engine==null)return;String site=current==null?"":host(current.url);
        Engine.Stats stats=site.isEmpty()||current==null||current.session==null?null:engine.snapshot(current.session);
        activeShield.render(site,stats,engine.shieldsEnabled(site),engine.dnsChoice(),engine.dnsUri(),current!=null&&current.privateTab);
    }
    private void siteInfo(){
        if(current==null||!BrowserStore.isWebURL(current.url)){toast("Open a website first.");return;}String info=current.url;
        if(current.security!=null){info+="\n\n"+(current.security.isSecure?"Encrypted HTTPS connection":"Connection is not verified HTTPS");if(current.security.certificate!=null)info+="\n\nCertificate issuer:\n"+current.security.certificate.getIssuerX500Principal().getName();}
        dialogBuilder().setTitle("Site information").setMessage(info).setPositiveButton("Done",null).show();
    }
    private void showLoadError(String uri,WebRequestError error){
        loadErrorUri=uri;lastLoadError=error;
        boolean encryptedDNS=engine!=null&&!engine.dnsChoice().equals("system");
        LoadErrorInfo info=LoadErrorInfo.from(error.code,error.category,encryptedDNS);
        LinearLayout body=column();body.setPadding(dp(28),dp(44),dp(28),dp(24));body.addView(text(info.title,24,TEXT));row(body,host(uri),info.message,null);
        if(info.dnsRelated&&encryptedDNS)row(body,BuildConfig.HOME?"DNS provider":"Encrypted DNS",BuildConfig.HOME?dnsLabel(engine.dnsChoice()):engine.dnsUri()+"\nNo silent fallback to System DNS.",null);
        row(body,"Retry","",()->navigate(uri));
        if(info.dnsRelated)row(body,"DNS settings","",this::showDns);
        if(!BuildConfig.HOME)row(body,"Technical details","Error "+error.code+" · category "+error.category,null);
        content.removeAllViews();content.addView(body);
    }
    private void showSettings(){
        LinearLayout body=column();
        if(!BuildConfig.HOME)row(body,"Profiles",workMode()?"Work":"Personal",this::showModes);
        section(body,"Make it yours");
        row(body,"Appearance",AppearancePanel.themeLabel(appearance.theme)+" · "+(appearance.compact()?"Compact":"Comfortable"),()->{dismissDialog(body);showAppearance();});
        row(body,"Default browser","Choose Cyphra in Android settings",()->{
            android.app.role.RoleManager roles=(android.app.role.RoleManager)getSystemService(ROLE_SERVICE);
            if(roles!=null&&roles.isRoleAvailable(android.app.role.RoleManager.ROLE_BROWSER))startActivityForResult(roles.createRequestRoleIntent(android.app.role.RoleManager.ROLE_BROWSER),53);
        });
        section(body,"Privacy");row(body,BuildConfig.HOME?"DNS provider":"DNS",BuildConfig.HOME?dnsLabel(engine.dnsChoice()):engine.dnsChoice(),this::showDns);
        Switch history=new Switch(this);history.setText("Save browsing history");history.setTextColor(TEXT);history.setPadding(dp(16),dp(16),dp(16),dp(16));history.setChecked(store.booleanPref("save-history",!workMode()));history.setOnCheckedChangeListener((v,on)->store.setBooleanPref("save-history",on));body.addView(history);
        row(body,"Encrypted sync",sync.isPaired()?"Paired · manual sync":"Not paired",this::showSync);
        section(body,"Cyphra");row(body,"Updates","Manual checks · "+BuildConfig.VERSION_NAME,this::showUpdates);
        row(body,"Clear browsing data","Cookies, website storage, cache and local history",()->dialogBuilder().setTitle(BuildConfig.HOME?"Clear browsing data?":"Clear "+mode()+" browsing data?").setMessage("Bookmarks and settings are kept. This signs you out of websites in this profile.")
            .setPositiveButton("Clear",(d,w)->engine.runtime.getStorageController().clearData(StorageController.ClearFlags.ALL).accept(v->{store.clearHistory();toast("Browsing data cleared.");},e->toast("Could not clear browsing data."))).setNegativeButton("Cancel",null).show());
        row(body,"About "+getString(R.string.app_name),"Version "+BuildConfig.VERSION_NAME,()->dialogBuilder().setTitle(getString(R.string.app_name)+" "+BuildConfig.VERSION_NAME).setMessage((BuildConfig.HOME?"Home edition":BuildConfig.TEAM?"Byte Team edition":"Public edition")+"\nGeckoView "+BuildConfig.GECKOVIEW_VERSION+"\n\nTelemetry and background update checks are disabled. Optional sync and updates contact only their configured services when requested.\n\nAndroid source and license notices are in the release.").setPositiveButton("Done",null).show());dialog("Settings",body);
    }
    private String dnsLabel(String choice){switch(choice){case "system":return "System DNS";case "toxitech":return "Toxitech";case "quad9":return "Quad9";case "cloudflare":return "Cloudflare";default:return "Custom provider";}}
    private void showDns(){
        String[] choices={"toxitech","system","quad9","cloudflare","custom"};String[] labels={"Toxitech · encrypted","System DNS","Quad9 · encrypted","Cloudflare · encrypted","Custom HTTPS"};int selected=Arrays.asList(choices).indexOf(engine.dnsChoice());
        dialogBuilder().setTitle(BuildConfig.HOME?"DNS provider":"DNS for "+mode()).setSingleChoiceItems(labels,selected,(d,w)->{
            d.dismiss();if(w==4){EditText custom=input("https://resolver.example/dns-query");custom.setText(engine.dnsChoice().equals("custom")?engine.dnsUri():"");LinearLayout body=column();body.setPadding(dp(16),0,dp(16),0);body.addView(custom);
                AlertDialog dialog=dialogBuilder().setTitle("Custom encrypted DNS").setView(body).setPositiveButton("Save",null).setNegativeButton("Cancel",null).create();dialog.setOnShowListener(x->dialog.getButton(-1).setOnClickListener(v->{try{engine.setDns("custom",custom.getText().toString());toast("Custom DNS saved.");dialog.dismiss();}catch(Exception e){custom.setError(e.getMessage());}}));dialog.show();
            }else{try{engine.setDns(choices[w],"");toast(BuildConfig.HOME?"DNS provider saved.":"DNS saved for "+mode()+".");}catch(Exception e){toast(e.getMessage());}}
        }).setNegativeButton("Cancel",null).show();
    }
    private void showUpdates(){
        if(current!=null&&current.privateTab){toast("Updates are disabled in private tabs.");return;}
        LinearLayout body=column();row(body,"Installed version",BuildConfig.VERSION_NAME+" · "+BuildConfig.EDITION,null);row(body,"Check GitHub","No automatic checks or silent installs",this::checkUpdates);
        if(BuildConfig.TEAM){row(body,"Repository read token",updates.hasToken()?"Stored with Android Keystore":"Required for private releases",()->{EditText token=input("GitHub repository read token");token.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD);LinearLayout holder=column();holder.setPadding(dp(16),0,dp(16),0);holder.addView(token);
            AlertDialog d=dialogBuilder().setTitle("Private GitHub updates").setMessage("Use a token limited to Cyphra-Browser, Contents: read.").setView(holder).setPositiveButton("Save",null).setNegativeButton("Cancel",null).create();d.setOnShowListener(x->d.getButton(-1).setOnClickListener(v->{try{updates.configureToken(token.getText().toString());token.setText("");d.dismiss();toast("Token saved.");}catch(Exception e){token.setError(e.getMessage());}}));d.show();});
            if(updates.hasToken())row(body,"Remove token","",()->{try{updates.forgetToken();toast("Token removed.");}catch(Exception e){toast("Could not remove token.");}});}dialog("Updates",body);
    }
    private void checkUpdates(){busy("Checking GitHub…",()->{
        UpdateClient.Offer offer=updates.check();return offer;
    },value->{UpdateClient.Offer offer=(UpdateClient.Offer)value;if(offer==null||!offer.newer){toast("Cyphra is up to date.");return;}
        dialogBuilder().setTitle("Cyphra "+offer.version).setMessage("Download the signed release and verify it before opening Android's installer?")
            .setPositiveButton("Download",(d,w)->busy("Downloading and verifying update…",()->{File file=updates.download(offer);updates.verifyForInstall(file,offer);return file;},file->{pendingInstall=(File)file;pendingOffer=offer;installUpdate();}))
            .setNegativeButton("Later",null).show();});}
    private void installUpdate(){
        if(pendingInstall==null)return;
        if(!getPackageManager().canRequestPackageInstalls()){
            dialogBuilder().setTitle("Allow Cyphra updates").setMessage("Android needs permission for Cyphra to open its package installer. Return here after allowing it.")
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
        AlertDialog d=dialogBuilder().setTitle(create?"Create encrypted vault":"Pair encrypted vault").setView(body).setPositiveButton(create?"Create":"Pair",null).setNegativeButton("Cancel",null).create();
        d.setOnShowListener(x->d.getButton(-1).setOnClickListener(v->{String server=endpoint.getText().toString(),code=secret.getText().toString();d.dismiss();busy(create?"Creating encrypted vault…":"Pairing device…",()->{if(create)return sync.create(server,code);sync.pair(server,code);return null;},result->{secret.setText("");if(create){String pairing=(String)result;dialogBuilder().setTitle("Pairing code").setMessage("Keep this secret. It gives access to your "+mode()+" vault.\n\n"+pairing).setPositiveButton("Copy",(dialog,w)->copy(pairing)).setNegativeButton("Done",null).show();}else toast("Device paired. Use Sync now to merge bookmarks.");});}));d.show();
    }
    private void showTools(){if(BuildConfig.HOME)return;dialogBuilder().setTitle("Tools").setItems(new String[]{"JSON format","Base64 encode","Base64 decode","URL encode","URL decode","SHA-256","Page source"},(d,w)->{if(w==6){if(current!=null&&BrowserStore.isWebURL(current.url))navigate("view-source:"+current.url);return;}tool(w);}).show();}
    private void tool(int operation){
        if(BuildConfig.HOME)return;
        LinearLayout body=column();body.setPadding(dp(16),0,dp(16),0);EditText input=input("Input");input.setMinLines(3);input.setMaxLines(6);body.addView(input);TextView output=text("",14,TEXT);output.setTextIsSelectable(true);body.addView(output);
        AlertDialog d=dialogBuilder().setTitle(new String[]{"JSON format","Base64 encode","Base64 decode","URL encode","URL decode","SHA-256"}[operation]).setView(body).setPositiveButton("Run",null).setNegativeButton("Close",null).setNeutralButton("Copy output",(x,w)->copy(output.getText().toString())).create();
        d.setOnShowListener(x->d.getButton(-1).setOnClickListener(v->{try{String value=input.getText().toString();if(value.length()>1024*1024)throw new IllegalArgumentException("Input is too large.");String result;
            switch(operation){case 0:result=value.trim().startsWith("[")?new JSONArray(value).toString(2):new JSONObject(value).toString(2);break;case 1:result=android.util.Base64.encodeToString(value.getBytes(StandardCharsets.UTF_8),android.util.Base64.NO_WRAP);break;case 2:result=new String(android.util.Base64.decode(value,android.util.Base64.DEFAULT),StandardCharsets.UTF_8);break;case 3:result=URLEncoder.encode(value,"UTF-8");break;case 4:result=URLDecoder.decode(value,"UTF-8");break;default:byte[] bytes=MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8));StringBuilder hex=new StringBuilder();for(byte b:bytes)hex.append(String.format(Locale.ROOT,"%02x",b&255));result=hex.toString();}output.setText(result);
        }catch(Exception error){output.setText("Could not process this input: "+error.getMessage());}}));d.show();
    }
    private void download(Tab tab,GeckoSession respondingSession,WebResponse response){
        if(!ownsSession(tab,respondingSession,"external-response-stale")||!respondingSession.isOpen()){if(response.body!=null)try{response.body.close();}catch(IOException ignored){}return;}
        // An attachment response is not a committed document. Keep the existing
        // page (or native Home) and never restore an attachment as a saved tab.
        traceNavigation("external-response-before",tab);
        boolean restored=tab.navigation.external(response.uri);long navigation=tab.navigation.serial;
        traceNavigation(restored?"external-response-restored":"external-response-stale",tab);
        if(restored){
            engine.restoreDocument(respondingSession,tab.navigation.documentUrl);
            traceNavigation("external-context-restored",tab);
            tab.url=tab.navigation.documentUrl;tab.title=tab.navigation.documentTitle;tab.security=tab.previousSecurity;
            if(tab==current){lastLoadError=null;loadErrorUri=null;loading.setVisibility(View.GONE);address.setText("about:blank".equals(tab.url)?"":tab.url);if("about:blank".equals(tab.url)){respondingSession.setActive(false);showHomeView();}refreshButtons();}
        }
        saveTabs();
        Runnable finish=()->runOnUiThread(()->{
            if(restored&&tab.navigation.serial==navigation&&tab.session==respondingSession&&"about:blank".equals(tab.url)&&"about:blank".equals(tab.navigation.documentUrl)){
                if(gecko.getSession()==respondingSession)gecko.releaseSession();if(respondingSession.isOpen())respondingSession.close();tab.session=null;tab.canBack=false;tab.canForward=false;tab.security=null;if(!destroyed&&tab==current)refreshButtons();
            }
        });
        if(response.body==null){finish.run();return;}
        DownloadPolicy.Metadata metadata=DownloadPolicy.derive(response.uri,response.headers.get("Content-Disposition"),response.headers.get("Content-Type"));
        boolean[] accepted={false};
        AlertDialog confirmation=dialogBuilder().setTitle("Save download?").setMessage(metadata.filename+"\n\n"+host(response.uri)).setPositiveButton("Save",(d,w)->{
            accepted[0]=true;
            busy("Saving download…",()->{
                Uri dest=null;
                try(InputStream in=response.body){
                    ContentValues values=new ContentValues();values.put(MediaStore.Downloads.DISPLAY_NAME,metadata.filename);values.put(MediaStore.Downloads.MIME_TYPE,metadata.mimeType);values.put(MediaStore.Downloads.RELATIVE_PATH,Environment.DIRECTORY_DOWNLOADS+"/Cyphra");values.put(MediaStore.Downloads.IS_PENDING,1);
                    dest=getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI,values);if(dest==null)throw new IOException("Could not create download.");
                    try(OutputStream out=getContentResolver().openOutputStream(dest)){if(out==null)throw new IOException("Could not write download.");byte[] b=new byte[32768];int n;while((n=in.read(b))!=-1)out.write(b,0,n);out.flush();}
                    ContentValues finished=new ContentValues();finished.put(MediaStore.Downloads.IS_PENDING,0);
                    if(getContentResolver().update(dest,finished,null,null)!=1)throw new IOException("Could not finish saving download.");
                    return metadata.filename;
                }catch(Exception e){if(dest!=null)try{getContentResolver().delete(dest,null,null);}catch(Exception ignored){}throw e;}finally{finish.run();}
            },value->toast("Saved to Downloads/Cyphra."));
        }).setNegativeButton("Cancel",null).create();
        confirmation.setOnDismissListener(d->{if(!accepted[0]){try{response.body.close();}catch(IOException ignored){}finish.run();}});
        confirmation.show();
    }
    private void traceNavigation(String event,Tab tab){
        if(!BuildConfig.DEBUG)return;
        Engine.Stats stats=tab.session==null?null:engine.snapshot(tab.session);
        android.util.Log.d("CyphraNavigation","event="+event+" serial="+tab.navigation.serial
            +" retained="+tab.navigation.retainingDocument()+" blocked="+(stats==null?0:stats.blocked)
            +" nativeBlocked="+(stats==null?0:stats.nativeBlocked));
    }
    private boolean ownsSession(Tab tab,GeckoSession session,String staleEvent){
        // A tab can retain its identity after Home retires its GeckoSession.
        // Delayed callbacks from that old renderer do not own its replacement.
        if(!isFinishing()&&!destroyed&&!shuttingDown&&tab.session==session&&tab.delegateOwner==sessionOwner)return true;
        traceNavigation(staleEvent,tab);return false;
    }
    private interface Task{Object run() throws Exception;}
    private void busy(String label,Task task,java.util.function.Consumer<Object> done){
        ProgressDialog dialog=new ProgressDialog(appearance.dialogContext(this),appearance.dialogTheme());dialogs.add(dialog);appearance.applyAccent(dialog.getContext());dialog.setMessage(label);dialog.setCancelable(false);dialog.show();appearance.decorateDialog(dialog,this);
        jobs.submit(()->{try{Object value=task.run();runOnUiThread(()->{dialog.dismiss();if(!isFinishing()&&!destroyed)done.accept(value);});}catch(Exception e){runOnUiThread(()->{dialog.dismiss();if(!isFinishing()&&!destroyed)dialogBuilder().setTitle("Could not complete this action").setMessage(e.getMessage()==null?"Please try again.":e.getMessage()).setPositiveButton("Done",null).show();});}});
    }
    private AlertDialog dialog(String title,LinearLayout body){ScrollView scroll=new ScrollView(this);scroll.addView(body);AlertDialog d=dialogBuilder().setTitle(title).setView(scroll).setNegativeButton("Done",null).create();body.setTag(d);d.show();return d;}
    private AlertDialog.Builder dialogBuilder(){return new NativeDialogs.Builder(this,appearance,dialogs::add);}
    private void dismissDialog(View body){Object tag=body.getTag();if(tag instanceof Dialog)((Dialog)tag).dismiss();}
    private LinearLayout column(){LinearLayout v=new LinearLayout(this);v.setOrientation(LinearLayout.VERTICAL);return v;}
    private TextView text(String value,float size,int color){TextView v=new TextView(this);v.setText(value);v.setTextSize(appearance.sp(size));v.setTextColor(color);appearance.markScaled(v);return v;}
    private EditText input(String hint){EditText v=new EditText(this);v.setHint(hint);v.setTextColor(TEXT);v.setHintTextColor(MUTED);v.setTextSize(appearance.sp(15));appearance.markScaled(v);return v;}
    private void section(LinearLayout body,String label){TextView v=text(label,12,MUTED);v.setTypeface(null,Typeface.BOLD);v.setPadding(0,dp(appearance.compact()?22:30),0,dp(10));v.setAccessibilityHeading(true);body.addView(v);}
    private View row(LinearLayout body,String title,String detail,Runnable action){LinearLayout item=column();item.setMinimumHeight(dp(48));item.setPadding(dp(16),dp(appearance.rowPadding()),dp(16),dp(appearance.rowPadding()));item.addView(text(title,15,TEXT));if(detail!=null&&!detail.isEmpty()){TextView sub=text(detail,12,MUTED);sub.setPadding(0,dp(5),0,0);item.addView(sub);}if(action!=null){item.setBackground(selectable());item.setOnClickListener(v->action.run());}body.addView(item,new LinearLayout.LayoutParams(-1,-2));return item;}
    private android.graphics.drawable.Drawable selectable(){return appearance.ripple();}
    private ImageButton iconButton(String icon,String label,Runnable action){ImageButton v=new ImageButton(this);v.setImageDrawable(new IconDrawable(icon,TEXT));v.setPadding(dp(12),dp(12),dp(12),dp(12));v.setBackground(selectable());v.setContentDescription(label);v.setOnClickListener(w->action.run());return v;}
    private GradientDrawable shape(int color,int radius,int border){GradientDrawable d=new GradientDrawable();d.setColor(color);d.setCornerRadius(dp(radius));d.setStroke(dp(1),border);return d;}
    private int dp(int n){return Math.round(n*getResources().getDisplayMetrics().density);}
    private String host(String url){try{String host=Uri.parse(url).getHost();return host==null?"":host;}catch(Exception e){return "";}}
    private void toast(String message){Toast.makeText(this,message==null?"Could not complete the action.":message,Toast.LENGTH_SHORT).show();}
    private void copy(String value){((ClipboardManager)getSystemService(CLIPBOARD_SERVICE)).setPrimaryClip(ClipData.newPlainText("Cyphra",value));toast("Copied.");}
    @Override protected void onNewIntent(Intent intent){super.onNewIntent(intent);setIntent(intent);String url=intent.getStringExtra("url");if(BrowserStore.isWebURL(url))navigate(url);}
    @Override protected void onPause(){if(current!=null)traceNavigation("activity-pause",current);saveTabs();if(current!=null&&current.session!=null)current.session.setActive(false);super.onPause();}
    @Override protected void onResume(){super.onResume();if(current!=null&&current.session!=null)current.session.setActive(true);if(current!=null)traceNavigation("activity-resume",current);}
    @Override public void onConfigurationChanged(android.content.res.Configuration configuration){super.onConfigurationChanged(configuration);if(appearance!=null&&"system".equals(appearance.theme))applyAppearance();}
    // API 33+ uses the native OnBackInvokedDispatcher registered above.
    // This override is the required fallback only on Android 10–12.
    @android.annotation.SuppressLint("GestureBackNavigation")
    @Override public void onBackPressed(){if(Build.VERSION.SDK_INT<33)backAction();}
    private void shutdownProfile(){
        if(shuttingDown||engine==null)return;shuttingDown=true;ready=false;saveTabs();prompts.dismissPending();
        engine.shutdownGracefully(()->{finishAndRemoveTask();android.os.Process.killProcess(android.os.Process.myPid());});
    }
    @Override public Object onRetainNonConfigurationInstance(){return shuttingDown?null:new RetainedTabs(this);}
    @Override protected void onDestroy(){
        destroyed=true;
        if(activeShield!=null)activeShield.dismiss();if(appearancePanel!=null)appearancePanel.dismiss();
        try{unregisterReceiver(modeReceiver);}catch(Exception ignored){}
        if(engine!=null){engine.clearListener(engineListener);if(!isChangingConfigurations()&&!shuttingDown)shutdownProfile();}
        if(prompts!=null)prompts.dismissPending();detachSessions();
        for(Dialog dialog:new ArrayList<>(dialogs))dialog.dismiss();dialogs.clear();
        jobs.shutdown();super.onDestroy();
    }
    @Override protected void onActivityResult(int request,int result,Intent data){super.onActivityResult(request,result,data);if(request==52){if(getPackageManager().canRequestPackageInstalls())installUpdate();}else prompts.onActivityResult(request,result,data);}
    @Override public void onRequestPermissionsResult(int request,String[] permissions,int[] results){super.onRequestPermissionsResult(request,permissions,results);prompts.onRequestPermissionsResult(request,results);}
}
