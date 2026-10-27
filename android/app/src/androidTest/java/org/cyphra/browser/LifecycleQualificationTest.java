/* MPL-2.0. Native lifecycle qualification on a disposable test profile only. */
package org.cyphra.browser;

import android.app.Activity;
import android.app.Application;
import android.app.Instrumentation;
import android.content.ComponentName;
import android.content.Intent;
import android.os.Bundle;
import android.os.Process;
import android.os.SystemClock;
import android.view.WindowManager;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.net.HttpURLConnection;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Objects;
import java.util.concurrent.Callable;
import java.util.concurrent.atomic.AtomicReference;
import org.json.JSONArray;
import org.json.JSONObject;
import org.mozilla.geckoview.GeckoRuntime;
import org.mozilla.geckoview.GeckoSession;
import org.mozilla.geckoview.GeckoView;

/** Each manifest declaration targets exactly one real browser process. */
public abstract class LifecycleQualificationTest extends Instrumentation {
    private static final long TIMEOUT=90000;
    private final JSONObject observed=new JSONObject();
    private final JSONArray events=new JSONArray();
    private volatile MainActivity initial;
    private volatile String failure;
    private volatile boolean proofWritten;
    private String run,scenario,fixture,packageName,activityName;
    private ActivityMonitor monitor;
    protected abstract String mode();

    @Override public void onCreate(Bundle arguments){
        super.onCreate(arguments);
        try{
            run=arguments.getString("run","");scenario=arguments.getString("scenario","");
            fixture=arguments.getString("fixture","http://localhost:8766");
            require(run.matches("[a-zA-Z0-9_-]{1,64}"),"A unique bounded run ID is required.");
            require(List.of("retained","cold-recreate","early-finish").contains(scenario),"Unknown lifecycle scenario.");
            URI endpoint=URI.create(fixture);
            require("http".equals(endpoint.getScheme())&&List.of("localhost","127.0.0.1").contains(endpoint.getHost())
                &&endpoint.getPort()>0&&endpoint.getRawUserInfo()==null&&endpoint.getRawQuery()==null&&endpoint.getRawFragment()==null
                &&(endpoint.getPath().isEmpty()||"/".equals(endpoint.getPath())),"Only an explicit loopback fixture is permitted.");
            fixture=fixture.replaceFirst("/$","");packageName=getTargetContext().getPackageName();
            require(Application.getProcessName().equals(packageName+":"+mode()),"Instrumentation is in the wrong process.");
            activityName="org.cyphra.browser."+("work".equals(mode())?"WorkActivity":"PersonalActivity");
            monitor=addMonitor(activityName,null,false);
        }catch(Throwable error){failure=error.toString();}
        start();
    }

