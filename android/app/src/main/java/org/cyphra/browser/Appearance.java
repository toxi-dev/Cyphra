/* This Source Code Form is subject to the Mozilla Public License, v. 2.0. */
package org.cyphra.browser;

import android.app.Activity;
import android.app.Dialog;
import android.content.Context;
import android.content.res.ColorStateList;
import android.content.res.Configuration;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.graphics.drawable.RippleDrawable;
import android.os.Build;
import android.util.TypedValue;
import android.view.ContextThemeWrapper;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.widget.TextView;
import java.util.Arrays;

/** Native chrome preferences only. These never change Gecko, DNS or protection policy. */
final class Appearance {
    static final String PREFIX="appearance.";
    static final String[] KEYS={"theme","accent","density","text-scale","toolbar-forward","toolbar-reload","home-bookmarks","home-reading","home-layout","home-bookmark-count","home-quick-actions","home-alignment"};
    final String theme,accent,density,scaleChoice,homeLayout,bookmarkCountChoice,homeAlignment;
    final boolean light,forward,reload,bookmarks,reading,quickActions;
    final int background,panel,line,text,muted,accentColor,bookmarkCount;
    final float textScale;

    Appearance(Context context,BrowserStore store){
        theme=choice(store,"theme",BuildConfig.HOME?"system":"graphite","graphite","black","light","system");
        accent=choice(store,"accent","neutral","neutral","blue","teal","amber");
        density=choice(store,"density","comfortable","compact","comfortable");
        scaleChoice=choice(store,"text-scale","100","90","100","110","125");
        homeLayout=choice(store,"home-layout",BuildConfig.HOME?"grid":"list","list","grid");
        bookmarkCountChoice=choice(store,"home-bookmark-count",BuildConfig.HOME?"8":"4","4","8","12");
        homeAlignment=choice(store,"home-alignment","start","start","center");
        quickActions=store.booleanPref(PREFIX+"home-quick-actions",true);
        textScale=Integer.parseInt(scaleChoice)/100f;bookmarkCount=Integer.parseInt(bookmarkCountChoice);
        light="light".equals(theme)||("system".equals(theme)&&(context.getResources().getConfiguration().uiMode&Configuration.UI_MODE_NIGHT_MASK)!=Configuration.UI_MODE_NIGHT_YES);
        if(light){background=0xfff7f7f5;panel=0xffffffff;line=0xffddddda;text=0xff20211f;muted=0xff656760;}
        else if("black".equals(theme)){background=Color.BLACK;panel=0xff111214;line=0xff292c31;text=0xfff1f2f4;muted=0xffa0a6b0;}
        else{background=0xff121314;panel=0xff1c1d1f;line=0xff303235;text=0xfff2f2ef;muted=0xffa8aaa6;}
        switch(accent){case "blue":accentColor=light?0xff345c93:0xff9ebce5;break;case "teal":accentColor=light?0xff226b62:0xff99c8bd;break;case "amber":accentColor=light?0xff865807:0xffd9bd83;break;default:accentColor=light?0xff424b59:0xffcad2df;}
        forward=store.booleanPref(PREFIX+"toolbar-forward",true);reload=store.booleanPref(PREFIX+"toolbar-reload",false);
        bookmarks=store.booleanPref(PREFIX+"home-bookmarks",true);reading=!BuildConfig.HOME&&store.booleanPref(PREFIX+"home-reading",true);
    }
    private static String choice(BrowserStore store,String key,String fallback,String... allowed){String value=store.stringPref(PREFIX+key,fallback);return Arrays.asList(allowed).contains(value)?value:fallback;}
    static void reset(BrowserStore store){String[] names=new String[KEYS.length];for(int i=0;i<KEYS.length;i++)names[i]=PREFIX+KEYS[i];store.removePrefs(names);}
    boolean compact(){return "compact".equals(density);}
    int toolbarHeight(){return compact()?48:56;}
    int rowPadding(){return compact()?9:14;}
    float sp(float size){return size*textScale;}
    int baseTheme(){return light?R.style.CyphraLightTheme:"black".equals(theme)?R.style.CyphraBlackTheme:R.style.CyphraTheme;}
    int dialogTheme(){return light?R.style.CyphraLightDialog:"black".equals(theme)?R.style.CyphraBlackDialog:R.style.CyphraGraphiteDialog;}
    private int accentTheme(){switch(accent){case "blue":return light?R.style.CyphraBlueLight:R.style.CyphraBlueDark;case "teal":return light?R.style.CyphraTealLight:R.style.CyphraTealDark;case "amber":return light?R.style.CyphraAmberLight:R.style.CyphraAmberDark;default:return light?R.style.CyphraNeutralLight:R.style.CyphraNeutralDark;}}
    void applyAccent(Context context){context.getTheme().applyStyle(accentTheme(),true);}
    void apply(Activity activity){activity.setTheme(baseTheme());applyAccent(activity);applyWindow(activity.getWindow());}
    Context dialogContext(Context context){ContextThemeWrapper wrapper=new ContextThemeWrapper(context,dialogTheme());wrapper.getTheme().applyStyle(accentTheme(),true);return wrapper;}
    void rethemeDialog(Dialog dialog,Activity activity){dialog.getContext().getTheme().applyStyle(dialogTheme(),true);dialog.getContext().getTheme().applyStyle(accentTheme(),true);decorateDialog(dialog,activity);}
    void applyWindow(Window window){
        if(window==null)return;window.setStatusBarColor(background);window.setNavigationBarColor(background);
        if(Build.VERSION.SDK_INT>=30){WindowInsetsController controller=window.getDecorView().getWindowInsetsController();if(controller!=null)controller.setSystemBarsAppearance(light?WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS|WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS:0,WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS|WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS);}
        else{View decor=window.getDecorView();int flags=decor.getSystemUiVisibility();flags&=~(View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR|View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR);if(light)flags|=View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR|View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;decor.setSystemUiVisibility(flags);}
    }
    void decorateDialog(Dialog dialog,Activity activity){
        Window window=dialog.getWindow();if(window==null)return;applyWindow(window);
        if((activity.getWindow().getAttributes().flags&WindowManager.LayoutParams.FLAG_SECURE)!=0)window.addFlags(WindowManager.LayoutParams.FLAG_SECURE);
        scaleTextTree(window.getDecorView());
    }
    void scaleTextTree(View view){
        if(view instanceof TextView&&view.getTag(R.id.cyphra_text_scaled)!=Boolean.TRUE){TextView label=(TextView)view;label.setTextSize(TypedValue.COMPLEX_UNIT_PX,label.getTextSize()*textScale);markScaled(label);}
        if(view instanceof ViewGroup){ViewGroup group=(ViewGroup)view;for(int i=0;i<group.getChildCount();i++)scaleTextTree(group.getChildAt(i));}
    }
    void markScaled(TextView view){view.setTag(R.id.cyphra_text_scaled,Boolean.TRUE);}
    RippleDrawable ripple(){return new RippleDrawable(ColorStateList.valueOf((accentColor&0x00ffffff)|0x18000000),null,null);}
    GradientDrawable surface(Context context,int color,int radius){GradientDrawable shape=new GradientDrawable();shape.setColor(color);shape.setCornerRadius(radius*context.getResources().getDisplayMetrics().density);shape.setStroke(Math.max(1,Math.round(context.getResources().getDisplayMetrics().density)),line);return shape;}
    ColorStateList controlTint(){return new ColorStateList(new int[][]{new int[]{android.R.attr.state_checked},new int[]{}},new int[]{accentColor,muted});}
}
