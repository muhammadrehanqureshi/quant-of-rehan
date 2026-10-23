package pk.quantofrehan;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RadialGradient;
import android.graphics.Shader;
import android.util.AttributeSet;
import android.view.View;

/**
 * The quant's own look, owner order 2026-10-23 (fourth pass, v1.9.13).
 *
 * The owner sent the reference screenshot back beside v1.9.9's picture and
 * rejected it: the feature is the constellation once more, the web of dots
 * and lines around a small core, but it must show MORE lines revolving
 * around the core than the versions before it, and the white orb at the
 * centre is replaced by a sun-looking ball of the SAME size, which is a
 * lit 3D sphere and burns without pause.
 *
 * How the picture is built, exactly three layers:
 *
 *   - The constellation: 30 field dots scattered through a lopsided cloud
 *     around the centre, joined by the mesh edges the distances decide
 *     (capped, so no knot over-draws). The whole cloud revolves as one
 *     body around the ball, which is the reference's own orbit.
 *   - The revolving lines: three rings of nodes circle the ball on tilted
 *     ellipses, each at its own radius, direction and speed, and each
 *     ring's nodes are joined into its polyline. Rings and mesh together
 *     hold more lines than the prominence count of any pass before, and
 *     the sun keeps its own six arcs revolving at the limb.
 *   - The sun: a small 3D ball the same size the white orb held, lit by a
 *     radial gradient whose hotspot sits up and to the left, white-hot
 *     through the solar golds to deep burning orange at the limb. It burns
 *     ALWAYS: granulation cells on its face, flame tongues on its ragged
 *     limb, plasma arcs that revolve around it, and a flare spark alive
 *     almost every second. A grey rest ring behind it holds the
 *     reference's own disc.
 *
 * The feature stops when the market stops (owner order 2026-10-23): the
 * market gate is the ON badge's own boolean in MainActivity, the same
 * knowledge the status dot uses, so the view is ordered stop() whenever
 * the relay reports the session closed or on a break, and start() again
 * the moment it trades. stop() parks the loop and holds the last frame,
 * so a closed market shows one still burning sun: no motion claims the
 * session is live (SO-3), and the picture never blanks.
 *
 * The budget is the budget that survived the earlier passes: one View,
 * zero relay requests, zero allocations per frame (the cloud, its edges,
 * the rings' nodes, the cells, flames, prominences and sparks are built
 * once in onSizeChanged and every draw touches preallocated arrays), and
 * the frame loop is the view's own paced invalidate at FPS_MS. start()
 * and stop() stay the only public controls, wired to MainActivity's
 * startHud and stopHud: a paused console draws nothing at all, and the
 * market gate decides the rest.
 */

public class ThinkingOrb extends View {

    /**
     * Populations, chosen once. The owner's order compares this pass with
     * the ones before it on ONE count: more lines revolve around the core
     * than before.
     */
    private static final int NODES = 30;
    /** x, y, z (radius-weighted unit sphere), brightness, twinkle phase. */
    private static final int NODE_STRIDE = 5;
    /** One mesh edge's two node indices; built here, read on the frame. */
    private static final int EDGE_STRIDE = 2;

    /** The three revolving rings: node counts, radii, speed, tilt. */
    private static final int[] RING_NODES = {8, 10, 12};
    private static final float[] RING_FACTOR = {2.1f, 3.2f, 4.35f};
    private static final float[] RING_SPEED = {0.55f, -0.40f, 0.26f};
    private static final float[] RING_TILT = {0.62f, 0.50f, 0.40f};

    /** The maximum distance two field dots may keep to be joined. */
    private static final float LINK_DIST = 0.62f;
    /** The cap on connections at one node, so no knot over-draws. */
    private static final int LINK_MAX = 4;

    private static final int GRANULES = 10;
    private static final int GRANULE_STRIDE = 6;
    private static final int FLAMES = 12;
    private static final int PROMINENCES = 6;
    private static final int FLARES = 5;

    /** Pacing of the frame loop, aimed at a smooth 30fps. */
    private static final long FPS_MS = 33L;

    /** The wake ramp: 1.2 seconds, so the sun is up when the owner looks. */
    private static final float WAKE_SECONDS = 1.2f;

