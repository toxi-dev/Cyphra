/* This Source Code Form is subject to the Mozilla Public License, v. 2.0. */
package org.cyphra.browser;

import android.app.Application;
import android.content.Context;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Handler;
import android.os.Looper;
import androidx.annotation.OptIn;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.lang.ref.WeakReference;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.WeakHashMap;
import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;
import org.mozilla.geckoview.ContentBlocking;
import org.mozilla.geckoview.ExperimentalGeckoViewApi;
import org.mozilla.geckoview.GeckoPreferenceController;
import org.mozilla.geckoview.GeckoResult;
import org.mozilla.geckoview.GeckoRuntime;
import org.mozilla.geckoview.GeckoRuntimeSettings;
import org.mozilla.geckoview.GeckoSession;
import org.mozilla.geckoview.GeckoSessionSettings;
import org.mozilla.geckoview.WebExtension;

/** A single Gecko runtime per Android process and an app-private profile per mode. */
@OptIn(markerClass=ExperimentalGeckoViewApi.class)
public final class Engine {
    private static final String EXTENSION_ID="android-shields@cyphra.org";
    private static final String TOXITECH="https://dns.toxitechnetwork.org/dns-query";
    private static final String STARTUP_CACHE_ENGINE_KEY="compiledStartupCacheEngineSHA256";
    private static final String STARTUP_CACHE_APK_KEY="compiledStartupCacheApkUpdateTime";
    private static Engine instance;
    private final Handler ui=new Handler(Looper.getMainLooper());
    private final boolean work,team;
    private final SharedPreferences preferences;
    private final long installedApkUpdateTime;
    private final File profile,config;
    private final WeakHashMap<GeckoSession,String> pageUrls=new WeakHashMap<>();
    private final WeakHashMap<GeckoSession,Stats> statistics=new WeakHashMap<>();
    private final WeakHashMap<GeckoSession,Stats> previousStatistics=new WeakHashMap<>();
    private final WeakHashMap<GeckoSession,String> documentIds=new WeakHashMap<>();
    private final HashMap<Integer,WeakReference<GeckoSession>> tabSessions=new HashMap<>();
    private final Set<String> exceptions=new HashSet<>();
    private Listener listener;
    private WebExtension extension;
    private WebExtension.Port port;
    private boolean ready,extensionReady,privateReady,preferencesVerified,failed,closing;
    private final RuntimeShutdown shutdown;
    private int rules;
    private String updatedAt="",failure="";
    public final GeckoRuntime runtime;

    public interface Listener {
        void onReady();
        void onStats(GeckoSession session,Stats stats);
        void onFailure(String message);
    }

    /** The extension's cancelled requests and Gecko's events are deliberately separate. */
    public static final class Stats {
        public final int blocked,filters,telemetry,strict,nativeBlocked,rules;
        public final boolean ready;
        public final String updatedAt;
        public final List<String> hosts;
        private Stats(int blocked,int filters,int telemetry,int strict,int nativeBlocked,
                      int rules,boolean ready,String updatedAt,List<String> hosts){
            this.blocked=blocked;this.filters=filters;this.telemetry=telemetry;
            this.strict=strict;this.nativeBlocked=nativeBlocked;this.rules=rules;
            this.ready=ready;this.updatedAt=updatedAt;
            this.hosts=Collections.unmodifiableList(new ArrayList<>(hosts));
        }
    }

    /** Activities may be recreated; Gecko itself must not be created twice in one process. */
    public static synchronized Engine get(Context context,boolean work,boolean team,Listener listener){
        if(!EditionPolicy.allowsMode(BuildConfig.EDITION,work?"work":"personal")||team!=BuildConfig.TEAM)throw new IllegalArgumentException("Invalid edition runtime profile.");
        if(Looper.myLooper()!=Looper.getMainLooper())throw new IllegalStateException("Create Gecko on the main thread.");
        if(instance==null)instance=new Engine(context.getApplicationContext(),work,team);
        if(instance.work!=work||instance.team!=team)throw new IllegalStateException("A profile cannot change modes inside its process.");
        instance.setListener(listener);return instance;
    }

