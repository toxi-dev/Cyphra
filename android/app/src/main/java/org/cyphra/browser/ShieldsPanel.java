/* This Source Code Form is subject to the Mozilla Public License, v. 2.0. */
package org.cyphra.browser;

import android.app.Activity;
import android.app.Dialog;
import android.content.Context;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.text.TextUtils;
import android.view.Gravity;
import android.view.View;
import android.view.Window;
import android.view.WindowManager;
import android.view.WindowInsets;
import android.widget.ImageButton;
import android.widget.ImageView;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Switch;
import android.widget.TextView;
import java.util.List;
import java.util.function.Consumer;

/** A native sheet whose controls and scroll position survive live statistics updates. */
final class ShieldsPanel {
    private final Activity activity;
    private final Appearance appearance;
    private final Dialog dialog;
    private final Consumer<Boolean> onToggle;
    private final TextView domain, total, totalDetail, filters, strict, telemetry, nativeEvents;
    private final TextView switchDetail, destinations, dnsName, dnsEndpoint;
    private final LinearLayout siteControl;
    private final Switch siteSwitch;
    private boolean updating;

    ShieldsPanel(Activity activity, boolean work, Appearance appearance, Consumer<Boolean> onToggle, Runnable onDismiss) {
        this.activity=activity;this.appearance=appearance;this.onToggle=onToggle;
        dialog=new Dialog(appearance.dialogContext(activity),appearance.dialogTheme());appearance.applyAccent(dialog.getContext());
        dialog.requestWindowFeature(Window.FEATURE_NO_TITLE);
        dialog.setOnDismissListener(ignored->onDismiss.run());

        LinearLayout sheet=column();
        GradientDrawable background=new GradientDrawable();
        background.setColor(appearance.panel);
        background.setCornerRadii(new float[]{dp(26),dp(26),dp(26),dp(26),0,0,0,0});
        sheet.setBackground(background);
        sheet.setPadding(dp(20),dp(10),dp(20),dp(18));
        sheet.setOnApplyWindowInsetsListener((view,insets)->{
            if(Build.VERSION.SDK_INT>=30){
                android.graphics.Insets bars=insets.getInsets(WindowInsets.Type.systemBars()|WindowInsets.Type.displayCutout());
                view.setPadding(dp(20)+bars.left,dp(10),dp(20)+bars.right,dp(18)+bars.bottom);
            }else view.setPadding(dp(20)+insets.getSystemWindowInsetLeft(),dp(10),dp(20)+insets.getSystemWindowInsetRight(),dp(18)+insets.getSystemWindowInsetBottom());
            return insets;
        });
        View handle=new View(activity);
        GradientDrawable handleShape=new GradientDrawable();handleShape.setColor(appearance.line);handleShape.setCornerRadius(dp(2));handle.setBackground(handleShape);
        LinearLayout.LayoutParams handleLayout=new LinearLayout.LayoutParams(dp(32),dp(3));
        handleLayout.gravity=Gravity.CENTER_HORIZONTAL;handleLayout.bottomMargin=dp(9);sheet.addView(handle,handleLayout);

        LinearLayout heading=new LinearLayout(activity);heading.setGravity(Gravity.CENTER_VERTICAL);
        ImageView shield=new ImageView(activity);shield.setImageDrawable(new IconDrawable("shield",appearance.text));
        heading.addView(shield,new LinearLayout.LayoutParams(dp(22),dp(22)));
        TextView title=text("Cyphra Shields",18,appearance.text);
        title.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));title.setPadding(dp(10),0,0,0);title.setAccessibilityHeading(true);
        heading.addView(title,new LinearLayout.LayoutParams(0,dp(44),1));title.setGravity(Gravity.CENTER_VERTICAL);
        ImageButton close=new ImageButton(activity);close.setImageDrawable(new IconDrawable("close",appearance.muted));
        close.setBackgroundColor(Color.TRANSPARENT);close.setPadding(dp(12),dp(12),dp(12),dp(12));close.setContentDescription("Close Shields");close.setOnClickListener(v->dismiss());
        heading.addView(close,new LinearLayout.LayoutParams(dp(48),dp(48)));sheet.addView(heading);
        domain=text("No website in this tab",14,appearance.muted);domain.setMaxLines(2);domain.setEllipsize(TextUtils.TruncateAt.END);domain.setPadding(dp(32),0,0,dp(18));sheet.addView(domain);

        int usableHeight=activity.getWindow().getDecorView().getHeight();
        if(usableHeight<=0)usableHeight=activity.getResources().getDisplayMetrics().heightPixels;
        BoundedScrollView scroll=new BoundedScrollView(activity,Math.max(dp(80),(int)(usableHeight*.85f)-dp(128)));
        scroll.setFillViewport(false);scroll.setClipToPadding(false);scroll.setVerticalScrollBarEnabled(false);
        LinearLayout body=column();scroll.addView(body);sheet.addView(scroll,new LinearLayout.LayoutParams(-1,-2));

        siteControl=column();
        siteSwitch=new Switch(activity);siteSwitch.setText("Shields for this site");siteSwitch.setTextColor(appearance.text);siteSwitch.setTextSize(appearance.sp(15));appearance.markScaled(siteSwitch);siteSwitch.setThumbTintList(appearance.controlTint());
        siteSwitch.setMinHeight(dp(48));siteSwitch.setSwitchPadding(dp(12));siteControl.addView(siteSwitch,new LinearLayout.LayoutParams(-1,-2));
        switchDetail=text("",12,appearance.muted);switchDetail.setPadding(0,0,0,dp(12));siteControl.addView(switchDetail);body.addView(siteControl);
        siteSwitch.setOnCheckedChangeListener((button,enabled)->{if(!updating)this.onToggle.accept(enabled);});
        divider(body);

        LinearLayout summary=new LinearLayout(activity);summary.setGravity(Gravity.CENTER_VERTICAL);summary.setPadding(dp(18),dp(16),dp(18),dp(16));summary.setBackground(appearance.surface(activity,appearance.background,16));
        total=text("—",44,appearance.text);total.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));
        summary.addView(total,new LinearLayout.LayoutParams(-2,-2));
        LinearLayout description=column();description.setPadding(dp(18),0,0,0);
        description.addView(text("Requests blocked",14,appearance.text));
        totalDetail=text("No page requests recorded",11,appearance.muted);totalDetail.setPadding(0,dp(4),0,0);description.addView(totalDetail);
        summary.addView(description,new LinearLayout.LayoutParams(0,-2,1));LinearLayout.LayoutParams summaryLayout=new LinearLayout.LayoutParams(-1,-2);summaryLayout.topMargin=dp(14);summaryLayout.bottomMargin=dp(14);body.addView(summary,summaryLayout);
        filters=counter(body,"Ads and trackers");
        LinearLayout technical=column();technical.setVisibility(BuildConfig.HOME?View.GONE:View.VISIBLE);body.addView(technical);
        strict=counter(technical,"Strict third-party filtering");telemetry=counter(technical,"Telemetry blocked");
        TextView exceptionNote=text("Telemetry blocking stays on when site filtering is off.",11,appearance.muted);exceptionNote.setPadding(0,dp(6),0,dp(12));technical.addView(exceptionNote);
        divider(technical);
        nativeEvents=counter(technical,"Native tracking protection events");
        TextView nativeNote=text("Gecko events · counted separately from requests above",11,appearance.muted);nativeNote.setPadding(0,0,0,dp(14));technical.addView(nativeNote);

        TextView destinationsTitle=text("Blocked destinations",12,appearance.muted);destinationsTitle.setAccessibilityHeading(true);technical.addView(destinationsTitle);
        destinations=text("None recorded on this page",12,appearance.text);destinations.setTypeface(Typeface.MONOSPACE);destinations.setMaxLines(12);destinations.setEllipsize(TextUtils.TruncateAt.END);destinations.setPadding(0,dp(6),0,dp(14));destinations.setLineSpacing(dp(3),1);technical.addView(destinations);
        divider(body);

        TextView dnsTitle=text(BuildConfig.HOME?"DNS provider":"DNS",12,appearance.muted);dnsTitle.setPadding(0,dp(12),0,0);body.addView(dnsTitle);
        dnsName=text("",14,appearance.text);dnsName.setPadding(0,dp(4),0,0);body.addView(dnsName);
        dnsEndpoint=text("",12,appearance.muted);dnsEndpoint.setPadding(0,dp(4),0,0);body.addView(dnsEndpoint);
        TextView profile=text(BuildConfig.HOME?"Site exceptions apply only to this browser.":work?"Work · stricter filtering · WebGL off":"Personal · balanced filtering · WebGL available",11,appearance.muted);profile.setPadding(0,dp(18),0,0);body.addView(profile);

        dialog.setContentView(sheet);
        Window window=dialog.getWindow();
        if(window!=null){
            window.setBackgroundDrawableResource(android.R.color.transparent);
            window.addFlags(WindowManager.LayoutParams.FLAG_DIM_BEHIND);
            window.setDimAmount(.55f);
            window.setGravity(Gravity.BOTTOM);
            window.setNavigationBarColor(appearance.panel);
        }
    }

    void show(){dialog.show();appearance.decorateDialog(dialog,activity);Window window=dialog.getWindow();if(window!=null){window.setLayout(-1,-2);window.getDecorView().requestApplyInsets();}}
    void dismiss(){dialog.dismiss();}
    boolean isShowing(){return dialog.isShowing();}

    void render(String site, Engine.Stats stats, boolean enabled, String dnsChoice, String dnsUri, boolean privateTab){
        boolean website=site!=null&&!site.isEmpty();
        set(domain,website?site:"No website in this tab");
        siteControl.setVisibility(website?View.VISIBLE:View.GONE);
        updating=true;try{if(siteSwitch.isChecked()!=enabled)siteSwitch.setChecked(enabled);}finally{updating=false;}
        set(switchDetail,enabled?"Site filtering is on.":BuildConfig.HOME?"Ads and trackers are allowed for this site. Core privacy protections stay on.":"Site filtering is off. Telemetry blocking stays on.");
        set(total,stats==null?"—":Integer.toString(stats.blocked));
        set(totalDetail,stats==null?"Open a website to see its activity":"On this page · actual cancelled requests");
        set(filters,stats==null?"—":Integer.toString(stats.filters));set(strict,stats==null?"—":Integer.toString(stats.strict));
        set(telemetry,stats==null?"—":Integer.toString(stats.telemetry));set(nativeEvents,stats==null?"—":Integer.toString(stats.nativeBlocked));
        set(destinations,destinationText(stats==null?null:stats.hosts));
        String name;
        switch(dnsChoice){case "system":name="System DNS";break;case "toxitech":name=BuildConfig.HOME?"Toxitech":"Toxitech · encrypted DNS";break;case "quad9":name=BuildConfig.HOME?"Quad9":"Quad9 · encrypted DNS";break;case "cloudflare":name=BuildConfig.HOME?"Cloudflare":"Cloudflare · encrypted DNS";break;default:name=BuildConfig.HOME?"Custom provider":"Custom · encrypted DNS";}
        set(dnsName,name);set(dnsEndpoint,"system".equals(dnsChoice)?"Uses your Android network settings":BuildConfig.HOME?"Encrypted connection to your chosen provider":dnsUri);
        Window window=dialog.getWindow();
        if(window!=null){
            boolean secure=privateTab||(activity.getWindow().getAttributes().flags&WindowManager.LayoutParams.FLAG_SECURE)!=0;
            if(secure)window.addFlags(WindowManager.LayoutParams.FLAG_SECURE);else window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE);
        }
    }

    private String destinationText(List<String> hosts){
        if(hosts==null||hosts.isEmpty())return "None recorded on this page";
        StringBuilder text=new StringBuilder();int shown=Math.min(6,hosts.size());
        for(int i=0;i<shown;i++){if(i>0)text.append('\n');text.append(hosts.get(i));}
        if(hosts.size()>shown)text.append("\n+").append(hosts.size()-shown).append(" more destinations");
        return text.toString();
    }
    private TextView counter(LinearLayout body,String label){
        LinearLayout row=new LinearLayout(activity);row.setGravity(Gravity.CENTER_VERTICAL);row.setMinimumHeight(dp(34));
        TextView title=text(label,13,appearance.text);title.setPadding(0,dp(7),dp(12),dp(7));row.addView(title,new LinearLayout.LayoutParams(0,-2,1));
        TextView value=text("0",14,appearance.text);value.setTypeface(Typeface.create("sans-serif-medium",Typeface.NORMAL));value.setGravity(Gravity.END);row.addView(value,new LinearLayout.LayoutParams(-2,-2));body.addView(row);return value;
    }
    private void divider(LinearLayout body){View line=new View(activity);line.setBackgroundColor(appearance.line);body.addView(line,new LinearLayout.LayoutParams(-1,dp(1)));}
    private LinearLayout column(){LinearLayout view=new LinearLayout(activity);view.setOrientation(LinearLayout.VERTICAL);return view;}
    private TextView text(String value,int size,int color){TextView view=new TextView(activity);view.setText(value);view.setTextSize(appearance.sp(size));view.setTextColor(color);appearance.markScaled(view);return view;}
    private static void set(TextView view,String value){if(!TextUtils.equals(view.getText(),value))view.setText(value);}
    private int dp(int value){return Math.round(value*activity.getResources().getDisplayMetrics().density);}
    private static final class BoundedScrollView extends ScrollView {
        private final int maximumHeight;
        BoundedScrollView(Context context,int maximumHeight){super(context);this.maximumHeight=maximumHeight;}
        @Override protected void onMeasure(int widthSpec,int heightSpec){super.onMeasure(widthSpec,View.MeasureSpec.makeMeasureSpec(maximumHeight,View.MeasureSpec.AT_MOST));}
    }
}
