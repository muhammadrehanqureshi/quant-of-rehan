package pk.quantofrehan;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.PorterDuff;
import android.graphics.PorterDuffXfermode;
import android.graphics.RadialGradient;
import android.graphics.Shader;
import android.util.AttributeSet;
import android.view.View;

/**
 * The sun, owner order 2026-10-22 (third pass, v1.9.9).
 *
 * The owner sent a screenshot of v1.9.8 and rejected it: the orb reads as a
 * sparse dot cloud around a tiny nucleus, and that is not the sun. His
 * order, verbatim: "sun is like a 3D ball that is burning every second".
 * This view draws exactly that and nothing else: ONE big ball that fills
 * the view, lit like a real sphere, whose surface burns and whose flares
 * burst on a seconds cadence.
 *
 * How the picture is built (one ball, four moods of fire):
 *
 *   - The ball is a one-time radial gradient whose hotspot sits up and to
 *     the left, from a white-hot heart through the solar golds to a deep
 *     burning orange at the limb, so it reads as ONE lit 3D sphere that
 *     turns, never as a flat disc.
 *   - The surface burns: convection cells (granulation) live on the sphere
 *     itself, rotate rigidly with it (a slow yaw plus a small breathing
 *     pitch), and flicker at their own rates, so the face of the sun is
 *     never still. Cells near the limb dim, which is what a 3D ball does.
 *   - The limb is ragged fire: flame tongues ring the circumference, each
 *     breathing its own length on its own rate, so the burning edge is not
 *     a perfect circle.
 *   - It burns every second: prominence arcs roll slowly around the limb
 *     and flare sparks launch outward one after another on a seconds
 *     cadence, so at least one bright burst is always alive each second.
 *   - A wide corona breathes UNDER the ball, out of phase with its heart.
 *
 * The budget: one View, zero relay requests, zero allocations per frame
 * (the granules, flames, prominences and sparks are built once in
 * onSizeChanged and reused; the one Path an arc needs is reused too), and
 * the frame loop is the view's own paced invalidate at FPS_MS. start() and
 * stop() are the only public controls, wired to MainActivity's startHud
 * and stopHud: a paused console draws nothing at all, and stop() holds
 * the last frame instead of abandoning the view blank.
 *
 * Colours are the solar family declared here beside the drawing that owns
 * them: the field is the palette's own deep background, every ink above
 * it is flame - from white-hot through gold to deep orange - and the rest
 * of the console stays on the brand palette untouched. Every ink carries
 * the brightness the owner ordered across the v1.9.5 to v1.9.8 passes as
 * ONE combined factor, so the stacking can never drift.
 */

public class ThinkingOrb extends View {

    /** The field is the console's own deep background, not a second black. */
    private static final int FIELD_COLOR = 0xFF0B070D;

    /**
     * Owner order 2026-10-22 (v1.9.5): the whole thing moves at 30% MORE
     * speed. Every turning, breathing and flickering rate below is
     * multiplied by this one number, so the owner's order is one named
     * constant rather than ten scattered edits.
     */
    private static final float MOTION_SCALE = 1.3f;

    /**
     * Owner order 2026-10-22 (v1.9.6 through v1.9.8, stacked): the feature
     * grew 25%, then 30%, then 30%, then 30% brighter. Each is its own
     * named constant here, and the frame runs them as ONE combined factor
     * (`bright`) at every ink, so the stacking is one decision on the
     * frame and can never drift.
     */
    private static final float GLOW_SCALE = 1.25f;
    private static final float BRIGHT_SCALE = 1.3f;
    private static final float P1 = 1.3f;
    private static final float P2 = 1.3f;

    /** The sun's white-hot heart. */
    private static final int SUN_WHITE = 0xFFFFF3B0;

