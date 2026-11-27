package pk.quantofrehan;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RadialGradient;
import android.graphics.RectF;
import android.graphics.Shader;
import android.util.AttributeSet;
import android.view.View;

/**
 * The console's core (owner order 2026-11-27: "remove this ORB feature ... give
 * it a new ORB type/Jarvis type feature").
 *
 * The photographed sun inside a wireframe cloud is retired. The station under
 * the brand is an instrument now, the way a targeting console reads: a ring of
 * compass ticks that ignite one by one as a radar sweep passes them, three
 * arc rings turning at their own speeds around a breathing reactor core, two
 * satellites on their own orbits with their trails, a scan line crossing the
 * field, and the four corner brackets of a live sight. Nothing is a picture of
 * anything: every mark is an instrument mark, drawn in the theme's own accent,
 * so the same view reads as the console's own head on every theme.
 *
 * The budget is the same as the old orb's promise: one View, zero relay
 * requests, no allocation on the frame path. The tick table, the arc
 * rectangles and the core's gradient are built once in onSizeChanged; every
 * frame touches preallocated paints, floats, rectangles and a fixed loop.
 *
 * start() and stop() stay the only public controls, wired to MainActivity's
 * startHud and stopHud behind the market gate. A parked view repaints the pose
 * the loop last drew, fully lit and still, so a closed market never shows a
 * moving instrument and never blanks the station either (SO-3).
 */
public class ThinkingOrb extends View {

    /** One completed picture every 33ms, the old orb's own frame budget. */
    private static final long FPS_MS = 33L;

    /** The compass: 96 ticks, one every 3.75 degrees. */
    private static final int TICKS = 96;

    /** The wake ramp, so the instrument grows out of the dark. */
    private static final float WAKE_SECONDS = 2.0f;

    /** The pose a parked view shows when the loop never reached a frame. */
    private static final float PARKED_SECONDS = 2.0f;

    /** The console's own instrument cyan, until the theme speaks. */
    private static final int DEFAULT_INK = 0xFF3FE0FF;

    private final Paint ringPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint arcPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint tickPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint corePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint sweepPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint satellitePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint hotPaint = new Paint(Paint.ANTI_ALIAS_FLAG);

    /** The three arc rings' own rectangles, rebuilt once per size. */
    private final RectF outerArc = new RectF();
    private final RectF middleArc = new RectF();
    private final RectF innerArc = new RectF();
    private final RectF coreArc = new RectF();

    private float cx;
    private float cy;
    private float reach;
    /** Where every tick begins, and so the radius of the compass circle. */
    private float tickInner;

    private int ink = DEFAULT_INK;
    private RadialGradient coreGradient;

    private boolean built;
    private boolean running;
    private long clockAnchor = System.currentTimeMillis();
    private long lastFrameAt = -1L;
    private float lastSeconds;
    private float frozenSeconds = -1f;

    public ThinkingOrb(Context context) {
        super(context);
        init();
    }

    public ThinkingOrb(Context context, AttributeSet attrs) {
        super(context, attrs);
        init();
    }

    public ThinkingOrb(Context context, AttributeSet attrs, int style) {
        super(context, attrs, style);
        init();
    }

    private void init() {
        ringPaint.setStyle(Paint.Style.STROKE);
        ringPaint.setStrokeCap(Paint.Cap.ROUND);
        arcPaint.setStyle(Paint.Style.STROKE);
        arcPaint.setStrokeCap(Paint.Cap.ROUND);
        tickPaint.setStyle(Paint.Style.STROKE);
        tickPaint.setStrokeCap(Paint.Cap.ROUND);
        sweepPaint.setStyle(Paint.Style.STROKE);
        sweepPaint.setStrokeCap(Paint.Cap.ROUND);
        hotPaint.setStyle(Paint.Style.FILL);
        corePaint.setStyle(Paint.Style.FILL);
        satellitePaint.setStyle(Paint.Style.FILL);
        setInk(ink);
    }

    /**
     * Starts the frame loop; a second call while running is a no-op. The
     * clock is NOT reset, so a resume replays from the frozen second and the
     * instrument neither blanks nor restarts its wake.
     */
    public void start() {
        if (running) {
            return;
        }
        running = true;
        clockAnchor = frozenSeconds >= 0f
                ? System.currentTimeMillis() - (long) (frozenSeconds * 1000f)
                : System.currentTimeMillis();
        lastFrameAt = -1L;
        postInvalidateOnAnimation();
    }

    /** Parks the loop on the pose it last drew, lit and still. */
    public void stop() {
        if (!running) {
            return;
        }
        running = false;
        frozenSeconds = lastSeconds;
        lastFrameAt = -1L;
    }

    /**
     * The theme's accent, so the instrument is the console's own colour on
     * every theme. The core's glow is rebuilt with it.
     */
    public void setThemeInk(int color) {
        setInk(color);
        invalidate();
    }

