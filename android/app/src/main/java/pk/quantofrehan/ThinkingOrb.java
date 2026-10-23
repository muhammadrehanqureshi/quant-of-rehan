package pk.quantofrehan;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RadialGradient;
import android.graphics.Shader;
import android.util.AttributeSet;
import android.view.View;

/**
 * The thinking orb, owner order 2026-10-23 (v2.2.0, seventh pass).
 *
 * The owner sent the v2.1.0 screenshots back with one sentence and one
 * correction: "have a look at the 1.8.7 build I think that was the correct
 * one, but you will also need to change the ORB, I want the center as the
 * sun." The feature is therefore the v1.8.9 LIVING PARTICLE CLOUD again -
 * the reference look the owner first approved, the organism that breathed,
 * turned in depth and held itself together: 105 nodes gathered around five
 * cluster anchors, joined by fine links, drawn in the ice family, projected
 * in perspective so the far side renders smaller and dimmer, every node
 * breathing radially on its own phase while the cloud turns. The radial
 * burst of v2.1.0 and the rings of v1.9.13/v1.9.14 are retired; the scattered
 * excesses the later passes grew around the cloud go with them.
 *
 * "I want the center as the sun": the cloud's old breathing core gradient is
 * replaced by the ALWAYS-BURNING SUN v1.9.9 built and v1.9.14 made hotter -
 * the same 3D ball with its convection cells, flame tongues, revolving
 * prominence arcs and the spark cadence, drawn at the cloud's own centre,
 * so the organism circles a star instead of a light.
 *
 * The park law of v1.9.14 stands: stop() freezes the pose the loop last
 * DREW and the parked frame REPAINTS it fully awake, so a closed market, a
 * break, a theme repaint or a layout pass can never blank the feature; the
 * loop only stops MOVING. A resume replays from the frozen second.
 *
 * The budget is the one that survived every pass: one View, zero relay
 * requests, zero allocations per frame - the cloud's nodes and links and
 * the sun's cells, flames, prominences and flares are all built once in
 * onSizeChanged, and every frame touches preallocated arrays. The frame
 * loop is the view's own paced invalidate at FPS_MS; start() and stop()
 * stay the only public controls, wired to MainActivity's startHud and
 * stopHud behind the market gate.
 */

public class ThinkingOrb extends View {

    /** The population. Chosen once; more nodes would cost every frame. */
    private static final int NODES = 105;
    /** Cluster anchors the nodes are gathered around. */
    private static final int CLUSTERS = 5;
    /** Per-node slots in the cloud[] record: x, y, z, breath, shimmer. */
    private static final int NODE_STRIDE = 5;
    /** Per-node pace of the frame loop, aimed at a smooth 30fps. */
    private static final long FPS_MS = 33L;

    /**
     * The wake ramp: four seconds, so the organism grows out of the dark
     * instead of popping in (v1.8.9's own number).
     */
    private static final float WAKE_SECONDS = 4f;

    /**
     * The pose a parked view shows when the loop never reached a frame
     * (a console that resumed straight onto a closed market): two
     * seconds in, past the wake ramp, fully lit and still.
     */
    private static final float PARKED_SECONDS = 2.0f;

    /**
     * Every turning, breathing, shimmering rate carries the owner's 30%
     * speed order of v1.9.5: one named constant, so the pace is one
     * decision rather than a factor copied into five places.
     */
    private static final float MOTION_SCALE = 1.3f;

    /** The node ink, a cold cloud blue. */
    private static final int NODE_COLOR = 0xFF86AEDC;
    /** The link ink, dimmer than the nodes it joins. */
    private static final int LINK_COLOR = 0xFF3E6E9E;

    private final Paint linkPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint nodePaint = new Paint(Paint.ANTI_ALIAS_FLAG);

    /** The sun's own fire (kept from v1.9.14): its six painters. */
    private final Paint sunPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint sunHeart = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint sunCell = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint sunFlame = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint sunProm = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint sunFlare = new Paint(Paint.ANTI_ALIAS_FLAG);

    /** The one Path the prominence arcs share; reset, never reallocated. */
    private final Path promPath = new Path();

    /** The sun's granulation: unit position, size, phase, rate. */
    private static final int GRANULES = 10;
    private static final int GRANULE_STRIDE = 6;
    private final float[] cells = new float[GRANULES * GRANULE_STRIDE];