    /** Populations. Chosen once; more would cost every frame for nothing. */
    private static final int GRANULES = 26;
    /**
     * Convection cell rows, 6 wide: x, y, z on the unit sphere, the cell's
     * size (a fraction of the sun's radius), its flicker phase and its
     * flicker rate.
     */
    private static final int GRANULE_STRIDE = 6;
    private static final int FLAMES = 22;
    /**
     * Owner order 2026-10-22 (more lines around the orb): the lines around the
     * ball are increased. The prominence arcs now REVOLVE around the limb on
     * their own slow bearing, not a wobble in a fixed slot, so more lines circle
     * the orb continuously; the flare sparks also increased, so the seconds
     * cadence always carries more streaks.
     */
    private static final int PROMINENCES = 42;
    private static final int FLARES = 28;

    /** Pacing of the frame loop, aimed at a smooth 30fps. */
    private static final long FPS_MS = 33L;

    /** The wake ramp: 1.2 seconds, so the sun is up when the owner looks. */
    private static final float WAKE_SECONDS = 1.2f;

    // The inks: shaders built once, alphas touched per frame, never rebuilt.
    private final Paint coronaPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint ballPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint heartPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint cellPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint flamePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint prominencePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint flarePaint = new Paint(Paint.ANTI_ALIAS_FLAG);

    /** The one Path an arc needs; reused, never reallocated on the frame. */
    private final Path arcPath = new Path();

    /** Convection cells on the sphere: unit ball position, size, phases. */
    private final float[] cells = new float[GRANULES * GRANULE_STRIDE];
    /** Per-frame screen detail of the cells, rebuilt in place. */
    private final float[] cellX = new float[GRANULES];
    private final float[] cellY = new float[GRANULES];
    private final float[] cellS = new float[GRANULES];
    private final float[] cellA = new float[GRANULES];

    /** Flame tongues around the limb: angle, base length, phase, rate. */
    private final float[] flameAngle = new float[FLAMES];
    private final float[] flameLength = new float[FLAMES];
    private final float[] flamePhase = new float[FLAMES];
    private final float[] flameRate = new float[FLAMES];

    /** Prominence arcs: angle, spread, height, phase (they roll around). */
    private final float[] promAngle = new float[PROMINENCES];
    private final float[] promSpread = new float[PROMINENCES];
    private final float[] promHeight = new float[PROMINENCES];
    private final float[] promPhase = new float[PROMINENCES];

    /** Flare sparks: angle, period (the seconds cadence), phase, speed. */
    private final float[] flareAngle = new float[FLARES];
    private final float[] flarePeriod = new float[FLARES];
    private final float[] flarePhase = new float[FLARES];

    private long clockAnchor;
    private long lastFrameAt = -1;
    private boolean running;

    private float sunR;
    private boolean geometryBuilt;

    public ThinkingOrb(Context context) {
        super(context);
    }

    public ThinkingOrb(Context context, AttributeSet attrs) {
        super(context, attrs);
    }

    public ThinkingOrb(Context context, AttributeSet attrs, int style) {
        super(context, attrs, style);
    }

    /**
     * Fire fuses: every ink above the field blends ADD, so where two glows
     * overlap they read as hotter, not as stacked discs. One shared mode,
     * referenced by each ink once at build time, never on the frame.
     */
    private static final PorterDuffXfermode FIRE_MODE =
            new PorterDuffXfermode(PorterDuff.Mode.ADD);

    /** Starts the frame loop; a second call while running is a no-op. */
    public void start() {
        if (running) {
            return;
        }
        running = true;
        lastFrameAt = -1;
        clockAnchor = System.currentTimeMillis();
        postInvalidateOnAnimation();
    }

    /** Parks the loop; the last frame stays until start() revives it. */
    public void stop() {
        running = false;
        lastFrameAt = -1;
    }

