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
 * The quant's own look, owner order 2026-10-23 (sixth pass, v2.1.0).
 *
 * The owner sent the reference screenshot back with this order: the feature
 * is a RADIAL BURST, spokes of icy lines shot out from the core in every
 * direction, each spoke carrying its own run of dots, the tips lit
 * brightest, a faint web joining the spokes near the core - the whole body
 * of it slowly revolving. The rings of v1.9.13/v1.9.14 and the scattered
 * lopsided cloud before them are retired in favour of exactly that
 * picture.
 *
 * "But with sun as the core": the centre is the same always-burning sun
 * v1.9.9 built and v1.9.14 made hotter (a lit 3D ball, granulation on its
 * face, flame tongues on its limb, revolving prominence arcs, a spark
 * alive almost every second). The burst does not replace the sun; it
 * RADIATES from it, and the grey rest ring of the older reference is gone
 * because the new reference's core is the star itself.
 *
 * How the picture is built, exactly two layers:
 *
 *   - The burst: RAYS spokes, evenly spread around the core with a small
 *     deterministic jitter per spoke. Each spoke is a polyline of
 *     RAY_NODES nodes from just outside the sun's limb out to the rim, its
 *     radii spaced so the spokes bunch near the core the way the reference
 *     does, its tip the largest and brightest node. A capped web joins
 *     neighbouring spokes' inner nodes to each other, which is what reads
 *     as the "structure" around the core. The whole burst revolves as ONE
 *     body around the sun, which is the reference's own orbit.
 *   - The sun: unchanged from v1.9.14, at a tenth of the box's short side,
 *     burning without pause, awake or parked.
 *
 * The feature stops when the market stops (owner order 2026-10-23): the
 * market gate is the ON badge's own boolean in MainActivity, the same
 * knowledge the status dot uses, so the view is ordered stop() whenever
 * the relay reports the session closed or on a break, and start() again
 * the moment it trades. stop() parks the loop and holds the last frame,
 * so a closed market shows one still burning sun inside a still burst: no
 * motion claims the session is live (SO-3), and the picture never blanks.
 *
 * The budget is the budget that survived every pass: one View, zero relay
 * requests, zero allocations per frame (the burst's nodes and edges, the
 * cells, flames, prominences and sparks are built once in onSizeChanged
 * and every draw touches preallocated arrays), and the frame loop is the
 * view's own paced invalidate at FPS_MS. start() and stop() stay the only
 * public controls, wired to MainActivity's startHud and stopHud.
 */

public class ThinkingOrb extends View {

    /** The spokes of the burst: more lines around the core than ever. */
    private static final int RAYS = 22;
    /** Nodes per spoke, from the limb to the rim. */
    private static final int RAY_NODES = 5;
    /** Node count the arrays are sized for: every spoke's every node. */
    private static final int NODES = RAYS * RAY_NODES;
    /** x, y, z (unit sphere scaled by radius frac), size, twinkle phase. */
    private static final int NODE_STRIDE = 5;
    /** One mesh edge's two node indices; built here, read on the frame. */
    private static final int EDGE_STRIDE = 2;

    /**
     * Each spoke's radii, in fractions of the burst radius, bunched near
     * the core and stretched at the rim (the reference's own density).
     */
    private static final float[] RAY_FRACTION = {0.16f, 0.30f, 0.46f, 0.64f, 0.88f};

    /** The index past which a node joins the cross-spoke web (inner half). */
    private static final int WEB_TO_INDEX = 3;

    /** The maximum unit distance two inner nodes may keep to be joined. */
    private static final float LINK_DIST = 0.34f;
    /** The cross-web cap on connections at one node, so no over-draw. */
    private static final int LINK_MAX = 2;

    private static final int GRANULES = 10;
    private static final int GRANULE_STRIDE = 6;
    private static final int FLAMES = 12;
    private static final int PROMINENCES = 8;
    private static final int FLARES = 7;

    /** Pacing of the frame loop, aimed at a smooth 30fps. */
    private static final long FPS_MS = 33L;

    /** The wake ramp: 1.2 seconds, so the sun is up when the owner looks. */
    private static final float WAKE_SECONDS = 1.2f;