    /** Flame tongues around the limb: angle, length, phase, rate. */
    private static final int FLAMES = 12;
    private final float[] flameAngle = new float[FLAMES];
    private final float[] flameLength = new float[FLAMES];
    private final float[] flamePhase = new float[FLAMES];
    private final float[] flameRate = new float[FLAMES];

    /** Revolving prominence arcs: angle, spread, height, phase, speed. */
    private static final int PROMINENCES = 8;
    private final float[] promAngle = new float[PROMINENCES];
    private final float[] promSpread = new float[PROMINENCES];
    private final float[] promHeight = new float[PROMINENCES];
    private final float[] promPhase = new float[PROMINENCES];
    private final float[] promSpeed = new float[PROMINENCES];

    /** Flare sparks: angle, period (the seconds cadence), phase. */
    private static final int FLARES = 7;
    private final float[] flareAngle = new float[FLARES];
    private final float[] flarePeriod = new float[FLARES];
    private final float[] flarePhase = new float[FLARES];

    /**
     * Node geometry, in a unit ball: [0..2] x,y,z; [3] breath phase; [4]
     * shimmer phase. Per-frame screen coordinates and depths are parallel
     * arrays rebuilt in place, so no allocation ever lands on the frame.
     */
    private final float[] cloud = new float[NODES * NODE_STRIDE];
    private final float[] screenX = new float[NODES];
    private final float[] screenY = new float[NODES];
    private final float[] depth = new float[NODES];
    /** Link bookkeeping, capped by budget; triples in (a, b, distance). */
    private final int[] linkA = new int[linkBudget()];
    private final int[] linkB = new int[linkBudget()];
    private final float[] linkDist = new float[linkBudget()];
    private int linkCount;

    private long clockAnchor;
    private long lastFrameAt = -1;
    private boolean running;
    private boolean built;

    private float cx;
    private float cy;
    private float orbRadius;
    /** The sun's own ball, at the cloud's centre. */
    private float ballR;
    private float nodeRadius;
    private float linkWidth;
    private float cellRadiusBase;

    /**
     * The clock the frame loop reads, in seconds, so a parked frame can
     * be REPAINTED at exactly the pose it froze on (v1.9.14): park no
     * longer blanks, and resume continues from the frozen second instead
     * of restarting the wake ramp.
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
     * frozen second, so the picture neither blanks nor restarts its wake.
     */
    public void start() {
        if (running) {
            return;
        }
        running = true;
        if (frozenSeconds >= 0f) {
            clockAnchor = System.currentTimeMillis()
                    - (long) (frozenSeconds * 1000f);
        } else {
            clockAnchor = System.currentTimeMillis();
        }
        lastFrameAt = -1;
        postInvalidateOnAnimation();
    }