    // The fixed inks of the constellation, silver on the deep field.
    private static final int NODE_BRIGHT = 0xFFE3ECFA;
    private static final int NODE_DIM = 0xFF9FB0C8;
    private static final int LINE_INK = 0xFF7E93B4;

    private final Paint cloudDot = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint cloudLine = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint sunPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint sunHeart = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint sunCell = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint sunFlame = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint sunProm = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint sunFlare = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint restRing = new Paint(Paint.ANTI_ALIAS_FLAG);

    /** The one Path the prominence arcs share; reset, never reallocated. */
    private final Path promPath = new Path();

    private float cx;
    private float cy;
    private float ballR;
    private float restR;
    private float cloudR;
    private float cellRadiusBase;

    /**
     * Field cloud nodes: unit sphere position weighted by each dot's own
     * gravity, plus brightness and twinkle phase, all built once. Edges
     * are the two node indices per line.
     */
    private final float[] nodes = new float[NODES * NODE_STRIDE];
    private final int[] edges = new int[NODES * LINK_MAX * EDGE_STRIDE];
    private int edgeCount;

    /** The sun's granulation cells: unit position, size, phase, rate. */
    private final float[] cells = new float[GRANULES * GRANULE_STRIDE];

    /** Flame tongues around the limb: angle, length, phase, rate. */
    private final float[] flameAngle = new float[FLAMES];
    private final float[] flameLength = new float[FLAMES];
    private final float[] flamePhase = new float[FLAMES];
    private final float[] flameRate = new float[FLAMES];

    /** Revolving prominence arcs: angle, spread, height, phase, speed. */
    private final float[] promAngle = new float[PROMINENCES];
    private final float[] promSpread = new float[PROMINENCES];
    private final float[] promHeight = new float[PROMINENCES];
    private final float[] promPhase = new float[PROMINENCES];
    private final float[] promSpeed = new float[PROMINENCES];

    /** Flare sparks: angle, period (the seconds cadence), phase. */
    private final float[] flareAngle = new float[FLARES];
    private final float[] flarePeriod = new float[FLARES];
    private final float[] flarePhase = new float[FLARES];

    private long clockAnchor;
    private long lastFrameAt = -1;
    private boolean running;
    private boolean built;

    public ThinkingOrb(Context context) {
        super(context);
    }

    public ThinkingOrb(Context context, AttributeSet attrs) {
        super(context, attrs);
    }