    private void setInk(int color) {
        ink = color;
        ringPaint.setColor(ink);
        arcPaint.setColor(ink);
        tickPaint.setColor(ink);
        sweepPaint.setColor(ink);
        satellitePaint.setColor(ink);
        if (built) {
            buildGradient();
        }
        invalidate();
    }

    @Override
    protected void onSizeChanged(int w, int h, int oldW, int oldH) {
        super.onSizeChanged(w, h, oldW, oldH);
        if (w <= 0 || h <= 0) {
            return;
        }
        cx = w / 2f;
        cy = h / 2f;
        reach = Math.min(w, h) / 2f - dp(9f);
        tickInner = reach - dp(9f);
        outerArc.set(cx - reach * 0.86f, cy - reach * 0.86f,
                cx + reach * 0.86f, cy + reach * 0.86f);
        middleArc.set(cx - reach * 0.72f, cy - reach * 0.72f,
                cx + reach * 0.72f, cy + reach * 0.72f);
        innerArc.set(cx - reach * 0.58f, cy - reach * 0.58f,
                cx + reach * 0.58f, cy + reach * 0.58f);
        coreArc.set(cx - reach * 0.34f, cy - reach * 0.34f,
                cx + reach * 0.34f, cy + reach * 0.34f);
        ringPaint.setStrokeWidth(Math.max(1f, dp(1f)));
        arcPaint.setStrokeWidth(Math.max(1f, dp(1.4f)));
        tickPaint.setStrokeWidth(Math.max(1f, dp(1.3f)));
        sweepPaint.setStrokeWidth(Math.max(1f, dp(1.2f)));
        buildGradient();
        built = true;
        invalidate();
    }

    /** The core's glow: white heart, the ink around it, nothing at the edge. */
    private void buildGradient() {
        int soft = (ink & 0x00FFFFFF) | 0x99000000;
        int faint = (ink & 0x00FFFFFF);
        coreGradient = new RadialGradient(cx, cy, Math.max(1f, reach * 0.52f),
                new int[]{0xFFFFFFFF, soft, faint}, new float[]{0f, 0.42f, 1f},
                Shader.TileMode.CLAMP);
    }

    @Override
    protected void onDraw(Canvas canvas) {
        if (!built) {
            postInvalidateOnAnimation();
            return;
        }
        if (!running) {
            drawScene(canvas, frozenSeconds >= 0f ? frozenSeconds
                    : PARKED_SECONDS);
            return;
        }
        long now = System.currentTimeMillis() - clockAnchor;
        if (lastFrameAt >= 0 && now - lastFrameAt < FPS_MS) {
            drawScene(canvas, lastSeconds);
            postInvalidateOnAnimation();
            return;
        }
        lastFrameAt = now;
        lastSeconds = now / 1000f;
        drawScene(canvas, lastSeconds);
        postInvalidateOnAnimation();
    }

    /** One whole picture of the instrument. */
    private void drawScene(Canvas canvas, float seconds) {
        float wake = Math.min(1f, Math.max(0f, seconds) / WAKE_SECONDS);
        if (wake <= 0f) {
            return;
        }
        float pulse = 1f + 0.05f * (float) Math.sin(seconds * 2.2f);
        float sweep = (seconds * 54f) % 360f;
        drawRing(canvas, wake);
        drawTicks(canvas, wake, sweep);
        drawArcs(canvas, wake, seconds);
        drawSweep(canvas, wake, sweep);
        drawOrbiters(canvas, wake, seconds);
        drawCore(canvas, wake, pulse, seconds);
    }

    /**
     * The faint compass circle, drawn on the exact radius every tick begins
     * on, so the circle and the first point of every little line are one
     * edge (owner order 2026-11-27: "make that outside circle sit on the
     * exact starting of the little lines that are making a circle").
     */
    private void drawRing(Canvas canvas, float wake) {
        ringPaint.setAlpha((int) (70f * wake));
        canvas.drawCircle(cx, cy, tickInner, ringPaint);
        ringPaint.setAlpha((int) (26f * wake));
        canvas.drawCircle(cx, cy, reach * 0.52f, ringPaint);
    }

    /**
     * The compass. Every tick is dim until the sweep reaches it, then it
     * burns and cools behind the beam, and every eighth tick is a long one.
     */
    private void drawTicks(Canvas canvas, float wake, float sweep) {
        for (int i = 0; i < TICKS; i++) {
            float angle = i * 360f / TICKS;
            float behind = ((sweep - angle) % 360f + 360f) % 360f;
            float heat = Math.max(0f, 1f - behind / 130f);
            float alpha = (0.22f + 0.78f * heat * heat) * wake;
            boolean major = i % 8 == 0;
            // Owner order 2026-11-27: every tick STARTS on the compass
            // circle and runs outward from it, the majors reaching the
            // field's own edge, so the circle sits exactly on the start of
            // all 96 little lines instead of standing off their tips.
            float from = tickInner;
            float to = from + dp(major ? 11f : 6f);
            double rad = Math.toRadians(angle - 90f);
            float cos = (float) Math.cos(rad);
            float sin = (float) Math.sin(rad);
            tickPaint.setAlpha((int) (alpha * (major ? 235f : 150f)));
            tickPaint.setStrokeWidth(Math.max(1f, dp(major ? 1.6f : 1.1f)));
            canvas.drawLine(cx + cos * from, cy + sin * from,
                    cx + cos * to, cy + sin * to, tickPaint);
        }
    }