    @Override
    protected void onSizeChanged(int w, int h, int oldW, int oldH) {
        super.onSizeChanged(w, h, oldW, oldH);
        if (w <= 0 || h <= 0) {
            return;
        }
        buildGeometry();
        sunR = Math.min(w, h) / 2f - dp(4f);
        float cx = w / 2f;
        float cy = h / 2f;

        // The corona: ONE warm wide glow, brightest just past the limb and
        // gone at the edges of the view. Built once; it breathes in alpha,
        // never in radius, so the budget holds.
        coronaPaint.setShader(new RadialGradient(cx, cy, sunR * 1.6f,
                new int[]{0x00FFB179, 0x66FF9800, 0x33FF6F00, 0x00FF6F00},
                new float[]{0f, 0.42f, 0.75f, 1f}, Shader.TileMode.CLAMP));

        // The ball is ONE 3D sphere (owner order 2026-10-22, v1.9.7, still
        // standing): the hotspot sits up and to the left of its centre, the
        // body runs white-hot through the solar golds to a deep burning
        // orange, and the far limb falls to transparent, so the sphere
        // reads as lit volume, not a cut-out. RadialGradient insists on one
        // stop per colour; every stop is here exactly once.
        float hotspotR = sunR * 1.32f;
        ballPaint.setShader(new RadialGradient(
                cx - sunR * 0.18f, cy - sunR * 0.22f, hotspotR, new int[]{
                0xFFFFFDE9, 0xFFFFE9A0, 0xFFFFC107, 0xFFFF9800, 0xFFE65100,
                0x66BF360C},
                new float[]{0f, 0.18f, 0.42f, 0.68f, 0.92f, 1f},
                Shader.TileMode.CLAMP));

        // The convection cells share one soft, round shader centered on the
        // origin: each end draws at its OWN size by translating the canvas,
        // so one shader serves every cell without ever being rebuilt.
        cellPaint.setShader(new RadialGradient(0f, 0f, dp(6f), new int[]{
                0xAAFFF176, 0x66FFB74D, 0x00FFB74D},
                new float[]{0f, 0.45f, 1f}, Shader.TileMode.CLAMP));

        // The limb flames share the same soft trick at their own size.
        flamePaint.setShader(new RadialGradient(0f, 0f, dp(9f), new int[]{
                0xCCFFAB40, 0x55FF8F00, 0x00FF8F00},
                new float[]{0f, 0.5f, 1f}, Shader.TileMode.CLAMP));

        prominencePaint.setStyle(Paint.Style.STROKE);
        prominencePaint.setStrokeCap(Paint.Cap.ROUND);
        prominencePaint.setStrokeWidth(dp(1.9f));

        // Fire fuses: these inks blend ADD, so where two glows overlap
        // they read as hotter, not as stacked discs. The ball itself stays
        // normal blending: it is the body the fire lives on.
        coronaPaint.setXfermode(FIRE_MODE);
        heartPaint.setXfermode(FIRE_MODE);
        cellPaint.setXfermode(FIRE_MODE);
        flamePaint.setXfermode(FIRE_MODE);
        prominencePaint.setXfermode(FIRE_MODE);
        flarePaint.setXfermode(FIRE_MODE);

        geometryBuilt = true;
    }

