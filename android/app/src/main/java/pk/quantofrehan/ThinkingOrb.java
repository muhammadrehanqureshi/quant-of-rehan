package pk.quantofrehan;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.RadialGradient;
import android.graphics.Shader;
import android.util.AttributeSet;
import android.view.View;

/**
 * The thinking orb, owner order 2026-10-22 (second pass).
 *
 * The owner sent the reference look that evening: a black field, a glowing
 * cloud of small points held in clusters by fine links, a bright core that
 * breathes, the whole organism slowly turning. This view draws exactly that,
 * and nothing else: no words, no beam, no second clock on the console.
 *
 * How the picture is built:
 *
 *   - A fixed population of nodes lives in a unit ball, gathered around a
 *     few cluster anchors, so the cloud reads as one organism rather than
 *     static noise. The build is deterministic, so every launch draws the
 *     same organism.
 *   - Links are precomputed once (pairs under a link distance in ball
 *     space, capped) and re-drawn every frame in screen space; a link's
 *     alpha rises toward the core, which gives the heart its bright
 *     filaments and the rim its faint web.
 *   - Each frame rotates the whole cloud rigidly (a slow yaw plus a small
 *     breathing pitch) and projects it with a perspective divide, so the
 *     far side renders smaller and dimmer and the network reads in depth.
 *   - Every node breathes radially on its own phase, and the core is a
 *     one-time radial gradient whose alpha breathes on a slower clock, so
 *     the two rhythms cross and the picture never looks mechanical.
 *
 * The budget: one View, zero relay requests, zero allocations per frame
 * (nodes and link indices are built once in onSizeChanged and reused), and
 * the frame loop is the view's own invalidate pacing at FPS_MS. start() and
 * stop() are the only public controls, wired to MainActivity's startHud and
 * stopHud: a paused console draws nothing at all, and stop() holds the last
 * frame instead of abandoning the view blank.
 *
 * Colours are the reference look's own ice family (a pale near-white for
 * the core, a cold blue for nodes and links), declared here beside the
 * drawing that owns them; the rest of the console stays on the brand
 * palette untouched.
 */
public class ThinkingOrb extends View {

    /** The core's near-white, the lit heart of the cloud. */
    private static final int CORE_COLOR = 0xFFE4F0FF;
    /** The node ink, a cold cloud blue. */
    private static final int NODE_COLOR = 0xFF86AEDC;
    /** The link ink, dimmer than the nodes it joins. */
    private static final int LINK_COLOR = 0xFF3E6E9E;
    /** The dark field the picture sits on. */
    private static final int FIELD_COLOR = 0xFF0B0F16;

    /** The population. Chosen once; more nodes would cost every frame. */
    private static final int NODES = 105;
    /** Cluster anchors the nodes are gathered around. */
    private static final int CLUSTERS = 5;
    /** Per-node pace of the frame loop, aimed at a smooth 30fps. */
    private static final long FPS_MS = 33L;

    private final Paint linkPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint nodePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint corePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    /** The core's own halo: a plain translucent disc, colour set once. */
    private final Paint haloPaint = new Paint(Paint.ANTI_ALIAS_FLAG);

    /**
     * Node geometry, in a unit ball: [0..2] x,y,z; [3] breath phase; [4]
     * shimmer phase. Per-frame screen coordinates and depths are parallel
     * arrays rebuilt in place, so no allocation ever lands on the frame.
     */
    private final float[] cloud = new float[NODES * 5];
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

    private float orbRadius;
    private float nodeRadius;
    private float linkWidth;
    private float coreRadius;
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
        orbRadius = Math.min(w, h) / 2f - dp(6f);
        nodeRadius = dp(1.3f);
        linkWidth = Math.max(1f, dp(0.9f));
        coreRadius = orbRadius * 0.17f;
        corePaint.setShader(new RadialGradient(
                w / 2f, h / 2f, coreRadius * 3f, new int[]{
                CORE_COLOR, withAlpha(CORE_COLOR, 0x40), 0x00E4F0FF},
                new float[]{0f, 0.35f, 1f}, Shader.TileMode.CLAMP));
        geometryBuilt = true;
    }

    /**
     * One full build of the cloud: cluster anchors, node placement, link
     * list. Ran once per size; never on the frame path.
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
            // Anchors sit between heart and shell, reachable by links.
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
            int o = n * 5;
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
                float dx = cloud[i * 5] - cloud[j * 5];
                float dy = cloud[i * 5 + 1] - cloud[j * 5 + 1];
                float dz = cloud[i * 5 + 2] - cloud[j * 5 + 2];
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
        float yaw = seconds * 0.22f;
        float pitch = 0.16f * (float) Math.sin(seconds * 0.13);
        float cosYaw = (float) Math.cos(yaw);
        float sinYaw = (float) Math.sin(yaw);
        float cosPitch = (float) Math.cos(pitch);
        float sinPitch = (float) Math.sin(pitch);
        float cloudBreath = 1f + 0.035f * (float) Math.sin(seconds * 0.55f);
        float coreBreath = 0.55f + 0.45f * (float) Math.sin(seconds * 0.9f);
        // Wake over the first four seconds of a run, so the organism grows
        // out of the dark instead of popping in.
        float wake = Math.min(1f, seconds / 4f);

        canvas.drawColor(FIELD_COLOR);

        float distance = orbRadius * 2.8f;
        for (int n = 0; n < NODES; n++) {
            int o = n * 5;
            float breathe = 1f + 0.06f * (float) Math.sin(
                    seconds * 0.8f + cloud[o + 3]);
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
            linkPaint.setARGB(Math.min(255, alpha),
                    Color.red(LINK_COLOR), Color.green(LINK_COLOR),
                    Color.blue(LINK_COLOR));
            linkPaint.setStrokeWidth(linkWidth * (0.7f + 0.6f * toward));
            canvas.drawLine(screenX[a], screenY[a], screenX[b], screenY[b],
                    linkPaint);
        }
        for (int n = 0; n < NODES; n++) {
            int o = n * 5;
            float toward = clamp((depth[n] - 1f) / 0.6f, 0f, 1f);
            float shimmer = 0.8f + 0.2f * (float) Math.sin(
                    seconds * 1.4f + cloud[o + 4]);
            float size = nodeRadius * (0.6f + 0.9f * toward) * shimmer;
            int alpha = (int) ((40f + 170f * toward) * wake);
            nodePaint.setARGB(Math.min(255, alpha),
                    Color.red(NODE_COLOR), Color.green(NODE_COLOR),
                    Color.blue(NODE_COLOR));
            canvas.drawCircle(screenX[n], screenY[n], size, nodePaint);
        }
        haloPaint.setColor(withAlpha(CORE_COLOR, 255));
        corePaint.setAlpha((int) (255f * coreBreath * wake));
        canvas.drawCircle(cx, cy, coreRadius * 3f, corePaint);
        // The halo: one plain translucent disc the core sits in, no blur
        // filter (a BlurMaskFilter is a no-op under hardware acceleration
        // and a software layer for one circle is not worth the bitmap).
        haloPaint.setAlpha((int) (70f * wake));
        canvas.drawCircle(cx, cy, coreRadius * 1.5f, haloPaint);
        postInvalidateOnAnimation();
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

    private static int withAlpha(int color, int alpha) {
        return Color.argb(alpha, Color.red(color), Color.green(color),
                Color.blue(color));
    }

    /** The pair cap: O(N^2) once at build, never on the frame path. */
    private static int linkBudget() {
        return NODES * 4;
    }

    private float dp(float dp) {
        return dp * getResources().getDisplayMetrics().density;
    }
}
