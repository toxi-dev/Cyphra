/* MPL-2.0. Small native stroke icons; no remote image or font requests. */
package org.cyphra.browser;
import android.graphics.*;
import android.graphics.drawable.Drawable;

public final class IconDrawable extends Drawable {
    private final String name;
    private final Paint paint = new Paint(Paint.ANTI_ALIAS_FLAG);
    public IconDrawable(String name, int color) {
        this.name = name;
        paint.setColor(color); paint.setStyle(Paint.Style.STROKE);
        paint.setStrokeWidth(1.65f); paint.setStrokeCap(Paint.Cap.ROUND); paint.setStrokeJoin(Paint.Join.ROUND);
    }
    private void line(Canvas c, float... p) {
        Path path = new Path(); path.moveTo(p[0],p[1]);
        for(int i=2;i<p.length;i+=2) path.lineTo(p[i],p[i+1]);
        c.drawPath(path,paint);
    }
    @Override public void draw(Canvas canvas) {
        Rect b=getBounds(); canvas.save(); canvas.translate(b.left,b.top); canvas.scale(b.width()/24f,b.height()/24f);
        switch(name) {
            case "back": line(canvas,14,5,7,12,14,19); break;
            case "forward": line(canvas,10,5,17,12,10,19); break;
            case "search": canvas.drawCircle(10.5f,10.5f,6.2f,paint); line(canvas,15,15,20,20); break;
            case "tabs": canvas.drawRoundRect(4,4,20,20,4,4,paint); break;
            case "plus": line(canvas,5,12,19,12); line(canvas,12,5,12,19); break;
            case "close": line(canvas,6,6,18,18); line(canvas,18,6,6,18); break;
            case "menu": for(int y:new int[]{5,12,19}) canvas.drawCircle(12,y,0.9f,paint); break;
            case "refresh": canvas.drawArc(5,5,19,19,35,285,false,paint); line(canvas,19,5,19,10,14,10); break;
            case "bookmark": line(canvas,6,4,18,4,18,21,12,17,6,21,6,4); break;
            case "home": line(canvas,3,11,12,4,21,11); line(canvas,6,9,6,20,18,20,18,9); break;
            case "shield": line(canvas,12,3,4,6,4,12,6,16,12,21,18,16,20,12,20,6,12,3); break;
            case "lock": canvas.drawRoundRect(5,10,19,21,2,2,paint); canvas.drawArc(8,2,16,14,180,180,false,paint); break;
            case "tools": line(canvas,4,20,10,14); line(canvas,14,10,20,4); canvas.drawCircle(13,11,5,paint); break;
            case "private": canvas.drawRoundRect(3,8,21,16,4,4,paint); line(canvas,9,12,9,12); line(canvas,15,12,15,12); break;
        }
        canvas.restore();
    }
    @Override public void setAlpha(int a) {paint.setAlpha(a); invalidateSelf();}
    @Override public void setColorFilter(ColorFilter f) {paint.setColorFilter(f);invalidateSelf();}
    @Override public int getOpacity() {return PixelFormat.TRANSLUCENT;}
}