    /**
     * The pose a parked view shows when the loop never reached a frame
     * (a console that resumed straight onto a closed market): two
     * seconds in, past the wake ramp, fully lit and still.
     */
    private static final float PARKED_SECONDS = 2.0f;

    // The fixed inks of the burst, ice on the deep field.
    private static final int NODE_BRIGHT = 0xFFEAF3FF;
    private static final int NODE_DIM = 0xFFA9BBD6;
    private static final int LINE_INK = 0xFF9CB8DE;

    private final Paint burstDot = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint burstHalo = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint burstLine = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint sunPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint sunHeart = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint sunCell = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint sunFlame = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint sunProm = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint sunFlare = new Paint(Paint.ANTI_ALIAS_FLAG);

    /** The one Path the prominence arcs share; reset, never reallocated. */
    private final Path promPath = new Path();

    private float cx;
    private float cy;
    private float ballR;
    private float burstR;
    private float cellRadiusBase;

    /**
     * Burst nodes: unit sphere position scaled by each node's own radius
     * fraction, plus size and twinkle phase, all built once. Edges are
     * the two node indices per line: the spokes first, then the web.
     */
    private final float[] nodes = new float[NODES * NODE_STRIDE];
    private final int[] edges = new int[(RAYS * (RAY_NODES - 1)
            + NODES * LINK_MAX) * EDGE_STRIDE];
    private int edgeCount;
    /** The index where the spoke polylines end and the web begins. */
    private int spokeEdgeCount;

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

    /**
     * The clock the frame loop reads, in seconds, so a parked frame can
     * be REPAINTED at exactly the pose it froze on (fifth pass,
     * v1.9.14): park no longer blanks, and resume continues from the
     * frozen second instead of restarting the wake ramp.
     */
    private float lastSeconds;
    private float frozenSeconds = -1f;

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
     * Starts the frame loop; a second call while running is a no-op.
     * The clock is NOT reset: a resume after a park replays from the
     * frozen second, so the sun neither blanks nor restarts its wake.
     */
    public void start() {
        if (running) {
            return;
        }
        running = true;
        if (frozenSeconds >= 0f) {
            clockAnchor = System.currentTimeMillis()
                    - (long) (frozenSeconds * 1000f);
        }
        lastFrameAt = -1;
        postInvalidateOnAnimation();
    }

    /**
     * Parks the loop, holding the pose the loop last DREW. The parked
     * pose is repainted (not merely left) whenever anything invalidates
     * the view, which is what keeps a theme paint, a layout pass or a
     * closed market from ever blanking the feature.
     */
    public void stop() {
        if (!running) {
            return;
        }
        running = false;
        frozenSeconds = lastSeconds;
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
        // The reference's proportions and the fifth pass's own: the burst
        // fills the box the old cloud openned (three tenths of the short
        // side) plus the rim the tips carry, and the BALL stays at a
        // tenth of the short side, the sun the owner fixed at v1.9.14.
        float shortSide = Math.min(w, h);
        ballR = shortSide * 0.10f;
        burstR = shortSide * 0.34f;
        cellRadiusBase = dp(6f);
        clockAnchor = System.currentTimeMillis();
        buildBurst();
        buildSun();
        buildInks();
        built = true;
    }

