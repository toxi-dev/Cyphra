/* MPL-2.0. Test APK only; Android starts this runner in the Work process. */
package org.cyphra.browser;

public final class WorkLifecycleTest extends LifecycleQualificationTest {
    @Override protected String mode(){return "work";}
}
