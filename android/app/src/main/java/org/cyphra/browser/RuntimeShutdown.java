/* This Source Code Form is subject to the Mozilla Public License, v. 2.0. */
package org.cyphra.browser;

import java.util.ArrayList;
import java.util.function.Consumer;

/** Main-thread shutdown ordering. Readiness never substitutes for actual exit. */
final class RuntimeShutdown {
    private final Runnable shutdown;
    private final Consumer<Runnable> post;
    private final ArrayList<Runnable> callbacks=new ArrayList<>();
    private boolean ready,requested,started,exited;

    RuntimeShutdown(Runnable shutdown,Consumer<Runnable> post){this.shutdown=shutdown;this.post=post;}

    void request(Runnable callback){
        if(callback!=null){if(exited)post.accept(callback);else callbacks.add(callback);}
        requested=true;maybeShutdown();
    }

    void onReady(){ready=true;maybeShutdown();}

    void onExited(){
        if(exited)return;exited=true;
        ArrayList<Runnable> pending=new ArrayList<>(callbacks);callbacks.clear();
        for(Runnable callback:pending)post.accept(callback);
    }

    private void maybeShutdown(){
        if(requested&&ready&&!started&&!exited){started=true;shutdown.run();}
    }
}