    /**
     * One full build of the deterministic geometry: the radial burst of
     * spokes and its inner web (capped so no node over-connects) and the
     * sun's fire. Runs once per size; never on the frame path.
     */
    private void buildBurst() {
        long seed = 20261023L;
        for (int r = 0; r < RAYS; r++) {
            // The spoke's own bearing, evenly spread, then joggled once so
            // the burst never reads as a mechanical radial chart.
            seed = nextSeed(seed);
            float jitter = (frac(seed) * 2f - 1f) * 0.34f
                    * ((float) Math.PI * 2f / RAYS);
            float base = (float) Math.PI * 2f * r / RAYS + jitter;
            for (int n = 0; n < RAY_NODES; n++) {
                int index = r * RAY_NODES + n;
                // Inner nodes sit near their spoke's line; outwards, the
                // spoke fans slightly, the way the reference's spokes
                // splinter at the rim.
                seed = nextSeed(seed);
                float fan = (frac(seed) * 2f - 1f) * 0.04f * n;
                float angle = base + fan;
                seed = nextSeed(seed);
                float radius = RAY_FRACTION[n]
                        * (0.92f + frac(seed) * 0.16f);
                seed = nextSeed(seed);
                // Tip nodes are the reference's brightest stars; inner
                // ones are the smaller beads.
                float size = n == RAY_NODES - 1 ? 2.6f : 0.9f + 1.1f * n / RAY_NODES;
                seed = nextSeed(seed);
                float twinkle = frac(seed) * 2f - 1f;
                int o = index * NODE_STRIDE;
                nodes[o] = (float) Math.cos(angle) * radius;
                // The burst is a shallow sphere around the core, so the
                // revolution gives it depth without ever swallowing the
                // sun: the circle is squashed in y and given a small z.
                nodes[o + 1] = (float) Math.sin(angle) * radius * 0.94f;
                nodes[o + 2] = 0.30f * radius;
                nodes[o + 3] = size;
                nodes[o + 4] = twinkle;
            }
        }
        // The spokes first: each ray's polyline, limb to rim.
        edgeCount = 0;
        for (int r = 0; r < RAYS; r++) {
            for (int n = 0; n < RAY_NODES - 1; n++) {
                edges[edgeCount++] = r * RAY_NODES + n;
                edges[edgeCount++] = r * RAY_NODES + n + 1;
            }
        }
        spokeEdgeCount = edgeCount;
        // The web: inner nodes of neighbouring spokes, distances decide,
        // the cap keeps any one bead from gathering all of them.
        for (int i = 0; i < NODES; i++) {
            int drawn = 0;
            for (int j = i + 1; j < NODES && drawn < LINK_MAX; j++) {
                if (indexOnSpoke(i) >= WEB_TO_INDEX
                        || indexOnSpoke(j) >= WEB_TO_INDEX) {
                    continue;
                }
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

    /** Which node of its own spoke a node index is (0 = innermost). */
    private static int indexOnSpoke(int index) {
        return index % RAY_NODES;
    }

    /** The sun's fire: cells, flames, prominences, sparks (v1.9.14 kept). */
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
            promSpeed[p] = 0.18f + frac(seed) * 0.12f;
        }
        for (int s = 0; s < FLARES; s++) {
            seed = nextSeed(seed);
            flareAngle[s] = frac(seed) * (float) Math.PI * 2f;
            seed = nextSeed(seed);
            flarePeriod[s] = 0.7f + frac(seed) * 0.5f;
            seed = nextSeed(seed);
            flarePhase[s] = frac(seed) * flarePeriod[s];
        }
    }

    /** The paints and the one shader the sun keeps by its builder. */
    private void buildInks() {
        burstDot.setStyle(Paint.Style.FILL);
        burstLine.setStyle(Paint.Style.STROKE);
        burstLine.setStrokeWidth(dp(1.2f));
        burstLine.setStrokeCap(Paint.Cap.ROUND);

        // The tips' halo: one soft disc under each tip dot, the icy glow
        // the reference's stars read through.
        burstHalo.setStyle(Paint.Style.FILL);
        burstHalo.setColor(0xFF9CB8DE);

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
    }

    @Override
    protected void onDraw(Canvas canvas) {
        if (!built) {
            return;
        }
        if (!running) {
            // Parked (v1.9.14, kept): the view REPAINTS the pose the loop
            // froze on, fully awake, so a theme repaint, a layout pass or
            // a closed market can never blank it. It stops moving and
            // stays exactly as seen, and schedules nothing.
            drawScene(canvas, frozenSeconds >= 0f ? frozenSeconds
                    : PARKED_SECONDS, 1f);
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
        lastSeconds = seconds;
        drawScene(canvas, seconds, wake);
        postInvalidateOnAnimation();
    }

    /** One full picture: the revolving burst and the sun it radiates. */
    private void drawScene(Canvas canvas, float seconds, float wake) {
        drawBurst(canvas, seconds, wake);
        drawSun(canvas, seconds, wake);
    }

    /**
     * The burst, ONE body revolving around the core: single yaw on every
     * node, so the spokes' shape is kept by the frame. spokes first (line
     * colour set once for the whole pass, alpha per segment by depth),
     * then the web, then the dots; tips last so their halo reads on top.
     */
    private void drawBurst(Canvas canvas, float seconds, float wake) {
        float yaw = seconds * 0.13f;
        float cosYaw = (float) Math.cos(yaw);
        float sinYaw = (float) Math.sin(yaw);
        burstLine.setColor(LINE_INK);
        // Lines first, in one pass over the pairs: spokes then web, the
        // alpha of each line by its mean depth, near brighter.
        for (int e = 0; e < edgeCount; e += EDGE_STRIDE) {
            int i = edges[e];
            int j = edges[e + 1];
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
            boolean spoke = e < spokeEdgeCount;
            int alpha = (int) ((spoke ? 0.62f : 0.34f)
                    * (0.55f + 0.45f * depth) * 235f * wake);
            burstLine.setAlpha(Math.max(0, Math.min(255, alpha)));
            canvas.drawLine(cx + fx * burstR, cy + nodes[oi + 1] * burstR,
                    cx + gx * burstR, cy + nodes[oj + 1] * burstR, burstLine);
        }
        // Dots, tips after all others so the halos never fall under a line.
        for (int pass = 0; pass < 2; pass++) {
            for (int n = 0; n < NODES; n++) {
                boolean isTip = indexOnSpoke(n) == RAY_NODES - 1;
                if (pass == 0 && isTip) {
                    continue;
                }
                if (pass == 1) {
                    if (!isTip) {
                        continue;
                    }
                    // The halo under the tip: a soft disc of the line ink.
                    int oi = n * NODE_STRIDE;
                    float x = nodes[oi];
                    float z = nodes[oi + 2];
                    float rx = x * cosYaw + z * sinYaw;
                    burstHalo.setAlpha(Math.min(255,
                            (int) (60f * wake)));
                    canvas.drawCircle(cx + rx * burstR,
                            cy + nodes[oi + 1] * burstR, dp(5.5f), burstHalo);
                }
                drawBurstDot(canvas, n, cosYaw, sinYaw, wake);
            }
        }
    }

    /** One node's own dot: twinkle on the shared turn, size by depth. */
    private void drawBurstDot(Canvas canvas, int n, float cosYaw,
                              float sinYaw, float wake) {
        int o = n * NODE_STRIDE;
        float x = nodes[o];
        float z = nodes[o + 2];
        float rx = x * cosYaw + z * sinYaw;
        float rz = -x * sinYaw + z * cosYaw;
        boolean tip = indexOnSpoke(n) == RAY_NODES - 1;
        float baseSize = nodes[o + 3] * (tip ? 1f : (0.6f + 0.4f * (rz + 1f) / 2f));
        float twinkle = 0.7f + 0.3f
                * (float) Math.sin(secondsFor(n) + nodes[o + 4] * 3f);
        float size = baseSize * twinkle * (0.65f + 0.35f * (rz + 1f) / 2f);
        burstDot.setColor(rz > -0.1f ? NODE_BRIGHT : NODE_DIM);
        burstDot.setAlpha(Math.min(255, (int) (255f * wake
                * (tip ? 0.85f : 0.42f) * (0.5f + 0.5f * (rz + 1f) / 2f))));
        canvas.drawCircle(cx + rx * burstR, cy + nodes[o + 1] * burstR,
                dp(size), burstDot);
    }

    /** A per-node tick source for the twinkle, from the shared clock. */
    private float secondsFor(int n) {
        return lastSeconds * (0.8f + 0.35f * (n % 7));
    }

    /**
     * The sun itself: the always-burning mix of its four moods of fire at
     * the small scale. Ball first, breath on top, then granulation, the
     * flame ring, the revolving arcs and the spark cadence.
     */
    private void drawSun(Canvas canvas, float seconds, float wake) {
        sunPaint.setAlpha((int) (255f * wake));
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
        float yaw = seconds * 0.45f;
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
            sunProm.setAlpha(Math.min(255, (int) (185f
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
                    (int) (230f * fade * k * wake)));
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
