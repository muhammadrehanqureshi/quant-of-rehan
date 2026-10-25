package pk.quantofrehan;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.RadialGradient;
import android.graphics.RectF;
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
 *     * "I want the center as the sun": the cloud's old breathing core gradient
     * is replaced by the ALWAYS-BURNING SUN v1.9.9 built and v1.9.14 made
     * hotter - flame tongues on the limb and the spark cadence drawn at the
     * cloud's own centre, so the organism circles a star instead of a light.
     * * Owner order 2026-10-23 (v2.2.1, eighth pass): three edits
     * the owner listed in one message.
     *
     * 1. No flicker: every fast alpha modulation on the picture is gone.
     *    The node shimmer term, the harsh flame length bounce and the deep
     *    cell-breath dimming all read as flicker on a real screen; the
     *    motion that remains is slow rotation and gentle breathing only,
     *    so the organism turns but never strobes.
     * 2. Brighter everywhere: the link ink is the fire family now
     *    (orangish/yellow, the owner's own words), the node ink is warm
     *    gold, and every alpha floor is raised, so the whole feature
     *    reads hot instead of dark.
     * 3. More lines: the pair cap grows 30% (owner's own figure) and the
     *    link threshold widens, so the cloud carries visibly more
     *    filaments; and the sun itself grows from 17% to 26% of the
     *    feature's radius, a proper star at the centre.
     *
     * Owner order 2026-10-25 ("fix the sun, that looked so bad, you just
     * turned a 3D SUN into two disc slices type crap, also don't flicker
     * my SUN"): the centre is a RENDERED SPHERE. Every picture projection
     * is retired - a flat photograph covers one hemisphere and the mirror
     * that covers the rest is the two-discs join he kept catching - and the
     * fire is put on the ball's own body instead: a surface baked once on
     * the unit sphere, its palette read from his own sun picture, and each
     * frame's longitude travelling over it. The ball never pulses: its
     * alpha is the wake alone and its shade is baked, so it turns without
     * a flicker.
     *
     * Owner order 2026-10-25, second pass ("I want my SUN looking like this
     * ... with fire like features burning", "don't have the curve lines
     * that were moving just outside the sun"): the ball wears the
     * photograph's own crown now, the wide amber band and the white-hot
     * edge pinned to the radii his sun carries them at, so it reads as the
     * blazing star he sent rather than a mottled orange disc. The thin
     * curved arcs that revolved at the limb are deleted with their book
     * keeping, the flame tongues and the spark cadence stay so the fire
     * still burns, and the cloud and its laws are untouched.
     *
     * The park law of v1.9.14 stands: stop() freezes the pose the loop last
     * DREW and the parked frame REPAINTS it fully awake, so a closed market, a
     * break, a theme repaint or a layout pass can never blank the feature; the
     * loop only stops MOVING. A resume replays from the frozen second.
     *
     * The budget is the one that survived every pass: one View, zero relay
     * requests, zero allocations per frame - the cloud's nodes and links and
     * the sun's flames and flares are all built once in
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

    /** The node ink, warm gold in the sun's own family (v2.2.1). */
    private static final int NODE_COLOR = 0xFFFFD166;
    /** The link ink, the orangish/yellow the owner ordered (v2.2.1). */
    private static final int LINK_COLOR = 0xFFFFA62B;

    private final Paint linkPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint nodePaint = new Paint(Paint.ANTI_ALIAS_FLAG);

    /**
     * The sun's fire (kept from v1.9.14): the flaming limb and the spark
     * painter, and the one paint that carries the rendered sphere (alpha
     * per frame, filtered scaling).
     */
    private final Paint sunPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    /** The baked halo's own paint: only its alpha moves, with the wake. */
    private final Paint sunHaloPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint sunFlame = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint sunFlare = new Paint(Paint.ANTI_ALIAS_FLAG);
    /** The steady halo glow, baked once per size beside the ball. */
    private Bitmap halo;
    /** The rendered sphere: one bitmap of the ball, reused every frame. */
    private Bitmap sunBall;
    /** The ball's own pixel buffer, refilled each frame, never reallocated. */
    private int[] sunBallPixels;
    /** The equirectangular surface, baked once per size from the palette. */
    private int[] sunSurface;
    /**
     * The sphere's frame tables, baked once per size: the longitude each
     * ball pixel reads at zero spin, the surface row it reads, the shade
     * the ball's own curvature gives it, the crown's two lifts and the
     * pixel's edge coverage. Nothing here is computed on the frame path
     * but the one shared spin.
     */
    private float[] sphereU;
    private float[] sphereV;
    private float[] sphereShade;
    private float[] sphereRing;
    private float[] sphereEdge;
    private int[] sphereCover;
    /** The destination square the ball fills, preallocated for the frame. */
    private final RectF ballDst = new RectF();
    /**
     * Owner order 2026-10-25 ("fix the sun ... you just turned a 3D SUN
     * into two disc slices type crap, also don't flicker my SUN"): the
     * centre is a RENDERED SPHERE and nothing less, and none of the
     * picture-projection machinery survives. See drawSun for the law.
     */
    private static final float SUN_AXIS_TILT = 10f;
    /** The ball's own render resolution: the sphere is shaded into this. */
    private static final int SUN_RENDER = 256;
    /** The surface map: equirectangular, baked once per size. */
    private static final int SUN_MAP_W = 256;
    private static final int SUN_MAP_H = 128;
    /**
     * The palette, read off the owner's own sun photograph: the ramp his
     * ORB.jpg shows, from the deep red of its cooler lanes to the near
     * white of its hottest granules. The photograph itself cannot be
     * revolved - a flat disc covers one hemisphere only, and the mirror
     * that covers the rest is the two-discs wreckage he kept sending
     * back - so its COLOURS seed the surface and the sphere owns the
     * geometry.
     */
    private static final int[] SUN_RAMP = {
            0xFF480C02, 0xFF7F1902, 0xFFBC421D, 0xFFE27C28,
            0xFFF5A947, 0xFFFFDB69, 0xFFFCFBA1, 0xFFFFFFD6,
    };
    private static final float[] SUN_STOP = {
            0.00f, 0.18f, 0.38f, 0.55f, 0.70f, 0.82f, 0.92f, 1.00f,
    };
    /** How far the ball's own limb lifts its fire, and its bright ring. */
    private static final float SUN_LIMB_FLOOR = 0.90f;
    private static final float SUN_LIMB_GAIN = 0.38f;
    /**
     * The owner's own ring (owner order 2026-10-25, "I want my SUN looking
     * like this"): the photograph's wide amber band and its white-hot
     * edge, pinned to the same radii his sun carries them at, so the ball
     * reads as the blazing crowned star he sent rather than a mottled
     * orange disc.
     */
    private static final float SUN_RING_IN = 0.42f;
    private static final float SUN_RING_OUT = 0.78f;
    private static final float SUN_RING_LIFT = 0.55f;
    private static final float SUN_EDGE_IN = 0.78f;
    private static final float SUN_EDGE_OUT = 0.96f;
    /** The rim's own antialiasing width, in render pixels. */
    private static final float SUN_FEATHER = 1.3f;
    /**
     * The halo's own reach, as a multiple of the ball's radius: baked
     * ONCE per size into a bitmap (buildSunSphere), so the frame only
     * alpha-drives it, never a per-frame shader and never a flicker term.
     */
    private static final float SUN_HALO = 1.55f;
    /** One revolution of the sphere's own longitude. */
    private static final float SUN_LAP = (float) (2f * Math.PI);
    /**
     * Owner order 2026-10-24 ("right now the SUN itself is not revolving,
     * it's just like a picture there, standing still, make it revolving"):
     * the surface TRAVELS. The bake puts the granulation on the ball's own
     * body and the render reads it through the frame's longitude, so the
     * fire slides limb to limb the way the Earth's turn reads from space.
     */
    private static final float SUN_SPIN_RATE = 0.35f;
    /**
     * Owner order 2026-10-24, fifth pass ("reduce its revolving speed by
     * 10% from the current speed"): the bearing above runs at 10% under
     * the speed the owner last saw, carried as one named factor so the
     * pace stays one decision.
     */
    private static final float SUN_SLOWDOWN = 0.9f;

    /** Flame tongues around the limb: angle, length, phase, rate. */
    private static final int FLAMES = 12;
    private final float[] flameAngle = new float[FLAMES];
    private final float[] flameLength = new float[FLAMES];
    private final float[] flamePhase = new float[FLAMES];
    private final float[] flameRate = new float[FLAMES];

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
    /**
     * Owner order 2026-10-24, fourth pass ("the lines that are moving
     * outside the SUN, make them look like they are breathing, like
     * the lines will get a bit short and then will get long"): each
     * filament gets its own breath phase, one golden-angle step apart,
     * so the mesh breathes with a ripple instead of every line
     * twitching in unison. Preallocated once per size, like the rest
     * of the link bookkeeping.
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
        buildSun();
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
        // Owner order 2026-10-24 ("the lines that are revolving the SUN,
        // they look very tangled, make them untangled and make them look
        // nice and refined"): the pair threshold narrows from the v2.2.1
        // 0.62 to 0.42, so a link is a short filament inside its own
        // neighbourhood and never a long chord crossing the ball; the
        // fade at the bottom of this file steepens to match, so whatever
        // length the threshold leaves quietly drops away before it can
        // cross another neighbourhood. The v2.2.1 pair cap stands.
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

    /**
     * The sun's fire: flames and sparks. Owner order 2026-10-25: the thin
     * curved arcs that revolved on the limb are GONE ("don't have the
     * curve lines that were moving just outside the sun ... those little
     * curve lines that were moving as well on the SUN"), so the limb
     * carries fire alone.
     */
    private void buildSun() {
        long seed = 20261024L;
        for (int f = 0; f < FLAMES; f++) {
            flameAngle[f] = (float) Math.PI * 2f * f / FLAMES;
            seed = nextSeed(seed);
            flameLength[f] = 0.12f + frac(seed) * 0.10f;
            seed = nextSeed(seed);
            flamePhase[f] = frac(seed) * (float) Math.PI * 2f;
            seed = nextSeed(seed);
            flameRate[f] = 1.5f + frac(seed) * 1.5f;
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

    /** The paints: the rendered ball first, then the limb's own fire. */
    private void buildInks() {
        linkPaint.setStyle(Paint.Style.STROKE);
        linkPaint.setStrokeCap(Paint.Cap.ROUND);
        linkPaint.setColor(LINK_COLOR);
        nodePaint.setStyle(Paint.Style.FILL);
        // The sun is the rendered sphere (owner order 2026-10-25): the
        // ball bitmap is drawn scaled with filtering, its alpha the
        // wake's. No shader of ours repaints the ball.
        sunPaint.setFilterBitmap(true);

        // The flame tongues share the same soft trick at the limb.
        sunFlame.setShader(new RadialGradient(0f, 0f, dp(9f), new int[]{
                0xCCFFC96A, 0x66FF8F00, 0x00FF8F00},
                new float[]{0f, 0.5f, 1f}, Shader.TileMode.CLAMP));

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
        drawFlames(canvas, seconds, wake);
        drawSun(canvas, seconds, wake);
        drawFlares(canvas, seconds, wake);
    }

    /**
     * Owner order 2026-10-25 ("fix the sun, that looked so bad, you just
     * turned a 3D SUN into two disc slices type crap, also don't flicker
     * my SUN"): the centre is a RENDERED SPHERE.
     *
     * The picture projections are retired for good. A flat photograph
     * covers one hemisphere of a sphere and nothing else; wrapping it into
     * a loop means laying it beside its own mirror, and the moment that
     * loop turns, some frame shows half of the disc joined to half of its
     * mirror. That join IS the two-discs wreckage the owner kept sending
     * back, and no phase offset, melt band or strip height could hide it,
     * because it lives in the geometry, not in the filter.
     *
     * So the fire is put ON the sphere instead: the surface is baked once
     * as an equirectangular map sampled on the ball's own unit sphere (the
     * noise lives on the sphere, not on a sheet), the palette comes from
     * the owner's own sun photograph, and each frame reads that surface
     * through the frame's longitude. Every ball pixel carries the sphere's
     * own latitude and its own place on the turning body, so the
     * granulation slides limb to limb with real foreshortening in BOTH
     * directions, and no frame can show a join: the map is continuous by
     * construction and wraps in longitude without a seam.
     *
     * The shade is the curvature: a steady limb lift plus the photograph's
     * own crown, both baked into the frame tables. Nothing on this path
     * pulses - the ball breathes in nothing, its alpha is the wake alone,
     * and the halo is one baked bitmap - which is the owner's "don't
     * flicker my SUN" order of the same pass.
     */
    private void drawSun(Canvas canvas, float seconds, float wake) {
        if (sunBall == null) {
            return;     // no sphere built, no picture invented (SO-3)
        }
        // The halo first, under everything: one baked bitmap, its alpha
        // only the wake - steady, never a flicker term.
        float haloHalf = halo.getWidth() / 2f;
        sunHaloPaint.setAlpha((int) (175f * wake));
        canvas.drawBitmap(halo, cx - haloHalf, cy - haloHalf, sunHaloPaint);
        // The bearing: the owner's own pace under the owner's own 10% cut.
        float phi = seconds * SUN_SPIN_RATE * MOTION_SCALE * SUN_SLOWDOWN;
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
     * One frame of the sphere: fill the ball's buffer from the baked
     * surface, reading each pixel at the frame's longitude. Every table
     * this loop touches was baked once per size, and the only arithmetic
     * per pixel is the wrapped map read and the baked shade, so the ball
     * can turn every frame without allocating or stuttering.
     */
    private void renderSunBall(float phi) {
        // The spin as a number of map columns: longitude is uniform in
        // the map, so one frame is one shared shift for every pixel.
        float spin = phi / SUN_LAP * SUN_MAP_W;
        int count = SUN_RENDER * SUN_RENDER;
        for (int k = 0; k < count; k++) {
            int cover = sphereCover[k];
            if (cover == 0) {
                sunBallPixels[k] = 0;
                continue;
            }
            float u = sphereU[k] + spin;
            u = u % SUN_MAP_W;
            if (u < 0f) {
                u += SUN_MAP_W;
            }
            int c0 = (int) u;
            int c1 = c0 + 1 == SUN_MAP_W ? 0 : c0 + 1;
            float fu = u - c0;
            float v = sphereV[k];
            int r0 = (int) v;
            int r1 = r0 + 1 < SUN_MAP_H ? r0 + 1 : r0;
            float fv = v - r0;
            int a = sunSurface[r0 * SUN_MAP_W + c0];
            int b = sunSurface[r0 * SUN_MAP_W + c1];
            int c = sunSurface[r1 * SUN_MAP_W + c0];
            int d = sunSurface[r1 * SUN_MAP_W + c1];
            float w00 = (1f - fu) * (1f - fv);
            float w10 = fu * (1f - fv);
            float w01 = (1f - fu) * fv;
            float w11 = fu * fv;
            float shade = sphereShade[k];
            float ring = sphereRing[k];
            float edge = sphereEdge[k];
            float redLift = 255f * ring + 255f * edge;
            float greenLift = 200f * ring + 250f * edge;
            float blueLift = 95f * ring + 215f * edge;
            int red = (int) ((((a >> 16) & 0xFF) * w00
                    + ((b >> 16) & 0xFF) * w10
                    + ((c >> 16) & 0xFF) * w01
                    + ((d >> 16) & 0xFF) * w11) * shade + redLift);
            int green = (int) ((((a >> 8) & 0xFF) * w00
                    + ((b >> 8) & 0xFF) * w10
                    + ((c >> 8) & 0xFF) * w01
                    + ((d >> 8) & 0xFF) * w11) * shade + greenLift);
            int blue = (int) (((a & 0xFF) * w00 + (b & 0xFF) * w10
                    + (c & 0xFF) * w01 + (d & 0xFF) * w11) * shade
                    + blueLift);
            sunBallPixels[k] = (cover << 24)
                    | (Math.min(255, Math.max(0, red)) << 16)
                    | (Math.min(255, Math.max(0, green)) << 8)
                    | Math.min(255, Math.max(0, blue));
        }
        sunBall.setPixels(sunBallPixels, 0, SUN_RENDER, 0, 0,
                SUN_RENDER, SUN_RENDER);
    }

    /**
     * The sphere, baked once per size: the surface map, the frame tables
     * and the halo. Never on the frame path.
     */
    private void buildSunSphere() {
        buildSunSurface();
        int count = SUN_RENDER * SUN_RENDER;
        sunBall = Bitmap.createBitmap(SUN_RENDER, SUN_RENDER,
                Bitmap.Config.ARGB_8888);
        sunBallPixels = new int[count];
        sphereU = new float[count];
        sphereV = new float[count];
        sphereShade = new float[count];
        sphereRing = new float[count];
        sphereEdge = new float[count];
        sphereCover = new int[count];
        float half = SUN_RENDER / 2f;
        float feather = SUN_FEATHER / half;
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
                float limb = 1f - z;
                sphereShade[k] = SUN_LIMB_FLOOR
                        + SUN_LIMB_GAIN * limb * limb;
                sphereRing[k] = smoothstep(SUN_RING_IN, SUN_RING_OUT, limb)
                        * SUN_RING_LIFT;
                sphereEdge[k] = smoothstep(SUN_EDGE_IN, SUN_EDGE_OUT, limb);
                float edge = (1f - (float) Math.sqrt(d2)) / feather;
                sphereCover[k] = (int) (255f * Math.min(1f, edge));
            }
        }
        buildSunHalo();
    }

    /**
     * The surface: one equirectangular map, sampled on the ball's own unit
     * sphere so the noise lives on the sphere and never stretches with an
     * image's sheet. Three value-noise fields - the coarse cells, the
     * granulation grain and a slow region term - are summed and coloured
     * through the owner's own palette. Baked once per size.
     */
    private void buildSunSurface() {
        sunSurface = new int[SUN_MAP_W * SUN_MAP_H];
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
                float coarse = fbm3(nx * 6.5f, ny * 6.5f, nz * 6.5f, 4);
                float grain = fbm3(nx * 13f + 11f, ny * 13f - 7f,
                        nz * 13f + 3f, 3);
                float region = fbm3(nx * 1.9f + 41f, ny * 1.9f + 9f,
                        nz * 1.9f - 23f, 2);
                float v = (0.66f * coarse + 0.34f * grain)
                        * (0.80f + 0.40f * region);
                v = clamp((v - 0.22f) / 0.50f, 0f, 1f);
                sunSurface[row * SUN_MAP_W + col] = sunRamp(v);
            }
        }
    }

    /** The steady halo, baked once per size: alpha only moves with the wake. */
    private void buildSunHalo() {
        int haloD = Math.max(2, (int) (ballR * 2f * SUN_HALO));
        halo = Bitmap.createBitmap(haloD, haloD, Bitmap.Config.ARGB_8888);
        Canvas warm = new Canvas(halo);
        Paint glow = new Paint(Paint.ANTI_ALIAS_FLAG);
        glow.setShader(new RadialGradient(haloD / 2f, haloD / 2f, haloD / 2f,
                new int[]{0x80FFC24A, 0x2AFFA726, 0x00000000},
                new float[]{0f, 0.55f, 1f}, Shader.TileMode.CLAMP));
        warm.drawCircle(haloD / 2f, haloD / 2f, haloD / 2f, glow);
    }

    /** One colour of the owner's palette, at the given position. */
    private static int sunRamp(float t) {
        int last = SUN_STOP.length - 1;
        for (int s = 1; s <= last; s++) {
            if (t <= SUN_STOP[s]) {
                float span = SUN_STOP[s] - SUN_STOP[s - 1];
                float k = span <= 0f ? 0f : (t - SUN_STOP[s - 1]) / span;
                return rampMix(SUN_RAMP[s - 1], SUN_RAMP[s], k);
            }
        }
        return SUN_RAMP[last];
    }

    /** Linear mix of two opaque colours, the ramp's own blend. */
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
        float total = 0f;
        float amplitude = 1f;
        float norm = 0f;
        for (int o = 0; o < octaves; o++) {
            total += noise3(x, y, z) * amplitude;
            norm += amplitude;
            x *= 2.03f;
            y *= 2.03f;
            z *= 2.03f;
            amplitude *= 0.5f;
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
        // v2.2.1: floor 16 to 70 and reach 96 to 165, the brightness
        // order; v2.2.4: the refined filament draws thinner as it
        // recedes, 0.85+0.65 narrowed to 0.8+0.45, so the mesh reads as
        // fine hair instead of a tangled net.
            int alpha = (int) ((70f + 165f * toward) * wake);
            linkPaint.setAlpha(Math.min(255, alpha));
            linkPaint.setStrokeWidth(linkWidth * (0.8f + 0.45f * toward));
            // Owner order 2026-10-24, fourth pass ("the lines that are
            // moving outside the SUN, make them look like they are
            // breathing, like the lines will get a bit short and then
            // will get long"): every filament SHORTENS to a bit short
            // and reaches back out to a bit long, one breath period,\n            // each link a golden-angle step apart. The breath shrinks
            // the line around its own MIDPOINT, so the swing never
            // detaches the filament from the nodes it joins.
            float breath = 1f + 0.12f * (float) Math.sin(
                    seconds * 0.7f * MOTION_SCALE + linkPhase[l]);
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
     * The limb: flame tongues that always breathe around the burning
     * edge, so the rim is never a perfect circle.
     */
    private void drawFlames(Canvas canvas, float seconds, float wake) {
        for (int f = 0; f < FLAMES; f++) {
            float angle = flameAngle[f] + 0.07f * (float) Math.sin(
                    seconds * flameRate[f] * MOTION_SCALE + flamePhase[f]);
            // v2.2.1: both the length swing and the alpha swing narrow
            // (0.55/0.55 to 0.72/0.28, 0.4/0.6 to 0.75/0.25) and the rate
            // multiplier drops 1.7x to 1.1x - the rim rolls instead of
            // strobing.
            // v2.2.5: the swing narrows again (0.72/0.28 to 0.82/0.18) -
            // the tongue breathes in LENGTH alone, its ink now steady,
            // because the alpha swing was the flicker the owner sent
            // back. The alpha floor stands below.
            float len = flameLength[f] * (0.82f + 0.18f * (float) Math.sin(
                    seconds * flameRate[f] * 1.1f * MOTION_SCALE
                            + flamePhase[f] * 2f));
            if (len < 0.02f) {
                continue;
            }
            canvas.save();
            canvas.translate(cx + ballR * (float) Math.cos(angle),
                    cy + ballR * (float) Math.sin(angle));
            sunFlame.setAlpha(Math.min(255, (int) (200f * wake)));
            canvas.drawCircle(0f, 0f, ballR * len, sunFlame);
            canvas.restore();
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
     * to the only line budget this feature keeps. The widened pair
     * threshold below is what actually spends the cap.
     */
    private static int linkBudget() {
        return NODES * 26 / 5;
    }

    private float dp(float dp) {
        return dp * getResources().getDisplayMetrics().density;
    }
}