    private Engine(Context context,boolean work,boolean team){
        this.work=work;this.team=team;
        String mode=work?"work":"personal";
        if(!Application.getProcessName().endsWith(":"+mode))throw new IllegalStateException("Work and Personal require separate Android processes.");
        preferences=context.getSharedPreferences("cyphra-engine-"+mode,Context.MODE_PRIVATE);
        try { installedApkUpdateTime=context.getPackageManager().getPackageInfo(context.getPackageName(),0).lastUpdateTime; }
        catch(android.content.pm.PackageManager.NameNotFoundException e){throw new IllegalStateException("The installed browser package could not be identified.",e);}
        Set<String> saved=preferences.getStringSet("disabledHosts",Collections.emptySet());
        if(saved!=null)for(String host:saved)if(validHost(host))exceptions.add(host);
        File managed=new File(context.getFilesDir(),"gecko/"+mode);
        profile=new File(managed,"profile");config=new File(managed,"policy.yaml");
        if(!profile.isDirectory()&&!profile.mkdirs())throw new IllegalStateException("Cyphra cannot create its private profile.");
        try { writeConfiguration(); } catch(IOException e){throw new IllegalStateException("Cyphra cannot write its private privacy policy.",e);}
        ContentBlocking.Settings blocking=new ContentBlocking.Settings.Builder()
            .antiTracking(work?ContentBlocking.AntiTracking.STRICT:ContentBlocking.AntiTracking.DEFAULT)
            .cookieBehavior(ContentBlocking.CookieBehavior.ACCEPT_FIRST_PARTY_AND_ISOLATE_OTHERS)
            .cookieBehaviorPrivateMode(ContentBlocking.CookieBehavior.ACCEPT_FIRST_PARTY_AND_ISOLATE_OTHERS)
            .enhancedTrackingProtectionLevel(work?ContentBlocking.EtpLevel.STRICT:ContentBlocking.EtpLevel.DEFAULT)
            .enhancedTrackingProtectionCategory(work?ContentBlocking.EtpCategory.STRICT:ContentBlocking.EtpCategory.STANDARD)
            .strictSocialTrackingProtection(work)
            .allowListBaselineTrackingProtection(true)
            .allowListConvenienceTrackingProtection(!work)
            .cookiePurging(true)
            .queryParameterStrippingEnabled(true)
            .queryParameterStrippingPrivateBrowsingEnabled(true)
            // Online lookups and reporting are not silently enabled. The offline
            // Shields snapshot is distinct from a real-time malware reputation service.
            .safeBrowsing(0).build();
        GeckoRuntimeSettings settings=new GeckoRuntimeSettings.Builder()
            // Gecko's own build ID is unchanged by the source-module overlay.
            // Invalidate compiled startup cache once per overlay and profile,
            // before loading privileged modules from an existing installation.
            // Native startup also soft-invalidates derived quota-cache metadata.
            .arguments(startupCacheMatches()
                ?new String[]{"-profile",profile.getAbsolutePath()}
                :new String[]{"-profile",profile.getAbsolutePath(),"-purgecaches"})
            .configFilePath(config.getAbsolutePath())
            .contentBlocking(blocking)
            .globalPrivacyControlEnabled(true)
            .remoteDebuggingEnabled(false)
            .aboutConfigEnabled(false)
            .extensionsWebAPIEnabled(false)
            .debugLogging(false).consoleOutput(false)
            .enterpriseRootsEnabled(false)
            .isolatedProcessEnabled(true)
            .allowInsecureConnections(work?GeckoRuntimeSettings.HTTPS_ONLY:GeckoRuntimeSettings.ALLOW_ALL)
            .trustedRecursiveResolverMode(dnsMode())
            .trustedRecursiveResolverUri(dnsUri().isEmpty()?TOXITECH:dnsUri())
            .build();
        settings.setDohAutoselectEnabled(false);
        runtime=GeckoRuntime.create(context,settings);
        shutdown=new RuntimeShutdown(runtime::shutdown,callback->ui.post(callback));
        runtime.setDelegate(()->{
            shutdown.onExited();
            if(!closing)fail("The Gecko engine stopped. Restart Cyphra to continue browsing.");
        });
        // GeckoView 158's shutdown calls native forceQuit directly, even while
        // GeckoRuntime.create is still loading JNI. This read-only query is
        // queued until Gecko is RUNNING. Either Gecko reply proves native
        // startup reached that state; only the delegate above proves exit.
        runtime.getWebExtensionController().list().accept(value->shutdown.onReady(),error->shutdown.onReady());
        runtime.getWebExtensionController().ensureBuiltIn("resource://android/assets/shields/",EXTENSION_ID).accept(value->{
            extension=value;
            extension.setMessageDelegate(messages,"cyphra");
            // An existing profile's permission flag does not prove its native
            // blocker connection is live. Gecko reloads here, after attaching
            // the message delegate, so both fresh and restored profiles must
            // deliver the same verified rules/configuration handshake.
            runtime.getWebExtensionController().setAllowedInPrivateBrowsing(extension,true)
                .accept(this::privateProtectionReady,e->fail("Private-tab protection could not be enabled."));
        },e->fail("The bundled request blocker could not be installed."));
        ui.postDelayed(()->{if(!ready&&!failed)fail("Local protection did not finish starting.");},45000);
    }