    @Override public void onStart(){
        try{
            checkFailure();
            getTargetContext().startActivity(new Intent().setComponent(new ComponentName(packageName,activityName)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            await(()->initial!=null,"The target Activity was not created.");
            if("early-finish".equals(scenario)){
                // Production intentionally kills this mode after Gecko exits.
                // The host requires the durable actual-exit proof and PID loss;
                // am instrument's termination is never the success signal.
                await(()->proofWritten,"No actual Gecko exit was observed.");return;
            }
            if("cold-recreate".equals(scenario))coldRecreation();else retainedRecreation();
            writeProof(true);Bundle result=new Bundle();result.putString("stream","\nLifecycle proof: "+proofFile()+"\n");finish(Activity.RESULT_OK,result);
        }catch(Throwable error){
            failure=error.toString();writeFailure();Bundle result=new Bundle();result.putString("stream","\nLifecycle failed: "+failure+"\n");finish(Activity.RESULT_CANCELED,result);
        }finally{if(monitor!=null)removeMonitor(monitor);}
    }

    @Override public void callActivityOnCreate(Activity activity,Bundle saved){
        super.callActivityOnCreate(activity,saved);
        if(!(activity instanceof MainActivity)||initial!=null)return;
        initial=(MainActivity)activity;
        try{
            Engine engine=(Engine)field(initial,"engine");Object gate=field(engine,"shutdown");
            observe("runtimeBefore",identity(engine.runtime));observe("pidBefore",Process.myPid());
            observe("barrierReadyAtRequest",field(gate,"ready"));event("created");
            if("cold-recreate".equals(scenario)){
                require(!(Boolean)field(gate,"ready"),"Cold recreation missed the native-readiness window.");
                event("recreate-requested");activity.recreate();
            }else if("early-finish".equals(scenario)){
                require(!(Boolean)field(gate,"ready"),"Early finish missed the native-readiness window.");
                GeckoRuntime.Delegate original=engine.runtime.getDelegate();
                require(original!=null,"The production runtime delegate is missing.");
                engine.runtime.setDelegate(()->{
                    original.onShutdown();
                    try{
                        event("actual-gecko-exited");observe("actualExited",field(gate,"exited"));
                        observe("barrierReadyAtExit",field(gate,"ready"));observe("shutdownStartedAtExit",field(gate,"started"));
                        observe("engineClosingAtExit",field(engine,"closing"));observe("activityShuttingDownAtExit",field(initial,"shuttingDown"));
                        require(Boolean.FALSE.equals(value("barrierReadyBeforeDestroy")),"Destruction missed the early native-readiness window.");
                        require(Boolean.TRUE.equals(value("shutdownRequestedAfterDestroy"))&&Boolean.FALSE.equals(value("shutdownStartedAfterDestroy")),"Early destruction did not queue shutdown.");
                        require((Boolean)field(gate,"ready")&&(Boolean)field(gate,"started")&&(Boolean)field(gate,"exited"),"Actual exit did not follow queued native shutdown.");
                        require((Boolean)field(engine,"closing")&&(Boolean)field(initial,"shuttingDown"),"The production exit path did not run.");
                        writeProof(true);
                    }catch(Throwable error){failure=error.toString();writeFailure();}
                });
                event("finish-requested");activity.finish();
            }
        }catch(Throwable error){failure=error.toString();writeFailure();}
    }

    @Override public void callActivityOnDestroy(Activity activity){
        if(activity==initial)try{
            Object gate=field(field(initial,"engine"),"shutdown");
            observe("configurationDestroy",activity.isChangingConfigurations());observe("barrierReadyBeforeDestroy",field(gate,"ready"));event("destroy-before");
        }catch(Throwable error){failure=error.toString();}
        super.callActivityOnDestroy(activity);
        if(activity==initial)try{
            Object gate=field(field(initial,"engine"),"shutdown");
            observe("shutdownRequestedAfterDestroy",field(gate,"requested"));observe("shutdownStartedAfterDestroy",field(gate,"started"));event("destroy-after");
        }catch(Throwable error){failure=error.toString();writeFailure();}
    }

    private void coldRecreation()throws Exception{
        MainActivity replacement=replacement();awaitReady(replacement);
        Engine before=(Engine)field(initial,"engine"),after=(Engine)field(replacement,"engine");
        require(before==after,"Cold recreation replaced the Engine singleton.");
        require(Boolean.TRUE.equals(value("configurationDestroy")),"The original Activity did not undergo configuration destruction.");
        require(Boolean.FALSE.equals(value("shutdownRequestedAfterDestroy")),"Configuration destruction requested Gecko shutdown.");
        require(!(Boolean)ui(()->field(field(after,"shutdown"),"requested")),"Cold recreation shut down Gecko.");
        observe("sameRuntime",true);observe("replacementReady",true);observe("differentActivity",replacement!=initial);
        observe("runtimeAfter",identity(after.runtime));observe("pidAfter",Process.myPid());
        require(value("pidBefore").equals(Process.myPid()),"The browser process changed during recreation.");
    }

    private void retainedRecreation()throws Exception{
        awaitReady(initial);
        require(((List<?>)ui(()->field(initial,"tabs"))).size()<=18,"The disposable profile needs two free tab slots.");
        Object ordinary=ui(()->{invoke(initial,"newTab",new Class<?>[]{boolean.class,String.class},false,page("ordinary"));return field(initial,"current");});
        JSONObject ordinaryBefore=awaitDocument("ordinary",null,-1,2);
        observe("ordinaryDocumentBeforeRecreation",ordinaryBefore);
        Object privateTab=ui(()->{invoke(initial,"newTab",new Class<?>[]{boolean.class,String.class},true,page("private"));return field(initial,"current");});
        JSONObject privateBefore=awaitDocument("private",null,-1,2);
        observe("privateDocumentBeforeRecreation",privateBefore);
        GeckoSession ordinarySession=(GeckoSession)field(ordinary,"session"),privateSession=(GeckoSession)field(privateTab,"session");
        Object ordinaryNavigation=field(ordinary,"navigation"),privateNavigation=field(privateTab,"navigation");
        Object ordinaryDelegate=ui(ordinarySession::getNavigationDelegate),privateDelegate=ui(privateSession::getNavigationDelegate);
        Engine engine=(Engine)field(initial,"engine");Object oldListener=field(initial,"engineListener");
        observe("retainedStage","requesting-recreation");
        event("recreate-requested");ui(()->{initial.recreate();return null;});MainActivity replacement=replacement();awaitReady(replacement);
        observe("retainedStage","replacement-ready");
        retainedURLs("retainedURLsAfterReplacementReady",ordinary,privateTab,ordinaryBefore,privateBefore);
        ui(()->{
            require(field(replacement,"engine")==engine,"Recreation replaced the runtime.");
            require(field(replacement,"current")==privateTab&&field(replacement,"lastOrdinary")==ordinary,"Private/ordinary selection was lost.");
            require(field(ordinary,"session")==ordinarySession&&field(privateTab,"session")==privateSession,"A retained GeckoSession was replaced.");
            require(field(ordinary,"navigation")==ordinaryNavigation&&field(privateTab,"navigation")==privateNavigation,"Document navigation memory was replaced.");
            require(ordinarySession.getNavigationDelegate()!=ordinaryDelegate&&privateSession.getNavigationDelegate()!=privateDelegate,"Old Activity delegates were retained.");
            Object owner=field(replacement,"sessionOwner");require(field(ordinary,"delegateOwner")==owner&&field(privateTab,"delegateOwner")==owner,"Session callbacks have the wrong Activity owner.");
            require(((GeckoView)field(initial,"gecko")).getSession()==null,"The destroyed GeckoView retained a session.");
            require(field(engine,"listener")!=oldListener&&field(engine,"listener")==field(replacement,"engineListener"),"The Engine retained the destroyed Activity listener.");
            require(((GeckoView)field(replacement,"gecko")).getSession()==privateSession,"The selected private session was not attached.");
            require((replacement.getWindow().getAttributes().flags&WindowManager.LayoutParams.FLAG_SECURE)!=0,"Private screenshot protection was lost.");return null;
        });
        JSONObject privateAfter=awaitDocument("private",privateBefore.getJSONObject("latest").getString("token"),privateBefore.getJSONObject("latest").getLong("sequence"),2);
        sameDocument(privateBefore,privateAfter);
        observe("retainedStage","private-document-live-after-recreation");
        retainedURLs("retainedURLsBeforeOrdinarySelection",ordinary,privateTab,ordinaryBefore,privateBefore);
        ui(()->{invoke(replacement,"select",new Class<?>[]{ordinary.getClass()},ordinary);return null;});
        observe("retainedStage","ordinary-selected-after-recreation");
        JSONObject ordinaryAfter=awaitDocument("ordinary",ordinaryBefore.getJSONObject("latest").getString("token"),ordinaryBefore.getJSONObject("latest").getLong("sequence"),2);
        sameDocument(ordinaryBefore,ordinaryAfter);history(ordinarySession,"ordinary",ordinaryAfter);
        ui(()->{invoke(replacement,"select",new Class<?>[]{privateTab.getClass()},privateTab);return null;});history(privateSession,"private",privateAfter);
        String saved=getTargetContext().getSharedPreferences("cyphra-data-"+mode(),0).getString("tabs","");
        require(!saved.contains("private-"+run),"The private test URL was saved to persistent tabs.");
        require(ui(initial::isDestroyed),"The original Activity was not destroyed.");
        observe("sameRuntime",true);observe("ordinarySessionSame",true);observe("privateSessionSame",true);observe("navigationMemorySame",true);
        observe("ordinarySessionBefore",identity(ordinarySession));observe("ordinarySessionAfter",identity(field(ordinary,"session")));
        observe("privateSessionBefore",identity(privateSession));observe("privateSessionAfter",identity(field(privateTab,"session")));
        observe("selectedPrivateRetained",true);observe("lastOrdinaryRetained",true);observe("delegatesRebound",true);observe("oldViewReleased",true);observe("oldListenerDetached",true);
        observe("oldActivityDestroyed",true);observe("privateAbsentFromSavedTabs",true);observe("privateSecureWindow",true);observe("historyBackForwardVerified",true);
        observe("ordinaryDocument",new JSONObject().put("before",ordinaryBefore).put("after",ordinaryAfter));
        observe("privateDocument",new JSONObject().put("before",privateBefore).put("after",privateAfter));
        observe("runtimeAfter",identity(engine.runtime));observe("pidAfter",Process.myPid());
    }

    private void retainedURLs(String checkpoint,Object ordinary,Object privateTab,JSONObject ordinaryDocument,JSONObject privateDocument)throws Exception{
        String expectedOrdinary=ordinaryDocument.getJSONObject("latest").getString("href");
        String expectedPrivate=privateDocument.getJSONObject("latest").getString("href");
        JSONObject urls=ui(()->new JSONObject()
            .put("expectedOrdinary",expectedOrdinary).put("expectedPrivate",expectedPrivate)
            .put("ordinaryTab",field(ordinary,"url")).put("ordinaryNavigation",field(field(ordinary,"navigation"),"documentUrl"))
            .put("privateTab",field(privateTab,"url")).put("privateNavigation",field(field(privateTab,"navigation"),"documentUrl")));
        // Persist all four actual values before any assertion can abort the case.
        observe(checkpoint,urls);
        require(expectedOrdinary.equals(urls.getString("ordinaryTab")),checkpoint+": the retained ordinary tab URL changed.");
        require(expectedOrdinary.equals(urls.getString("ordinaryNavigation")),checkpoint+": the retained ordinary navigation URL changed.");
        require(expectedPrivate.equals(urls.getString("privateTab")),checkpoint+": the retained private tab URL changed.");
        require(expectedPrivate.equals(urls.getString("privateNavigation")),checkpoint+": the retained private navigation URL changed.");
    }

    private void history(GeckoSession session,String kind,JSONObject baseline)throws Exception{
        String token=baseline.getJSONObject("latest").getString("token");long sequence=baseline.getJSONObject("latest").getLong("sequence");
        ui(()->{session.goBack();return null;});JSONObject back=awaitDocument(kind,token,sequence,1);
        ui(()->{session.goForward();return null;});JSONObject forward=awaitDocument(kind,token,back.getJSONObject("latest").getLong("sequence"),2);
        require(baseline.getInt("pageRequests")==forward.getInt("pageRequests"),"History navigation reloaded the document.");
        require(baseline.getJSONObject("latest").getString("form").equals(forward.getJSONObject("latest").getString("form")),"History navigation lost runtime form input.");
    }

    private void sameDocument(JSONObject before,JSONObject after)throws Exception{
        require(before.getInt("pageRequests")==1&&after.getInt("pageRequests")==1,"Recreation loaded the fixture document again.");
        JSONObject a=before.getJSONObject("latest"),b=after.getJSONObject("latest");
        for(String key:List.of("token","form","href","historyLength","stateToken","stateStep"))require(Objects.equals(a.get(key),b.get(key)),"Recreation changed document field "+key);
        require(a.getLong("sequence")<b.getLong("sequence"),"The retained document timer did not advance.");
        require(a.getInt("historyLength")>=3&&a.getInt("stateStep")==2,"The document history fixture did not initialize.");
    }

    private MainActivity replacement()throws Exception{
        long deadline=SystemClock.elapsedRealtime()+TIMEOUT;
        while(SystemClock.elapsedRealtime()<deadline){checkFailure();Activity activity=monitor.waitForActivityWithTimeout(1000);if(activity instanceof MainActivity&&activity!=initial)return (MainActivity)activity;}
        throw new AssertionError("ActivityMonitor did not observe a replacement Activity.");
    }
    private void awaitReady(MainActivity activity)throws Exception{
        await(()->ui(()->{Engine engine=(Engine)field(activity,"engine");if((Boolean)field(engine,"failed"))throw new AssertionError("Gecko protection failed: "+field(engine,"failure"));return (Boolean)field(activity,"ready");}),"The replacement Activity did not become ready.");
    }
    private String page(String kind){return fixture+"/page?run="+run+"&kind="+kind+"&marker="+kind+"-"+run;}
    private JSONObject awaitDocument(String kind,String token,long previous,int step)throws Exception{
        AtomicReference<JSONObject> found=new AtomicReference<>();
        observe("documentWait",new JSONObject().put("kind",kind).put("stateStep",step).put("previousSequence",previous)
            .put("expectedToken",token==null?JSONObject.NULL:token));
        await(()->{JSONObject snapshot=getJSON(fixture+"/snapshot?run="+run+"&kind="+kind);observe("lastDocumentSnapshot",snapshot);JSONObject latest=snapshot.optJSONObject("latest");
            if(latest==null)return false;require(token==null||token.equals(latest.getString("token")),"The "+kind+" live document token changed.");
            if(latest.getLong("sequence")>previous&&latest.getInt("stateStep")==step){found.set(snapshot);return true;}return false;},
            "The "+kind+" document did not report the required live state (stateStep="+step+", sequence>"+previous+").");return found.get();
    }
    private JSONObject getJSON(String url)throws Exception{
        HttpURLConnection connection=(HttpURLConnection)new java.net.URL(url).openConnection();connection.setConnectTimeout(3000);connection.setReadTimeout(3000);
        try(InputStream input=connection.getInputStream()){return new JSONObject(new String(input.readAllBytes(),StandardCharsets.UTF_8));}finally{connection.disconnect();}
    }
    private void await(Callable<Boolean> condition,String message)throws Exception{
        long deadline=SystemClock.elapsedRealtime()+TIMEOUT;
        while(SystemClock.elapsedRealtime()<deadline){checkFailure();if(condition.call())return;Thread.sleep(50);}throw new AssertionError(message);
    }
    private <T>T ui(Callable<T> action)throws Exception{
        AtomicReference<T> result=new AtomicReference<>();AtomicReference<Throwable> error=new AtomicReference<>();
        runOnMainSync(()->{try{result.set(action.call());}catch(Throwable caught){error.set(caught);}});
        if(error.get()!=null){if(error.get() instanceof Exception)throw (Exception)error.get();throw new AssertionError(error.get());}return result.get();
    }
    private static Object field(Object owner,String name)throws Exception{
        for(Class<?> type=owner.getClass();type!=null;type=type.getSuperclass())try{Field field=type.getDeclaredField(name);field.setAccessible(true);return field.get(owner);}catch(NoSuchFieldException next){}
        throw new NoSuchFieldException(name);
    }
    private static Object invoke(Object owner,String name,Class<?>[] types,Object...args)throws Exception{Method method=MainActivity.class.getDeclaredMethod(name,types);method.setAccessible(true);return method.invoke(owner,args);}
    private static int identity(Object value){return System.identityHashCode(value);}
    private static void require(boolean value,String message){if(!value)throw new AssertionError(message);}
    private void checkFailure(){if(failure!=null)throw new AssertionError(failure);}
    private synchronized void observe(String key,Object value)throws Exception{observed.put(key,value);}
    private synchronized Object value(String key)throws Exception{return observed.get(key);}
    private synchronized void event(String name){events.put(name);android.util.Log.i("CyphraLifecycleTest","run="+run+" scenario="+scenario+" event="+name);}
    private File proofFile(){return new File(getTargetContext().getCacheDir(),"lifecycle-"+run+".json");}
    private synchronized void writeProof(boolean passed)throws Exception{
        JSONObject proof=new JSONObject().put("schema","cyphra-android-lifecycle-case-v1").put("package",packageName).put("edition",BuildConfig.EDITION)
            .put("mode",mode()).put("scenario",scenario).put("run",run).put("pid",Process.myPid()).put("process",Application.getProcessName())
            .put("passed",passed).put("observations",observed).put("events",events);
        if(failure!=null)proof.put("failure",failure);
        File file=proofFile(),temporary=new File(file.getPath()+".tmp");
        try(FileOutputStream output=new FileOutputStream(temporary)){output.write(proof.toString(2).getBytes(StandardCharsets.UTF_8));output.getFD().sync();}
        require(temporary.renameTo(file),"Could not commit native lifecycle proof.");proofWritten=true;
    }
    private void writeFailure(){try{writeProof(false);}catch(Throwable error){android.util.Log.e("CyphraLifecycleTest","Could not write failure proof",error);}}
}
