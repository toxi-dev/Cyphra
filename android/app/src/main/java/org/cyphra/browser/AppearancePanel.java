/* This Source Code Form is subject to the Mozilla Public License, v. 2.0. */
package org.cyphra.browser;

import android.app.Activity;
import android.app.Dialog;
import android.graphics.Typeface;
import android.graphics.drawable.ColorDrawable;
import android.os.Build;
import android.view.Gravity;
import android.view.View;
import android.view.Window;
import android.view.WindowInsets;
import android.widget.ImageButton;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;
import java.util.Arrays;
import java.util.Locale;

/** A local customization screen with a real palette/chrome preview and mode-bound settings. */
final class AppearancePanel {
    private final Activity activity;
    private final BrowserStore store;
    private final Runnable onChanged;
    private final Dialog dialog;
    private Appearance appearance;
    private ScrollView scroll;

    AppearancePanel(Activity activity,BrowserStore store,Runnable onChanged,Runnable onDismiss){
        this.activity=activity;this.store=store;this.onChanged=onChanged;appearance=new Appearance(activity,store);
        dialog=new Dialog(appearance.dialogContext(activity),appearance.dialogTheme());dialog.requestWindowFeature(Window.FEATURE_NO_TITLE);dialog.setOnDismissListener(ignored->onDismiss.run());refresh();
    }
    void show(){dialog.show();Window window=dialog.getWindow();if(window!=null){window.setLayout(-1,-1);window.setBackgroundDrawable(new ColorDrawable(appearance.background));window.getDecorView().requestApplyInsets();}appearance.decorateDialog(dialog,activity);}
    void dismiss(){dialog.dismiss();}
    boolean isShowing(){return dialog.isShowing();}
    void refresh(){
        int position=scroll==null?0:scroll.getScrollY();appearance=new Appearance(activity,store);appearance.rethemeDialog(dialog,activity);
        LinearLayout root=column();root.setBackgroundColor(appearance.background);
        root.setOnApplyWindowInsetsListener((view,insets)->{
            if(Build.VERSION.SDK_INT>=30){android.graphics.Insets bars=insets.getInsets(WindowInsets.Type.systemBars()|WindowInsets.Type.displayCutout());view.setPadding(bars.left,bars.top,bars.right,bars.bottom);}
            else view.setPadding(insets.getSystemWindowInsetLeft(),insets.getSystemWindowInsetTop(),insets.getSystemWindowInsetRight(),insets.getSystemWindowInsetBottom());
            return insets;
        });
        LinearLayout header=new LinearLayout(activity);header.setGravity(Gravity.CENTER_VERTICAL);header.setPadding(dp(8),dp(4),dp(16),dp(4));
        ImageButton back=new ImageButton(activity);back.setImageDrawable(new IconDrawable("back",appearance.text));back.setPadding(dp(12),dp(12),dp(12),dp(12));back.setBackground(appearance.ripple());back.setContentDescription("Close appearance");back.setOnClickListener(v->dismiss());header.addView(back,new LinearLayout.LayoutParams(dp(48),dp(48)));
        TextView title=text("Appearance",20,appearance.text);title.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));title.setAccessibilityHeading(true);title.setPadding(dp(6),0,0,0);header.addView(title,new LinearLayout.LayoutParams(0,-2,1));root.addView(header);divider(root);

        scroll=new ScrollView(activity);scroll.setFillViewport(false);LinearLayout body=column();body.setPadding(dp(20),dp(18),dp(20),dp(28));scroll.addView(body);root.addView(scroll,new LinearLayout.LayoutParams(-1,0,1));
        TextView profile=text(BuildConfig.HOME?"Cyphra Home":capitalize(store.mode())+" profile",13,appearance.muted);profile.setPadding(0,0,0,dp(12));body.addView(profile);
        body.addView(preview());
        section(body,"Look and feel");
        choice(body,"Theme",themeLabel(appearance.theme),"theme",new String[]{"graphite","black","light","system"},new String[]{"Graphite","Black","Light","System"},appearance.theme);
        choice(body,"Accent",capitalize(appearance.accent),"accent",new String[]{"neutral","blue","teal","amber"},new String[]{"Neutral","Blue","Teal","Amber"},appearance.accent);
        choice(body,"Spacing",appearance.compact()?"Compact":"Comfortable","density",new String[]{"compact","comfortable"},new String[]{"Compact","Comfortable"},appearance.density);
        choice(body,"Text size",appearance.scaleChoice+"%","text-scale",new String[]{"90","100","110","125"},new String[]{"90%","100%","110%","125%"},appearance.scaleChoice);
        TextView sizeNote=text("Android's font size also applies. These controls style Cyphra's interface.",12,appearance.muted);sizeNote.setPadding(0,dp(10),0,0);body.addView(sizeNote);

        section(body,"Toolbar");
        value(body,"Home","Always available",null);
        toggle(body,"Forward button","toolbar-forward",appearance.forward);
        toggle(body,"Reload button","toolbar-reload",appearance.reload);
        TextView navigationNote=text("Forward and Reload also stay in the menu.",12,appearance.muted);navigationNote.setPadding(0,dp(10),0,0);body.addView(navigationNote);

        section(body,"Home");
        toggle(body,"Bookmarks on Home","home-bookmarks",appearance.bookmarks);
        choice(body,"Bookmark layout","grid".equals(appearance.homeLayout)?"Grid":"List","home-layout",new String[]{"list","grid"},new String[]{"List","Grid"},appearance.homeLayout);
        choice(body,"Bookmark limit",appearance.bookmarkCountChoice+" bookmarks","home-bookmark-count",new String[]{"4","8","12"},new String[]{"4 bookmarks","8 bookmarks","12 bookmarks"},appearance.bookmarkCountChoice);
        toggle(body,"Quick actions","home-quick-actions",appearance.quickActions);
        choice(body,"Home alignment","center".equals(appearance.homeAlignment)?"Centered":"Left","home-alignment",new String[]{"start","center"},new String[]{"Left","Centered"},appearance.homeAlignment);
        if(!BuildConfig.HOME)toggle(body,"Security reading","home-reading",appearance.reading);
        TextView homeNote=text("Home uses local bookmarks and links. Nothing loads in the background.",12,appearance.muted);homeNote.setPadding(0,dp(10),0,dp(24));body.addView(homeNote);
        TextView reset=text("Reset appearance",14,appearance.accentColor);reset.setMinimumHeight(dp(48));reset.setGravity(Gravity.CENTER_VERTICAL);reset.setBackground(appearance.ripple());reset.setOnClickListener(v->new NativeDialogs.Builder(activity,appearance).setTitle(BuildConfig.HOME?"Reset appearance?":"Reset "+store.mode()+" appearance?").setMessage("Restore the default theme, toolbar and Home layout. Browser data and protections are kept.").setPositiveButton("Reset",(d,w)->change(()->Appearance.reset(store))).setNegativeButton("Cancel",null).show());body.addView(reset);
        dialog.setContentView(root);Window window=dialog.getWindow();if(window!=null){window.setBackgroundDrawable(new ColorDrawable(appearance.background));if(dialog.isShowing())window.setLayout(-1,-1);window.getDecorView().requestApplyInsets();}
        final ScrollView target=scroll;target.post(()->target.scrollTo(0,position));
    }

    private View preview(){
        LinearLayout sample=column();sample.setPadding(dp(14),dp(12),dp(14),dp(8));sample.setBackground(appearance.surface(activity,appearance.panel,14));
        TextView label=text("Preview",11,appearance.muted);label.setPadding(0,0,0,dp(12));sample.addView(label);
        LinearLayout identity=new LinearLayout(activity);identity.setGravity(Gravity.CENTER_VERTICAL|("center".equals(appearance.homeAlignment)?Gravity.CENTER_HORIZONTAL:Gravity.START));ImageView logo=new ImageView(activity);logo.setImageResource(R.drawable.ic_logo);logo.setImageTintList(android.content.res.ColorStateList.valueOf(appearance.text));identity.addView(logo,new LinearLayout.LayoutParams(dp(27),dp(27)));
        TextView name=text("Cyphra",24,appearance.text);name.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));name.setPadding(dp(10),0,0,0);identity.addView(name);sample.addView(identity);
        TextView search=text("Search with Brave",14,appearance.muted);search.setPadding(dp(12),0,dp(12),0);search.setGravity(Gravity.CENTER_VERTICAL);search.setBackground(appearance.surface(activity,appearance.background,10));LinearLayout.LayoutParams searchLayout=new LinearLayout.LayoutParams(-1,dp(appearance.compact()?48:54));searchLayout.topMargin=dp(16);searchLayout.bottomMargin=dp(8);sample.addView(search,searchLayout);
        LinearLayout toolbar=new LinearLayout(activity);toolbar.setGravity(Gravity.CENTER_VERTICAL);
        previewIcon(toolbar,"back",appearance.muted);if(appearance.forward)previewIcon(toolbar,"forward",appearance.muted);if(appearance.reload)previewIcon(toolbar,"refresh",appearance.text);
        if(BuildConfig.HOME)previewIcon(toolbar,"bookmark",appearance.text);
        else{TextView mode=text(capitalize(store.mode()),11,appearance.text);mode.setGravity(Gravity.CENTER);toolbar.addView(mode,new LinearLayout.LayoutParams(0,dp(appearance.toolbarHeight()),1.5f));}
        previewIcon(toolbar,"tabs",appearance.text);previewIcon(toolbar,"menu",appearance.text);sample.addView(toolbar);
        sample.setImportantForAccessibility(View.IMPORTANT_FOR_ACCESSIBILITY_NO_HIDE_DESCENDANTS);sample.setContentDescription("Preview of the selected Cyphra appearance");return sample;
    }
    private void previewIcon(LinearLayout toolbar,String icon,int color){ImageView image=new ImageView(activity);image.setImageDrawable(new IconDrawable(icon,color));image.setPadding(dp(12),dp(12),dp(12),dp(12));toolbar.addView(image,new LinearLayout.LayoutParams(0,dp(appearance.toolbarHeight()),1));}
    private void choice(LinearLayout body,String title,String current,String key,String[] ids,String[] labels,String selected){value(body,title,current,()->new NativeDialogs.Builder(activity,appearance).setTitle(title).setSingleChoiceItems(labels,Arrays.asList(ids).indexOf(selected),(d,index)->{d.dismiss();change(()->store.setStringPref(Appearance.PREFIX+key,ids[index]));}).setNegativeButton("Cancel",null).show());}
    private void toggle(LinearLayout body,String title,String key,boolean checked){
        Switch control=new Switch(activity);control.setText(title);control.setTextColor(appearance.text);control.setTextSize(appearance.sp(14));appearance.markScaled(control);control.setMinHeight(dp(52));control.setSwitchPadding(dp(12));control.setThumbTintList(appearance.controlTint());control.setChecked(checked);control.setOnCheckedChangeListener((v,on)->change(()->store.setBooleanPref(Appearance.PREFIX+key,on)));body.addView(control,new LinearLayout.LayoutParams(-1,-2));divider(body);
    }
    private void value(LinearLayout body,String title,String selected,Runnable action){
        LinearLayout row=new LinearLayout(activity);row.setGravity(Gravity.CENTER_VERTICAL);row.setMinimumHeight(dp(52));row.setPadding(0,dp(12),0,dp(12));
        TextView label=text(title,14,appearance.text);label.setPadding(0,0,dp(8),0);row.addView(label,new LinearLayout.LayoutParams(0,-2,1));TextView selection=text(selected,13,action==null?appearance.muted:appearance.accentColor);selection.setMaxLines(2);selection.setMaxWidth(dp(132));selection.setGravity(Gravity.END);row.addView(selection);
        if(action!=null){ImageView arrow=new ImageView(activity);arrow.setImageDrawable(new IconDrawable("forward",appearance.muted));LinearLayout.LayoutParams params=new LinearLayout.LayoutParams(dp(12),dp(16));params.leftMargin=dp(8);row.addView(arrow,params);row.setBackground(appearance.ripple());row.setOnClickListener(v->action.run());}
        body.addView(row);divider(body);
    }
    private void change(Runnable save){try{save.run();onChanged.run();}catch(IllegalStateException error){Toast.makeText(activity,error.getMessage(),Toast.LENGTH_LONG).show();}}
    static String themeLabel(String id){return capitalize(id);}
    private static String capitalize(String value){return value.substring(0,1).toUpperCase(Locale.ROOT)+value.substring(1);}
    private void section(LinearLayout body,String label){TextView view=text(label,12,appearance.muted);view.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));view.setAccessibilityHeading(true);view.setPadding(0,dp(26),0,dp(8));body.addView(view);}
    private void divider(LinearLayout body){View line=new View(activity);line.setBackgroundColor(appearance.line);body.addView(line,new LinearLayout.LayoutParams(-1,dp(1)));}
    private TextView text(String value,int size,int color){TextView view=new TextView(activity);view.setText(value);view.setTextSize(appearance.sp(size));view.setTextColor(color);appearance.markScaled(view);return view;}
    private LinearLayout column(){LinearLayout view=new LinearLayout(activity);view.setOrientation(LinearLayout.VERTICAL);return view;}
    private int dp(int value){return Math.round(value*activity.getResources().getDisplayMetrics().density);}
}