    public void setListener(Listener next){
        listener=next;
        if(next!=null)ui.post(()->{if(listener!=next)return;if(failed)next.onFailure(failure);else if(ready)next.onReady();});
    }
    public void clearListener(Listener previous){if(listener==previous)listener=null;}
    public boolean isReady(){return ready&&!failed;}
    public boolean workMode(){return work;}
    public File profileDirectory(){return profile;}
    public File configurationFile(){return config;}

    private void privateProtectionReady(WebExtension value){
        if(value.metaData==null||!value.metaData.allowedInPrivateBrowsing){fail("Private-tab protection did not apply.");return;}
        extension=value;extension.setMessageDelegate(messages,"cyphra");
        privateReady=true;
        for(GeckoSession session:pageUrls.keySet())attachMessages(session);
        maybeReady();
    }

    /**
     * Mobile Gecko child-service names are package-wide. Before switching modes,
     * wait for Gecko's actual Exited event, then finish and terminate this mode's
     * Android process. A new runtime must start in the other mode's process.
     * The callback never fires early based on a guessed delay.
     */
    public void shutdownGracefully(Runnable exited){
        if(closing)return;closing=true;ready=false;
        for(GeckoSession session:new ArrayList<>(pageUrls.keySet()))try{session.stop();session.close();}catch(Exception ignored){}
        shutdown.request(exited);
    }

    public GeckoSession newSession(boolean privateTab){return newSession(privateTab,true);}
    /** Gecko's popup contract needs an unopened session, with the same protections. */
    public GeckoSession newSession(boolean privateTab,boolean open){
        if(!isReady())throw new IllegalStateException("Local protections are not ready.");
        GeckoSession session=new GeckoSession(new GeckoSessionSettings.Builder()
            .usePrivateMode(privateTab).useTrackingProtection(true)
            .userAgentMode(GeckoSessionSettings.USER_AGENT_MODE_MOBILE).build());
        pageUrls.put(session,"");statistics.put(session,empty());
        session.setContentBlockingDelegate(new ContentBlocking.Delegate(){
            @Override public void onContentBlocked(GeckoSession s,ContentBlocking.BlockEvent event){
                Stats old=snapshot(s);LinkedHashSet<String> hosts=new LinkedHashSet<>(old.hosts);
                String host=hostOf(event.uri);if(validHost(host)&&hosts.size()<32)hosts.add(host);
                Stats next=new Stats(old.blocked,old.filters,old.telemetry,old.strict,
                    Math.min(1000000,old.nativeBlocked+1),rules,isReady(),updatedAt,new ArrayList<>(hosts));
                statistics.put(s,next);emitStats(s,next);
            }
        });
        attachMessages(session);
        if(open)session.open(runtime);return session;
    }