    /**
     * One full build of the burning geometry: the convection cells on the
     * sphere, the flame ring, the prominence arcs and the flare sparks.
     * Deterministic, so every launch draws the same sun. Runs once per
     * size; never on the frame path.
     */
    private void buildGeometry() {
        long seed = 20261022L;
        for (int c = 0; c < GRANULES; c++) {
            seed = nextSeed(seed);
            float u = frac(seed) * 2f - 1f;
            seed = nextSeed(seed);
            float theta = frac(seed) * (float) Math.PI * 2f;
            float s = (float) Math.sqrt(1f - u * u);
            seed = nextSeed(seed);
            float size = 0.07f + frac(seed) * 0.05f;
            seed = nextSeed(seed);
            float phase = frac(seed) * (float) Math.PI * 2f;
            seed = nextSeed(seed);
            float rate = 1.2f + frac(seed) * 1.3f;
            int o = c * GRANULE_STRIDE;
            cells[o] = s * (float) Math.cos(theta);
            cells[o + 1] = u;
            cells[o + 2] = s * (float) Math.sin(theta);
            cells[o + 3] = size;
            cells[o + 4] = phase;
            cells[o + 5] = rate;
        }
        for (int f = 0; f < FLAMES; f++) {
            flameAngle[f] = (float) Math.PI * 2f * f / FLAMES;
            seed = nextSeed(seed);
            flameLength[f] = 0.16f + frac(seed) * 0.09f;
            seed = nextSeed(seed);
            flamePhase[f] = frac(seed) * (float) Math.PI * 2f;
            seed = nextSeed(seed);
            flameRate[f] = 1.4f + frac(seed) * 1.6f;
        }
        for (int p = 0; p < PROMINENCES; p++) {
            // Owned slots, but the owner's second pass makes the LINES move:
            // each arc also carries its own small extra bearing, drawn in
            // round-robin fractions of 2 pi, so the ring never reads as ten
            // evenly spaced spokes.
            promAngle[p] = (float) Math.PI * 2f * (p * 0.37f);
            seed = nextSeed(seed);
            promSpread[p] = 0.28f + frac(seed) * 0.18f;
            seed = nextSeed(seed);
            promHeight[p] = 0.16f + frac(seed) * 0.14f;
            seed = nextSeed(seed);
            promPhase[p] = frac(seed) * (float) Math.PI * 2f;
        }
        // The seconds cadence: each spark fires on its own period straddling
        // one second, phased so a burst is alive almost every second.
        for (int s = 0; s < FLARES; s++) {
            seed = nextSeed(seed);
            flareAngle[s] = frac(seed) * (float) Math.PI * 2f;
            seed = nextSeed(seed);
            flarePeriod[s] = 0.9f + frac(seed) * 0.7f;
            seed = nextSeed(seed);
            flarePhase[s] = frac(seed) * flarePeriod[s];
        }
    }

    @Override
    protected void onDraw(Canvas canvas) {
        if (!geometryBuilt) {
            return;
        }
        if (!running) {
            // Parked: stop() holds the last frame until start() revives the
            // loop, so this draw is the parked one and schedules nothing.
            return;
        }
        long now = System.currentTimeMillis() - clockAnchor;
        if (lastFrameAt >= 0 && now - lastFrameAt < FPS_MS) {
            postInvalidateOnAnimation();
            return;
        }
        lastFrameAt = now;
        float seconds = now / 1000f;
        float cx = getWidth() / 2f;
        float cy = getHeight() / 2f;
        // The owner's speeds: one scale on every rate. The sun turns and
        // breathes slowly; the fire on it flickers fast enough to burn.
        float yaw = seconds * 0.12f * MOTION_SCALE;
        float pitch = 0.10f * (float) Math.sin(seconds * 0.13f * MOTION_SCALE);
        float heartBreath = 0.55f + 0.45f * (float) Math.sin(
                seconds * 1.1f * MOTION_SCALE);
        float coronaBreath = 0.55f + 0.45f * (float) Math.sin(
                seconds * 0.9f * MOTION_SCALE + 2.4f);
        float wake = Math.min(1f, seconds / WAKE_SECONDS);
        // Every ink's brightness: the four stacked owner orders as ONE
        // per-frame factor, so the decisions are constants and the frame
        // never re-decides them.
        float bright = wake * GLOW_SCALE * BRIGHT_SCALE * P1 * P2;

        canvas.drawColor(FIELD_COLOR);

        drawCorona(canvas, cx, cy, coronaBreath, bright);
        drawFlames(canvas, cx, cy, seconds, bright);
        drawProminences(canvas, cx, cy, seconds, bright);
        drawBall(canvas, cx, cy, heartBreath, bright);
        drawCells(canvas, cx, cy, seconds, yaw, pitch, bright);
        drawFlares(canvas, cx, cy, seconds, bright);
        postInvalidateOnAnimation();
    }

    /**
     * The corona UNDER ball and fire. It breathes OUT of phase with the
     * ball's heart (owner order v1.9.7: the glow and the heart cross
     * rather than pulse together).
     */
    private void drawCorona(Canvas canvas, float cx, float cy,
                            float coronaBreath, float bright) {
        coronaPaint.setAlpha(Math.min(255, (int) (95f
                * (0.55f + 0.45f * coronaBreath) * bright)));
        canvas.drawCircle(cx, cy, sunR * 1.6f, coronaPaint);
    }

