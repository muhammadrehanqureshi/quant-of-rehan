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
 * The thinking orb (v2.3.3).
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
 *   v2.2.8  the picture projections were retired and the centre became a
 *           RENDERED SPHERE.
 *   v2.3.0  the fake rays were deleted and the surface raised to a noise
 *           photograph at 448x224.
 *   v2.3.1  one heat field folded through his palette, a boil, eruptions,
 *           a bloom, and filaments that breathe in width and ink.
 *   v2.3.2  sharper fire and longer eruption cores.
 *
 * Owner order 2026-10-25, sixth pass: "you made the sun transparent, SUN is
 * a solid entity, make it solid, make it look high quality", "the very left
 * one is my own uploaded photo, and I would really love to have that same
 * exact render, and then you can make it revolve just like the Earth does",
 * with "the outside revolving lines are still not breathing" and "few
 * independent dots without any lines". Four answers, and not one of them is
 * another noise field:
 *
 *   1. THE BALL IS HIS PICTURE. Noise can only approximate fire, which is
 *      why every procedural pass since v2.2.9 came back as "PS2 graphics".
 *      The surface is the photograph itself (drawable-nodpi/sun.jpg), never
 *      a generated field: its fire crop is wrapped onto the sphere as a
 *      planet map and its rim is the crown below.
 *   2. IT REVOLVES LIKE THE EARTH. One shared longitude shift per frame
 *      (his 10% cut kept), read through the sphere's own latitude, so the
 *      fire slides limb to limb with foreshortening in both directions
 *      instead of a flat sheet scrolling behind a circle. The crop travels
 *      on a TRIANGLE wrap, because his disc is an orthographic view and not
 *      a texture: wrapped as a disc, one quarter turn collapsed the face
 *      into a single column and dragged his bright ring through the
 *      middle. The triangle makes the turn rigid, so nothing collapses.
 *   3. IT IS SOLID. A pixel inside the disc is opaque; only the outermost
 *      pixel of the edge carries partial coverage. The ball's alpha is
 *      still the wake alone, so a solid ball cannot flicker.
 *   4. THE CROWN IS FIXED. A star's limb is bright because of where the
 *      light leaves it, not because of what pattern sits under it: his
 *      picture's own rim is sampled once per screen angle and blended back
 *      at the limb every frame, so the edge blazes while the fire turns.
 *
 * The cloud answers the other two sentences: every node now wears at least
 * one filament (no naked dots), the filament fade bottoms out above zero
 * (a link at the cap used to be painted at alpha zero, which is exactly the
 * invisible thread), and the breath is nearly tripled, so the outer lines
 * visibly swell and thin instead of changing length by a few percent.
 *
 * The park law of v1.9.14 stands: stop() freezes the pose the loop last
 * DREW and the parked frame REPAINTS it fully awake, so a closed market, a
 * break, a theme repaint or a layout pass can never blank the feature; the
 * loop only stops MOVING. A resume replays from the frozen second.
 *
 * The budget stands too: one View, zero relay requests, zero allocations on
 * the frame path. The cloud's nodes and links, and the sun's planet map,
 * crown, frame tables, bloom buffers and glow are all built once in
 * onSizeChanged; every frame touches preallocated arrays. start() and
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
    /** The planet map: the owner's own photograph wrapped onto a sphere. */
    private int[] sunMap;
    /** The photograph's rim, one ink per screen angle: the steady crown. */
    private int[] sunCrown;
    /** The crown's average ink, which tints the glow. */
    private int crownInk;
    /**
     * The sphere's frame tables, baked once per size: the map column each
     * ball pixel reads at zero spin, the map row it reads, the ball's own
     * direction there (the eruptions are lit from it), the photograph's
     * crown index and its blend weight at that place on the limb, and the
     * pixel's edge coverage. Nothing here is computed on the frame path
     * but the one shared spin.
     */
    private float[] sphereU;
    private float[] sphereV;
    private float[] sphereX;
    private float[] sphereY;
    private float[] sphereZ;
    private float[] sphereRim;
    private int[] sphereCrown;
    private int[] sphereCover;
    /** The destination square the ball fills, preallocated for the frame. */
    private final RectF ballDst = new RectF();

    /**
     * The ball's own render resolution. It is SET BY THE TEXTURE, not by the
     * phone: his fire crop carries about 146 pixels across, so a 320 pixel
     * buffer only interpolated it (that is what read as soft, "PS2" fire).
     * 192 still supersamples the 154 pixel ball the handset draws, and every
     * texel above that is invented detail anyway.
     */
    private static final int SUN_RENDER = 192;

    /**
     * The planet map. Row 0 is the top of the ball and the last row its
     * bottom; the columns are the sphere's longitudes. The visible face
     * reads HALF the columns, which is his crop exactly at zero spin.
     */
    private static final int SUN_MAP_W = 640;
    private static final int SUN_MAP_H = 320;

    /** The standing tilt: the pose; the longitude carries the motion. */
    private static final float SUN_AXIS_TILT = 10f;
    /** One revolution of the sphere's own longitude. */
    private static final float SUN_LAP = (float) (2f * Math.PI);

    /**
     * His photograph's own disc, as a fraction of its half side: the crown
     * blazes at 0.85 of the half side and has fallen away by 0.90, so the
     * disc edge is 0.86 and the glow beyond it is the baked halo's.
     */
    private static final float SUN_BALL_EDGE = 0.86f;
    /**
     * The crop the ball is made of, again as a fraction of that disc. The
     * whole disc cannot be the texture: it is an orthographic VIEW, so one
     * quarter turn of a sphere wearing it collapses the face into a single
     * column (the streaks) and drags its bright ring through the middle (the
     * band). This crop is the uniform fire inside the ring, and the ring
     * itself is the fixed crown below. 0.62 keeps his own filaments at close
     * to one texel per screen pixel on the handset.
     */
    private static final float SUN_CROP = 0.62f;

    /**
     * The fixed crown: the picture's rim, sampled once per screen angle and
     * blended back in at the limb every frame, because a star's edge is
     * bright from its own light and not from whatever pattern is under it.
     */
    private static final int SUN_CROWN = 512;
    private static final float SUN_CROWN_AT = 0.96f;
    private static final float SUN_CROWN_IN = 0.90f;
    private static final float SUN_CROWN_OUT = 0.995f;
    private static final float SUN_HOT = 0.25f;

    /**
     * The grade his picture needs to survive the crop. The crop sits in the
     * photograph's darker middle (a mean luminance near 110 where the disc
     * runs to 240), so the body is lifted and its darks are held by a
     * contrast curve, and the result is his own fire, not a milky blur.
     */
    private static final float SUN_CONTRAST = 1.22f;
    private static final float SUN_GAIN = 1.45f;
    private static final float SUN_GAMMA = 0.88f;

    /** The eruptions lift his own texels toward white; they draw nothing. */
    private static final float SUN_FLARE = 0.45f;

    /**
     * The bloom: a quarter-resolution bright pass, blurred and added back.
     * The knee is high, so only the plasma and the eruptions bleed; a low
     * knee blurs the whole disc and washes it out.
     */
    private static final int SUN_BLOOM = 64;
    private static final int SUN_BLOOM_CELL = SUN_RENDER / SUN_BLOOM;
    private static final int SUN_BLOOM_KNEE = 228;
    private static final float SUN_BLOOM_ADD = 0.26f;

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
        linkWidth = Math.max(1f, dp(1.1f));
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
        // v2.3.3 (owner order 2026-10-25, "few independent dots without any
        // lines"): every node must wear at least one filament. A node whose
        // neighbours all sat beyond the cap used to be drawn as a naked
        // dot, so each orphan now joins its own nearest neighbour whatever
        // the distance, and the fade's floor keeps that thread visible.
        boolean[] joined = new boolean[NODES];
        for (int l = 0; l < linkCount; l++) {
            joined[linkA[l]] = true;
            joined[linkB[l]] = true;
        }
        for (int i = 0; i < NODES && linkCount < linkBudget(); i++) {
            if (joined[i]) {
                continue;
            }
            int nearest = -1;
            float nearestDist = Float.MAX_VALUE;
            for (int j = 0; j < NODES; j++) {
                if (j == i) {
                    continue;
                }
                float dx = cloud[i * NODE_STRIDE] - cloud[j * NODE_STRIDE];
                float dy = cloud[i * NODE_STRIDE + 1]
                        - cloud[j * NODE_STRIDE + 1];
                float dz = cloud[i * NODE_STRIDE + 2]
                        - cloud[j * NODE_STRIDE + 2];
                float dist = (float) Math.sqrt(dx * dx + dy * dy + dz * dz);
                if (dist < nearestDist) {
                    nearestDist = dist;
                    nearest = j;
                }
            }
            if (nearest < 0) {
                continue;
            }
            linkA[linkCount] = i;
            linkB[linkCount] = nearest;
            linkDist[linkCount] = nearestDist;
            linkPhase[linkCount] = 2.39996f * linkCount;
            linkCount++;
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
     * The centre is a RENDERED SPHERE wearing the owner's own photograph:
     * the glow goes down first, then the ball, whose face is his picture
     * read through the frame's longitude.
     *
     * Nothing on this path pumps the ball's alpha: its ink is the wake
     * alone, the fire moves in the map and in the eruptions, and the glow
     * is one baked bitmap. That is how a picture burns continuously
     * without ever flickering (the owner's own order).
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
     * One frame of the sphere. Each ball pixel reads HIS photograph at the
     * frame's longitude, blends in the picture's own rim at the limb, and
     * lifts whatever eruptions are burning over it. Then the bloom pass
     * lets the hottest plasma bleed.
     *
     * The ball is SOLID (owner order 2026-10-25, "SUN is a solid entity,
     * make it solid"): a pixel inside the disc is opaque, and only the
     * outermost pixel of the edge carries partial coverage.
     *
     * The whole loop is array reads and multiply-adds on preallocated
     * tables: no allocation, no trigonometry, no texture object.
     */
    private void renderSunBall(float phi) {
        stepEruptions(sunSeconds, phi);
        float spin = phi / SUN_LAP * SUN_MAP_W;
        int count = SUN_RENDER * SUN_RENDER;
        for (int k = 0; k < count; k++) {
            int cover = sphereCover[k];
            if (cover == 0) {
                sunScratch[k] = 0;
                continue;
            }
            // His picture, read at the frame's own longitude.
            int rgb = sampleMap(sphereU[k] + spin, sphereV[k]);
            float rim = sphereRim[k];
            if (rim > 0f) {
                rgb = mixInk(rgb, sunCrown[sphereCrown[k]], rim);
            }
            // The eruptions lift the texels they cover toward white, so a
            // burst reads as his plasma flaring and not as a drawn shape.
            float px = sphereX[k];
            float py = sphereY[k];
            float pz = sphereZ[k];
            float flare = 0f;
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
                flare += (q3 * 0.20f + q8 * 0.55f) * energy;
            }
            if (flare > 0f) {
                rgb = mixInk(rgb, 0xFFFFFF, Math.min(1f, flare * SUN_FLARE));
            }
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
     * One bilinear read of the planet map. The columns wrap (longitude is a
     * circle); the rows are clamped, because the ball never reads past them.
     */
    private int sampleMap(float u, float v) {
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
        int a = sunMap[r0 * SUN_MAP_W + c0];
        int b = sunMap[r0 * SUN_MAP_W + c1];
        int c = sunMap[r1 * SUN_MAP_W + c0];
        int d = sunMap[r1 * SUN_MAP_W + c1];
        int red = bilinearChannel(a, b, c, d, fu, fv, 16);
        int green = bilinearChannel(a, b, c, d, fu, fv, 8);
        int blue = bilinearChannel(a, b, c, d, fu, fv, 0);
        return 0xFF000000 | (red << 16) | (green << 8) | blue;
    }

    /** One channel of a bilinear read over four corner colours. */
    private static int bilinearChannel(int a, int b, int c, int d,
            float fu, float fv, int shift) {
        float top = ((a >> shift) & 0xFF)
                + (((b >> shift) & 0xFF) - ((a >> shift) & 0xFF)) * fu;
        float bottom = ((c >> shift) & 0xFF)
                + (((d >> shift) & 0xFF) - ((c >> shift) & 0xFF)) * fu;
        return (int) (top + (bottom - top) * fv + 0.5f);
    }

    /** One colour moved toward another, channel by channel, edges clamped. */
    private static int mixInk(int from, int to, float k) {
        int red = (int) (((from >> 16) & 0xFF) + (((to >> 16) & 0xFF)
                - ((from >> 16) & 0xFF)) * k);
        int green = (int) (((from >> 8) & 0xFF) + (((to >> 8) & 0xFF)
                - ((from >> 8) & 0xFF)) * k);
        int blue = (int) ((from & 0xFF) + ((to & 0xFF) - (from & 0xFF)) * k);
        return 0xFF000000 | (clampInt(red, 0, 255) << 16)
                | (clampInt(green, 0, 255) << 8) | clampInt(blue, 0, 255);
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
     * The sphere, baked once per size: the planet map off his photograph,
     * the picture's rim, the frame tables and the glow. Never on the frame
     * path.
     */
    private void buildSunSphere() {
        buildSunMap();
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
        sphereRim = new float[count];
        sphereCrown = new int[count];
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
        // The edge is ONE pixel of anti-aliasing, not a fade: a sun is a
        // solid body (owner order 2026-10-25, "SUN is a solid entity").
        float feather = 1.15f / half;
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
                float rn = (float) Math.sqrt(d2);
                // His fire, read at the sphere's own longitude and
                // latitude. At zero spin this IS his crop; the one shared
                // spin then slides it limb to limb with foreshortening.
                float longitude = (float) Math.atan2(x, z);
                sphereU[k] = (longitude / SUN_LAP + 0.5f) * SUN_MAP_W;
                float latitude = (float) Math.asin(clamp(y, -1f, 1f));
                sphereV[k] = (0.5f - latitude / (float) Math.PI)
                        * (SUN_MAP_H - 1);
                sphereX[k] = x;
                sphereY[k] = y;
                sphereZ[k] = z;
                // The picture's rim at this place on the limb, which does
                // not turn with the fire under it.
                float ang = (float) Math.atan2(y, x);
                int crown = (int) ((ang + (float) Math.PI) / SUN_LAP
                        * SUN_CROWN);
                sphereCrown[k] = crown >= SUN_CROWN ? 0 : crown;
                sphereRim[k] = smoothstep(SUN_CROWN_IN, SUN_CROWN_OUT, rn);
                sphereCover[k] = (int) (255f * clamp((1f - rn) / feather,
                        0f, 1f));
            }
        }
        buildSunHalo();
    }

    /**
     * The planet map, built once: his photograph wrapped onto the sphere.
     *
     * At zero spin the visible face is his crop exactly, one texel of his
     * fire per texel of the ball. The columns run the crop's own width over
     * the visible half turn and then mirror it for the hidden half, so a
     * revolution is a rigid slide and the join is a mirror line rather than
     * a seam: there is no second disc and no edge to see.
     */
    private void buildSunMap() {
        int count = SUN_MAP_W * SUN_MAP_H;
        sunMap = new int[count];
        sunCrown = new int[SUN_CROWN];
        Bitmap photo = null;
        try {
            photo = BitmapFactory.decodeResource(getResources(),
                    R.drawable.sun);
        } catch (RuntimeException ignored) {
            // No picture is no excuse to invent one (SO-3).
        }
        if (photo == null) {
            // A missing asset is reported as a plain disc, never as a fake
            // photograph: his fire is his, and nothing here invents it.
            for (int i = 0; i < count; i++) {
                sunMap[i] = 0xFFAA3A0E;
            }
            for (int i = 0; i < SUN_CROWN; i++) {
                sunCrown[i] = 0xFFF3B051;
            }
            crownInk = 0xFFF3B051;
            return;
        }
        int w = photo.getWidth();
        int h = photo.getHeight();
        int[] pixels = new int[w * h];
        photo.getPixels(pixels, 0, w, 0, 0, w, h);
        photo.recycle();
        float midX = w / 2f;
        float midY = h / 2f;
        float disc = Math.min(w, h) / 2f * SUN_BALL_EDGE;
        float crop = disc * SUN_CROP;
        for (int row = 0; row < SUN_MAP_H; row++) {
            float latitude = (0.5f - (row + 0.5f) / SUN_MAP_H)
                    * (float) Math.PI;
            float py = midY + crop * (float) Math.sin(latitude);
            for (int col = 0; col < SUN_MAP_W; col++) {
                float longitude = ((col + 0.5f) / SUN_MAP_W - 0.5f)
                        * (float) (2f * Math.PI);
                // The triangle wrap: linear across the visible half turn,
                // mirrored behind it. His crop slides round the sphere as a
                // rigid texture, so a quarter turn is a quarter turn and
                // never a collapse into one column.
                float swing = (float) Math.asin(Math.sin(longitude));
                float px = midX + swing * (2f / (float) Math.PI) * crop;
                sunMap[row * SUN_MAP_W + col] =
                        gradeInk(samplePhoto(pixels, w, h, px, py));
            }
        }
        long red = 0L;
        long green = 0L;
        long blue = 0L;
        for (int i = 0; i < SUN_CROWN; i++) {
            float ang = i * (float) (2f * Math.PI) / SUN_CROWN;
            float px = midX + (float) Math.cos(ang) * disc * SUN_CROWN_AT;
            float py = midY + (float) Math.sin(ang) * disc * SUN_CROWN_AT;
            int ink = mixInk(gradeInk(samplePhoto(pixels, w, h, px, py)),
                    0xFFFFFF, SUN_HOT);
            sunCrown[i] = ink;
            red += (ink >> 16) & 0xFF;
            green += (ink >> 8) & 0xFF;
            blue += ink & 0xFF;
        }
        crownInk = 0xFF000000
                | ((int) (red / SUN_CROWN) << 16)
                | ((int) (green / SUN_CROWN) << 8)
                | (int) (blue / SUN_CROWN);
    }

    /** His picture's own tonality, applied once to every texel of the map. */
    private static int gradeInk(int ink) {
        return 0xFF000000
                | (gradeChannel((ink >> 16) & 0xFF) << 16)
                | (gradeChannel((ink >> 8) & 0xFF) << 8)
                | gradeChannel(ink & 0xFF);
    }

    /** One channel of the grade: contrast about the middle, then a lift. */
    private static int gradeChannel(int value) {
        float v = (value / 255f - 0.5f) * SUN_CONTRAST + 0.52f;
        v = clamp(v, 0f, 1f) * SUN_GAIN;
        v = (float) Math.pow(clamp(v, 0f, 1f), SUN_GAMMA);
        return (int) (clamp(v, 0f, 1f) * 255f + 0.5f);
    }

    /** One bilinear read of the photograph, edges clamped. */
    private static int samplePhoto(int[] pixels, int w, int h,
            float x, float y) {
        x = clamp(x, 0f, w - 1.001f);
        y = clamp(y, 0f, h - 1.001f);
        int x0 = (int) x;
        int y0 = (int) y;
        int x1 = x0 + 1 < w ? x0 + 1 : x0;
        int y1 = y0 + 1 < h ? y0 + 1 : y0;
        float fx = x - x0;
        float fy = y - y0;
        int a = pixels[y0 * w + x0];
        int b = pixels[y0 * w + x1];
        int c = pixels[y1 * w + x0];
        int d = pixels[y1 * w + x1];
        int red = bilinearChannel(a, b, c, d, fx, fy, 16);
        int green = bilinearChannel(a, b, c, d, fx, fy, 8);
        int blue = bilinearChannel(a, b, c, d, fx, fy, 0);
        return 0xFF000000 | (red << 16) | (green << 8) | blue;
    }

    /**
     * The glow, baked once per size. It is light in the air, not a ring: a
     * gaussian peaking at the limb plus a wide tail, its strength value
     * noise at three scales, and its ink his picture's own rim, because
     * pale cream at low alpha over black reads as grey.
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
                int ink = mixInk(crownInk, 0xFFFFF2C0,
                        clamp(0.10f + 0.55f * wisp, 0f, 1f));
                pixels[j * haloD + i] = (Math.min(255, (int) (alpha * 255f))
                        << 24) | (ink & 0x00FFFFFF);
            }
        }
        halo = Bitmap.createBitmap(haloD, haloD, Bitmap.Config.ARGB_8888);
        halo.setPixels(pixels, 0, haloD, 0, 0, haloD, haloD);
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
            // a big small and then get bigger"), answered again in v2.3.3
            // because the phone showed "still not breathing": the breath
            // carries the filament's width and its ink as well as its
            // length, and the swing is tripled, so it is unmistakable.
            float breathWave = (float) Math.sin(
                    seconds * 0.55f * MOTION_SCALE + linkPhase[l]);
            float widthBreath = 1f + 0.60f * breathWave;
            int alpha = (int) ((70f + 165f * toward) * wake
                    * (0.55f + 0.55f * widthBreath));
            linkPaint.setAlpha(Math.min(255, alpha));
            linkPaint.setStrokeWidth(linkWidth * (0.8f + 0.45f * toward)
                    * widthBreath);
            // The length swings around the filament's own MIDPOINT, so
            // both ends breathe outward and inward together instead of the
            // whole line sliding off the nodes it joins.
            float breath = 1f + 0.30f * breathWave;
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
     * ink out to 0.14 and fades to a fifth by 0.42 - the v2.2.1 numbers
     * drew out to 0.55 and let the longest threads cross the whole ball,
     * which is the tangle the owner sent back.
     */
    private float linkFade(float dist) {
        // The floor is what killed the "independent dots without any
        // lines": a link at the 0.42 cap used to be painted at alpha
        // ZERO, so its two nodes sat there looking unconnected.
        return 1f - 0.80f * clamp((dist - 0.14f) / 0.28f, 0f, 1f);
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