    private void attachMessages(GeckoSession session){
        if(extension!=null)session.getWebExtensionController().setMessageDelegate(extension,messages,"cyphra");
    }
    public void onPageStart(GeckoSession session,String uri){
        if(!previousStatistics.containsKey(session))previousStatistics.put(session,snapshot(session));
        pageUrls.put(session,uri==null?"":uri);statistics.put(session,empty());
        session.getSettings().setUseTrackingProtection(shieldsEnabled(hostOf(uri)));
        emitStats(session,snapshot(session));
    }
    /** An attachment leaves its initiating document, including its actual counters, alive. */
    public void restoreDocument(GeckoSession session,String uri){
        traceDocument("restore-before",session,false);
        String pendingUri=pageUrls.get(session);pageUrls.put(session,uri);Stats previous=previousStatistics.remove(session);
        Stats pending=snapshot(session);
        if(previous==null){if(!uri.equals(pendingUri))statistics.put(session,empty());}
        else{
            LinkedHashSet<String> hosts=new LinkedHashSet<>(previous.hosts);
            for(String host:pending.hosts){if(hosts.size()>=32)break;hosts.add(host);}
            // No new document was committed: native cancellations observed
            // during the attachment belong to this still-live session/page.
            statistics.put(session,new Stats(previous.blocked,previous.filters,previous.telemetry,previous.strict,
                Math.min(1000000,previous.nativeBlocked+pending.nativeBlocked),rules,isReady(),updatedAt,new ArrayList<>(hosts)));
        }
        session.getSettings().setUseTrackingProtection(shieldsEnabled(hostOf(uri)));
        for(Map.Entry<Integer,WeakReference<GeckoSession>> entry:tabSessions.entrySet())if(entry.getValue().get()==session&&port!=null){
            JSONObject message=new JSONObject();try{message.put("type","restore-document");message.put("tabId",entry.getKey());message.put("url",uri);port.postMessage(message);}catch(JSONException error){fail("The document protection context could not be restored.");}break;
        }
        emitStats(session,snapshot(session));
        traceDocument("restore-after",session,false);
    }
    public Stats snapshot(GeckoSession session){Stats found=statistics.get(session);return found==null?empty():found;}
    private Stats empty(){return new Stats(0,0,0,0,0,rules,isReady(),updatedAt,Collections.emptyList());}
    private void emitStats(GeckoSession session,Stats stats){if(listener!=null)listener.onStats(session,stats);}

    public boolean shieldsEnabled(String host){return !exceptions.contains(normalizeHost(host));}
    public void setShieldsForHost(String host,boolean enabled){
        host=normalizeHost(host);if(!validHost(host))throw new IllegalArgumentException("Choose a website hostname.");
        if(!enabled&&exceptions.size()>=2048&&!exceptions.contains(host))throw new IllegalStateException("The exception limit has been reached.");
        Set<String> next=new HashSet<>(exceptions);if(enabled)next.remove(host);else next.add(host);
        if(!preferences.edit().putStringSet("disabledHosts",next).commit())throw new IllegalStateException("The website choice could not be saved.");
        exceptions.clear();exceptions.addAll(next);
        for(Map.Entry<GeckoSession,String> entry:pageUrls.entrySet())entry.getKey().getSettings().setUseTrackingProtection(shieldsEnabled(hostOf(entry.getValue())));
        sendConfiguration();
    }
    public String dnsChoice(){
        String choice=preferences.getString("dnsChoice",team?"toxitech":"system");
        return Arrays.asList("toxitech","system","quad9","cloudflare","custom").contains(choice)?choice:(team?"toxitech":"system");
    }
    public String dnsUri(){
        switch(dnsChoice()){
            case "system":return "";
            case "quad9":return "https://dns.quad9.net/dns-query";
            case "cloudflare":return "https://cloudflare-dns.com/dns-query";
            case "custom":return checkedDns(preferences.getString("customDns",TOXITECH));
            default:return TOXITECH;
        }
    }
    private int dnsMode(){return "system".equals(dnsChoice())?GeckoRuntimeSettings.TRR_MODE_DISABLED:GeckoRuntimeSettings.TRR_MODE_ONLY;}
    public void setDns(String choice,String customUri){
        if(!Arrays.asList("toxitech","system","quad9","cloudflare","custom").contains(choice))throw new IllegalArgumentException("Choose a DNS provider.");
        String custom="custom".equals(choice)?checkedDns(customUri):preferences.getString("customDns",TOXITECH);
        if(!preferences.edit().putString("dnsChoice",choice).putString("customDns",custom).commit())throw new IllegalStateException("The DNS choice could not be saved.");
        try {writeConfiguration();}catch(IOException e){throw new IllegalStateException("The DNS policy could not be saved.",e);}
        // No TRR-first mode and no implicit plaintext fallback. Android's own
        // DNS settings are untouched; System is a deliberate user selection.
        runtime.getSettings().setTrustedRecursiveResolverUri(dnsUri().isEmpty()?TOXITECH:dnsUri());
        runtime.getSettings().setTrustedRecursiveResolverMode(dnsMode());
    }
    private static String checkedDns(String value){
        if(value==null||value.length()>2048)throw new IllegalArgumentException("Enter a valid HTTPS DNS endpoint.");
        String clean=value.trim();
        try{
            java.net.URI uri=new java.net.URI(clean).parseServerAuthority();
            if(!"https".equalsIgnoreCase(uri.getScheme())||uri.getHost()==null||uri.getHost().isEmpty()
                ||uri.getUserInfo()!=null||uri.getFragment()!=null||uri.getPort()==0||uri.getPort()>65535
                ||uri.isOpaque())throw new IllegalArgumentException();
        }catch(Exception e){throw new IllegalArgumentException("DNS must use a valid HTTPS endpoint without credentials or a fragment.");}
        return clean;
    }