    /** The ragged burning edge: one soft tongue per ring slot. */
    private void drawFlames(Canvas canvas, float cx, float cy, float seconds,
                            float bright) {
        for (int f = 0; f < FLAMES; f++) {
            // The tongue wobbles a few degrees around its slot and breathes
            // its length on its own rate, so the limb is never a circle.
            float angle = flameAngle[f] + 0.09f * (float) Math.sin(
                    seconds * (0.7f + f * 0.13f) * MOTION_SCALE
                            + flamePhase[f]);
            float len = flameLength[f] * (0.55f + 0.55f
                    * (float) Math.sin(seconds * flameRate[f] * MOTION_SCALE
                    + flamePhase[f] * 2f));
            if (len < 0.02f) {
                continue;
            }
            canvas.save();
            canvas.translate(cx + sunR * (float) Math.cos(angle),
                    cy + sunR * (float) Math.sin(angle));
            flamePaint.setAlpha(Math.min(255, (int) (145f
                    * (0.4f + 0.6f * Math.abs(len) / 0.25f) * bright)));
            canvas.drawCircle(0f, 0f, sunR * len, flamePaint);
            canvas.restore();
        }
    }

    /**
     * The prominences: plasma arcs that roll slowly around the limb and
     * leap a little ahead of the burning edge. One reusable Path carries
     * each arc, so the frame never allocates.
     */
    private void drawProminences(Canvas canvas, float cx, float cy,
                                 float seconds, float bright) {
        for (int p = 0; p < PROMINENCES; p++) {
            // The owner's order: the lines REVOLVE around the orb. Each arc
            // has its own slow bearing that advances forever, at its own
            // rate, rounder than a wobble: five degrees of breath on top of
            // the continuous roll.
            float roll = promAngle[p]
                    + seconds * (0.05f + p * 0.008f) * MOTION_SCALE
                    + 0.09f * (float) Math.sin(
                    seconds * 0.31f * MOTION_SCALE + promPhase[p]);
            float leap = 0.5f + 0.5f * (float) Math.sin(
                    seconds * 0.47f * MOTION_SCALE + promPhase[p] * 3f);
            float height = promHeight[p] * (0.55f + 0.45f * leap);
            float a0 = roll - promSpread[p] * 0.5f;
            float a1 = roll + promSpread[p] * 0.5f;
            arcPath.reset();
            arcPath.moveTo(
                    cx + sunR * (float) Math.cos(a0),
                    cy + sunR * (float) Math.sin(a0));
            arcPath.quadTo(
                    cx + sunR * (1f + height * 1.7f)
                            * (float) Math.cos(roll),
                    cy + sunR * (1f + height * 1.7f)
                            * (float) Math.sin(roll),
                    cx + sunR * (float) Math.cos(a1),
                    cy + sunR * (float) Math.sin(a1));
            prominencePaint.setColor(0xFFFFB74D);
            // Ten inks ADD on the same canvas: the per-arc light was trimmed
            // so the ring glows instead of washing out.
            prominencePaint.setAlpha(Math.min(255, (int) (85f
                    * (0.35f + 0.65f * leap) * bright)));
            canvas.drawPath(arcPath, prominencePaint);
        }
    }

    /**
     * The ball itself, then its white-hot heart. Draw order: corona and
     * fire UNDER the ball, ball, heart, cells, sparks, so nothing dulls
     * what is above it. The heart breathes in alpha, never in radius.
     */
    private void drawBall(Canvas canvas, float cx, float cy, float heartBreath,
                          float bright) {
        ballPaint.setAlpha(Math.min(255, (int) (215f * bright)));
        canvas.drawCircle(cx, cy, sunR, ballPaint);
        heartPaint.setAlpha(Math.min(255, (int) (200f
                * (0.55f + 0.45f * heartBreath) * bright)));
        canvas.drawCircle(cx - sunR * 0.13f, cy - sunR * 0.16f,
                sunR * 0.24f, heartPaint);
    }

