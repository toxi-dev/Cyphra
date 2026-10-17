/* This Source Code Form is subject to the Mozilla Public License, v. 2.0. */
package org.cyphra.browser;

import static org.junit.Assert.assertEquals;
import java.util.ArrayList;
import org.junit.Test;

public final class RuntimeShutdownTest {
    @Test public void coldStartExitWaitsForNativeReadinessThenActualExit(){
        int[] calls={0,0};ArrayList<Runnable> posted=new ArrayList<>();
        RuntimeShutdown shutdown=new RuntimeShutdown(()->calls[0]++,posted::add);
        shutdown.request(()->calls[1]++);
        assertEquals(0,calls[0]);assertEquals(0,posted.size());
        shutdown.onReady();
        assertEquals(1,calls[0]);assertEquals(0,posted.size());assertEquals(0,calls[1]);
        shutdown.onExited();
        assertEquals(1,posted.size());assertEquals(0,calls[1]);
        posted.remove(0).run();assertEquals(1,calls[1]);
    }

    @Test public void repeatedRequestsAndReadinessNeverShutdownTwice(){
        int[] calls={0,0};ArrayList<Runnable> posted=new ArrayList<>();
        RuntimeShutdown shutdown=new RuntimeShutdown(()->calls[0]++,posted::add);
        shutdown.onReady();shutdown.onReady();assertEquals(0,calls[0]);
        shutdown.request(null);shutdown.request(()->calls[1]++);shutdown.onReady();
        assertEquals(1,calls[0]);assertEquals(0,calls[1]);
        shutdown.onExited();shutdown.onExited();assertEquals(1,posted.size());
        posted.remove(0).run();assertEquals(1,calls[1]);
    }

    @Test public void failureShutdownCanLaterCompleteAProfileExit(){
        int[] calls={0,0};ArrayList<Runnable> posted=new ArrayList<>();
        RuntimeShutdown shutdown=new RuntimeShutdown(()->calls[0]++,posted::add);
        shutdown.request(null);shutdown.onReady();shutdown.onExited();
        assertEquals(1,calls[0]);assertEquals(0,posted.size());
        shutdown.request(()->calls[1]++);
        assertEquals(1,calls[0]);assertEquals(1,posted.size());assertEquals(0,calls[1]);
        posted.remove(0).run();assertEquals(1,calls[1]);
    }

    @Test public void realExitBeforeReadinessNeverInvokesNativeShutdown(){
        int[] calls={0,0};ArrayList<Runnable> posted=new ArrayList<>();
        RuntimeShutdown shutdown=new RuntimeShutdown(()->calls[0]++,posted::add);
        shutdown.request(()->calls[1]++);shutdown.onExited();shutdown.onReady();
        assertEquals(0,calls[0]);assertEquals(1,posted.size());
        posted.remove(0).run();assertEquals(1,calls[1]);
    }

    @Test public void synchronousRealExitDuringShutdownDoesNotLoseTheCallback(){
        int[] calls={0,0};ArrayList<Runnable> posted=new ArrayList<>();RuntimeShutdown[] gate={null};
        gate[0]=new RuntimeShutdown(()->{calls[0]++;gate[0].onExited();},posted::add);
        gate[0].onReady();gate[0].request(()->calls[1]++);
        assertEquals(1,calls[0]);assertEquals(1,posted.size());
        posted.remove(0).run();assertEquals(1,calls[1]);
    }
}