    private final WebExtension.MessageDelegate messages=new WebExtension.MessageDelegate(){
        @Override public void onConnect(WebExtension.Port connected){
            if(connected.sender.environmentType!=WebExtension.MessageSender.ENV_TYPE_EXTENSION
                ||!EXTENSION_ID.equals(connected.sender.webExtension.id))return;
            port=connected;port.setDelegate(new WebExtension.PortDelegate(){
                @Override public void onPortMessage(Object value,WebExtension.Port p){
                    if(p!=port||!(value instanceof JSONObject))return;
                    JSONObject message=(JSONObject)value;
                    switch(message.optString("type")){
                        case "ready":
                            if(message.optInt("rules")!=107582){fail("The local protection rules are invalid.");return;}
                            rules=message.optInt("rules");updatedAt=message.optString("updatedAt");extensionReady=true;verifyPreferences();break;
                        case "stats":
                            WeakReference<GeckoSession> ref=tabSessions.get(message.optInt("tabId",-1));
                            if(ref!=null&&ref.get()!=null)receiveStats(ref.get(),message.optJSONObject("snapshot"));break;
                        case "failure":fail("Cyphra Shields could not verify its bundled protection.");break;
                    }
                }
                @Override public void onDisconnect(WebExtension.Port p){if(p==port){
                    port=null;extensionReady=false;
                    // Gecko intentionally reloads the extension when granting its
                    // private-browsing permission. Browsing is still gated here.
                    if(ready&&!closing)fail("The request blocker disconnected. Restart Cyphra to restore protection.");
                }}
            });sendConfiguration();
        }
        @Override public GeckoResult<Object> onMessage(String nativeApp,Object value,WebExtension.MessageSender sender){
            if(!"cyphra".equals(nativeApp)||!EXTENSION_ID.equals(sender.webExtension.id)
                ||sender.environmentType!=WebExtension.MessageSender.ENV_TYPE_CONTENT_SCRIPT
                ||sender.session==null||!sender.isTopLevel()||!(value instanceof JSONObject))return null;
            JSONObject message=(JSONObject)value;
            if("bind".equals(message.optString("type"))&&message.optInt("tabId",-1)>=0&&pageUrls.containsKey(sender.session)){
                tabSessions.values().removeIf(ref->ref.get()==null||!ref.get().isOpen());
                tabSessions.put(message.optInt("tabId"),new WeakReference<>(sender.session));
                // A progress stop and a same-URL bind can both finish an
                // attachment. A new isolated content world proves a new document.
                String documentId=message.optString("documentId");
                boolean generationChanged=documentId.matches("[a-f0-9]{32}")&&!documentId.equals(documentIds.get(sender.session));
                traceDocument("content-bind-before",sender.session,generationChanged);
                if(generationChanged){
                    documentIds.put(sender.session,documentId);previousStatistics.remove(sender.session);
                }
                receiveStats(sender.session,message.optJSONObject("snapshot"));
                traceDocument("content-bind-after",sender.session,generationChanged);
            }
            return GeckoResult.fromValue(null);
        }
    };

