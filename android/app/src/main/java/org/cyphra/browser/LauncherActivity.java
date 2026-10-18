/* MPL-2.0. Only this routing activity accepts external browser intents. */
package org.cyphra.browser;
import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.app.ActivityManager;
import android.widget.Toast;
public final class LauncherActivity extends Activity {
    private final Handler handler=new Handler(Looper.getMainLooper());
    private String mode,url;
    private long deadline;
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        String requested=getIntent().getStringExtra("mode");
        mode=EditionPolicy.launchMode(BuildConfig.EDITION,requested,getPreferencesMode(),BuildConfig.DEFAULT_MODE);
        url=getIntent().getDataString();
        if(url==null)url=getIntent().getStringExtra("url");
        if(!BrowserStore.isWebURL(url))url=null;
        deadline=SystemClock.elapsedRealtime()+20000;
        if(otherModeRunning())sendBroadcast(new Intent(getPackageName()+".CLOSE_MODE").setPackage(getPackageName()).putExtra("mode",mode.equals("work")?"personal":"work"));
        waitThenOpen();
    }
    private String getPreferencesMode(){return getSharedPreferences("cyphra-routing",MODE_PRIVATE).getString("mode",BuildConfig.DEFAULT_MODE);}
    private boolean otherModeRunning(){
        ActivityManager manager=(ActivityManager)getSystemService(ACTIVITY_SERVICE);
        java.util.List<ActivityManager.RunningAppProcessInfo> processes=manager.getRunningAppProcesses();
        if(processes!=null)for(ActivityManager.RunningAppProcessInfo process:processes)
            if(process.uid==android.os.Process.myUid()&&process.processName.equals(getPackageName()+":"+(mode.equals("work")?"personal":"work")))return true;
        return false;
    }
    private void waitThenOpen(){
        if(isFinishing())return;
        if(otherModeRunning()){
            if(SystemClock.elapsedRealtime()>=deadline){Toast.makeText(this,"Cyphra is still closing the other profile. Please try again.",Toast.LENGTH_LONG).show();finish();return;}
            handler.postDelayed(this::waitThenOpen,100);return;
        }
        getSharedPreferences("cyphra-routing",MODE_PRIVATE).edit().putString("mode",mode).commit();
        Intent next=new Intent(this,mode.equals("work")?WorkActivity.class:PersonalActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        if(url!=null)next.putExtra("url",url);
        startActivity(next);finish();
    }
    @Override protected void onDestroy(){handler.removeCallbacksAndMessages(null);super.onDestroy();}
}