    /** Three arc rings, each turning at its own speed and place. */
    private void drawArcs(Canvas canvas, float wake, float seconds) {
        arcPaint.setStrokeWidth(Math.max(1f, dp(1.6f)));
        arcPaint.setAlpha((int) (150f * wake));
        canvas.drawArc(outerArc, seconds * 22f - 90f, 104f, false, arcPaint);
        arcPaint.setAlpha((int) (110f * wake));
        canvas.drawArc(outerArc, seconds * 22f + 60f, 26f, false, arcPaint);
        arcPaint.setAlpha((int) (135f * wake));
        canvas.drawArc(middleArc, -seconds * 31f, 212f, false, arcPaint);
        arcPaint.setAlpha((int) (95f * wake));
        canvas.drawArc(innerArc, seconds * 47f + 20f, 74f, false, arcPaint);
        arcPaint.setAlpha((int) (60f * wake));
        canvas.drawArc(innerArc, seconds * 47f + 160f, 30f, false, arcPaint);
    }

    /** The radar beam: a bright leading line and the wake behind it. */
    private void drawSweep(Canvas canvas, float wake, float sweep) {
        for (int k = 0; k < 26; k++) {
            float angle = sweep - k * 1.6f;
            float fade = 1f - k / 26f;
            double rad = Math.toRadians(angle - 90f);
            float cos = (float) Math.cos(rad);
            float sin = (float) Math.sin(rad);
            sweepPaint.setAlpha((int) (fade * fade * 130f * wake));
            canvas.drawLine(cx, cy, cx + cos * reach * 0.9f,
                    cy + sin * reach * 0.9f, sweepPaint);
        }
        double lead = Math.toRadians(sweep - 90f);
        sweepPaint.setAlpha((int) (200f * wake));
        canvas.drawLine(cx, cy,
                cx + (float) Math.cos(lead) * reach * 0.9f,
                cy + (float) Math.sin(lead) * reach * 0.9f, sweepPaint);
    }

    /**
     * Two satellites on their own orbits, each trailing its light. Owner
     * order 2026-11-27: both travel the SAME way round, each at its own
     * speed, so neither of them swims against the other.
     */
    private void drawOrbiters(Canvas canvas, float wake, float seconds) {
        orbit(canvas, wake, seconds * 26f + 40f, reach * 0.66f, 0.9f);
        orbit(canvas, wake, seconds * 44f + 200f, reach * 0.46f, 0.75f);
    }

    private void orbit(Canvas canvas, float wake, float angle, float radius,
                       float scale) {
        for (int k = 6; k >= 0; k--) {
            double rad = Math.toRadians(angle - k * 3.4f - 90f);
            float x = cx + (float) Math.cos(rad) * radius;
            float y = cy + (float) Math.sin(rad) * radius;
            float fade = (7 - k) / 7f;
            satellitePaint.setAlpha((int) (fade * fade * 150f * wake));
            canvas.drawCircle(x, y, dp(1.1f) * scale * (0.6f + 0.4f * fade),
                    satellitePaint);
        }
        double head = Math.toRadians(angle - 90f);
        float hx = cx + (float) Math.cos(head) * radius;
        float hy = cy + (float) Math.sin(head) * radius;
        satellitePaint.setAlpha((int) (235f * wake));
        canvas.drawCircle(hx, hy, dp(2.1f) * scale, satellitePaint);
        satellitePaint.setAlpha((int) (60f * wake));
        canvas.drawCircle(hx, hy, dp(4.4f) * scale, satellitePaint);
    }

    /** The reactor: a breathing glow, its ring, and the hot heart. */
    private void drawCore(Canvas canvas, float wake, float pulse,
                          float seconds) {
        if (coreGradient != null) {
            corePaint.setShader(coreGradient);
            corePaint.setAlpha((int) (200f * wake));
            canvas.drawCircle(cx, cy, reach * 0.5f * pulse, corePaint);
            corePaint.setShader(null);
        }
        arcPaint.setAlpha((int) (170f * wake));
        arcPaint.setStrokeWidth(Math.max(1f, dp(1.3f)));
        canvas.drawArc(coreArc, -seconds * 70f, 132f, false, arcPaint);
        arcPaint.setAlpha((int) (110f * wake));
        canvas.drawArc(coreArc, seconds * 96f, 46f, false, arcPaint);
        hotPaint.setColor(Color.WHITE);
        hotPaint.setAlpha((int) (235f * wake));
        canvas.drawCircle(cx, cy, reach * 0.055f * pulse, hotPaint);
        hotPaint.setAlpha((int) (60f * wake));
        canvas.drawCircle(cx, cy, reach * 0.115f * pulse, hotPaint);
    }

    private float dp(float value) {
        return value * getResources().getDisplayMetrics().density;
    }
}