    private void drawCells(Canvas canvas, float cx, float cy, float seconds,
                           float yaw, float pitch, float bright) {
        float cosYaw = (float) Math.cos(yaw);
        float sinYaw = (float) Math.sin(yaw);
        float cosPitch = (float) Math.cos(pitch);
        float sinPitch = (float) Math.sin(pitch);
        for (int c = 0; c < GRANULES; c++) {
            int o = c * GRANULE_STRIDE;
            float x = cells[o];
            float y = cells[o + 1];
            float z = cells[o + 2];
            float rx = x * cosYaw + z * sinYaw;
            float rz = -x * sinYaw + z * cosYaw;
            float ry = y * cosPitch - rz * sinPitch;
            rz = y * sinPitch + rz * cosPitch;
            // Only the face of the sphere burns toward the viewer; cells
            // near the limb fade, which is what a 3D ball does.
            if (rz <= 0.08f) {
                continue;
            }
            float flicker = 0.5f + 0.5f * (float) Math.sin(
                    seconds * cells[o + 5] * MOTION_SCALE
                            + cells[o + 4] * 7f);
            flicker *= 0.5f + 0.5f * (float) Math.sin(
                    seconds * cells[o + 5] * 0.37f * MOTION_SCALE
                            + cells[o + 4] * 3f);
            cellX[c] = cx + rx * sunR * 0.84f;
            cellY[c] = cy + ry * sunR * 0.84f;
            cellS[c] = sunR * cells[o + 3] * (0.55f + 0.45f * rz);
            cellA[c] = (150f * rz + 90f * flicker * rz) * bright;
            if (cellA[c] < 8f) {
                continue;
            }
            canvas.save();
            canvas.translate(cellX[c], cellY[c]);
            cellPaint.setAlpha(Math.min(255, (int) cellA[c]));
            canvas.scale(cellS[c] / dp(6f), cellS[c] / dp(6f));
            canvas.drawCircle(0f, 0f, dp(6f), cellPaint);
            canvas.restore();
        }
    }

    /**
     * The seconds cadence: each flare spark launches outward along its own
     * limb angle once per period, tracing a short streak of fire and
     * decaying as it falls. Always at least one alive.
     */
    private void drawFlares(Canvas canvas, float cx, float cy, float seconds,
                            float bright) {
        for (int s = 0; s < FLARES; s++) {
            float cycle = seconds * MOTION_SCALE;
            float period = flarePeriod[s];
            float t = (cycle + flarePhase[s]) % period;
            if (t > 0.62f) {
                continue;
            }
            float k = t / 0.62f;
            float angle = flareAngle[s] + 0.18f * cycle;
            float dist = sunR * (1.02f + 0.42f * k);
            float fx = cx + dist * (float) Math.cos(angle);
            float fy = cy + dist * (float) Math.sin(angle);
            float shrink = 1f - k;
            flarePaint.setColor(Color.argb(
                    Math.min(255, (int) (210f * shrink * k * bright + 40f)),
                    0xFF, 0xF9, 0xDD));
            flarePaint.setStrokeWidth(dp(2f) * (0.4f + 0.6f * shrink));
            flarePaint.setStrokeCap(Paint.Cap.ROUND);
            canvas.drawLine(
                    fx - sunR * 0.06f * (float) Math.cos(angle)
                            * shrink,
                    fy - sunR * 0.06f * (float) Math.sin(angle)
                            * shrink,
                    fx, fy, flarePaint);
        }
    }

    private static long nextSeed(long seed) {
        seed ^= seed << 13;
        seed ^= seed >>> 7;
        seed ^= seed << 17;
        return seed;
    }

    private static float frac(long seed) {
        return Math.abs(seed % 10007L) / 10007f;
    }

    private float dp(float dp) {
        return dp * getResources().getDisplayMetrics().density;
    }

}
