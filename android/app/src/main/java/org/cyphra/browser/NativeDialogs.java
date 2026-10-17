/* This Source Code Form is subject to the Mozilla Public License, v. 2.0. */
package org.cyphra.browser;

import android.app.Activity;
import android.app.AlertDialog;
import android.view.View;

/** Applies the selected native palette and text size without replacing action callbacks. */
final class NativeDialogs {
    static final class Builder extends AlertDialog.Builder {
        private final Activity activity;
        private final Appearance appearance;
        private final java.util.function.Consumer<AlertDialog> created;
        Builder(Activity activity,Appearance appearance){this(activity,appearance,null);}
        Builder(Activity activity,Appearance appearance,java.util.function.Consumer<AlertDialog> created){super(appearance.dialogContext(activity),appearance.dialogTheme());this.activity=activity;this.appearance=appearance;this.created=created;appearance.applyAccent(getContext());}
        @Override public AlertDialog create(){
            AlertDialog dialog=super.create();
            dialog.getWindow().getDecorView().addOnAttachStateChangeListener(new View.OnAttachStateChangeListener(){
                @Override public void onViewAttachedToWindow(View view){appearance.decorateDialog(dialog,activity);}
                @Override public void onViewDetachedFromWindow(View view){}
            });
            if(created!=null)created.accept(dialog);
            return dialog;
        }
    }
}