    private void sendConfiguration(){
        if(port==null)return;
        JSONObject message=new JSONObject();try{
            message.put("type","configuration");message.put("work",work);
            message.put("disabledHosts",new JSONArray(exceptions));port.postMessage(message);
        }catch(JSONException e){fail("The local protection policy could not be sent.");}
    }
    private void receiveStats(GeckoSession session,JSONObject data){
        if(data==null||!data.optBoolean("ready")||!isReady())return;
        String expected=hostOf(pageUrls.get(session)),reported=normalizeHost(data.optString("host"));
        if(!expected.isEmpty()&&!expected.equals(reported))return;
        int blocked=count(data,"blocked"),filters=count(data,"filters"),telemetry=count(data,"telemetry"),strict=count(data,"strict");
        if(blocked!=filters+telemetry+strict)return;
        LinkedHashSet<String> hosts=new LinkedHashSet<>();JSONArray list=data.optJSONArray("hosts");
        if(list!=null)for(int i=0;i<Math.min(32,list.length());i++){String host=normalizeHost(list.optString(i));if(validHost(host))hosts.add(host);}
        Stats old=snapshot(session);hosts.addAll(old.hosts);
        Stats next=new Stats(blocked,filters,telemetry,strict,old.nativeBlocked,rules,isReady(),updatedAt,new ArrayList<>(hosts));
        statistics.put(session,next);emitStats(session,next);
    }
    private void traceDocument(String event,GeckoSession session,boolean generationChanged){
        if(!BuildConfig.DEBUG)return;
        Stats stats=snapshot(session);
        // Local debug diagnostics contain no URL, hostname, document ID or data.
        android.util.Log.d("CyphraDocument","event="+event+" generationChanged="+generationChanged
            +" blocked="+stats.blocked+" nativeBlocked="+stats.nativeBlocked);
    }
    private int count(JSONObject value,String key){return Math.max(0,Math.min(1000000,value.optInt(key)));}

    private void verifyPreferences(){
        Map<String,Object> expected=new LinkedHashMap<>();
        expected.put("cyphra.android.policy",1);
        expected.put("dom.ipc.processHangMonitor",true);
        expected.put("toolkit.telemetry.enabled",false);
        expected.put("toolkit.telemetry.unified",false);
        expected.put("toolkit.telemetry.server","data:,");
        expected.put("datareporting.healthreport.uploadEnabled",false);
        expected.put("datareporting.policy.dataSubmissionEnabled",false);
        expected.put("privacy.resistFingerprinting",work);
        expected.put("webgl.disabled",work);
        expected.put("security.tls.version.min",3);
        expected.put("network.trr.mode",dnsMode());
        expected.put("network.trr.uri",dnsUri().isEmpty()?TOXITECH:dnsUri());
        expected.put("security.webauth.webauthn",false);
        GeckoPreferenceController.getGeckoPrefs(new ArrayList<>(expected.keySet())).accept(values->{
            Map<String,Object> actual=new HashMap<>();for(GeckoPreferenceController.GeckoPreference<?> pref:values)actual.put(pref.pref,pref.getValue());
            for(Map.Entry<String,Object> entry:expected.entrySet())if(!entry.getValue().equals(actual.get(entry.getKey()))){
                android.util.Log.e("CyphraEngine","Privacy policy verification failed for "+entry.getKey());
                fail("Gecko did not apply its privacy policy.");return;
            }
            // A boolean-only native policy trace provides positive readback
            // evidence without recording URLs, script names or profile data.
            android.util.Log.i("CyphraEngine","processHangMonitor=true verified before browsing");
            preferencesVerified=true;maybeReady();
        },e->fail("Gecko's privacy policy could not be verified."));
    }
    private void maybeReady(){
        if(!closing&&!failed&&!ready&&extensionReady&&privateReady&&preferencesVerified){
            // A failed/interrupted startup retries the purge next time. This
            // marker never changes browsing data or user settings.
            if(!startupCacheMatches()
                &&!preferences.edit().putString(STARTUP_CACHE_ENGINE_KEY,BuildConfig.GECKOVIEW_OMNI_SHA256)
                    .putLong(STARTUP_CACHE_APK_KEY,installedApkUpdateTime).commit()){
                fail("The engine startup cache version could not be saved.");return;
            }
            ready=true;if(listener!=null)ui.post(()->{if(listener!=null&&isReady())listener.onReady();});
        }
    }
    private boolean startupCacheMatches(){
        return BuildConfig.GECKOVIEW_OMNI_SHA256.equals(preferences.getString(STARTUP_CACHE_ENGINE_KEY,""))
            &&installedApkUpdateTime==preferences.getLong(STARTUP_CACHE_APK_KEY,-1);
    }
    private void fail(String reason){
        if(failed||closing)return;failed=true;ready=false;failure=reason;
        // stop() alone leaves already loaded JavaScript alive. When the blocker
        // goes away, close every renderer and stop Gecko before further browsing.
        for(GeckoSession session:new ArrayList<>(pageUrls.keySet()))try{session.stop();session.close();}catch(Exception ignored){}
        shutdown.request(null);
        if(listener!=null)listener.onFailure(reason);
    }

