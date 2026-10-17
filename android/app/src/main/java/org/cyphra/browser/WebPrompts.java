/* MPL-2.0. Website requests are answered through native, origin-labelled dialogs. */
package org.cyphra.browser;

import android.app.*;
import android.content.*;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.text.InputType;
import android.widget.*;
import java.util.*;
import org.mozilla.geckoview.*;

public final class WebPrompts implements GeckoSession.PromptDelegate,GeckoSession.PermissionDelegate {
    private final Activity activity;
    private Appearance appearance;
    private final java.util.function.Function<GeckoSession,String> sessionURL;
    private GeckoSession.PermissionDelegate.Callback permissionCallback;
    private boolean androidPermissionInFlight;
    private boolean androidFileInFlight;
    private String[] requestedAndroidPermissions;
    private FilePrompt filePrompt;
    private GeckoResult<PromptResponse> fileResult;
    private final ArrayList<Dialog> dialogs=new ArrayList<>();
    WebPrompts(Activity activity,Appearance appearance,java.util.function.Function<GeckoSession,String> sessionURL){this.activity=activity;this.appearance=appearance;this.sessionURL=sessionURL;}
    /** Occupancy survives recreation; website callbacks and Activity references do not. */
    static final class PendingAndroidRequests {
        final boolean permission,file;
        PendingAndroidRequests(boolean permission,boolean file){this.permission=permission;this.file=file;}
    }
    PendingAndroidRequests pendingAndroidRequests(){return new PendingAndroidRequests(androidPermissionInFlight,androidFileInFlight);}
    void inheritPendingAndroidRequests(PendingAndroidRequests pending){androidPermissionInFlight=pending.permission;androidFileInFlight=pending.file;}
    void setAppearance(Appearance appearance){this.appearance=appearance;}
    private AlertDialog.Builder builder(){return new NativeDialogs.Builder(activity,appearance);}
    private String origin(GeckoSession session){return origin(sessionURL.apply(session));}
    private String origin(String uri){try{Uri parsed=Uri.parse(uri);String host=parsed.getHost();return host==null?"Website request":parsed.getScheme()+"://"+(host.contains(":")?"["+host+"]":host)+(parsed.getPort()==-1?"":":"+parsed.getPort());}catch(Exception e){return "Website request";}}
    private AlertDialog show(AlertDialog.Builder builder){AlertDialog d=builder.create();dialogs.add(d);d.setOnDismissListener(v->dialogs.remove(d));d.show();return d;}
    private AlertDialog show(BasePrompt prompt,AlertDialog.Builder builder){
        AlertDialog dialog=show(builder);
        prompt.setDelegate(new PromptInstanceDelegate(){
            @Override public void onPromptDismiss(BasePrompt obsolete){dialog.dismiss();}
        });
        return dialog;
    }
    @Override public GeckoResult<PromptResponse> onAlertPrompt(GeckoSession session,AlertPrompt prompt){
        GeckoResult<PromptResponse> result=new GeckoResult<>();show(prompt,builder().setTitle(origin(session)).setMessage(prompt.message).setPositiveButton("OK",(d,w)->result.complete(prompt.dismiss())).setOnCancelListener(d->result.complete(prompt.dismiss())));return result;
    }
    @Override public GeckoResult<PromptResponse> onButtonPrompt(GeckoSession session,ButtonPrompt prompt){
        GeckoResult<PromptResponse> result=new GeckoResult<>();show(prompt,builder().setTitle(origin(session)).setMessage(prompt.message).setPositiveButton("OK",(d,w)->result.complete(prompt.confirm(ButtonPrompt.Type.POSITIVE))).setNegativeButton("Cancel",(d,w)->result.complete(prompt.confirm(ButtonPrompt.Type.NEGATIVE))).setOnCancelListener(d->result.complete(prompt.dismiss())));return result;
    }
    @Override public GeckoResult<PromptResponse> onBeforeUnloadPrompt(GeckoSession session,BeforeUnloadPrompt prompt){
        GeckoResult<PromptResponse> result=new GeckoResult<>();show(prompt,builder().setTitle("Leave this page?").setMessage("Changes you made may not be saved.").setPositiveButton("Leave",(d,w)->result.complete(prompt.confirm(AllowOrDeny.ALLOW))).setNegativeButton("Stay",(d,w)->result.complete(prompt.confirm(AllowOrDeny.DENY))).setOnCancelListener(d->result.complete(prompt.confirm(AllowOrDeny.DENY))));return result;
    }
    @Override public GeckoResult<PromptResponse> onTextPrompt(GeckoSession session,TextPrompt prompt){
        EditText input=new EditText(activity);input.setText(prompt.defaultValue);GeckoResult<PromptResponse> result=new GeckoResult<>();show(prompt,builder().setTitle(origin(session)).setMessage(prompt.message).setView(input).setPositiveButton("OK",(d,w)->result.complete(prompt.confirm(input.getText().toString()))).setNegativeButton("Cancel",(d,w)->result.complete(prompt.dismiss())).setOnCancelListener(d->result.complete(prompt.dismiss())));return result;
    }
    @Override public GeckoResult<PromptResponse> onAuthPrompt(GeckoSession session,AuthPrompt prompt){
        LinearLayout fields=new LinearLayout(activity);fields.setOrientation(LinearLayout.VERTICAL);EditText user=new EditText(activity);user.setHint("Username");fields.addView(user);EditText password=new EditText(activity);password.setHint("Password");password.setInputType(InputType.TYPE_CLASS_TEXT|InputType.TYPE_TEXT_VARIATION_PASSWORD);fields.addView(password);
        GeckoResult<PromptResponse> result=new GeckoResult<>();show(prompt,builder().setTitle(prompt.authOptions.uri==null?origin(session):origin(prompt.authOptions.uri)).setMessage("Website sign-in").setView(fields).setPositiveButton("Sign in",(d,w)->{result.complete(prompt.confirm(user.getText().toString(),password.getText().toString()));password.setText("");}).setNegativeButton("Cancel",(d,w)->result.complete(prompt.dismiss())).setOnCancelListener(d->result.complete(prompt.dismiss())));return result;
    }
    private void flatten(ChoicePrompt.Choice[] choices,List<ChoicePrompt.Choice> out){for(ChoicePrompt.Choice c:choices){if(c.items!=null)flatten(c.items,out);else if(!c.separator&&!c.disabled)out.add(c);}}
    @Override public GeckoResult<PromptResponse> onChoicePrompt(GeckoSession session,ChoicePrompt prompt){
        ArrayList<ChoicePrompt.Choice> choices=new ArrayList<>();flatten(prompt.choices,choices);String[] labels=new String[choices.size()];for(int i=0;i<labels.length;i++)labels[i]=choices.get(i).label;
        GeckoResult<PromptResponse> result=new GeckoResult<>();AlertDialog.Builder builder=builder().setTitle("Choose an option").setNegativeButton("Cancel",(d,w)->result.complete(prompt.dismiss())).setOnCancelListener(d->result.complete(prompt.dismiss()));
        if(prompt.type==ChoicePrompt.Type.MULTIPLE){boolean[] selected=new boolean[choices.size()];for(int i=0;i<selected.length;i++)selected[i]=choices.get(i).selected;builder.setMultiChoiceItems(labels,selected,(d,w,on)->selected[w]=on).setPositiveButton("Done",(d,w)->{ArrayList<String> ids=new ArrayList<>();for(int i=0;i<selected.length;i++)if(selected[i])ids.add(choices.get(i).id);result.complete(prompt.confirm(ids.toArray(new String[0])));});}
        else builder.setItems(labels,(d,w)->result.complete(prompt.confirm(choices.get(w).id)));show(prompt,builder);return result;
    }
    @Override public GeckoResult<PromptResponse> onColorPrompt(GeckoSession s,ColorPrompt prompt){
        EditText value=new EditText(activity);value.setText(prompt.defaultValue);GeckoResult<PromptResponse> result=new GeckoResult<>();show(prompt,builder().setTitle("Colour").setView(value).setPositiveButton("Choose",(d,w)->result.complete(value.getText().toString().matches("#[0-9a-fA-F]{6}")?prompt.confirm(value.getText().toString()):prompt.dismiss())).setNegativeButton("Cancel",(d,w)->result.complete(prompt.dismiss())).setOnCancelListener(d->result.complete(prompt.dismiss())));return result;
    }
    @Override public GeckoResult<PromptResponse> onDateTimePrompt(GeckoSession s,DateTimePrompt prompt){
        EditText value=new EditText(activity);value.setText(prompt.defaultValue);GeckoResult<PromptResponse> result=new GeckoResult<>();show(prompt,builder().setTitle("Date or time").setView(value).setPositiveButton("Choose",(d,w)->result.complete(prompt.confirm(value.getText().toString()))).setNegativeButton("Cancel",(d,w)->result.complete(prompt.dismiss())).setOnCancelListener(d->result.complete(prompt.dismiss())));return result;
    }
    @Override public GeckoResult<PromptResponse> onFilePrompt(GeckoSession s,FilePrompt prompt){
        if(androidFileInFlight)return GeckoResult.fromValue(prompt.dismiss());
        filePrompt=prompt;fileResult=new GeckoResult<>();GeckoResult<PromptResponse> result=fileResult;
        prompt.setDelegate(new PromptInstanceDelegate(){@Override public void onPromptDismiss(BasePrompt obsolete){if(filePrompt==prompt){filePrompt=null;fileResult=null;}}});Intent intent=new Intent(Intent.ACTION_OPEN_DOCUMENT).addCategory(Intent.CATEGORY_OPENABLE).setType("*/*");
        if(prompt.mimeTypes!=null&&prompt.mimeTypes.length>0)intent.putExtra(Intent.EXTRA_MIME_TYPES,prompt.mimeTypes);
        intent.putExtra(Intent.EXTRA_ALLOW_MULTIPLE,prompt.type==FilePrompt.Type.MULTIPLE);
        androidFileInFlight=true;
        try{activity.startActivityForResult(intent,71);}catch(Exception e){androidFileInFlight=false;fileResult=null;filePrompt=null;result.complete(prompt.dismiss());}return result;
    }
    @Override public GeckoResult<PromptResponse> onPopupPrompt(GeckoSession s,PopupPrompt prompt){
        GeckoResult<PromptResponse> result=new GeckoResult<>();show(prompt,builder().setTitle(origin(s)).setMessage("Allow this website to open another tab?")
            .setPositiveButton("Open tab",(d,w)->result.complete(prompt.confirm(AllowOrDeny.ALLOW))).setNegativeButton("Block",(d,w)->result.complete(prompt.confirm(AllowOrDeny.DENY)))
            .setOnCancelListener(d->result.complete(prompt.confirm(AllowOrDeny.DENY))));return result;
    }
    @Override public void onAndroidPermissionsRequest(GeckoSession session,String[] permissions,GeckoSession.PermissionDelegate.Callback callback){
        if(permissions==null||permissions.length==0){callback.grant();return;}
        Set<String> permitted=new HashSet<>(Arrays.asList(android.Manifest.permission.CAMERA,android.Manifest.permission.RECORD_AUDIO,android.Manifest.permission.ACCESS_FINE_LOCATION,android.Manifest.permission.ACCESS_COARSE_LOCATION));
        for(String permission:permissions)if(!permitted.contains(permission)){callback.reject();return;}
        boolean all=true;for(String permission:permissions)if(activity.checkSelfPermission(permission)!=PackageManager.PERMISSION_GRANTED)all=false;
        if(all){callback.grant();return;}
        // Android supplies one result for this request code. A second page must
        // never replace the callback while the first OS dialog is still open.
        if(androidPermissionInFlight){callback.reject();return;}
        permissionCallback=callback;requestedAndroidPermissions=permissions.clone();androidPermissionInFlight=true;
        try{activity.requestPermissions(requestedAndroidPermissions.clone(),72);}
        catch(Exception error){permissionCallback=null;requestedAndroidPermissions=null;androidPermissionInFlight=false;callback.reject();}
    }
    @Override public GeckoResult<Integer> onContentPermissionRequest(GeckoSession session,ContentPermission perm){
        if(perm.permission==PERMISSION_AUTOPLAY_INAUDIBLE)return GeckoResult.fromValue(ContentPermission.VALUE_ALLOW);
        if(perm.permission==PERMISSION_DESKTOP_NOTIFICATION||perm.permission==PERMISSION_TRACKING||perm.permission==PERMISSION_XR)return GeckoResult.fromValue(ContentPermission.VALUE_DENY);
        String purpose=switch(perm.permission){case PERMISSION_GEOLOCATION->"your location";case PERMISSION_STORAGE_ACCESS->"its embedded sign-in storage";case PERMISSION_MEDIA_KEY_SYSTEM_ACCESS->"protected media playback";case PERMISSION_AUTOPLAY_AUDIBLE->"audio autoplay";case PERMISSION_PERSISTENT_STORAGE->"persistent website storage";case PERMISSION_LOCAL_NETWORK_ACCESS->"devices on your local network";case PERMISSION_LOCAL_DEVICE_ACCESS->"services on this device";default->null;};
        if(purpose==null)return GeckoResult.fromValue(ContentPermission.VALUE_DENY);
        GeckoResult<Integer> result=new GeckoResult<>();show(builder().setTitle(origin(perm.uri)).setMessage("Allow this website to use "+purpose+"?").setPositiveButton("Allow",(d,w)->result.complete(ContentPermission.VALUE_ALLOW)).setNegativeButton("Block",(d,w)->result.complete(ContentPermission.VALUE_DENY)).setOnCancelListener(d->result.complete(ContentPermission.VALUE_DENY)));return result;
    }
    @Override public void onMediaPermissionRequest(GeckoSession session,String uri,MediaSource[] video,MediaSource[] audio,MediaCallback callback){
        boolean wantsVideo=video!=null&&video.length>0,wantsAudio=audio!=null&&audio.length>0;
        if((wantsVideo&&activity.checkSelfPermission(android.Manifest.permission.CAMERA)!=PackageManager.PERMISSION_GRANTED)||(wantsAudio&&activity.checkSelfPermission(android.Manifest.permission.RECORD_AUDIO)!=PackageManager.PERMISSION_GRANTED)){callback.reject();return;}
        show(builder().setTitle(origin(uri)).setMessage("Allow this website to use "+(wantsVideo&&wantsAudio?"the camera and microphone":wantsVideo?"the camera":"the microphone")+"?").setPositiveButton("Allow",(d,w)->callback.grant(wantsVideo?video[0]:null,wantsAudio?audio[0]:null)).setNegativeButton("Block",(d,w)->callback.reject()).setOnCancelListener(d->callback.reject()));
    }
    void onActivityResult(int request,int result,Intent data){
        if(request!=71||!androidFileInFlight)return;androidFileInFlight=false;
        if(fileResult==null)return;GeckoResult<PromptResponse> pending=fileResult;FilePrompt prompt=filePrompt;fileResult=null;filePrompt=null;
        if(result!=Activity.RESULT_OK||data==null){pending.complete(prompt.dismiss());return;}ArrayList<Uri> uris=new ArrayList<>();if(data.getClipData()!=null)for(int i=0;i<data.getClipData().getItemCount();i++)uris.add(data.getClipData().getItemAt(i).getUri());else if(data.getData()!=null)uris.add(data.getData());
        try{pending.complete(uris.isEmpty()?prompt.dismiss():prompt.confirm(activity,uris.toArray(new Uri[0])));}catch(Exception e){pending.complete(prompt.dismiss());}
    }
    void onRequestPermissionsResult(int request,int[] results){
        if(request!=72||!androidPermissionInFlight)return;
        GeckoSession.PermissionDelegate.Callback pending=permissionCallback;String[] requested=requestedAndroidPermissions;
        permissionCallback=null;requestedAndroidPermissions=null;androidPermissionInFlight=false;
        if(pending==null)return; // A navigation already rejected this website request.
        boolean allowed=requested!=null&&requested.length>0&&results!=null&&results.length==requested.length;
        if(allowed)for(int i=0;i<requested.length;i++)if(results[i]!=PackageManager.PERMISSION_GRANTED||activity.checkSelfPermission(requested[i])!=PackageManager.PERMISSION_GRANTED)allowed=false;
        if(allowed)pending.grant();else pending.reject();
    }
    void dismissPending(){
        if(permissionCallback!=null){GeckoSession.PermissionDelegate.Callback pending=permissionCallback;permissionCallback=null;pending.reject();}
        // Keep the OS request occupied until its result arrives. Otherwise that
        // stale result could be mistaken for a new page's permission decision.
        if(fileResult!=null){GeckoResult<PromptResponse> pending=fileResult;FilePrompt prompt=filePrompt;fileResult=null;filePrompt=null;pending.complete(prompt.dismiss());}for(Dialog d:new ArrayList<>(dialogs))d.cancel();dialogs.clear();
    }
}
