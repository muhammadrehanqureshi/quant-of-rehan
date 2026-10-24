package pk.quantofrehan;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.PorterDuff;
import android.graphics.PorterDuffXfermode;
import android.graphics.Matrix;
import android.graphics.RadialGradient;
import android.graphics.Rect;
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
     * hotter - flame tongues on the limb, revolving prominence arcs and the
     * spark cadence drawn at the cloud's own centre, so the organism circles
     * a star instead of a light.
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
     * Owner order 2026-10-24 (ninth pass, THE order): the drawn ball at the
     * centre is RETIRED and the centre is the owner's own sun picture now -
     * the sun he cropped out of the picture he sent ("replace with the
     * picture that I just attached... only take the SUN looking feature,
     * don't touch anything else"), bundled once as drawable-nodpi/sun.jpg -
     * his ORB.jpg with the sun's square built out around its centre, the
     * HUD panels of the frame he sent cropped away by that square.
     * The picture is composed ONCE per size - clamped to a circle at the
     * limb, a short fade softening the clip edge - and each frame only ever
     * draws that composed disc, breathing gently in size and riding the wake
     * in alpha. The limb's own fire (flame tongues, revolving prominence
     * arcs and the spark cadence) stays where it is, and the cloud and its
     * laws stay untouched: the picture IS the sun, everything else is the
     * living organism as it was on the screen he asked to keep.
     *
     * The park law of v1.9.14 stands: stop() freezes the pose the loop last
     * DREW and the parked frame REPAINTS it fully awake, so a closed market, a
     * break, a theme repaint or a layout pass can never blank the feature; the
     * loop only stops MOVING. A resume replays from the frozen second.
     *
     * The budget is the one that survived every pass: one View, zero relay
     * requests, zero allocations per frame - the cloud's nodes and links and
     * the sun's flames, prominences and flares are all built once in
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
     * The sun's fire and picture (kept from v1.9.14): the flaming limb and
     * the spark painter, and the one paint that carries the composed photo
     * disc of the owner's own sun (alpha per frame, filtered scaling).
     */
    private final Paint sunPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint sunFlame = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint sunProm = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint sunFlare = new Paint(Paint.ANTI_ALIAS_FLAG);
    /** The owner's own sun picture, composed once per size. */
    private Bitmap sunPhoto;
    /**
     * The crop's own fill: the shipped asset was squared out around the
     * sun with a 1.18 margin (side = 2 x sun radius x 1.18), so the
     * disc's inscribed square holds the sun at 1/1.18 of its half side.
     * drawSun divides by this to land the picture's own sun on the
     * radius the drawn ball it replaced held.
     */
    private static final float SUN_SCALE = 1.18f;
    /**
     * The longitude draw's own pair of rect books (one source, one dest),
     * preallocated: every band of every frame reuses them and nothing is
     * ever allocated on the frame path.
     */
    private final Rect bandSrc = new Rect();
    private final RectF bandDst = new RectF();
    /**
     * Owner order 2026-10-24, fifth pass ("make the SUN revolve in
     * X-axis"): the face's plane leans by this many degrees, the way the
     * Earth's own axis leans, so the travel visibly reads as a revolve
     * about a tilted axis rather than a flat slide. Static: the tilt is
     * the pose, the travel supplies all the motion.
     */
    private static final float SUN_AXIS_TILT = 10f;
    /**
     * The longitude sample count: at the phone's silver sizes this keeps
     * the mapping visually smooth and well inside the frame budget.
     */
    private static final int SUN_STRIPS = 40;
    /** One revolution of the face's longitude loop. */
    private static final float SUN_LAP = (float) (2f * Math.PI);
    /**
     * Owner order 2026-10-24 ("right now the SUN itself is not revolving,
     * it's just like a picture there, standing still, make it revolving"):
     * the face TRAVELS - the photo is redrawn in longitude bands each
     * frame (drawSun), so the sun's own granulation slides from limb to
     * limb the way the Earth's turn reads from space, instead of the
     * picture standing still.
     */
    private static final float SUN_SPIN_RATE = 0.35f;
    /**
     * Owner order 2026-10-24, fifth pass ("reduce its revolving speed by
     * 10% from the current speed"): the bearing above runs at 10% under
     * the speed the owner last saw, carried as one named factor so the
     * pace stays one decision.
     */
    private static final float SUN_SLOWDOWN = 0.9f;

    /** The one Path the prominence arcs share; reset, never reallocated. */
    private final Path promPath = new Path();

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
        // The sun is the cloud's own core: the owner's own PICTURE now
        // (owner order 2026-10-24), sized by the same fraction the drawn
        // ball held - 0.26f, the bigger-sun order of v2.2.1 - so the
        // photo's own sun lands exactly where the ball he replaced stood
        // (drawSun scales the destination by SUN_SCALE for that).
        ballR = orbRadius * 0.26f;
        nodeRadius = dp(1.3f);
        linkWidth = Math.max(1f, dp(0.9f));
        clockAnchor = System.currentTimeMillis();
        buildGeometry();
        buildSun();
        buildInks();
        buildSunPhoto();
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

    /** The sun's fire: flames, prominences, sparks (v1.9.14 kept). */
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

    /** The paints: the photo disc first, then the limb's own fire. */
    private void buildInks() {
        linkPaint.setStyle(Paint.Style.STROKE);
        linkPaint.setStrokeCap(Paint.Cap.ROUND);
        linkPaint.setColor(LINK_COLOR);
        nodePaint.setStyle(Paint.Style.FILL);
        // The sun is the owner's own picture (owner order 2026-10-24):
        // the composed disc is drawn scaled with filtering, its alpha the
        // wake's. No shader of ours repaints his photograph.
        sunPaint.setFilterBitmap(true);

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
        drawFlames(canvas, seconds, wake);
        drawProminences(canvas, seconds, wake);
        drawSun(canvas, seconds, wake);
        drawFlares(canvas, seconds, wake);
    }

    /**
     * Owner order 2026-10-24: the centre is the owner's own sun picture,
     * the composed disc of buildSunPhoto. It draws AFTER the cloud and
     * the limb fire, so the organism reads as circling its star and the
     * picture's disc sits clean over the tongues' inner halves; the
     * flares keep drawing after it, so a spark can still fly across the
     * face. The disc breathes gently in size and rides the wake in
     * alpha, exactly the never-goes-dark law the drawn ball kept.
     */
    /**
     * The revolve (owner order 2026-10-24, fifth pass, "make the SUN
     * revolve in X-axis and reduce its revolving speed by 10% from the
     * current speed", on the v2.2.5 build he still sent back for
     * flicker): the flat in-plane rotate is RETIRED - turning a whole
     * photograph in the plane is what read as flicker - and the face
     * now TRAVELS the way the Earth's turn reads from space: the photo
     * is resampled in SUN_STRIPS longitude bands each frame, band i
     * drawing the texture where asin(2x/r - 1) puts its line, so the
     * face's own granulation slides from limb to limb with a real
     * foreshortening at the edges while the composed rim's radial fade
     * and the circular clip hide the fold. The axis leans the owner's
     * SUN_AXIS_TILT, so the travel reads as a revolve in X. The pace is
     * the third pass's bearing under the owner's own 10% cut
     * (SUN_SLOWDOWN), and every term rides the frame clock, so the
     * frozen-second park law holds the pose for free.
     */
    private void drawSun(Canvas canvas, float seconds, float wake) {
        if (sunPhoto == null) {
            return;     // no asset, no picture invented in its place (SO-3)
        }
        float breath = 1f + 0.015f * (float) Math.sin(
                seconds * 0.9f * MOTION_SCALE);
        // The asset holds the sun at 1/SUN_SCALE of its half side (see
        // the constant's note), so scaling the destination UP by that
        // factor renders the picture's own sun at the ball radius the
        // drawn sun he retired carried.
        float r = ballR * SUN_SCALE * breath;
        sunPaint.setAlpha((int) (255f * wake));
        canvas.save();
        // The standing tilt: the pose; the longitude carries the motion.
        canvas.rotate(SUN_AXIS_TILT, cx, cy);
        // The longitude line: band i takes destination x in [-r, r], maps
        // it by the asin(2x/r - 1) of a sphere to the longitude visible
        // there, and rides the bearing across the texture.
        float phi = seconds * SUN_SPIN_RATE * MOTION_SCALE * SUN_SLOWDOWN;
        for (int i = 0; i < SUN_STRIPS; i++) {
            float x0 = 2f * r * i / SUN_STRIPS;
            float x1 = 2f * r * (i + 1) / SUN_STRIPS;
            float u0 = clamp(x0 / r - 1f, -1f, 1f);
            float u1 = clamp(x1 / r - 1f, -1f, 1f);
            drawFaceBand(canvas,
                    cx - r + x0, cx - r + x1, cy - r, cy + r,
                    phi + (float) Math.asin(u0),
                    phi + (float) Math.asin(u1));
        }
        canvas.restore();
    }

    /**
     * One longitude band of the face: the destination strip [x0, x1] x
     * [y0, 1] draws the texture's longitude window [lam0, lam1]; the
     * texture is the seam-free loop of buildSunPhoto, so a band whose
     * window crosses the loop's edge splits into two draws instead of
     * a seam. Built once, preallocated, never allocated on the frame
     * path.
     */
    private void drawFaceBand(Canvas canvas, float x0, float x1,
            float y0, float y1, float lam0, float lam1) {
        float texW = sunPhoto.getWidth();
        int texH = sunPhoto.getHeight();
        float span = (lam1 - lam0) / SUN_LAP * texW;
        float s0 = mod01(lam0 / SUN_LAP) * texW;
        float s1 = s0 + span;
        if (s1 <= texW) {
            paintFaceBand(canvas, x0, x1, y0, y1, s0, s1, texH);
            return;
        }
        // The window crosses the loop's own edge: two draws, split where
        // the texture runs out, so the face never shows a jump line.
        float cut = x0 + (x1 - x0) * (texW - s0) / span;
        paintFaceBand(canvas, x0, cut, y0, y1, s0, texW, texH);
        paintFaceBand(canvas, cut, x1, y0, y1, 0f, s1 - texW, texH);
    }

    /** One continuous (non-wrapping) window into the seam-free loop. */
    private void paintFaceBand(Canvas canvas, float x0, float x1,
            float y0, float y1, float s0, float s1, int texH) {
        if (x1 - x0 < 0.25f || s1 - s0 < 0.25f) {
            return;     // the asin fold's sliver at either limb
        }
        bandSrc.set((int) Math.round(s0), 0,
                Math.max((int) Math.round(s0) + 1,
                        (int) Math.round(s1)), texH);
        bandDst.set(x0, y0, x1, y1);
        canvas.drawBitmap(sunPhoto, bandSrc, bandDst, sunPaint);
    }

    /** Wrap a fraction into [0, 1): the loop's own modulus. */
    private static float mod01(float v) {
        return ((v % 1f) + 1f) % 1f;
    }

    /**
     * The owner's own sun (owner order 2026-10-24): the SUN ONLY of the
     * picture he sent, bundled once as drawable-nodpi/sun.jpg. Composed
     * ONCE per size and never on the frame path: the square carried over
     * drawable-nodpi keeps its own pixels, they are clamped to a circle
     * at the limb, and a short DST_OUT fade softens the very rim so the
     * clip edge never shows the way a coin edge would.
     *
     * The seam-free loop (owner order 2026-10-24, fifth pass): the face
     * now resamples in longitude bands, and a plain square would re-enter
     * its left edge from its right edge at the tube of the lap - a seam.
     * So the composed side is laid down beside ITS OWN MIRROR, each half
     * rim-faded and circle-clipped: every edge column of the loop is
     * shared by identical pixels, and the longitude line can cross the
     * fold without a jump. The asset is recycled off; the frame only
     * ever draws the composed loop.
     */
    private void buildSunPhoto() {
        Bitmap asset = BitmapFactory.decodeResource(
                getResources(), R.drawable.sun);
        if (asset == null) {
            sunPhoto = null;    // no asset, no faked picture (SO-3)
            return;
        }
        int size = Math.max(96, Math.min(768, asset.getWidth()));
        // The disc once: clip to the circle, fade the rim, exactly the
        // composition the drawn-ball era drew.
        Bitmap disc = Bitmap.createBitmap(size, size, Bitmap.Config.ARGB_8888);
        Canvas work = new Canvas(disc);
        Path circle = new Path();
        circle.addCircle(size / 2f, size / 2f, size / 2f, Path.Direction.CW);
        work.clipPath(circle);
        work.drawBitmap(asset, new Rect(0, 0, size, size),
                new Rect(0, 0, size, size), null);
        // The rim fade: transparent over the burn, opaque only at the
        // very edge, punched OUT of the composed disc.
        Paint rim = new Paint(Paint.ANTI_ALIAS_FLAG);
        rim.setShader(new RadialGradient(size / 2f, size / 2f, size / 2f,
                new int[]{0x00000000, 0x00000000, 0xFF000000},
                new float[]{0f, 0.86f, 1f}, Shader.TileMode.CLAMP));
        rim.setXfermode(new PorterDuffXfermode(PorterDuff.Mode.DST_OUT));
        work.drawCircle(size / 2f, size / 2f, size / 2f, rim);
        // The loop: the disc and its own mirror, so every longitude seam
        // is pixels meeting themselves and the wrap cannot show.
        sunPhoto = Bitmap.createBitmap(size * 2, size,
                Bitmap.Config.ARGB_8888);
        Canvas loop = new Canvas(sunPhoto);
        loop.drawBitmap(disc, 0f, 0f, null);
        Matrix mirror = new Matrix();
        mirror.setScale(-1f, 1f);
        mirror.postTranslate(size * 2f, 0f);
        loop.drawBitmap(disc, mirror, null);
        asset.recycle();
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
            sunFlame.setAlpha(Math.min(255, (int) (170f * wake)));
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
            sunProm.setAlpha(Math.min(255, (int) (185f * wake)));
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
