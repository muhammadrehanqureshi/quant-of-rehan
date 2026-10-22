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
 * Owner order 2026-10-22 (v1.9.5): the organism is more advanced. The whole
 * cloud moves at 30% more speed (MOTION_SCALE carries the owner's number so
 * it is one decision, not ten), the organism THINKS CONTINUOUSLY - every
 * node wanders its own slow orbit and a travelling spark runs the links,
 * so the cloud is never still between turns - and the nucleus is layered:
 * a breathing heart, an out-of-phase halo, a thin ring and a ring of
 * orbiting sparks, so the centre reads as an engine, not one disc.
 *
 * Owner order 2026-10-22 (v1.9.7): two further orders. The nucleus is ONE
 * 3D ball again - a shaded sphere whose light hotspot sits up and to the
 * left of its centre, its body falling off to transparent at the limb, an
 * ambient glow behind it and orbit sparks INSIDE the ball, so nothing
 * reads as a flat disc or a separate ring - and the ENTIRE feature, every
 * ink on the frame and not the nucleus alone, is 30% brighter than
 * v1.9.6's (BRIGHT_SCALE rides on GLOW_SCALE).
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
 *   - Every node breathes radially on its own phase, WANDERS on its own
 *     slower orbit (the continuous thinking), and the core is a one-time
 *     radial gradient whose alpha breathes on a slower clock, so the two
 *     rhythms cross and the picture never looks mechanical.
 *
 * The budget: one View, zero relay requests, zero allocations per frame
 * (nodes, link indices and the spark orbit are built once in
 * onSizeChanged and reused), and the frame loop is the view's own
 * invalidate pacing at FPS_MS. start() and stop() are the only public
 * controls, wired to MainActivity's startHud and stopHud: a paused console
 * draws nothing at all, and stop() holds the last frame instead of
 * abandoning the view blank.
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

    /**
     * Owner order 2026-10-22 (v1.9.5): the organism moves at 30% MORE
     * speed than v1.8.9's. Every turning, breathing and shimmering rate
     * below is multiplied by this one number, so the owner's order is one
     * named constant rather than ten scattered edits, and the applied speed
     * can never drift off it.
     */
    private static final float MOTION_SCALE = 1.3f;

    /**
     * Owner order 2026-10-22 (v1.9.6): the whole feature was reported too
     * dark, at least 20% brighter than v1.9.5's. Every ink alpha on the
     * frame (links, nodes, pulses, the nucleus's layers) multiplies this one
     * constant, so the brightness order is one named number rather than ten
     * scattered edits and can never drift back to the dim frame.
     */
    private static final float GLOW_SCALE = 1.25f;

    /**
     * Owner order 2026-10-22 (v1.9.7): the ENTIRE animated feature, every
     * ink on the frame and not the nucleus alone, is 30% brighter than
     * v1.9.6's. It rides on GLOW_SCALE as one named multiplier at the
     * links, the travelling pulses, the nodes, the ball, its glow, its
     * inner heart and its sparks, so this order stays one decision and
     * neither constant can drift.
     */
    private static final float BRIGHT_SCALE = 1.3f;

    /** Stride of a node's row in the cloud array. */
    private static final int NODE_STRIDE = 7;
    /** Orbiting sparks of the layered nucleus. Built once, drawn free. */
    private static final int SPARKS = 8;
    /** Cap on the travelling link sparks (the continuous "thinking" web). */
    private static final int PULSE_BUDGET = 16;

    private final Paint linkPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint nodePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    /** The nucleus ball's ambient glow: a one-time radial gradient. */
    private final Paint glowPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    /** The 3D nucleus ball: a one-time offset-highlight radial gradient. */
    private final Paint ballPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    /** The small white heart that breathes inside the ball. */
    private final Paint heartPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    /** The travelling link sparks and the nucleus's orbiting sparks. */
    private final Paint sparkPaint = new Paint(Paint.ANTI_ALIAS_FLAG);

    /**
     * Node geometry, in a unit ball: [0..2] x,y,z; [3] breath phase; [4]
     * shimmer phase; [5] wander phase; [6] wander rate (the continuous
     * thinking). Per-frame screen coordinates and depths are parallel
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
    /** The links that carry a travelling thought, and each one's phase. */
    private final int[] pulseA = new int[PULSE_BUDGET];
    private final int[] pulseB = new int[PULSE_BUDGET];
    private final float[] pulsePhase = new float[PULSE_BUDGET];
    private int pulseCount;
    /** The nucleus's orbiting sparks: (radius, phase, rate) triples. */
    private final float[] sparkRadius = new float[SPARKS];
    private final float[] sparkPhase = new float[SPARKS];
    private final float[] sparkRate = new float[SPARKS];

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
        // The nucleus is ONE 3D ball (owner order 2026-10-22, v1.9.7): a
        // sphere whose light hotspot sits up and to the left of its
        // centre, the body's colour falling off to transparent at the
        // limb, so the ball melts into the dark field instead of reading
        // as a flat grey disc. Both gradients are built ONCE here; the
        // ball breathes in alpha on the frame, never in radius, so no
        // frame ever rebuilds them (zero per-frame allocations stand).
        ballPaint.setShader(new RadialGradient(
                w / 2f - coreRadius * 0.32f, h / 2f - coreRadius * 0.38f,
                coreRadius * 1.45f, new int[]{
                0xFFFFFFFF, 0xFFEAF5FF, 0xFFB9DCF0, 0x666FA3D0, 0x003E6E9E},
                new float[]{0f, 0.2f, 0.45f, 0.78f, 1f},
                Shader.TileMode.CLAMP));
        // The ambient glow that sits UNDER the ball, so the sphere reads
        // as lit space rather than a cut-out.
        glowPaint.setShader(new RadialGradient(w / 2f, h / 2f,
                coreRadius * 2.6f, new int[]{
                withAlpha(CORE_COLOR, 0x4E), 0x00E4F0FF},
                new float[]{0f, 1f}, Shader.TileMode.CLAMP));
        geometryBuilt = true;
    }

    /**
     * One full build of the cloud: cluster anchors, node placement, link
     * list, the travelling link sparks and the nucleus's orbit ring. Ran
     * once per size; never on the frame path.
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
            seed = nextSeed(seed);
            float wanderRate = 0.35f + frac(seed) * 0.3f;
            seed = nextSeed(seed);
            float wanderPhase = frac(seed) * (float) Math.PI * 2f;
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
            cloud[o + 5] = wanderPhase;
            cloud[o + 6] = wanderRate;
        }
        float linkAt = 0.55f;
        linkCount = 0;
        for (int i = 0; i < NODES && linkCount < linkBudget(); i++) {
            for (int j = i + 1; j < NODES && linkCount < linkBudget(); j++) {
                float dx = cloud[i * NODE_STRIDE] - cloud[j * NODE_STRIDE];
                float dy = cloud[i * NODE_STRIDE + 1]
                        - cloud[j * NODE_STRIDE + 1];
                float dz = cloud[i * NODE_STRIDE + 2]
                        - cloud[j * NODE_STRIDE + 2];
                float dist = (float) Math.sqrt(dx * dx + dy * dy + dz * dz);
                if (dist <= linkAt) {
                    linkA[linkCount] = i;
                    linkB[linkCount] = j;
                    linkDist[linkCount] = dist;
                    linkCount++;
                }
            }
        }
        // The travelling thoughts: a slice of the links carries a moving
        // spark, so the web visibly carries activity every instant.
        pulseCount = 0;
        for (int l = 0; l < linkCount && pulseCount < PULSE_BUDGET; l++) {
            if (l % 5 == 0) {
                pulseA[pulseCount] = linkA[l];
                pulseB[pulseCount] = linkB[l];
                pulsePhase[pulseCount] = (float) Math.PI * 2f
                        * (l % 11) / 11f;
                pulseCount++;
            }
        }
        // The nucleus's orbiting sparks: eight points on their own radii,
        // phases and rates, all deterministic.
        for (int s = 0; s < SPARKS; s++) {
            seed = nextSeed(seed);
            // Inside the ball (owner order 2026-10-22, v1.9.7): the
            // sparks are plasma currents within the one sphere, so their
            // orbit never leaves the ball's radius.
            sparkRadius[s] = coreRadius * (0.55f + frac(seed) * 0.4f);
            seed = nextSeed(seed);
            sparkPhase[s] = frac(seed) * (float) Math.PI * 2f;
            seed = nextSeed(seed);
            sparkRate[s] = (0.9f + frac(seed) * 0.7f)
                    * (s % 2 == 0 ? 1f : -1f);
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
        float yaw = seconds * 0.22f * MOTION_SCALE;
        float pitch = 0.16f * (float) Math.sin(
                seconds * 0.13f * MOTION_SCALE);
        float cosYaw = (float) Math.cos(yaw);
        float sinYaw = (float) Math.sin(yaw);
        float cosPitch = (float) Math.cos(pitch);
        float sinPitch = (float) Math.sin(pitch);
        float cloudBreath = 1f + 0.035f * (float) Math.sin(
                seconds * 0.55f * MOTION_SCALE);
        float coreBreath = 0.55f + 0.45f * (float) Math.sin(
                seconds * 0.9f * MOTION_SCALE);
        // Wake over the first four seconds of a run, so the organism grows
        // out of the dark instead of popping in.
        float wake = Math.min(1f, seconds / 4f);

        canvas.drawColor(FIELD_COLOR);

        float distance = orbRadius * 2.8f;
        for (int n = 0; n < NODES; n++) {
            int o = n * NODE_STRIDE;
            float breathe = 1f + 0.06f * (float) Math.sin(
                    seconds * 0.8f * MOTION_SCALE + cloud[o + 3]);
            // The continuous thinking: every node wanders on its own slow
            // orbit (its own rate and phase), so no node is ever still.
            float wander = 1f + 0.05f * (float) Math.sin(
                    seconds * cloud[o + 6] * MOTION_SCALE + cloud[o + 5]);
            float x = cloud[o] * cloudBreath * breathe * wander;
            float y = cloud[o + 1] * cloudBreath * breathe * wander;
            float z = cloud[o + 2] * cloudBreath * breathe * wander;
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
            int alpha = (int) ((16f + 96f * toward) * wake
                    * GLOW_SCALE * BRIGHT_SCALE);
            linkPaint.setARGB(Math.min(255, alpha),
                    Color.red(LINK_COLOR), Color.green(LINK_COLOR),
                    Color.blue(LINK_COLOR));
            linkPaint.setStrokeWidth(linkWidth * (0.7f + 0.6f * toward));
            canvas.drawLine(screenX[a], screenY[a], screenX[b], screenY[b],
                    linkPaint);
        }
        // The travelling thoughts: a spark runs along its link and wraps,
        // dimmer at the ends it departs, so the web visibly carries
        // activity every instant.
        for (int p = 0; p < pulseCount; p++) {
            int a = pulseA[p];
            int b = pulseB[p];
            float t = frac2(seconds * 0.55f * MOTION_SCALE
                    + pulsePhase[p]);
            sparkPaint.setARGB(Math.min(255,
                            (int) ((70f + 110f * t) * wake
                                    * GLOW_SCALE * BRIGHT_SCALE)),
                    Color.red(CORE_COLOR), Color.green(CORE_COLOR),
                    Color.blue(CORE_COLOR));
            sparkPaint.setStrokeWidth(nodeRadius * 1.2f);
            float px = screenX[a] + (screenX[b] - screenX[a]) * t;
            float py = screenY[a] + (screenY[b] - screenY[a]) * t;
            canvas.drawPoint(px, py, sparkPaint);
        }
        for (int n = 0; n < NODES; n++) {
            int o = n * NODE_STRIDE;
            float toward = clamp((depth[n] - 1f) / 0.6f, 0f, 1f);
            float shimmer = 0.8f + 0.2f * (float) Math.sin(
                    seconds * 1.4f * MOTION_SCALE + cloud[o + 4]);
            float size = nodeRadius * (0.6f + 0.9f * toward) * shimmer;
            int alpha = (int) ((40f + 170f * toward) * wake
                    * GLOW_SCALE * BRIGHT_SCALE);
            nodePaint.setARGB(Math.min(255, alpha),
                    Color.red(NODE_COLOR), Color.green(NODE_COLOR),
                    Color.blue(NODE_COLOR));
            canvas.drawCircle(screenX[n], screenY[n], size, nodePaint);
        }

        // The nucleus is ONE 3D ball (owner order 2026-10-22, v1.9.7).
        // Draw order: the ambient glow UNDER the ball, then the shaded
        // sphere with its off-centre hotspot, then the white heart
        // breathing INSIDE it, then the orbit sparks still inside the
        // ball's radius, so the whole nucleus reads as a single object -
        // no stacked discs, no separate ring. The ball breathes in alpha,
        // the glow breathes OUT of phase with it, and every ink carries
        // the owner's 30% (BRIGHT_SCALE) on top of the glow pass.
        glowPaint.setAlpha(Math.min(255, (int) (95f * (1.4f - coreBreath)
                * wake * GLOW_SCALE * BRIGHT_SCALE)));
        canvas.drawCircle(cx, cy, coreRadius * 2.6f, glowPaint);
        ballPaint.setAlpha(Math.min(255, (int) (140f
                * (0.55f + 0.45f * coreBreath) * wake
                * GLOW_SCALE * BRIGHT_SCALE)));
        canvas.drawCircle(cx, cy, coreRadius, ballPaint);
        heartPaint.setColor(CORE_COLOR);
        heartPaint.setAlpha(Math.min(255, (int) (150f
                * (0.7f + 0.3f * coreBreath) * wake
                * GLOW_SCALE * BRIGHT_SCALE)));
        canvas.drawCircle(cx, cy, coreRadius * 0.3f, heartPaint);
        for (int s = 0; s < SPARKS; s++) {
            float angle = seconds * sparkRate[s] * MOTION_SCALE
                    + sparkPhase[s];
            float sx = cx + sparkRadius[s] * (float) Math.cos(angle);
            float sy = cy + sparkRadius[s] * 0.6f * (float) Math.sin(angle);
            sparkPaint.setARGB(Math.min(255, (int) ((130f
                    + 60f * (float) Math.cos(angle)) * wake
                    * GLOW_SCALE * BRIGHT_SCALE)),
                    Color.red(CORE_COLOR), Color.green(CORE_COLOR),
                    Color.blue(CORE_COLOR));
            canvas.drawCircle(sx, sy, nodeRadius * 1.05f, sparkPaint);
        }
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

    /** A float phase wrapped onto [0, 1). */
    private static float frac2(float v) {
        return v - (float) Math.floor(v);
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