    /**
     * Parks the loop, holding the pose the loop last DREW, so a closed
     * market still shows one burning sun inside a still cloud: no motion
     * claims the session is live (SO-3). The parked pose is repainted
     * (not merely left) whenever anything invalidates the view.
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
        orbRadius = Math.min(w, h) / 2f - dp(6f);
        // The sun is the cloud's own core: the old breathing heart's
        // radius, now a BALL that burns instead of a gradient that fades.
        ballR = orbRadius * 0.17f;
        nodeRadius = dp(1.3f);
        linkWidth = Math.max(1f, dp(0.9f));
        cellRadiusBase = dp(6f);
        clockAnchor = System.currentTimeMillis();
        buildGeometry();
        buildSun();
        buildInks();
        built = true;
        // The picture exists the moment the size exists; never count on a
        // later invalidation to introduce it.
        invalidate();
    }

    /**
     * One full build of the cloud (v1.8.9 kept): cluster anchors, node
     * placement, link list. Runs once per size; never on the frame path.
     */
    private void buildGeometry() {
        long seed = 20261022L;
        float[] anchorX = new float[CLUSTERS];
        float[] anchorY = new float[CLUSTERS];
        float[] anchorZ = new float[CLUSTERS];
        for (int c = 0; c < CLUSTERS; c++) {
            seed = nextSeed(seed);
            float u = frac(seed) * 2f - 1f;
            seed = nextSeed(seed);
            float theta = frac(seed) * (float) Math.PI * 2f;
            float s = (float) Math.sqrt(1f - u * u);
            // Anchors sit between the sun and the shell, reachable by links.
            anchorX[c] = s * (float) Math.cos(theta) * 0.55f;
            anchorY[c] = u * 0.55f;
            anchorZ[c] = s * (float) Math.sin(theta) * 0.55f;
        }
        for (int n = 0; n < NODES; n++) {
            int anchor = n % CLUSTERS;
            seed = nextSeed(seed);
            float jitter1 = frac(seed) * 2f - 1f;
            seed = nextSeed(seed);
            float jitter2 = frac(seed) * 2f - 1f;
            seed = nextSeed(seed);
            float jitter3 = frac(seed) * 2f - 1f;
            // Pull toward the anchor, then relax outward; most nodes hug a
            // cluster, the rest scatter into the halo between anchors.
            float x = anchorX[anchor] + jitter1 * 0.42f;
            float y = anchorY[anchor] + jitter2 * 0.42f;
            float z = anchorZ[anchor] + jitter3 * 0.42f;
            float length = (float) Math.sqrt(x * x + y * y + z * z);
            float pulled = (n % 4 == 0) ? 1.05f : 0.78f;
            float scale = pulled / Math.max(length, 0.01f);
            x *= scale;
            y *= scale;
            z *= scale;
            // A few escapees sit well outside the clusters, for the cloud's
            // ragged rim the reference picture carries.
            if (n % 9 == 0) {
                x *= 1.25f;
                y *= 1.25f;
                z *= 1.25f;
            }
            int o = n * NODE_STRIDE;
            cloud[o] = clampAbs(x, 0.97f);
            cloud[o + 1] = clampAbs(y, 0.97f);
            cloud[o + 2] = clampAbs(z, 0.97f);
            cloud[o + 3] = n * 0.7f;
            cloud[o + 4] = n * 1.9f;
        }
        float linkAt = 0.55f;
        linkCount = 0;
        for (int i = 0; i < NODES && linkCount < linkBudget(); i++) {
            for (int j = i + 1; j < NODES && linkCount < linkBudget(); j++) {
                float dx = cloud[i * NODE_STRIDE] - cloud[j * NODE_STRIDE];
                float dy = cloud[i * NODE_STRIDE + 1] - cloud[j * NODE_STRIDE + 1];
                float dz = cloud[i * NODE_STRIDE + 2] - cloud[j * NODE_STRIDE + 2];
                float dist = (float) Math.sqrt(dx * dx + dy * dy + dz * dz);
                if (dist <= linkAt) {
                    linkA[linkCount] = i;
                    linkB[linkCount] = j;
                    linkDist[linkCount] = dist;
                    linkCount++;
                }
            }
        }
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
            seed = nextSeed(seed);
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

    /** The paints and the one shader family the sun keeps by its builder. */
    private void buildInks() {
        linkPaint.setStyle(Paint.Style.STROKE);
        linkPaint.setStrokeCap(Paint.Cap.ROUND);
        linkPaint.setColor(LINK_COLOR);
        nodePaint.setStyle(Paint.Style.FILL);
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
        sunProm.setColor(0xFFFFCA66);

        sunFlare.setColor(0xFFF9E8C8);
        sunFlare.setStrokeCap(Paint.Cap.ROUND);
        sunFlare.setStrokeWidth(dp(1.8f));
    }

    @Override
    protected void onDraw(Canvas canvas) {
        if (!built) {
            // A view without a size yet cannot draw its scene; ask again
            // rather than leave the station blank (the owner's screenshots
            // of 2026-10-23 read exactly like a paint that never came).
            requestLayout();
            postInvalidateOnAnimation();
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

    /** One full picture: the living cloud around its burning sun. */
    private void drawScene(Canvas canvas, float seconds, float wake) {
        drawCloud(canvas, seconds, wake);
        drawSun(canvas, seconds, wake);
    }

    /**
     * The cloud, v1.8.9 kept: rigid yaw around the vertical plus a small
     * breathing pitch, projected with a perspective divide, links first
     * (brighter as their ends come forward), nodes after. The sun draws
     * after it, so the organism reads as circling its star.
     */
    private void drawCloud(Canvas canvas, float seconds, float wake) {
        float yaw = seconds * 0.22f * MOTION_SCALE;
        float pitch = 0.16f * (float) Math.sin(seconds * 0.13 * MOTION_SCALE);
        float cosYaw = (float) Math.cos(yaw);
        float sinYaw = (float) Math.sin(yaw);
        float cosPitch = (float) Math.cos(pitch);
        float sinPitch = (float) Math.sin(pitch);
        float cloudBreath = 1f + 0.035f * (float) Math.sin(seconds * 0.55f);
        float distance = orbRadius * 2.8f;
        for (int n = 0; n < NODES; n++) {
            int o = n * NODE_STRIDE;
            float breathe = 1f + 0.06f * (float) Math.sin(
                    seconds * 0.8f * MOTION_SCALE + cloud[o + 3]);
            float x = cloud[o] * cloudBreath * breathe;
            float y = cloud[o + 1] * cloudBreath * breathe;
            float z = cloud[o + 2] * cloudBreath * breathe;
            // Rigid yaw around the vertical, then a small breathing pitch.
            float rx = x * cosYaw + z * sinYaw;
            float rz = -x * sinYaw + z * cosYaw;
            float ry = y * cosPitch - rz * sinPitch;
            rz = y * sinPitch + rz * cosPitch;
            float persp = distance / (distance - rz * orbRadius);
            depth[n] = persp;
            screenX[n] = cx + rx * orbRadius * persp;
            screenY[n] = cy + ry * orbRadius * persp;
        }
        for (int l = 0; l < linkCount; l++) {
            int a = linkA[l];
            int b = linkB[l];
            float midway = (depth[a] + depth[b]) / 2f;
            // Perspective divide reading > 1 means this side is near the
            // viewer, so filaments brighten as their ends come forward.
            float toward = clamp((midway - 1f) / 0.6f, 0f, 1f)
                    * linkFade(linkDist[l]);
            int alpha = (int) ((16f + 96f * toward) * wake);
            linkPaint.setAlpha(Math.min(255, alpha));
            linkPaint.setStrokeWidth(linkWidth * (0.7f + 0.6f * toward));
            canvas.drawLine(screenX[a], screenY[a], screenX[b], screenY[b],
                    linkPaint);
        }
        for (int n = 0; n < NODES; n++) {
            int o = n * NODE_STRIDE;
            float toward = clamp((depth[n] - 1f) / 0.6f, 0f, 1f);
            float shimmer = 0.8f + 0.2f * (float) Math.sin(
                    seconds * 1.4f * MOTION_SCALE + cloud[o + 4]);
            float size = nodeRadius * (0.6f + 0.9f * toward) * shimmer;
            int alpha = (int) ((40f + 170f * toward) * wake);
            nodePaint.setAlpha(Math.min(255, alpha));
            nodePaint.setColor(NODE_COLOR);
            canvas.drawCircle(screenX[n], screenY[n], size, nodePaint);
        }
    }

    /**
     * The sun itself (v1.9.14 kept): the always-burning mix of its four
     * moods of fire at the cloud's centre. Ball first, breath on top,
     * then granulation, the flame ring, the revolving arcs and the spark
     * cadence. Its rates ride MOTION_SCALE with the cloud, so one body
     * keeps one clock.
     */
    private void drawSun(Canvas canvas, float seconds, float wake) {
        sunPaint.setAlpha((int) (255f * wake));
        canvas.drawCircle(cx, cy, ballR, sunPaint);
        // The heart breathes in alpha, never in radius.
        float breath = 0.55f + 0.45f * (float) Math.sin(
                seconds * 0.9f * MOTION_SCALE);
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
        float yaw = seconds * 0.45f * MOTION_SCALE;
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
                    seconds * cells[o + 5] * MOTION_SCALE + cells[o + 4]);
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
                    seconds * flameRate[f] * MOTION_SCALE + flamePhase[f]);
            float len = flameLength[f] * (0.55f + 0.55f * (float) Math.sin(
                    seconds * flameRate[f] * 1.7f * MOTION_SCALE
                            + flamePhase[f] * 2f));
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
        for (int p = 0; p < PROMINENCES; p++) {
            float roll = promAngle[p]
                    + seconds * promSpeed[p] * MOTION_SCALE;
            float leap = 0.5f + 0.5f * (float) Math.sin(
                    seconds * 0.47f * MOTION_SCALE + promPhase[p]);
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

    private float linkFade(float dist) {
        return 1f - clamp((dist - 0.18f) / 0.37f, 0f, 1f);
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

    private static float clampAbs(float v, float limit) {
        return v > limit ? limit : (v < -limit ? -limit : v);
    }

    private static float clamp(float v, float lo, float hi) {
        return v < lo ? lo : (v > hi ? hi : v);
    }

    /** The pair cap: O(N^2) once at build, never on the frame path. */
    private static int linkBudget() {
        return NODES * 4;
    }

    private float dp(float dp) {
        return dp * getResources().getDisplayMetrics().density;
    }
}