    /** This file is app-managed, never read from shared storage or adb's default location. */
    private void writeConfiguration()throws IOException{
        Map<String,Object> prefs=new LinkedHashMap<>();
        prefs.put("cyphra.android.policy",1);
        prefs.put("dom.ipc.processHangMonitor",true);
        for(String key:Arrays.asList("toolkit.telemetry.enabled","toolkit.telemetry.unified",
            "toolkit.telemetry.archive.enabled","toolkit.telemetry.newProfilePing.enabled",
            "toolkit.telemetry.firstShutdownPing.enabled","toolkit.telemetry.shutdownPingSender.enabled",
            "toolkit.telemetry.updatePing.enabled","toolkit.telemetry.bhrPing.enabled",
            "datareporting.healthreport.uploadEnabled","datareporting.policy.dataSubmissionEnabled",
            "datareporting.usage.uploadEnabled","app.normandy.enabled","app.shield.optoutstudies.enabled",
            "network.captive-portal-service.enabled","network.connectivity-service.enabled",
            "network.prefetch-next","network.predictor.enabled","network.dnsPrefetchFromHTTPS",
            "network.trr.allow_fallback","network.trr.use_fallback_when_no_answers",
            "network.android_doh.autoselect_enabled","network.trr.android_rollout_enabled",
            "extensions.update.enabled","extensions.systemAddon.update.enabled","media.gmp-manager.updateEnabled",
            "media.eme.enabled","browser.safebrowsing.downloads.remote.enabled",
            "browser.safebrowsing.provider.google4.dataSharing.enabled","dom.push.enabled",
            // The upstream Android FIDO bridge depends on proprietary GMS SDKs.
            // Its public API and backends remain disabled in this open-source APK.
            "security.webauth.webauthn","security.webauth.webauthn_enable_usbtoken",
            "security.webauth.webauthn_enable_softtoken"))prefs.put(key,false);
        prefs.put("toolkit.telemetry.server","data:,");
        prefs.put("services.settings.server","data:,");prefs.put("app.normandy.api_url","");
        prefs.put("media.gmp-manager.url","");prefs.put("network.http.speculative-parallel-limit",0);
        prefs.put("network.dns.disablePrefetch",true);prefs.put("privacy.globalprivacycontrol.enabled",true);
        prefs.put("privacy.donottrackheader.enabled",true);prefs.put("privacy.resistFingerprinting",work);
        prefs.put("privacy.fingerprintingProtection",true);prefs.put("privacy.fingerprintingProtection.pbmode",true);
        prefs.put("webgl.disabled",work);prefs.put("security.tls.version.min",3);
        prefs.put("network.trr.mode",dnsMode());prefs.put("network.trr.uri",dnsUri().isEmpty()?TOXITECH:dnsUri());
        prefs.put("network.trr.confirmationNS","skip");prefs.put("network.trr.strict_native_fallback",false);
        prefs.put("network.trr.excluded-domains","");prefs.put("network.trr.builtin-excluded-domains","");
        prefs.put("dom.security.https_only_mode.upgrade_local",false);
        prefs.put("dom.security.https_only_mode.upgrade_onion",false);
        prefs.put("devtools.debugger.remote-enabled",false);
        StringBuilder yaml=new StringBuilder("prefs:\n");
        for(Map.Entry<String,Object> entry:prefs.entrySet())yaml.append("  ").append(yamlQuote(entry.getKey())).append(": ")
            .append(entry.getValue() instanceof String?yamlQuote((String)entry.getValue()):entry.getValue()).append('\n');
        File temporary=new File(config.getParentFile(),"policy.yaml.tmp");
        try(FileOutputStream output=new FileOutputStream(temporary)){output.write(yaml.toString().getBytes(StandardCharsets.UTF_8));output.getFD().sync();}
        if(!temporary.renameTo(config)){temporary.delete();throw new IOException("Cannot replace managed policy.");}
    }
    // Android's JSON writer escapes '/', but '\/' is not a YAML escape. The
    // remaining JSON double-quote escapes are also valid in YAML double quotes.
    static String yamlQuote(String value){return JSONObject.quote(value).replace("\\/","/");}
    private static String normalizeHost(String value){return value==null?"":value.toLowerCase(java.util.Locale.ROOT).replaceFirst("\\.$","");}
    private static boolean validHost(String host){return host!=null&&!host.isEmpty()&&host.length()<=253&&host.matches("[a-z0-9.:\\[\\]-]+");}
    private static String hostOf(String uri){try{return normalizeHost(Uri.parse(uri==null?"":uri).getHost());}catch(Exception e){return "";}}
}
