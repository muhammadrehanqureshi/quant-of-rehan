package pk.quantofrehan;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.LinearGradient;
import android.graphics.Paint;
import android.graphics.Rect;
import android.graphics.Shader;
import android.graphics.Typeface;
import android.util.AttributeSet;
import android.util.TypedValue;
import android.view.View;

/**
 * Owner order 2026-11-11: the BIG BUYING &amp; SELLING board's scroll indicator
 * is a diamond in the middle of two fading lines. The diamond stands at the
 * board's own scroll fraction, the lines run from it to the top and the bottom
 * of the track and fade away from it, and every stroke wears the ink of the
 * theme the console is wearing.
 *
 * The diamond is the console's own brand glyph at the same 10sp QorDiamond
 * uses, not a hand-sized path, so the scroller can never draw a bigger diamond
 * than the rules across the rest of the app.
 */
public class OrnamentScroller extends View {

    private static final String DIAMOND = "\u25C6";
    private static final float DIAMOND_SP = 10f;

    private final Paint linePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint diamondPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Rect diamondBounds = new Rect();
    private int offset;
    private int range;
    private int ink = 0xFFFFFFFF;

    public OrnamentScroller(Context context) {
        this(context, null);
    }

    public OrnamentScroller(Context context, AttributeSet attrs) {
        super(context, attrs);
    }

    /** Re-inks the ornament from the worn theme's second colour. */
    public void setInk(int color) {
        ink = color;
        invalidate();
    }

    /** The board's scroll position and the pixels it can still travel. */
    public void setScroll(int offset, int range) {
        this.offset = Math.max(0, offset);
        this.range = Math.max(0, range);
        invalidate();
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        if (range <= 0 || getWidth() <= 0 || getHeight() <= 0) {
            return; // nothing to scroll into view
        }
        float w = getWidth();
        float h = getHeight();
        diamondPaint.setTextSize(TypedValue.applyDimension(
                TypedValue.COMPLEX_UNIT_SP, DIAMOND_SP,
                getResources().getDisplayMetrics()));
        diamondPaint.setTypeface(Typeface.DEFAULT);
        diamondPaint.setTextAlign(Paint.Align.LEFT);
        diamondPaint.setColor(ink);
        diamondPaint.getTextBounds(DIAMOND, 0, DIAMOND.length(),
                diamondBounds);
        float d = diamondBounds.height();
        float cx = w / 2f;
        float t = Math.min(1f, (float) offset / range);
        float cy = d / 2f + t * (h - d);

        // Centre the glyph's ink, not its advance box, on the track.
        float x = cx - (diamondBounds.left + diamondBounds.right) / 2f;
        float baseline = cy - (diamondBounds.top + diamondBounds.bottom) / 2f;
        canvas.drawText(DIAMOND, x, baseline, diamondPaint);

        linePaint.setStrokeWidth(Math.max(1f, dp(1.5f)));
        linePaint.setColor(ink);
        float top = cy - d / 2f;
        float bottom = cy + d / 2f;
        int clear = ink & 0x00FFFFFF; // same hue, transparent
        if (top > 0) {
            linePaint.setShader(new LinearGradient(0, 0, 0, top,
                    clear, ink, Shader.TileMode.CLAMP));
            canvas.drawLine(cx, 0, cx, top, linePaint);
        }
        if (bottom < h) {
            linePaint.setShader(new LinearGradient(0, bottom, 0, h,
                    ink, clear, Shader.TileMode.CLAMP));
            canvas.drawLine(cx, bottom, cx, h, linePaint);
        }
        linePaint.setShader(null);
    }

    private float dp(float v) {
        return v * getResources().getDisplayMetrics().density;
    }
}