    public ThinkingOrb(Context context, AttributeSet attrs, int style) {
        super(context, attrs, style);
    }

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
        cx = w / 2f;
        cy = h / 2f;
        // The reference's own proportions: the ball about one seventh of
        // the box's short side, the grey disc just outside it, the cloud
        // open to three tenths of the short side around the core.
        float shortSide = Math.min(w, h);
        ballR = shortSide * 0.072f;
        restR = ballR * 1.55f;
        cloudR = shortSide * 0.30f;
        cellRadiusBase = dp(6f);
        buildCloud();
        buildSun();
        buildInks();
        built = true;
    }

    /**
     * One full build of the deterministic geometry: the field cloud and
     * its edge web (capped so no node over-connects) and the sun's fire.
     * Runs once per size; never on the frame path.
     */
    private void buildCloud() {
        long seed = 20261023L;
        // Lopsided cloud: the reference gathers its dots tighter to the
        // core and lets a few wander further, so the gravity frac is
        // squared: dense near the sun, sparse at the rim.
        for (int n = 0; n < NODES; n++) {
            seed = nextSeed(seed);
            float u = frac(seed) * 2f - 1f;
            seed = nextSeed(seed);
            float theta = frac(seed) * (float) Math.PI * 2f;
            float s = (float) Math.sqrt(1f - u * u);
            seed = nextSeed(seed);
            float radius = 0.30f + 0.70f * frac(seed) * frac(seed);
            seed = nextSeed(seed);
            float bright = 0.45f + frac(seed) * 0.55f;
            seed = nextSeed(seed);
            float twinkle = frac(seed) * 2f - 1f;
            int o = n * NODE_STRIDE;
            nodes[o] = s * (float) Math.cos(theta) * radius;
            nodes[o + 1] = u * radius;
            nodes[o + 2] = s * (float) Math.sin(theta) * radius;
            nodes[o + 3] = bright;
            nodes[o + 4] = twinkle;
        }
        // The web: the distances decide, the cap keeps any one dot from
        // gathering all of them.
        edgeCount = 0;
        for (int i = 0; i < NODES; i++) {
            int drawn = 0;
            for (int j = i + 1; j < NODES && drawn < LINK_MAX; j++) {
                int oi = i * NODE_STRIDE;
                int oj = j * NODE_STRIDE;
                float dx = nodes[oi] - nodes[oj];
                float dy = nodes[oi + 1] - nodes[oj + 1];
                float dz = nodes[oi + 2] - nodes[oj + 2];
                if (dx * dx + dy * dy + dz * dz < LINK_DIST * LINK_DIST) {
                    edges[edgeCount++] = i;
                    edges[edgeCount++] = j;
                    drawn++;
                }
            }
        }
    }

    /** The sun's fire: cells, flames, prominences, sparks. */
    private void buildSun() {
        long seed = 20261024L;
        for (int c = 0; c < GRANULES; c++) {
            seed = nextSeed(seed);
            float u = frac(seed) * 2f - 1f;
            seed = nextSeed(seed);
            float theta = frac(seed) * (float) Math.PI * 2f;
            float s = (float) Math.sqrt(1f - u * u);
            seed = nextSeed(seed);
            float size = 0.10f + frac(seed) * 0.08f;
            seed = nextSeed(seed);
            float phase = frac(seed) * (float) Math.PI * 2f;
            seed = nextSeed(seed);
            float rate = 1.4f + frac(seed) * 1.6f;
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
            flameLength[f] = 0.12f + frac(seed) * 0.10f;
            seed = nextSeed(seed);
            flamePhase[f] = frac(seed) * (float) Math.PI * 2f;
            seed = nextSeed(seed);
            flameRate[f] = 1.5f + frac(seed) * 1.5f;
        }
        for (int p = 0; p < PROMINENCES; p++) {
            promAngle[p] = (float) Math.PI * 2f * p / PROMINENCES
                    + 0.37f * p;
            seed = nextSeed(seed);
            promSpread[p] = 0.30f + frac(seed) * 0.15f;
            seed = nextSeed(seed);
            promHeight[p] = 0.20f + frac(seed) * 0.18f;
            seed = nextSeed(seed);
            promPhase[p] = frac(seed) * (float) Math.PI * 2f;
            promSpeed[p] = 0.12f + frac(seed) * 0.10f;
        }
        for (int s = 0; s < FLARES; s++) {
            seed = nextSeed(seed);
            flareAngle[s] = frac(seed) * (float) Math.PI * 2f;
            seed = nextSeed(seed);
            flarePeriod[s] = 0.9f + frac(seed) * 0.6f;
            seed = nextSeed(seed);
            flarePhase[s] = frac(seed) * flarePeriod[s];
        }
    }

    /** The paints and the one shader the sun keeps by its builder. */
    private void buildInks() {
        cloudDot.setStyle(Paint.Style.FILL);
        cloudLine.setStyle(Paint.Style.STROKE);
        cloudLine.setStrokeWidth(dp(1.1f));

        // The sun is ONE 3D sphere: the hotspot up and to the left, the
        // body white-hot through the solar golds to a deep burning orange
        // at the limb, whose rim falls into the field. One stop per
        // colour; RadialGradient insists.
        sunPaint.setShader(new RadialGradient(
                cx - ballR * 0.20f, cy - ballR * 0.22f, ballR * 1.65f,
                new int[]{0xFFFFFCE7, 0xFFFFE07D, 0xFFFFBF12, 0xFFF57C00,
                          0xFFC44600, 0x77933A00},
                new float[]{0f, 0.16f, 0.30f, 0.48f, 0.75f, 1f},
                Shader.TileMode.CLAMP));

        // The heart shares the same face one disc further out.
        sunHeart.setShader(new RadialGradient(0f, 0f, ballR * 0.6f, new int[]{
                0x88FFF3C0, 0x33FFE082, 0x00FFE082},
                new float[]{0f, 0.45f, 1f}, Shader.TileMode.CLAMP));

        // The granulation cells share one soft shader on the origin, drawn
        // at each cell's OWN size by translating and scaling the canvas.
        sunCell.setShader(new RadialGradient(0f, 0f, cellRadiusBase,
                new int[]{0x88FFECB3, 0x44FFE082, 0x00FFE082},
                new float[]{0f, 0.45f, 1f}, Shader.TileMode.CLAMP));

        // The flame tongues share the same soft trick at the limb.
        sunFlame.setShader(new RadialGradient(0f, 0f, dp(7f), new int[]{
                0xAAFFB84D, 0x55FF8F00, 0x00FF8F00},
                new float[]{0f, 0.5f, 1f}, Shader.TileMode.CLAMP));

        sunProm.setStyle(Paint.Style.STROKE);
        sunProm.setStrokeCap(Paint.Cap.ROUND);
        sunProm.setStrokeWidth(dp(1.4f));

        sunFlare.setColor(0xFFF9E8C8);
        sunFlare.setStrokeCap(Paint.Cap.ROUND);
        sunFlare.setStrokeWidth(dp(1.8f));

        // The grey rest ring behind the ball, the reference's own disc.
        restRing.setStyle(Paint.Style.STROKE);
        restRing.setStrokeWidth(dp(2.2f));
        restRing.setColor(0xFF78839B);
    }

    @Override
    protected void onDraw(Canvas canvas) {
        if (!built) {
            return;
        }
        if (!running) {
            // Parked: stop() holds the last frame until start() revives
            // the loop, so this draw is the parked one and schedules
            // nothing.
            return;
        }
        long now = System.currentTimeMillis() - clockAnchor;
        if (lastFrameAt >= 0 && now - lastFrameAt < FPS_MS) {
            postInvalidateOnAnimation();
            return;
        }
        lastFrameAt = now;
        float seconds = now / 1000f;
        float wake = Math.min(1f, seconds / WAKE_SECONDS);
        drawRestRing(canvas, wake);
        drawCloud(canvas, seconds, wake);
        drawSun(canvas, seconds, wake);
        postInvalidateOnAnimation();
    }

    private void drawRestRing(Canvas canvas, float wake) {
        restRing.setAlpha(Math.min(255, (int) (76f * wake)));
        canvas.drawCircle(cx, cy, restR + dp(4), restRing);
    }

    /**
     * The cloud, ONE body revolving around the core: the rotation is a
     * single yaw on every dot, so the web's shape is kept by the frame.
     * Depth decides the alpha, near dots brighter, and each dot twinkles
     * at its own rate on top of the shared turn.
     */
    private void drawCloud(Canvas canvas, float seconds, float wake) {
        float yaw = seconds * 0.10f;
        float cosYaw = (float) Math.cos(yaw);
        float sinYaw = (float) Math.sin(yaw);
        // Edges first, dots second, so each ink's colour is set once for
        // its whole population and only the alpha moves per element.
        // edgeCount walks the flat pair array, two entries per edge, so
        // the loop runs over the pair count, never over the indices.
        cloudLine.setColor(LINE_INK);
        int edgePairs = edgeCount / 2;
        for (int e = 0; e < edgePairs; e++) {
            int i = edges[e * EDGE_STRIDE];
            int j = edges[e * EDGE_STRIDE + 1];
            int oi = i * NODE_STRIDE;
            int oj = j * NODE_STRIDE;
            float xi = nodes[oi];
            float zi = nodes[oi + 2];
            float fx = xi * cosYaw + zi * sinYaw;
            float fz = -xi * sinYaw + zi * cosYaw;
            float xj = nodes[oj];
            float zj = nodes[oj + 2];
            float gx = xj * cosYaw + zj * sinYaw;
            float gz = -xj * sinYaw + zj * cosYaw;
            float depth = (fz + gz) * 0.5f;
            int alpha = (int) ((0.55f + 0.45f * depth) * 165f * wake);
            cloudLine.setAlpha(Math.max(0, Math.min(255, alpha)));
            canvas.drawLine(cx + fx * cloudR, cy + nodes[oi + 1] * cloudR,
                    cx + gx * cloudR, cy + nodes[oj + 1] * cloudR, cloudLine);
        }
        for (int n = 0; n < NODES; n++) {
            int o = n * NODE_STRIDE;
            float x = nodes[o];
            float z = nodes[o + 2];
            float rx = x * cosYaw + z * sinYaw;
            float rz = -x * sinYaw + z * cosYaw;
            float size = 1.4f + 1.6f * nodes[o + 3] * (0.5f + 0.5f * rz);
            cloudDot.setColor(rz > 0f ? NODE_BRIGHT : NODE_DIM);
            cloudDot.setAlpha(Math.min(255, (int) (255f * wake
                    * (0.35f + 0.65f * (rz + 1f) / 2f))));
            canvas.drawCircle(cx + rx * cloudR, cy + nodes[o + 1] * cloudR,
                    dp(size), cloudDot);
        }
        drawRings(canvas, seconds, wake);
    }

    /**
     * The THREE revolving rings: each an ellipse of its own nodes, joined
     * into its polyline, and each drawn behind the next, so the reader
     * sees the orbits cross rather than stack. These complete the owner's
     * count: more lines revolve around the core here than in any pass
     * before this one.
     */
    private void drawRings(Canvas canvas, float seconds, float wake) {
        for (int r = 0; r < RING_NODES.length; r++) {
            int count = RING_NODES[r];
            float radius = ballR * RING_FACTOR[r];
            float speed = RING_SPEED[r];
            float tilt = RING_TILT[r];
            cloudLine.setColor(LINE_INK);
            for (int n = 0; n < count; n++) {
                float a0 = (float) Math.PI * 2f * n / count
                        + seconds * speed;
                float a1 = (float) Math.PI * 2f * (n + 1) / count
                        + seconds * speed;
                float x0 = cx + radius * (float) Math.cos(a0);
                float y0 = cy + radius * tilt * (float) Math.sin(a0);
                float x1 = cx + radius * (float) Math.cos(a1);
                float y1 = cy + radius * tilt * (float) Math.sin(a1);
                // The far half of each ellipse is dimmer: the ring is a
                // flat orbit read in depth, which is its own 3D.
                float mid = (a0 + a1) / 2f;
                float depth = 0.5f + 0.5f * (float) Math.sin(mid);
                cloudLine.setAlpha(Math.min(255,
                        (int) ((40f + 130f * depth) * wake)));
                canvas.drawLine(x0, y0, x1, y1, cloudLine);
                cloudDot.setColor(depth > 0.5f ? NODE_BRIGHT : NODE_DIM);
                cloudDot.setAlpha(Math.min(255, (int) (220f
                        * (0.4f + 0.6f * depth) * wake)));
                canvas.drawCircle(x0, y0, dp(1.6f), cloudDot);
            }
        }
    }

    /**
     * The sun itself: the always-burning mix of its four moods of fire at
     * the small scale. Ball first, breath on top, then granulation, the
     * flame ring, the revolving arcs and the spark cadence.
     */
    private void drawSun(Canvas canvas, float seconds, float wake) {
        sunPaint.setAlpha((int) (230f * wake));
        canvas.drawCircle(cx, cy, ballR, sunPaint);
        // The heart breathes in alpha, never in radius.
        float breath = 0.55f + 0.45f * (float) Math.sin(seconds * 0.9f);
        sunHeart.setAlpha(Math.min(255, (int) (255f * (0.4f
                + 0.6f * breath) * wake)));
        canvas.save();
        canvas.translate(cx - ballR * 0.15f, cy - ballR * 0.18f);
        canvas.drawCircle(0f, 0f, ballR * 0.55f, sunHeart);
        canvas.restore();
        drawCells(canvas, seconds, wake);
        drawFlames(canvas, seconds, wake);
        drawProminences(canvas, seconds, wake);
        drawFlares(canvas, seconds, wake);
    }

    /** The granulation: only the face of the sphere toward the viewer. */
    private void drawCells(Canvas canvas, float seconds, float wake) {
        float yaw = seconds * 0.32f;
        float cosYaw = (float) Math.cos(yaw);
        float sinYaw = (float) Math.sin(yaw);
        for (int c = 0; c < GRANULES; c++) {
            int o = c * GRANULE_STRIDE;
            float x = cells[o];
            float z = cells[o + 2];
            float rx = x * cosYaw + z * sinYaw;
            float rz = -x * sinYaw + z * cosYaw;
            if (rz <= 0.05f) {
                continue;
            }
            float flicker = 0.5f + 0.5f * (float) Math.sin(
                    seconds * cells[o + 5] + cells[o + 4]);
            float radius = cellRadiusBase * cells[o + 3] * (0.5f + 0.5f * rz);
            canvas.save();
            canvas.translate(cx + rx * ballR * 0.78f,
                    cy + cells[o + 1] * ballR * 0.78f);
            sunCell.setAlpha(Math.min(255, (int) (200f * (0.3f + 0.7f
                    * flicker) * wake * rz)));
            canvas.drawCircle(0f, 0f, radius, sunCell);
            canvas.restore();
        }
    }

    /**
     * The limb: flame tongues that always breathe around the burning
     * edge, so the rim is never a perfect circle.
     */
    private void drawFlames(Canvas canvas, float seconds, float wake) {
        for (int f = 0; f < FLAMES; f++) {
            float angle = flameAngle[f] + 0.07f * (float) Math.sin(
                    seconds * flameRate[f] + flamePhase[f]);
            float len = flameLength[f] * (0.55f + 0.55f * (float) Math.sin(
                    seconds * flameRate[f] * 1.7f + flamePhase[f] * 2f));
            if (len < 0.02f) {
                continue;
            }
            canvas.save();
            canvas.translate(cx + ballR * (float) Math.cos(angle),
                    cy + ballR * (float) Math.sin(angle));
            sunFlame.setAlpha(Math.min(255, (int) (170f * (0.4f + 0.6f
                    * len / 0.22f) * wake)));
            canvas.drawCircle(0f, 0f, ballR * len, sunFlame);
            canvas.restore();
        }
    }

    /** The arcs that REVOLVE around the limb on their own slow bearing. */
    private void drawProminences(Canvas canvas, float seconds, float wake) {
        sunProm.setColor(0xFFFFCA66);
        for (int p = 0; p < PROMINENCES; p++) {
            float roll = promAngle[p] + seconds * promSpeed[p];
            float leap = 0.5f + 0.5f * (float) Math.sin(
                    seconds * 0.47f + promPhase[p]);
            float height = promHeight[p] * (0.55f + 0.45f * leap);
            float a0 = roll - promSpread[p] * 0.5f;
            float a1 = roll + promSpread[p] * 0.5f;
            promPath.reset();
            promPath.moveTo(
                    cx + ballR * (float) Math.cos(a0),
                    cy + ballR * (float) Math.sin(a0));
            promPath.quadTo(
                    cx + ballR * (1f + height * 1.6f)
                            * (float) Math.cos(roll),
                    cy + ballR * (1f + height * 1.6f)
                            * (float) Math.sin(roll),
                    cx + ballR * (float) Math.cos(a1),
                    cy + ballR * (float) Math.sin(a1));
            sunProm.setAlpha(Math.min(255, (int) (150f
                    * (0.35f + 0.65f * leap) * wake)));
            canvas.drawPath(promPath, sunProm);
        }
    }

    /**
     * One spark alive almost every second: launches outward on its limb
     * angle once per period, traces its streak, and decays as it falls.
     */
    private void drawFlares(Canvas canvas, float seconds, float wake) {
        for (int s = 0; s < FLARES; s++) {
            float period = flarePeriod[s];
            float t = (seconds + flarePhase[s]) % period;
            if (t > 0.62f) {
                continue;
            }
            float k = t / 0.62f;
            float angle = flareAngle[s] + 0.16f * seconds;
            float dist = ballR * (1.04f + 0.5f * k);
            float fx = cx + dist * (float) Math.cos(angle);
            float fy = cy + dist * (float) Math.sin(angle);
            float fade = 1f - k;
            sunFlare.setAlpha(Math.min(255,
                    (int) (200f * fade * k * wake)));
            canvas.drawLine(
                    fx - ballR * 0.08f * fade * (float) Math.cos(angle),
                    fy - ballR * 0.08f * fade * (float) Math.sin(angle),
                    fx, fy, sunFlare);
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
