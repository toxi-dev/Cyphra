/* MPL-2.0. Test APK only; Android starts this runner in the Personal process. */
package org.cyphra.browser;

public final class PersonalLifecycleTest extends LifecycleQualificationTest {
    @Override protected String mode(){return "personal";}
}
