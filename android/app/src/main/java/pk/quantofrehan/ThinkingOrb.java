package pk.quantofrehan;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.RectF;
import android.graphics.BitmapFactory;
import android.util.AttributeSet;
import android.view.View;

/**
 * The thinking orb (v2.3.1).
 *
 * The feature is the v1.8.9 LIVING PARTICLE CLOUD the owner first approved:
 * 105 nodes gathered around five cluster anchors, joined by fine links,
 * turning rigidly in yaw with a breathing pitch and projected in
 * perspective, every node breathing radially on its own phase, around an
 * always-burning sun at its centre.
 *
 * The sun's own history, because each pass below is an order of his and the
 * constants in this file are the answers to it:
 *
 *   v2.2.0  the white core became a sun ("I want the center as the sun").
 *   v2.2.1  no fast alpha modulation anywhere ("don't flicker"), the inks
 *           warmed to the fire family, and the sun grew to 26% of the
 *           feature.
 *   v2.2.3  the flat photograph was wrapped into a panorama; its mirror
 *           seam is the two-discs wreckage he kept sending back.
 *   v2.2.6  the panorama turned, with the owner's own 10% speed cut.
 *   v2.2.8  the picture projections were retired for good and the centre
 *           became a RENDERED SPHERE: a surface baked on the ball's own
 *           unit sphere, read through the frame's longitude.
 *   v2.2.9  the photographs's crown (the wide amber band, the white edge)
 *           was baked into the ball.
 *   v2.3.0  the fake rays (twelve radial flame tongues, seven spark
 *           streaks) were deleted, the surface raised to 448x224 with five
 *           noise fields, and the painted ring replaced by a ragged one.
 *
 * Owner order 2026-10-25, fourth pass: "still looks very old fashioned
 * render, like it's from PS2, the SUN should be looking advanced, like it's
 * burning continuously, like small explosions, fire burning through the
 * SUN". Everything the v2.3.0 ball did wrong was structural, not cosmetic,
 * and each cure below is measured off his own photograph:
 *
 *   1. ONE HEAT FIELD, ONE PALETTE. The ball used to be coloured channel by
 *      channel with additive lifts, so every lift pushed green and blue up
 *      and the picture's saturated orange died into tan cream. Now the
 *      surface is a single heat field, every frame folds it through the
 *      photograph's own twelve colour quantiles (a 256 entry lookup), and
 *      the ink is his at every brightness.
 *   2. RANK NORMALISED, THEN STRETCHED. A noise sum clusters around its
 *      mean, which is the flat, moulded look he rejected. The bake sorts
 *      the field's own distribution so it spans the palette end to end and
 *      then stretches the levels, so the near-black lanes and the pale
 *      granules both exist.
 *   3. HIS OWN FIRE. The photograph's high-pass detail (its filaments, its
 *      granulation) is read through two planar projections at two scales
 *      and folded into the body, so the fine structure is his picture's
 *      and not another noise octave.
 *   4. LIMB BRIGHTENED, like the picture: dark in the middle, blazing at
 *      0.7-0.8 of the radius. A shaded ball does the opposite, which is
 *      exactly what reads as a render.
 *   5. THE FIRE BOILS. The same surface is read twice, one copy
 *      counter-turning and offset in latitude, and mixed per pixel, so no
 *      frame is a rigid rotation of the last.
 *   6. ERUPTIONS - the "small explosions": seven short, smooth bursts of
 *      white-hot plasma that travel with the surface, swell as they burn
 *      and fade, so something is always blowing somewhere on the disc.
 *   7. A QUARTER-RESOLUTION BLOOM. The hot plasma bleeds the way light
 *      does instead of sitting in crisp pixels.
 *   8. A WARM GLOW, baked once, pinned to the ball's radius: the bright
 *      limb is light in the air, not a painted ring of pixels.
 *
 * Owner order 2026-10-25, fifth pass, same message: "the big lines that are
 * moving outside the circle, make them look like they are breathing as
 * well, like they should be getting a big small and then get bigger". The
 * cloud's filaments already breathed in length (v2.2.4) but so gently that
 * he could not see it: the swing is nearly doubled now, and each filament's
 * stroke widens and its ink brightens on the same breath, one golden-angle
 * phase per line so no two are in step.
 *
 * The park law of v1.9.14 stands: stop() freezes the pose the loop last
 * DREW and the parked frame REPAINTS it fully awake, so a closed market, a
 * break, a theme repaint or a layout pass can never blank the feature; the
 * loop only stops MOVING. A resume replays from the frozen second.
 *
 * The budget stands too: one View, zero relay requests, zero allocations on
 * the frame path. The cloud's nodes and links, and the sun's surface, frame
 * tables, palette, detail field, bloom buffers and glow are all built once
 * in onSizeChanged; every frame touches preallocated arrays. start() and
 * stop() stay the only public controls, wired to MainActivity's startHud
 * and stopHud behind the market gate.
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

    /** The node ink, warm gold in the sun's own family (v2.2.1). */
    private static final int NODE_COLOR = 0xFFFFD166;
    /** The link ink, the orangish/yellow the owner ordered (v2.2.1). */
    private static final int LINK_COLOR = 0xFFFFA62B;

    private final Paint linkPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint nodePaint = new Paint(Paint.ANTI_ALIAS_FLAG);

    /** The one paint that carries the rendered ball (alpha per frame). */
    private final Paint sunPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    /** The baked halo's own paint: only its alpha moves, with the wake. */
    private final Paint sunHaloPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    /** The steady glow, baked once per size beside the ball. */
    private Bitmap halo;
    /** The rendered sphere: one bitmap of the ball, reused every frame. */
    private Bitmap sunBall;
    /** The ball's own pixel buffer, refilled each frame, never reallocated. */
    private int[] sunBallPixels;
    /** The frame's colours before the bloom is added, reused every frame. */
    private int[] sunScratch;
    /** The quarter-resolution bloom: current and scratch, both reused. */
    private int[] bloomPix;
    private int[] bloomTmp;
    /** The surface heat map, 0..255 per texel, baked once per size. */
    private int[] sunSurface;
    /** The photograph's own high-pass detail, luminance 0..255. */
    private int[] sunDetail;
    private int sunDetailW;
    private int sunDetailH;
    /**
     * The sphere's frame tables, baked once per size: the longitude each
     * ball pixel reads at zero spin, the surface row it reads, the ball's
     * own direction there (the eruptions are lit from it), the heat gain
     * its place on the limb earns, the crown's lift, the mix weight and
     * latitude wobble the second, counter-turning read uses, and the
     * pixel's edge coverage. Nothing here is computed on the frame path
     * but the one shared spin.
     */
    private float[] sphereU;
    private float[] sphereV;
    private float[] sphereX;
    private float[] sphereY;
    private float[] sphereZ;
    private float[] sphereGain;
    private float[] sphereRim;
    private float[] sphereMix;
    private float[] sphereWob;
    private int[] sphereCover;
    /** The destination square the ball fills, preallocated for the frame. */
    private final RectF ballDst = new RectF();

    /** The photograph's own twelve colour quantiles, 0% to 100% of its light. */
    private static final int[] SUN_RAMP = {
            0xFF260402, 0xFF861B08, 0xFFA72F0C, 0xFFC34E17, 0xFFD87028,
            0xFFE69039, 0xFFF3B051, 0xFFF8D56E, 0xFFFBF096, 0xFFFDFCB4,
            0xFFFDFEC8, 0xFFFEFEE4,
    };
    private static final float[] SUN_STOP = {
            0.00f, 0.05f, 0.10f, 0.20f, 0.32f, 0.44f,
            0.56f, 0.68f, 0.80f, 0.90f, 0.96f, 1.00f,
    };
    /** The heat lookups: 256 palette colours, built once from the ramp. */
    private final int[] sunHeat = new int[256];

    /**
     * The ball's own render resolution. v2.3.0 raised it to 320 and the
     * owner still read the picture as a render: detail was never the
     * problem, structure was. v2.3.1 spends the budget on the boil, the
     * eruptions and the bloom instead, on a 256 pixel buffer that still
     * oversamples the 154 pixel ball the phone draws.
     */
    private static final int SUN_RENDER = 256;
    /** The surface map: equirectangular, baked once per size. */
    private static final int SUN_MAP_W = 448;
    private static final int SUN_MAP_H = 224;

    /** The standing tilt: the pose; the longitude carries the motion. */
    private static final float SUN_AXIS_TILT = 10f;
    /** One revolution of the sphere's own longitude. */
    private static final float SUN_LAP = (float) (2f * Math.PI);

    /**
     * The boil: a second read of the same surface, counter-turning at 58%
     * of the main spin and offset by 61 rows of latitude, mixed per pixel.
     * Two decorrelated copies of the fire that drift against each other
     * read as plasma churning; one copy reads as a printed ball turning.
     */
    private static final float SUN_CHURN_TURN = -0.58f;
    private static final float SUN_CHURN_ROW = 61f;

    /**
     * The bloom: a quarter-resolution bright pass, blurred and added back.
     * The knee is high, so only the plasma and the eruptions bleed; a low
     * knee blurs the whole disc and washes it out.
     */
    private static final int SUN_BLOOM = 64;
    private static final int SUN_BLOOM_CELL = SUN_RENDER / SUN_BLOOM;
    private static final int SUN_BLOOM_KNEE = 214;
    private static final float SUN_BLOOM_ADD = 0.30f;

    /**
     * The glow's own reach, as a multiple of the ball's radius, and the
     * ink it peaks at. It is baked ONCE per size (buildSunHalo), so the
     * frame only alpha-drives it: no per-frame shader, no flicker term.
     */
    private static final float SUN_HALO = 1.55f;

    /**
     * The eruptions: the owner's "small explosions". Seven bursts, each
     * with its own direction on the ball, its own period and phase, and a
     * smooth attack and decay, so something is always blowing somewhere.
     */
    private static final int ERUPTIONS = 7;
    private static final float[] ERUPT_DIR = {
            0.62f, 0.28f, 0.73f, -0.55f, 0.44f, 0.71f, 0.20f, -0.30f, 0.93f,
            -0.72f, -0.38f, 0.58f, 0.48f, -0.62f, 0.62f, -0.25f, 0.78f, 0.57f,
            0.05f, 0.10f, 0.99f,
    };
    private static final float[] ERUPT_PERIOD = {
            3.4f, 4.6f, 2.9f, 5.2f, 3.9f, 4.2f, 3.1f,
    };
    private static final float[] ERUPT_PHASE = {
            0.00f, 0.37f, 0.61f, 0.18f, 0.83f, 0.49f, 0.72f,
    };
    private static final float[] ERUPT_STRENGTH = {
            0.95f, 0.75f, 1.00f, 0.68f, 0.88f, 0.72f, 0.82f,
    };
    private final float[] eruptDir = new float[ERUPTIONS * 3];
    private final float[] eruptTurnX = new float[ERUPTIONS];
    private final float[] eruptTurnY = new float[ERUPTIONS];
    private final float[] eruptTurnZ = new float[ERUPTIONS];
    private final float[] eruptCos = new float[ERUPTIONS];
    private final float[] eruptEnergy = new float[ERUPTIONS];

    /**
     * Owner order 2026-10-24 (the sun must revolve) and 2026-10-24 (the
     * 10% speed cut), both kept: the surface TRAVELS limb to limb.
     */
    private static final float SUN_SPIN_RATE = 0.35f;
    private static final float SUN_SLOWDOWN = 0.9f;

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
    /**
     * Owner order 2026-10-24 (the lines breathe) and 2026-10-25 (they must
     * visibly grow and shrink): each filament gets its own breath phase,
     * one golden-angle step apart, so the mesh breathes with a ripple
     * instead of every line twitching in unison.
     */
    private final float[] linkPhase = new float[linkBudget()];
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

    /**
     * The clock the frame loop reads, in seconds, so a parked frame can
     * be REPAINTED at exactly the pose it froze on (v1.9.14): park no
     * longer blanks, and resume continues from the frozen second instead
     * of restarting the wake ramp.
     */
    private float lastSeconds;
    private float frozenSeconds = -1f;
    /** The second the sun's own frame is being drawn at. */
    private float sunSeconds;

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
        // The sun is the cloud's own core: a rendered SPHERE now (owner
        // order 2026-10-25), sized by the same fraction the drawn ball
        // held - 0.26f, the bigger-sun order of v2.2.1 - so the star
        // stands exactly where the ball he approved stood.
        ballR = orbRadius * 0.26f;
        nodeRadius = dp(1.3f);
        linkWidth = Math.max(1f, dp(0.9f));
        clockAnchor = System.currentTimeMillis();
        buildGeometry();
        buildInks();
        buildSunSphere();
        built = true;
        // The ball exists the moment the size exists; never count on a
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
        // Owner order 2026-10-24 ("the lines ... look very tangled, make
        // them untangled"): a link is a short filament inside its own
        // neighbourhood, never a long chord crossing the ball.
        float linkAt = 0.42f;
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
                    // One golden-angle step per link: the multiplying
                    // constant spreads the phases around the circle so
                    // no two neighbours breathe in perfect step.
                    linkPhase[linkCount] = 2.39996f * linkCount;
                    linkCount++;
                }
            }
        }
    }

    /** The paints: the rendered ball, its glow, and the cloud's inks. */
    private void buildInks() {
        linkPaint.setStyle(Paint.Style.STROKE);
        linkPaint.setStrokeCap(Paint.Cap.ROUND);
        linkPaint.setColor(LINK_COLOR);
        nodePaint.setStyle(Paint.Style.FILL);
        // The sun is the rendered sphere: the ball bitmap is drawn scaled
        // with filtering, its alpha the wake's. No shader of ours repaints
        // the ball.
        sunPaint.setFilterBitmap(true);
        sunHaloPaint.setFilterBitmap(true);
    }

    @Override
    protected void onDraw(Canvas canvas) {
        if (!built) {
            // A view without a size yet cannot draw its scene; ask again
            // rather than leave the station blank.
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
     * The centre is a RENDERED SPHERE, and the picture is a star rather than
     * a lit ball: the glow goes down first, the ball over it, and the ball's
     * own frame is one heat field folded through the photograph's palette.
     *
     * Nothing on this path pumps the ball's alpha: its ink is the wake
     * alone, the heat moves in the surface and in the eruptions, and the
     * glow is one baked bitmap. That is how a picture burns continuously
     * without ever flickering (the owner's order of the same pass).
     */
    private void drawSun(Canvas canvas, float seconds, float wake) {
        if (sunBall == null) {
            return;     // no sphere built, no picture invented (SO-3)
        }
        float haloHalf = halo.getWidth() / 2f;
        sunHaloPaint.setAlpha((int) (175f * wake));
        canvas.drawBitmap(halo, cx - haloHalf, cy - haloHalf, sunHaloPaint);
        float phi = seconds * SUN_SPIN_RATE * MOTION_SCALE * SUN_SLOWDOWN;
        sunSeconds = seconds;
        renderSunBall(phi);
        sunPaint.setAlpha((int) (255f * wake));
        canvas.save();
        // The standing tilt: the pose; the longitude carries the motion.
        canvas.rotate(SUN_AXIS_TILT, cx, cy);
        float r = ballR;
        ballDst.set(cx - r, cy - r, cx + r, cy + r);
        canvas.drawBitmap(sunBall, null, ballDst, sunPaint);
        canvas.restore();
    }

    /**
     * One frame of the sphere. Each ball pixel reads the baked heat at the
     * frame's longitude, at a second counter-turning longitude, mixes the
     * two, scales the mix by its place on the limb, adds whatever eruptions
     * are burning over it, and folds the result through the palette. Then
     * the bloom pass lets the hot plasma bleed.
     *
     * The whole loop is array reads and multiply-adds on preallocated
     * tables: no allocation, no trigonometry, no texture object.
     */
    private void renderSunBall(float phi) {
        stepEruptions(sunSeconds, phi);
        float spin = phi / SUN_LAP * SUN_MAP_W;
        float spin2 = spin * SUN_CHURN_TURN;
        int count = SUN_RENDER * SUN_RENDER;
        for (int k = 0; k < count; k++) {
            int cover = sphereCover[k];
            if (cover == 0) {
                sunScratch[k] = 0;
                continue;
            }
            int hot1 = sampleSun(sphereU[k] + spin, sphereV[k]);
            int hot2 = sampleSun(sphereU[k] + spin2,
                    mirrorRow(sphereV[k] + SUN_CHURN_ROW + sphereWob[k]));
            float mix = sphereMix[k];
            float heat = (hot1 + (hot2 - hot1) * mix) * (1f / 255f);
            heat *= sphereGain[k];
            heat += sphereRim[k];
            // The eruptions: white-hot plasma, wide skirt and a small core.
            float px = sphereX[k];
            float py = sphereY[k];
            float pz = sphereZ[k];
            for (int e = 0; e < ERUPTIONS; e++) {
                float energy = eruptEnergy[e];
                if (energy <= 0.02f) {
                    continue;
                }
                float dot = px * eruptTurnX[e] + py * eruptTurnY[e]
                        + pz * eruptTurnZ[e];
                float cos = eruptCos[e];
                if (dot <= cos) {
                    continue;
                }
                float q = (dot - cos) / (1f - cos);
                float q2 = q * q;
                float q3 = q2 * q;
                float q4 = q2 * q2;
                float q8 = q4 * q4;
                heat += (q3 * 0.40f + q8 * 1.60f) * energy;
            }
            if (heat < 0f) {
                heat = 0f;
            } else if (heat > 1f) {
                heat = 1f;
            }
            int rgb = sunHeat[(int) (heat * 255f)];
            sunScratch[k] = (cover << 24) | (rgb & 0x00FFFFFF);
        }
        bloomSun();
        sunBall.setPixels(sunBallPixels, 0, SUN_RENDER, 0, 0,
                SUN_RENDER, SUN_RENDER);
    }

    /**
     * The bloom: the ball's own bright pass at a quarter of the resolution,
     * blurred, and added back. Only the plasma and the eruptions are above
     * the knee, so the disc's body keeps its contrast and the hot parts
     * carry light into the pixels around them. All buffers are fields.
     */
    private void bloomSun() {
        final int cell = SUN_BLOOM_CELL;
        final int area = cell * cell;
        for (int by = 0; by < SUN_BLOOM; by++) {
            for (int bx = 0; bx < SUN_BLOOM; bx++) {
                int red = 0;
                int green = 0;
                int blue = 0;
                for (int dy = 0; dy < cell; dy++) {
                    int row = (by * cell + dy) * SUN_RENDER + bx * cell;
                    for (int dx = 0; dx < cell; dx++) {
                        int pixel = sunScratch[row + dx];
                        red += (pixel >> 16) & 0xFF;
                        green += (pixel >> 8) & 0xFF;
                        blue += pixel & 0xFF;
                    }
                }
                red /= area;
                green /= area;
                blue /= area;
                int lum = (red * 77 + green * 150 + blue * 29) >> 8;
                int excess = lum - SUN_BLOOM_KNEE;
                if (excess <= 0) {
                    bloomPix[by * SUN_BLOOM + bx] = 0;
                    continue;
                }
                float k = excess * (1f / 255f);
                bloomPix[by * SUN_BLOOM + bx] =
                        ((int) (red * k) << 16)
                        | ((int) (green * k) << 8)
                        | (int) (blue * k);
            }
        }
        blurBloom();
        final float step = 1f / cell;
        for (int k = 0; k < SUN_RENDER * SUN_RENDER; k++) {
            int pixel = sunScratch[k];
            int cover = pixel >>> 24;
            if (cover == 0) {
                sunBallPixels[k] = 0;
                continue;
            }
            float gx = ((k % SUN_RENDER) + 0.5f) * step - 0.5f;
            float gy = ((k / SUN_RENDER) + 0.5f) * step - 0.5f;
            int bloom = sampleBloom(gx, gy);
            int red = ((pixel >> 16) & 0xFF)
                    + (int) (((bloom >> 16) & 0xFF) * SUN_BLOOM_ADD);
            int green = ((pixel >> 8) & 0xFF)
                    + (int) (((bloom >> 8) & 0xFF) * SUN_BLOOM_ADD);
            int blue = (pixel & 0xFF)
                    + (int) ((bloom & 0xFF) * SUN_BLOOM_ADD);
            sunBallPixels[k] = (cover << 24)
                    | (Math.min(255, red) << 16)
                    | (Math.min(255, green) << 8)
                    | Math.min(255, blue);
        }
    }

    /** One bilinear read of the bloom buffer, edges clamped. */
    private int sampleBloom(float gx, float gy) {
        int x0 = (int) gx;
        int y0 = (int) gy;
        float fx = gx - x0;
        float fy = gy - y0;
        int x1 = x0 + 1;
        int y1 = y0 + 1;
        if (x0 < 0) {
            x0 = 0;
        }
        if (x0 > SUN_BLOOM - 1) {
            x0 = SUN_BLOOM - 1;
        }
        if (x1 < 0) {
            x1 = 0;
        }
        if (x1 > SUN_BLOOM - 1) {
            x1 = SUN_BLOOM - 1;
        }
        if (y0 < 0) {
            y0 = 0;
        }
        if (y0 > SUN_BLOOM - 1) {
            y0 = SUN_BLOOM - 1;
        }
        if (y1 < 0) {
            y1 = 0;
        }
        if (y1 > SUN_BLOOM - 1) {
            y1 = SUN_BLOOM - 1;
        }
        int a = bloomPix[y0 * SUN_BLOOM + x0];
        int b = bloomPix[y0 * SUN_BLOOM + x1];
        int c = bloomPix[y1 * SUN_BLOOM + x0];
        int d = bloomPix[y1 * SUN_BLOOM + x1];
        int out = 0;
        for (int shift = 16; shift >= 0; shift -= 8) {
            float top = ((a >> shift) & 0xFF)
                    + (((b >> shift) & 0xFF) - ((a >> shift) & 0xFF)) * fx;
            float bottom = ((c >> shift) & 0xFF)
                    + (((d >> shift) & 0xFF) - ((c >> shift) & 0xFF)) * fx;
            int value = (int) (top + (bottom - top) * fy);
            out |= Math.min(255, Math.max(0, value)) << shift;
        }
        return out;
    }

    /**
     * One 5-tap separable blur over the bloom buffer: horizontal into the
     * scratch, vertical back into the bloom, edges clamped. All buffers are
     * fields, so it allocates nothing.
     */
    private void blurBloom() {
        for (int y = 0; y < SUN_BLOOM; y++) {
            for (int x = 0; x < SUN_BLOOM; x++) {
                int red = 0;
                int green = 0;
                int blue = 0;
                for (int t = -2; t <= 2; t++) {
                    int sx = clampInt(x + t, 0, SUN_BLOOM - 1);
                    int pixel = bloomPix[y * SUN_BLOOM + sx];
                    int weight = t == -2 || t == 2 ? 1 : (t == 0 ? 6 : 4);
                    red += ((pixel >> 16) & 0xFF) * weight;
                    green += ((pixel >> 8) & 0xFF) * weight;
                    blue += (pixel & 0xFF) * weight;
                }
                bloomTmp[y * SUN_BLOOM + x] = ((red >> 4) << 16)
                        | ((green >> 4) << 8) | (blue >> 4);
            }
        }
        for (int y = 0; y < SUN_BLOOM; y++) {
            for (int x = 0; x < SUN_BLOOM; x++) {
                int red = 0;
                int green = 0;
                int blue = 0;
                for (int t = -2; t <= 2; t++) {
                    int sy = clampInt(y + t, 0, SUN_BLOOM - 1);
                    int pixel = bloomTmp[sy * SUN_BLOOM + x];
                    int weight = t == -2 || t == 2 ? 1 : (t == 0 ? 6 : 4);
                    red += ((pixel >> 16) & 0xFF) * weight;
                    green += ((pixel >> 8) & 0xFF) * weight;
                    blue += (pixel & 0xFF) * weight;
                }
                bloomPix[y * SUN_BLOOM + x] = ((red >> 4) << 16)
                        | ((green >> 4) << 8) | (blue >> 4);
            }
        }
    }

    /** Integer clamp, the bloom's own edges. */
    private static int clampInt(int v, int lo, int hi) {
        return v < lo ? lo : (v > hi ? hi : v);
    }

    /**
     * One bilinear read of the heat map. The columns wrap (longitude is a
     * circle); the rows are clamped, because the ball never reads past them.
     */
    private int sampleSun(float u, float v) {
        u = u % SUN_MAP_W;
        if (u < 0f) {
            u += SUN_MAP_W;
        }
        int c0 = (int) u;
        int c1 = c0 + 1 == SUN_MAP_W ? 0 : c0 + 1;
        float fu = u - c0;
        int r0 = (int) v;
        if (r0 > SUN_MAP_H - 1) {
            r0 = SUN_MAP_H - 1;
        } else if (r0 < 0) {
            r0 = 0;
        }
        int r1 = r0 + 1 < SUN_MAP_H ? r0 + 1 : r0;
        float fv = clamp(v - r0, 0f, 1f);
        int a = sunSurface[r0 * SUN_MAP_W + c0];
        int b = sunSurface[r0 * SUN_MAP_W + c1];
        int c = sunSurface[r1 * SUN_MAP_W + c0];
        int d = sunSurface[r1 * SUN_MAP_W + c1];
        float top = a + (b - a) * fu;
        float bottom = c + (d - c) * fu;
        return (int) (top + (bottom - top) * fv + 0.5f);
    }

    /** A latitude coordinate mirrored instead of wrapped, so no seam shows. */
    private static float mirrorRow(float v) {
        float span = 2f * (SUN_MAP_H - 1);
        float m = v % span;
        if (m < 0f) {
            m += span;
        }
        return m > SUN_MAP_H - 1 ? span - m : m;
    }

    /**
     * The eruptions' own state for this frame: each burst's energy, the
     * cosine of its hot core's half angle, and its direction turned with
     * the surface it sits on (so a burst travels the disc with the fire
     * around it instead of hanging in front of the ball).
     */
    private void stepEruptions(float seconds, float phi) {
        float cosPhi = (float) Math.cos(phi);
        float sinPhi = (float) Math.sin(phi);
        for (int e = 0; e < ERUPTIONS; e++) {
            float t = seconds / ERUPT_PERIOD[e] + ERUPT_PHASE[e];
            t -= (float) Math.floor(t);
            float attack = smoothstep(0f, 0.20f, t);
            float decay = 1f - smoothstep(0.34f, 1f, t);
            eruptEnergy[e] = attack * decay * ERUPT_STRENGTH[e];
            eruptCos[e] = (float) Math.cos(0.150f + 0.130f * t);
            float dx = eruptDir[e * 3];
            float dy = eruptDir[e * 3 + 1];
            float dz = eruptDir[e * 3 + 2];
            eruptTurnX[e] = dx * cosPhi + dz * sinPhi;
            eruptTurnY[e] = dy;
            eruptTurnZ[e] = -dx * sinPhi + dz * cosPhi;
        }
    }

    /**
     * The sphere, baked once per size: the palette, the photograph's detail
     * field, the surface heat map, the frame tables and the glow. Never on
     * the frame path.
     */
    private void buildSunSphere() {
        buildSunHeat();
        buildSunDetail();
        buildSunSurface();
        int count = SUN_RENDER * SUN_RENDER;
        sunBall = Bitmap.createBitmap(SUN_RENDER, SUN_RENDER,
                Bitmap.Config.ARGB_8888);
        sunBallPixels = new int[count];
        sunScratch = new int[count];
        bloomPix = new int[SUN_BLOOM * SUN_BLOOM];
        bloomTmp = new int[SUN_BLOOM * SUN_BLOOM];
        sphereU = new float[count];
        sphereV = new float[count];
        sphereX = new float[count];
        sphereY = new float[count];
        sphereZ = new float[count];
        sphereGain = new float[count];
        sphereRim = new float[count];
        sphereMix = new float[count];
        sphereWob = new float[count];
        sphereCover = new int[count];
        for (int e = 0; e < ERUPTIONS; e++) {
            float dx = ERUPT_DIR[e * 3];
            float dy = ERUPT_DIR[e * 3 + 1];
            float dz = ERUPT_DIR[e * 3 + 2];
            float len = (float) Math.sqrt(dx * dx + dy * dy + dz * dz);
            eruptDir[e * 3] = dx / len;
            eruptDir[e * 3 + 1] = dy / len;
            eruptDir[e * 3 + 2] = dz / len;
        }
        float half = SUN_RENDER / 2f;
        float feather = 1.6f / half;
        for (int j = 0; j < SUN_RENDER; j++) {
            float y = (j + 0.5f) / half - 1f;
            for (int i = 0; i < SUN_RENDER; i++) {
                int k = j * SUN_RENDER + i;
                float x = (i + 0.5f) / half - 1f;
                float d2 = x * x + y * y;
                if (d2 >= 1f) {
                    continue;   // outside the ball: no coverage, no cost
                }
                float z = (float) Math.sqrt(1f - d2);
                // The azimuth about the ball's own standing axis: the
                // frame's spin is one addition to this, so no atan2 ever
                // runs on the frame path.
                float azimuth = (float) Math.atan2(z, x);
                sphereU[k] = (azimuth / SUN_LAP + 0.5f) * SUN_MAP_W;
                float latitude = (float) Math.asin(clamp(y, -1f, 1f));
                sphereV[k] = (0.5f - latitude / (float) Math.PI)
                        * (SUN_MAP_H - 1);
                sphereX[k] = x;
                sphereY[k] = y;
                sphereZ[k] = z;
                float rn = (float) Math.sqrt(d2);
                // The photograph is LIMB BRIGHTENED: dark in the middle,
                // blazing at 0.7-0.8 of the radius. A shaded ball does the
                // opposite, and that is exactly what reads as a render.
                float limb = smoothstep(0.02f, 0.90f, rn);
                float low = fbm3(x * 1.9f + 1.3f, y * 1.9f - 4.7f, 6.1f, 4);
                float gain = (0.46f + 0.66f * limb) * (0.94f + 0.12f * low);
                gain *= 0.84f + 0.26f * fbm3(x * 5.5f + 2f, y * 5.5f - 3f,
                        1.7f, 3);
                // Only an eruption may reach the palette's white; the body
                // tops out at pale yellow, because a surface that clips to
                // white everywhere is the plastic look he keeps sending back.
                sphereGain[k] = Math.min(gain, 0.93f);
                // A limb that blazes in PLACES, not all the way round: the
                // photograph's rim varies enormously along its
                // circumference, and an even ring is what reads as painted.
                float rag = 0.42f + 1.25f * fbm3(x * 5.5f + 2f,
                        y * 5.5f - 3f, 1.7f, 3);
                float blaze = (float) Math.pow(clamp(0.10f + 1.75f * low,
                        0f, 1f), 1.5f);
                float band = smoothstep(0.800f, 1f,
                        rn + 0.050f * (rag - 1f));
                sphereRim[k] = band * (0.04f + 0.08f * rag)
                        * (0.30f + 1.20f * blaze);
                sphereMix[k] = 0.24f + 0.38f * fbm3(x * 3.3f + 11f,
                        y * 3.3f - 7f, 5.3f, 2);
                sphereWob[k] = 3.1f * fbm3(x * 4.7f - 2f, y * 4.7f + 6f,
                        9.1f, 2);
                sphereCover[k] = (int) (255f * clamp((1f - rn) / feather,
                        0f, 1f));
            }
        }
        buildSunHalo();
    }

    /** The palette lookup: 256 colours of the photograph, built once. */
    private void buildSunHeat() {
        int last = SUN_STOP.length - 1;
        for (int t = 0; t < 256; t++) {
            float v = t / 255f;
            int stop = 1;
            while (stop < last && v > SUN_STOP[stop]) {
                stop++;
            }
            float span = SUN_STOP[stop] - SUN_STOP[stop - 1];
            float k = span <= 0f ? 0f : (v - SUN_STOP[stop - 1]) / span;
            sunHeat[t] = rampMix(SUN_RAMP[stop - 1], SUN_RAMP[stop],
                    clamp(k, 0f, 1f));
        }
    }

    /**
     * The photograph's own fire, as a high-pass detail field. The ball's
     * geometry must be ours (a flat disc maps to one hemisphere only), but
     * its TEXTURE can be his: the picture's filament structure is exactly
     * the fine detail that procedural noise never gets right. Luminance
     * minus a wide blur is that detail, neutral 128 outside the disc.
     */
    private void buildSunDetail() {
        Bitmap photo = null;
        try {
            photo = BitmapFactory.decodeResource(getResources(),
                    R.drawable.sun);
        } catch (RuntimeException ignored) {
            // No picture is no excuse to invent one (SO-3): the surface
            // falls back to its own noise, neutral detail.
        }
        if (photo == null) {
            sunDetail = null;
            return;
        }
        int w = photo.getWidth();
        int h = photo.getHeight();
        sunDetailW = w;
        sunDetailH = h;
        int[] pixels = new int[w * h];
        photo.getPixels(pixels, 0, w, 0, 0, w, h);
        photo.recycle();
        int[] gray = new int[w * h];
        for (int i = 0; i < gray.length; i++) {
            int pixel = pixels[i];
            gray[i] = (((pixel >> 16) & 0xFF) * 77
                    + ((pixel >> 8) & 0xFF) * 150
                    + (pixel & 0xFF) * 29) >> 8;
        }
        int radius = Math.max(3, w * 3 / 100);
        int[] blurred = boxBlurGray(gray, w, h, radius);
        sunDetail = new int[w * h];
        float midX = w / 2f;
        float midY = h / 2f;
        float midR = Math.min(w, h) / 2f;
        for (int y = 0; y < h; y++) {
            for (int x = 0; x < w; x++) {
                int i = y * w + x;
                float dx = x - midX;
                float dy = y - midY;
                float rn = (float) Math.sqrt(dx * dx + dy * dy) / midR;
                float weight = clamp((0.94f - rn) / 0.12f, 0f, 1f);
                float d = (gray[i] - blurred[i]) * 2.2f;
                float v = 128f + d * weight;
                sunDetail[i] = (int) clamp(v, 0f, 255f);
            }
        }
    }

    /** Separable box blur of a luminance field, edges clamped. */
    private static int[] boxBlurGray(int[] src, int w, int h, int radius) {
        int[] tmp = new int[w * h];
        int[] out = new int[w * h];
        int span = 2 * radius + 1;
        for (int y = 0; y < h; y++) {
            int row = y * w;
            for (int x = 0; x < w; x++) {
                int sum = 0;
                for (int d = -radius; d <= radius; d++) {
                    sum += src[row + clampInt(x + d, 0, w - 1)];
                }
                tmp[row + x] = sum / span;
            }
        }
        for (int x = 0; x < w; x++) {
            for (int y = 0; y < h; y++) {
                int sum = 0;
                for (int d = -radius; d <= radius; d++) {
                    sum += tmp[clampInt(y + d, 0, h - 1) * w + x];
                }
                out[y * w + x] = sum / span;
            }
        }
        return out;
    }

    /** The detail field read bilinearly, its edges clamped. */
    private float sampleDetail(float u, float v) {
        if (sunDetail == null) {
            return 0.5f;
        }
        float ww = sunDetailW - 1.001f;
        float hh = sunDetailH - 1.001f;
        u = clamp(u, 0f, ww);
        v = clamp(v, 0f, hh);
        int x0 = (int) u;
        int y0 = (int) v;
        float fx = u - x0;
        float fy = v - y0;
        int i00 = y0 * sunDetailW + x0;
        int row1 = y0 + 1 < sunDetailH ? y0 + 1 : y0;
        int i01 = row1 * sunDetailW + x0;
        float top = sunDetail[i00]
                + (sunDetail[y0 * sunDetailW + x0 + 1] - sunDetail[i00]) * fx;
        float bottom = sunDetail[i01]
                + (sunDetail[row1 * sunDetailW + x0 + 1] - sunDetail[i01]) * fx;
        return (top + (bottom - top) * fy) * (1f / 255f);
    }

    /**
     * The surface: one equirectangular heat map, sampled on the ball's own
     * unit sphere so the noise lives on the sphere and never stretches with
     * an image's sheet.
     *
     * Scale order of the photograph: broad hot tongues, the mottled cells
     * inside them, fine granulation, bright specks, few large cool regions
     * and the black-red lanes. Then HIS OWN filaments, read through two
     * planar projections at two scales. Then a blur (fire is smooth at a
     * few pixels' scale; raw noise reads as sandpaper), the rank
     * normalisation, the levels stretch, and the fine detail laid back on.
     */
    private void buildSunSurface() {
        int count = SUN_MAP_W * SUN_MAP_H;
        float[] heat = new float[count];
        for (int row = 0; row < SUN_MAP_H; row++) {
            float latitude = (0.5f - (row + 0.5f) / SUN_MAP_H)
                    * (float) Math.PI;
            float cosLat = (float) Math.cos(latitude);
            float sinLat = (float) Math.sin(latitude);
            for (int col = 0; col < SUN_MAP_W; col++) {
                float longitude = ((col + 0.5f) / SUN_MAP_W - 0.5f)
                        * (float) (2f * Math.PI);
                float nx = cosLat * (float) Math.cos(longitude);
                float nz = cosLat * (float) Math.sin(longitude);
                float ny = sinLat;
                // The warp: three low fields fold the body before it is read.
                float wx = fbm3(nx * 2.3f + 3.1f, ny * 2.3f - 1.7f,
                        nz * 2.3f + 5.3f, 2) - 0.5f;
                float wy = fbm3(nx * 2.3f - 7.9f, ny * 2.3f + 4.3f,
                        nz * 2.3f - 2.1f, 2) - 0.5f;
                float wz = fbm3(nx * 2.3f + 11.7f, ny * 2.3f + 8.1f,
                        nz * 2.3f + 1.3f, 2) - 0.5f;
                float px = nx + 0.34f * wx;
                float py = ny + 0.34f * wy;
                float pz = nz + 0.34f * wz;
                float tongueN = fbm3(px * 4.2f + 9f, py * 4.2f - 4f,
                        pz * 4.2f + 2f, 4);
                float ridge = 1f - Math.abs(2f * tongueN - 1f);
                float tongue = ridge * ridge;
                float cell = fbm3(px * 9f, py * 9f, pz * 9f, 5, 0.55f);
                float grain = fbm3(px * 22f + 31f, py * 22f - 13f,
                        pz * 22f + 7f, 4);
                float vein = fbm3(px * 10f - 5f, py * 10f + 11f,
                        pz * 10f - 19f, 3);
                float veinRidge = 1f - Math.abs(2f * vein - 1f);
                float lane = 1f - (float) Math.pow(veinRidge, 8f);
                float spec = fbm3(px * 52f + 17f, py * 52f - 23f,
                        pz * 52f + 41f, 3);
                float sparkle = clamp((spec - 0.66f) * 7f, 0f, 1f);
                sparkle *= sparkle;
                float coolN = fbm3(px * 2.6f + 5f, py * 2.6f - 2f,
                        pz * 2.6f + 9f, 3);
                float cool = smoothstep(0.56f, 0.26f, coolN);
                float v = 0.54f
                        + (tongue - 0.45f) * 0.30f
                        + (cell - 0.5f) * 0.34f
                        + (grain - 0.5f) * 0.18f
                        + sparkle * 0.20f
                        - cool * 0.46f
                        - lane * 0.10f;
                // His flames at two scales: the wide filaments that shape
                // the body, then a finer pass over them, so the fire has
                // depth instead of one blob size.
                float size = sunDetailW > 0 ? sunDetailW - 1.001f : 1f;
                float coarse = sampleDetail((px * 0.5f + 0.5f) * size,
                        (py * 0.5f + 0.5f) * size) * 0.6f
                        + sampleDetail((pz * 0.5f + 0.5f) * size,
                        (py * 0.5f + 0.5f) * size) * 0.4f;
                float fine = sampleDetail(mirrorDetail(
                                px * 1.05f * size + 40f), 
                                mirrorDetail(py * 1.05f * size + 90f)) * 0.5f
                        + sampleDetail(mirrorDetail(
                                pz * 1.05f * size + 70f),
                                mirrorDetail(px * 1.05f * size + 20f)) * 0.5f;
                v = v * 0.62f + (coarse - 0.5f) * 0.30f
                        + (fine - 0.5f) * 0.14f;
                heat[row * SUN_MAP_W + col] = v;
            }
        }
        heat = boxBlurHeat(heat, 1);
        // Rank normalisation: a field that clusters around its mean is the
        // flat, moulded look he rejected. Sorted, it spans the palette.
        int bins = 1024;
        int[] histogram = new int[bins];
        for (int i = 0; i < count; i++) {
            int bin = (int) (clamp(heat[i], 0f, 0.9999f) * bins);
            histogram[bin]++;
        }
        float[] cdf = new float[bins];
        int run = 0;
        for (int b = 0; b < bins; b++) {
            run += histogram[b];
            cdf[b] = run / (float) count;
        }
        sunSurface = new int[count];
        for (int i = 0; i < count; i++) {
            int bin = (int) (clamp(heat[i], 0f, 0.9999f) * bins);
            float rank = cdf[bin] * 0.85f;
            // The fine filaments go back on at a low amplitude, so the
            // ball has micro texture without salt-and-pepper.
            float detail = sampleDetail(mirrorDetail(
                    (i % SUN_MAP_W) * 1.7f + 11f),
                    mirrorDetail((i / SUN_MAP_W) * 1.7f + 33f));
            rank += (detail - 0.5f) * 0.30f;
            // A levels stretch: the photograph runs from near black to
            // white, and a field that sits in the middle reads as a peach.
            rank = (rank - 0.5f) * 1.38f + 0.47f;
            sunSurface[i] = (int) (clamp(rank, 0f, 1f) * 255f);
        }
    }

    /** Mirror the detail sheet's coordinates, so its tiling has no seam. */
    private float mirrorDetail(float u) {
        if (sunDetailW <= 0) {
            return 0f;
        }
        float span = 2f * (sunDetailW - 1f);
        float m = u % span;
        if (m < 0f) {
            m += span;
        }
        return m > sunDetailW - 1f ? span - m : m;
    }

    /** Separable box blur of the heat field: wrapped in longitude, clamped. */
    private static float[] boxBlurHeat(float[] src, int radius) {
        int w = SUN_MAP_W;
        int h = SUN_MAP_H;
        float[] tmp = new float[src.length];
        float[] out = new float[src.length];
        float norm = 1f / (2 * radius + 1);
        for (int y = 0; y < h; y++) {
            int row = y * w;
            for (int x = 0; x < w; x++) {
                float sum = 0f;
                for (int d = -radius; d <= radius; d++) {
                    int sx = (x + d) % w;
                    if (sx < 0) {
                        sx += w;
                    }
                    sum += src[row + sx];
                }
                tmp[row + x] = sum * norm;
            }
        }
        for (int x = 0; x < w; x++) {
            for (int y = 0; y < h; y++) {
                float sum = 0f;
                for (int d = -radius; d <= radius; d++) {
                    int sy = y + d;
                    if (sy < 0) {
                        sy = 0;
                    } else if (sy > h - 1) {
                        sy = h - 1;
                    }
                    sum += tmp[sy * w + x];
                }
                out[y * w + x] = sum * norm;
            }
        }
        return out;
    }

    /**
     * The glow, baked once per size. It is light in the air, not a ring: a
     * gaussian peaking at the limb plus a wide tail, its strength value
     * noise at three scales, and its ink warm (the palette's amber end),
     * because pale cream at low alpha over black reads as grey.
     */
    private void buildSunHalo() {
        int haloD = Math.max(8, (int) (ballR * 2f * SUN_HALO));
        int[] pixels = new int[haloD * haloD];
        float mid = haloD / 2f;
        float radius = Math.max(ballR, 1f);
        for (int j = 0; j < haloD; j++) {
            float ry = (j + 0.5f - mid) / radius;
            for (int i = 0; i < haloD; i++) {
                float rx = (i + 0.5f - mid) / radius;
                float rad = (float) Math.sqrt(rx * rx + ry * ry);
                float n = fbm3(rx * 2.6f + 5f, ry * 2.6f - 2f, 4.1f, 4);
                float n2 = fbm3(rx * 7.5f - 1f, ry * 7.5f + 6f, 8.3f, 4);
                float n3 = fbm3(rx * 19f + 3f, ry * 19f - 5f, 2.9f, 3);
                float wisp = clamp(0.35f + 0.85f * n + 0.55f * n2
                        + 0.30f * n3, 0f, 1.6f);
                float inner = (float) Math.exp(
                        -Math.pow((rad - 1f) / 0.20f, 2));
                float tail = rad > 1f
                        ? (float) Math.exp(-(rad - 1f) / 0.24f) * 0.30f
                        : 0f;
                float fall = Math.max(inner, tail);
                fall *= 0.40f + 0.55f * clamp(wisp - 0.35f, 0f, 1f);
                float alpha = clamp(fall, 0f, 1f)
                        * clamp((rad - 0.95f) / 0.04f, 0f, 1f);
                alpha *= clamp(0.90f - 0.20f * ry, 0.55f, 1.25f) * 0.72f;
                if (alpha <= 0.002f) {
                    continue;
                }
                int ink = sunHeat[(int) (clamp(0.24f + 0.30f * wisp,
                        0f, 1f) * 255f)];
                pixels[j * haloD + i] = (Math.min(255, (int) (alpha * 255f))
                        << 24) | (ink & 0x00FFFFFF);
            }
        }
        halo = Bitmap.createBitmap(haloD, haloD, Bitmap.Config.ARGB_8888);
        halo.setPixels(pixels, 0, haloD, 0, 0, haloD, haloD);
    }

    /** One colour of the owner's palette, at the given position. */
    private static int rampMix(int a, int b, float k) {
        int red = (int) (((a >> 16) & 0xFF) + (((b >> 16) & 0xFF)
                - ((a >> 16) & 0xFF)) * k);
        int green = (int) (((a >> 8) & 0xFF) + (((b >> 8) & 0xFF)
                - ((a >> 8) & 0xFF)) * k);
        int blue = (int) ((a & 0xFF) + ((b & 0xFF) - (a & 0xFF)) * k);
        return 0xFF000000 | (red << 16) | (green << 8) | blue;
    }

    /**
     * Fractal value noise on the unit sphere: the octaves are sampled in
     * three dimensions, so the granulation is isotropic everywhere and
     * the map carries no pole stretch and no longitude seam.
     */
    private static float fbm3(float x, float y, float z, int octaves) {
        return fbm3(x, y, z, octaves, 0.5f);
    }

    /** The same fractal sum, with the octave gain named by the caller. */
    private static float fbm3(float x, float y, float z, int octaves,
            float gain) {
        float total = 0f;
        float amplitude = 1f;
        float norm = 0f;
        for (int o = 0; o < octaves; o++) {
            total += noise3(x, y, z) * amplitude;
            norm += amplitude;
            x *= 2.03f;
            y *= 2.03f;
            z *= 2.03f;
            amplitude *= gain;
        }
        return total / norm;
    }

    /** Trilinear value noise over a hashed integer lattice. */
    private static float noise3(float x, float y, float z) {
        int ix = (int) Math.floor(x);
        int iy = (int) Math.floor(y);
        int iz = (int) Math.floor(z);
        float u = fade(x - ix);
        float v = fade(y - iy);
        float w = fade(z - iz);
        float c000 = hash3(ix, iy, iz);
        float c100 = hash3(ix + 1, iy, iz);
        float c010 = hash3(ix, iy + 1, iz);
        float c110 = hash3(ix + 1, iy + 1, iz);
        float c001 = hash3(ix, iy, iz + 1);
        float c101 = hash3(ix + 1, iy, iz + 1);
        float c011 = hash3(ix, iy + 1, iz + 1);
        float c111 = hash3(ix + 1, iy + 1, iz + 1);
        float x00 = c000 + (c100 - c000) * u;
        float x10 = c010 + (c110 - c010) * u;
        float x01 = c001 + (c101 - c001) * u;
        float x11 = c011 + (c111 - c011) * u;
        float y0 = x00 + (x10 - x00) * v;
        float y1 = x01 + (x11 - x01) * v;
        return y0 + (y1 - y0) * w;
    }

    /** The smoothstep the value noise interpolates with. */
    private static float fade(float t) {
        return t * t * t * (t * (t * 6f - 15f) + 10f);
    }

    /** One lattice corner of the noise, 0..1, from its integer cell. */
    private static float hash3(int x, int y, int z) {
        int n = x * 0x1f1f1f1f ^ y * 0x3b9aca07 ^ z * 0x27d4eb2d;
        n ^= n >>> 15;
        n *= 0x85ebca6b;
        n ^= n >>> 13;
        n *= 0xc2b2ae35;
        n ^= n >>> 16;
        return (n & 0xFFFF) / 65535f;
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
            // Owner order 2026-10-25 ("the big lines ... should be getting
            // a big small and then get bigger"): each filament's own breath,
            // one period, its own phase, and the breath carries its width
            // and its ink as well as its length, so the swell is visible
            // instead of lost in a straight line.
            float breathWave = (float) Math.sin(
                    seconds * 0.7f * MOTION_SCALE + linkPhase[l]);
            float widthBreath = 1f + 0.30f * breathWave;
            int alpha = (int) ((70f + 165f * toward) * wake
                    * (0.72f + 0.36f * widthBreath));
            linkPaint.setAlpha(Math.min(255, alpha));
            linkPaint.setStrokeWidth(linkWidth * (0.8f + 0.45f * toward)
                    * widthBreath);
            // The length swings around the filament's own MIDPOINT, so the
            // growth never detaches it from the nodes it joins.
            float breath = 1f + 0.20f * breathWave;
            float ax = screenX[a];
            float ay = screenY[a];
            float bx = screenX[b];
            float by = screenY[b];
            float midX = (ax + bx) / 2f;
            float midY = (ay + by) / 2f;
            canvas.drawLine(midX + (ax - midX) * breath,
                    midY + (ay - midY) * breath,
                    midX + (bx - midX) * breath,
                    midY + (by - midY) * breath, linkPaint);
        }
        for (int n = 0; n < NODES; n++) {
            int o = n * NODE_STRIDE;
            float toward = clamp((depth[n] - 1f) / 0.6f, 0f, 1f);
            // v2.2.1: the 1.4Hz shimmer term is GONE - it read as flicker
            // on a real screen. The node keeps its depth scaling alone,
            // motion smooth and slow.
            float size = nodeRadius * (0.6f + 0.9f * toward);
            int alpha = (int) ((95f + 160f * toward) * wake);
            nodePaint.setAlpha(Math.min(255, alpha));
            nodePaint.setColor(NODE_COLOR);
            canvas.drawCircle(screenX[n], screenY[n], size, nodePaint);
        }
    }

    /**
     * The refined fade (owner order 2026-10-24): a link keeps its full
     * ink out to 0.14 and is GONE by 0.42 - the v2.2.1 numbers drew to
     * 0.55 and let the longest threads cross the whole ball, which is
     * the tangle the owner sent back.
     */
    private float linkFade(float dist) {
        return 1f - clamp((dist - 0.14f) / 0.28f, 0f, 1f);
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

    /** Smooth 0..1 ramp, the sun's ring and edge in one place. */
    private static float smoothstep(float a, float b, float v) {
        float t = clamp((v - a) / (b - a), 0f, 1f);
        return t * t * (3f - 2f * t);
    }

    /**
     * The pair cap: O(N^2) once at build, never on the frame path.
     * v2.2.1: NODES x 4 grew 30% to NODES x 26 / 5 (4 x 1.3 = 5.2) - the
     * owner's "increase the number of lines by another 30%" order, applied
     * to the only line budget this feature keeps.
     */
    private static int linkBudget() {
        return NODES * 26 / 5;
    }

    private float dp(float dp) {
        return dp * getResources().getDisplayMetrics().density;
    }
}
