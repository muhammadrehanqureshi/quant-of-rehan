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
 * The thinking orb (v2.3.8).
 *
 * The feature is the v1.8.9 LIVING PARTICLE CLOUD the owner first approved:
 * 105 nodes gathered around five cluster anchors, joined by fine links,
 * turning rigidly in yaw with a breathing pitch and projected in
 * perspective, every node breathing radially on its own phase, around an
 * always-burning sun. v2.3.7 retuned the gather to an even shell; the
 * owner sent back the SAME screenshots: "you ruined the animating feature,
 * the LINES are looking absolute horseshit, change them back" - so the
 * clusters are back.
 *
 *   v2.3.8  (owner order 2026-10-26, tenth pass): three answers.
 *     1. THE CLUSTERS ARE BACK. The even shell opened the mesh into
 *        structureless mesh the owner called horseshit - the one side
 *        crowded, the other empty was the RENDERED SPEECH, not the
 *        cloud itself. v1.8.9's cluster law is restored as it was.
 *     2. THE BREATH IS MIDDLE-STRENGTH AGAIN. The one fifth swing
 *        read as "the animating feature is ruined": the lines grew
 *        and shrank without living. The swing is back over the line
 *        length, and the ink is pinned to a MIDDLE-STRENGTH breath:
 *        the ALPHA breathes over a HARMONIC window so the ink never
 *        rises above its own trough nor hollows out into blink, on
 *        the owner's own phase.
 *     3. THE SUN REVOLVES ON ITS OWN THREAD. The pass runs on a
 *        DEDICATE thread with its own cadence (60ms), publishing the
 *        finished frame with post() AND making HUD draws sleep, so
 *        the pitch is bounded by the pass's own speed and nothing's
 *        velocity is throttled inside a gear that passes give or
 *        take. The bitmap is double buffered, so the wide frame is
 *        IN as a whole per upload.
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
 *   v2.3.3  the surface became his own photograph on a revolving sphere,
 *           solid, with a fixed crown at the limb.
 *   v2.3.4  the crown became a per-pixel limb curve and the glow moved into
 *           the ball's own bitmap; read back as "one outline" and "cheap".
 *   v2.3.5  the outline was the crown itself, so it is gone: his own rim
 *           and his own corona, read from the picture per screen angle,
 *           plus the pole dissolve and his darker lanes.
 *   v2.3.6  the corona's gain and smoothing are retuned to the blend the
 *           prototype grid showed, so his feathered orange fringe reads
 *           the way his own picture reads it.
 *   v2.3.7  the cloud is an EVEN shell (order of 2026-10-26: one side
 *           tangled, the other side no lines), the filament breath is
 *           one fifth its v2.3.3 swing with its ink floor lifted so
 *           nothing blinks ("everything is flickering", same order),
 *           and the sun's own surface pass runs at 60ms instead of on
 *           every frame, because a 256x256 pass inside a 33ms budget
 *           janked the fire into stutter ("the SUN is flickering").
 *
 * Owner order 2026-10-26, fourteenth pass: "the entire thing is still
 * flickering ... the animation looks really disgusting, and also flickering
 * continuously, remove the entire feature then add it again, and fix it.
 * 2.3.8 sun was good but you always ruin things." The pass that wrecked
 * it was v2.3.9's alpha-blend handover: every publish blended the fresh
 * bitmap at half alpha over the previous one, which is a ghosting pass
 * nobody approved and the phasing he kept seeing. So the v2.3.8 render is
 * restored whole, with three deltas and not one more:
 *
 *   1. THE CORONA IS THIN AGAIN. The owner's earlier order named "the
 *      thick orange outline just outside the SUN"; the gain stays at its
 *      v2.3.6 blend of 1.45, not the eighth pass's 1.75 bulge.
 *   2. THE HANDOVER IS THE HARD SWAP. The published picture is swapped
 *      whole, never blended: no half-alpha double image can phase on the
 *      screen.
 *   3. THE COMMITS ARE GATED. The render thread signs its bitmap and
 *      the handover swaps under one shared monitor, so a torn half-pass
 *      can never become the visible frame even if the swap races the
 *      pass.
 *
 * The speed chain stands, each cut on the rate itself: 0.35 * 0.85 =
 * 0.2975 (2026-10-26), 0.2975 * 0.9 = 0.26775 (2026-10-27, third pass),
 * 0.26775 * 0.9 = 0.240975 (2026-10-27, the owner's "Decrease the sun's
 * revolving speed by another 10%").
 * Owner order 2026-10-26, ninth pass, with the three phone screenshots:
 * "also, the AI looking feature, the SUN and the LINES every thing is
 * flickering, make it fucking stop, also, the lines are really tangled
 * and overlapping, on one side of the LINES there are so many tangled
 * lines and on the other side of the LINES there are literally no
 * LINES". Three answers, none of them new noise:
 *
 *   1. THE CLOUD IS AN EVEN SHELL. The v1.8.9 cluster gather put five
 *      anchor bundles in the same 3D space, so their projections
 *      collapsed into one crowded lobe with an empty opposite side, and
 *      that is exactly the screen he sent. A Fibonacci walk over the
 *      sphere puts every node about as far from its neighbours as every
 *      other, in every direction, so the web fills all the way around
 *      the sun.
 *   2. NOTHING BLINKS. The v2.3.3 breath swung each filament's ink
 *      between 0.1x and 1.4x, so 546 differently phased lines dipped to
 *      near-invisible alpha cyclically, and that cycle read as the
 *      whole feature flickering. The swing is one fifth now and the
 *      ink's factor floors at 0.90, so the breathing stays and the
 *      blinking goes.
 *   3. NO FRAME SKIPS THE BUDGET. The sun's surface pass (256x256, two
 *      map reads, seven eruptions, bloom and blur) refired inside every
 *      33ms frame; when it overran, whole frames dropped and the
 *      surface jumped, which is what he saw as the SUN flickering. The
 *      surface now refires at a 60ms cadence and the fire's own speed
 *      barely hides the difference.
 *
 * Owner order 2026-10-25, eighth pass: "I don't see the orange fuzz from
 * the reference photo's rim. Also that the sun's fringes aren't the same
 * categories" (as the reference photo). The seventh pass's face and rim
 * hold their settings; what they lacked was the fuzz's weight and
 * breadth: the corona's alpha gain rises from 1.45 to 1.75 and its
 * lobes widen from 15 to 19 steps of smoothing, the two settings the
 * prototype grid (sun-preview/emulate_v238.py, variant j, built against
 * his uploaded render as reference) showed bring the fringe from his own
 * picture, drawn from his own picture, so it cannot be another category.
 *
 * Owner order 2026-10-25, seventh pass: "there is this one outline on the
 * SUN and even the render of SUN looks really cheap, make it look very
 * realistic", with his picture attached again. He was right about the
 * outline, and it was this file's own: anything that is a function of the
 * screen radius draws a circle, whether it is a crown of one ink or a limb
 * curve of many. So the radius stops deciding the edge and his photograph
 * decides it instead.
 *
 *   1. THE RIM IS HIS. His picture's edge is sampled once per screen angle,
 *      averaged over four radii so no stray pixel can sparkle, and its
 *      brightness around the disc becomes the rim's own tongues and gaps.
 *      It turns with the surface, because it is the same fire.
 *   2. THE CORONA IS HIS. The light outside the disc is read from the same
 *      picture, one cell per angle and radius, with its alpha taken from
 *      the picture's own brightness: the flames end where his end, and no
 *      exponential glow is baked anywhere.
 *   3. THE POLES DISSOLVE. A sphere converges every longitude into its
 *      poles, and converging photographic detail reads as a woven seam.
 *      Where the mapping converges the fire gives way to the colour of its
 *      own map row, so the ball has no cap at either end.
 *   4. THE FIRE IS AS SHARP AS HIS PICTURE. The crop opens from 0.62 to
 *      0.75 of the disc so the face is nearer his own scale, the unsharp
 *      pass doubles, and a second read of the map keeps it churning.
 *   5. IT IS STILL SOLID, STILL ONE ALPHA. A pixel inside the disc is
 *      opaque, the ball's alpha is the wake alone, and it still revolves on
 *      one shared longitude shift under his 10% cut.
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
 *      a generated field.
 *   2. IT REVOLVES LIKE THE EARTH. One shared longitude shift per frame
 *      (his 10% cut kept), read through the sphere's own latitude, so the
 *      fire slides limb to limb with foreshortening in both directions
 *      instead of a flat sheet scrolling behind a circle. The crop travels
 *      on a TRIANGLE wrap, because his disc is an orthographic view and not
 *      a texture: wrapped as a disc, one quarter turn collapsed the face
 *      into a single column and dragged its bright ring through the middle.
 *   3. IT IS SOLID. A pixel inside the disc is opaque; only the outermost
 *      pixel of the edge carries partial coverage. The ball's alpha is
 *      still the wake alone, so a solid ball cannot flicker.
 *
 * The cloud answers the other two sentences: every node wears at least
 * one filament (no naked dots) and the filament fade bottoms out above
 * zero (a link at the cap used to be painted at alpha zero, which is
 * exactly the invisible thread); the breath keeps breathing, at the
 * gentler ninth-pass swing, so the lines pulse without blinking.
 *
 * The park law of v1.9.14 stands: stop() freezes the pose the loop last
 * DREW and the parked frame REPAINTS it fully awake, so a closed market, a
 * break, a theme repaint or a layout pass can never blank the feature; the
 * loop only stops MOVING. A resume replays from the frozen second.
 *
 * The budget stands too: one View, zero relay requests, zero allocations on
 * the frame path. The cloud's nodes and links, and the sun's planet map,
 * row means, rim and corona tables, frame tables and bloom buffers are all
 * built once in onSizeChanged; every frame touches preallocated arrays.
 * start() and
 * stop() stay the only public controls, wired to MainActivity's startHud
 * and stopHud behind the market gate.
 */

public class ThinkingOrb extends View {

    /** The population. Chosen once; more nodes would cost every frame. */
    private static final int NODES = 105;
    /** Cluster anchors the nodes are gathered around (restored). */
    private static final int CLUSTERS = 5;
    /** Per-node slots in the cloud[] record: x, y, z, breath, shimmer. */
    private static final int NODE_STRIDE = 5;
    /** Per-node pace of the frame loop, aimed at a smooth 30fps. */
    private static final long FPS_MS = 33L;
    /**
     * The sun's own render cadence (v2.3.8): its dedicated thread fires
     * the surface pass every 60ms, once before the first paint and then
     * forever. The VISIBLE picture is whole every upload, so nothing is
     * less than anything, and the fire's own speed (0.41 rad/s) sets a
     * floor the cadence stays under.
     */
    private static final long SUN_CADENCE_MS = 60L;

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

    /** The one paint that carries the ball and its glow. */
    private final Paint sunPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
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
    /** Each map row's own mean ink, which is what a pole can show. */
    private int[] mapRowInk;
    /** His rim: one ink and one height per screen angle, baked once. */
    private int[] ringInk;
    private float[] ringFlame;
    /** His corona: alpha and ink per angle and radius, baked once. */
    private int[] coronaInk;
    /**
     * The sphere's frame tables, baked once per size: the map column each
     * ball pixel reads at zero spin, the map row it reads, the ball's own
     * direction there (the eruptions are lit from it), its radius (the rim
     * and the pole dissolve are both functions of it), the screen angle it
     * faces (his rim is read there) and the pixel's coverage. Nothing here
     * is computed on the frame path but the one shared spin.
     */
    private float[] sphereU;
    private float[] sphereV;
    private float[] sphereX;
    private float[] sphereY;
    private float[] sphereZ;
    private float[] sphereRn;
    private int[] sphereAng;
    private int[] sphereCover;
    /** The destination square the ball fills, preallocated for the frame. */
    private final RectF ballDst = new RectF();

    /**
     * ONE bitmap holds the ball AND the light it throws. The disc's limb and
     * the fire beyond it are the same pixels, so there is no seam to see and
     * no ring drawn at a fixed radius: the rim is his own, sampled once per
     * screen angle, and the light outside it is his own corona, sampled once
     * per angle and radius. Both turn with the surface, so the tongues stay
     * attached to the fire that throws them.
     *
     * The ball is 96 pixels of the bitmap's 128, which leaves the corona its
     * reach without ever touching the bitmap's edge.
     */
    private static final int SUN_RENDER = 256;
    private static final float SUN_BALL = 96f;
    /** Where the light dies: the bitmap's own half width, in ball radii. */
    private static final float SUN_REACH = SUN_RENDER / 2f / SUN_BALL;


    /**
     * The planet map. Row 0 is the top of the ball and the last row its
     * bottom; the columns are the sphere's longitudes. The visible face
     * reads HALF the columns, which is his crop exactly at zero spin.
     */
    private static final int SUN_MAP_W = 512;
    private static final int SUN_MAP_H = 256;

    /** The standing tilt: the pose; the longitude carries the motion. */
    private static final float SUN_AXIS_TILT = 10f;
    /** One revolution of the sphere's own longitude. */
    private static final float SUN_LAP = (float) (2f * Math.PI);

    /**
     * His photograph's own disc, as a fraction of its half side: his rim
     * blazes at 0.85 of the half side and has fallen away by 0.90, so the
     * disc edge is 0.86.
     */
    private static final float SUN_BALL_EDGE = 0.86f;
    /**
     * The crop the ball is made of, again as a fraction of that disc. The
     * whole disc cannot be the texture, because it is a view and not a map,
     * and the crop must stay inside his rim or a quarter turn would drag the
     * rim through the face. 0.75 is as much of his own fire as that allows.
     */
    private static final float SUN_CROP = 0.75f;

    /**
     * The grade his picture needs to survive the crop: the crop sits in the
     * darker middle of the disc, so the body is lifted a little and its
     * darks are held, and the result is his own fire, not a milky blur.
     */
    private static final float SUN_CONTRAST = 1.30f;
    private static final float SUN_GAIN = 1.06f;
    private static final float SUN_GAMMA = 1.02f;

    /**
     * The unsharp pass over the map. His filaments and grains are what make
     * a fire read as fire; rescaling softens them, and a softened fireball
     * is exactly the "cheap render" he keeps sending back.
     */
    private static final float SUN_SHARPEN = 1.05f;

    /**
     * The rim, as a fraction of the ball's radius: his own rim ink, read per
     * screen angle and turning with the surface, so the edge is as uneven as
     * his picture's instead of a drawn circle. The base keeps a floor of
     * light in the gaps between his tongues.
     */
    private static final float SUN_RING_IN = 0.87f;
    private static final float SUN_RING = 1.55f;
    private static final float SUN_RING_BASE = 0.30f;
    private static final float SUN_RING_FLAME = 1.35f;

    /**
     * The pole dissolve. A sphere converges every longitude into its poles,
     * and converging photographic detail reads as a woven seam whatever is
     * under it. Where the mapping converges the fire gives way to the colour
     * of its own map row, so the top and bottom are smooth plasma.
     */
    private static final float SUN_POLE_IN = 0.64f;
    private static final float SUN_POLE_MIX = 0.92f;

    /**
     * The boil: the same fire read a second time, a few rows away and a
     * little slower, mixed at a low weight, so the surface churns while it
     * turns instead of sliding like a printed ball.
     */
    private static final float SUN_BOIL_ROW = 5f;
    private static final float SUN_BOIL_MIX = 0.07f;

    /** The eruptions lift his own texels toward white; they draw nothing. */
    private static final float SUN_FLARE = 0.45f;

    /**
     * The bloom: a quarter-resolution bright pass, blurred and added back.
     * The knee is high, so only the plasma and the eruptions bleed.
     */
    private static final int SUN_BLOOM = 64;
    private static final int SUN_BLOOM_CELL = SUN_RENDER / SUN_BLOOM;
    private static final int SUN_BLOOM_KNEE = 228;
    private static final float SUN_BLOOM_ADD = 0.26f;

    /**
     * His rim and his corona, sampled once at build: 512 angles around the
     * disc, and the corona out to a fifth of a ball radius in 28 steps. The
     * frame only reads them, so the light never costs a shader.
     */
    private static final int FLAME_STEPS = 512;
    private static final int CORONA_STEPS = 28;
    private static final float CORONA_REACH = 0.20f;
    private static final float CORONA_GAIN = 1.45f;
    /** The radii of his rim that are averaged into the ring's own ink. */
    private static final float[] RING_BANDS = {
            0.90f, 0.95f, 1.00f, 1.05f,
    };
    private static final int RING_SMOOTH = 24;
    private static final int CORONA_SMOOTH = 19;

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
     *
     * Owner order 2026-10-27 ("reduce the SUN's revolving speed by 10%
     * from its current speed", third pass on the feature): the cut is
     * applied to the rate itself, the same place every earlier cut sat,
     * and never to SUN_SLOWDOWN below: 0.2975 * 0.9 = 0.26775 rad/s.
     *
     * Owner order 2026-10-27 ("Decrease the sun's revolving speed by
     * another 10%"): the same law, the fourth pass on the rate:
     * 0.26775 * 0.9 = 0.240975 rad/s.
     */
    private static final float SUN_SPIN_RATE = 0.240975f;
    // Owner order 2026-10-26: the 15% cut applied to the v2.3.8 rate
    // itself, not to the older slowdown multiplier. The 2026-10-27 pass
    // follows the same law - the rate alone carries the newer cuts.
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
    /**
     * The sun's own render THREAD (v2.3.8). HUD-choreographed rendering
     * hurt without helping: the UI loop could only jank - and skipping
     * surface passes throttled the fire's speed below its own law. A
     * dedicated low-priority thread fires the pass at its own steady
     * cadence and publishes BitMap-in, no wake ramp cycles either.
     */
    private Thread sunThread;
    private volatile boolean sunLoop;
    /** Double buffered: the visible surface and the pass being rendered. */
    private Bitmap sunBallBack;
    /** The commit monitor (v2.3.11): the render thread signs its pass and
     *  the handover swaps under this one monitor, so a torn half-pass can
     *  never become the visible frame. Restored from the v2.3.11 branch
     *  after the owner ordered the feature removed and readded. */
    private final Object sunGate = new Object();
    private android.os.Handler sunPublisher;
    /** The sun's session clock, set by startSunLoop, read by the body. */
    private volatile long sunSessionAt;

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
        startSunLoop();
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
        stopSunLoop();
    }

    @Override
    protected void onSizeChanged(int w, int h, int oldW, int oldH) {
        super.onSizeChanged(w, h, oldW, oldH);
        if (w <= 0 || h <= 0) {
            return;
        }
        cx = w / 2f;
        cy = h / 2f;
        // A rebuild must not meet a mid-pass thread: the render thread
        // stops BEFORE its buffers are reallocated and is relaunched after
        // the rebuild, so a pass can never run half inside a dead bitmap.
        stopSunLoop();
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
        ensureSunLoopInfrastructure();
        // The ball exists the moment the size exists; the wake-once law
        // of v2.3.7 is kept (parked or not), now on the thread's budget.
        warmSunOnce();
        if (running) {
            startSunLoop();
        }
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
        // Owner order 2026-10-27 ("they are very tangled and very
        // overlapped on one side of the entire section of the lines, and
        // they don't even connect on one side of the entire feature"):
        // the five anchors sat on FIVE RANDOM spots, so the lobes were
        // five random fists - two near each other made one crowded,
        // overlapped mass, and the sides between the anchors had almost
        // nothing to link. The anchors walk the golden angle's EVEN path
        // around the sphere now - one latitude band per cluster, one
        // 2.39996 turn apart - so the lobes stand apart everywhere in
        // every direction and the web fills all the way around the sun
        // by construction, never by luck.
        for (int c = 0; c < CLUSTERS; c++) {
            float v = (c + 0.5f) / CLUSTERS * 2f - 1f;
            float s = (float) Math.sqrt(Math.max(0f, 1f - v * v));
            float theta = c * 2.39996f;
            // Anchors sit between the sun and the shell, reachable by links.
            anchorX[c] = s * (float) Math.cos(theta) * 0.55f;
            anchorY[c] = v * 0.55f;
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
        //
        // Owner order 2026-10-27 (same subject, on the phone's own
        // screenshot: "they are very tangled and very overlapped on one
        // side ... they don't even connect on one side of the entire
        // feature"): the old sweep walked the pairs FIRST COME, FIRST
        // SERVED and died at the link budget, so wherever the nodes
        // crowded - and the anchors made them crowd - the budget was
        // spent there, and the far side of the sweep reached no pairs at
        // all. The mesh is a NEIGHBOURHOOD MESH now: every node joins
        // K of its own nearest neighbours, each pair once, every
        // link still under the one 0.42 cap - so every side of the ball
        // carries its own filaments and no lobe can spend another's
        // links. (v2.3.15 set K = 3; v2.3.16 carries the +20% below.) The sweep is O(N^2 x K) once, at build, never on the
        // frame path; the deduplicated pair count sits far under the
        // v2.2.1 budget the arrays were sized on.
        //
        // Owner order 2026-10-27, v2.3.16 ("the animating lines are less
        // as of now, make more LINES ... increase the number of LINES by
        // 20% from the current number, across the entire animating
        // feautre"): K carries the growth whole - 3 * 1.2 = 3.6, floored
        // to 4 - so every node joins one more neighbour than v2.3.15
        // gave it, under the same 0.42 cap and with the same one-pair
        // once rule: the lines grow 20% on the SAME law, not a new one.
        float linkAt = 0.42f;
        final int K = 4;
        boolean[] linked = new boolean[NODES * NODES];
        linkCount = 0;
        for (int i = 0; i < NODES; i++) {
            for (int take = 0; take < K; take++) {
                int nearest = -1;
                float nearestDist = Float.MAX_VALUE;
                for (int j = 0; j < NODES; j++) {
                    if (j == i || linked[i * NODES + j]) {
                        continue;
                    }
                    float dx = cloud[i * NODE_STRIDE]
                            - cloud[j * NODE_STRIDE];
                    float dy = cloud[i * NODE_STRIDE + 1]
                            - cloud[j * NODE_STRIDE + 1];
                    float dz = cloud[i * NODE_STRIDE + 2]
                            - cloud[j * NODE_STRIDE + 2];
                    float dist = (float) Math.sqrt(dx * dx + dy * dy
                            + dz * dz);
                    if (dist <= linkAt && dist < nearestDist) {
                        nearest = j;
                        nearestDist = dist;
                    }
                }
                if (nearest < 0) {
                    break;
                }
                linked[i * NODES + nearest] = true;
                linked[nearest * NODES + i] = true;
                linkA[linkCount] = i;
                linkB[linkCount] = nearest;
                linkDist[linkCount] = nearestDist;
                // One golden-angle step per link: the multiplying
                // constant spreads the phases around the circle so
                // no two neighbours breathe in perfect step.
                linkPhase[linkCount] = 2.39996f * linkCount;
                linkCount++;
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
            // v2.3.12 (owner order 2026-10-27: "the entire animating feature
            // is still flickering"): a Choreographer frame that arrived
            // before the 33ms gate used to return WITHOUT drawing, so the
            // vsync this skip belonged to carried whichever picture the
            // surface already held - and a sun publish rides the same
            // scheduler, so the alternation between a redraw and a held
            // frame showed at the screen's rate as phasing. A short frame
            // is now REPAINTED WHOLE at the pose the loop last drew, so
            // every vsync carries one complete picture and the picture
            // still changes only at the loop's own 33ms pace.
            drawScene(canvas, lastSeconds,
                    Math.min(1f, lastSeconds / WAKE_SECONDS));
            postInvalidateOnAnimation();
            return;
        }
        lastFrameAt = now;
        float seconds = now / 1000f;
        lastSeconds = seconds;
        float wake = Math.min(1f, seconds / WAKE_SECONDS);
        drawScene(canvas, seconds, wake);
        postInvalidateOnAnimation();
    }

    /** One full picture: the living cloud around its burning sun. */
    private void drawScene(Canvas canvas, float seconds, float wake) {
        drawCloud(canvas, seconds, wake);
        drawSun(canvas, seconds, wake);
    }

    /**
     * The centre is a RENDERED SPHERE wearing the owner's own photograph.
     * The bitmap carries the ball AND its glow, so there is no second edge
     * behind the disc: the limb runs straight into its own light.
     *
     * Nothing on this path pumps the ball's alpha: its ink is the wake
     * alone, the fire moves in the map, the boil and the eruptions. That is
     * how a picture burns continuously without ever flickering.
     */
    private void drawSun(Canvas canvas, float seconds, float wake) {
        if (sunBall == null) {
            return;     // no sphere built, no picture invented (SO-3)
        }
        sunPaint.setAlpha((int) (255f * wake));
        // The destination holds the whole bitmap, whose ball is SUN_BALL of
        // its half, so the disc still draws at ballR and the glow gets its
        // reach around it.
        float r = ballR * (SUN_RENDER / 2f) / SUN_BALL;
        canvas.save();
        // The standing tilt: the pose; the longitude carries the motion.
        canvas.rotate(SUN_AXIS_TILT, cx, cy);
        ballDst.set(cx - r, cy - r, cx + r, cy + r);
        canvas.drawBitmap(sunBall, null, ballDst, sunPaint);
        canvas.restore();
    }

    /** The sun's thread, v2.3.8. */
    private void ensureSunLoopInfrastructure() {
        if (sunPublisher == null) {
            sunPublisher = new android.os.Handler(
                    android.os.Looper.getMainLooper());
        }
    }

    private void warmSunOnce() {
        ensureSunLoopInfrastructure();
        if (sunPublisher != null) {
            sunPublisher.post(() -> fireSunPass(PARKED_SECONDS));
        }
    }

    private synchronized void startSunLoop() {
        ensureSunLoopInfrastructure();
        if (sunLoop || sunPublisher == null) {
            return;
        }
        sunLoop = true;
        // After a park the sun's clock replays from the frozen second,
        // same law the cloud's clock keeps: a resume continues, never
        // restarts.
        sunSessionAt = frozenSeconds >= 0f
                ? System.currentTimeMillis() - (long) (frozenSeconds * 1000f)
                : System.currentTimeMillis();
        sunThread = new Thread(this::sunLoopBody, "qor-sun");
        sunThread.setPriority(Thread.NORM_PRIORITY - 1);
        sunThread.setDaemon(true);
        sunThread.start();
    }

    private synchronized void stopSunLoop() {
        sunLoop = false;
        Thread t = sunThread;
        sunThread = null;
        if (t != null) {
            t.interrupt();
        }
    }

    /**
     * The thread's body: park, fire the pass, hand the frame over, wait
     * for the next pin. No adaptive tuning (it made halves), no jittered
     * waiting (nothing beyond this thread's own work), no UI work in it.
     */
    private void sunLoopBody() {
        android.os.Process.setThreadPriority(
                android.os.Process.THREAD_PRIORITY_LESS_FAVORABLE);
        long session = sunSessionAt;
        long lastFire = 0L;
        while (sunLoop) {
            try {
                long wait = SUN_CADENCE_MS - (System.currentTimeMillis()
                        - lastFire);
                if (wait > 0) {
                    Thread.sleep(wait);
                }
                if (!sunLoop) {
                    return;
                }
                lastFire = System.currentTimeMillis();
                // the revolve keeps its own law (the fire's speed), not
                // the UI frame's timing and not the thread's hiccup:
                float phi = (float) ((System.currentTimeMillis() - session)
                        / 1000d) * SUN_SPIN_RATE * MOTION_SCALE * SUN_SLOWDOWN;
                fireSunPass(phi);
            } catch (InterruptedException consumed) {
                return;
            }
        }
    }

    /** One surface pass, then the handover. */
    private void fireSunPass(float phi) {
        if (!built) {
            return;
        }
        renderSunBall(phi);
        android.os.Handler p = sunPublisher;
        if (p != null) {
            p.post(this::publishSun);
        }
    }

    private void renderSunBall(float phi) {
        stepEruptions(phi / (SUN_SPIN_RATE * MOTION_SCALE * SUN_SLOWDOWN), phi);
        float spin = phi / SUN_LAP * SUN_MAP_W;
        int shift = (int) (phi / SUN_LAP * FLAME_STEPS);
        int count = SUN_RENDER * SUN_RENDER;
        float reach = SUN_REACH - 1f;
        float cells = CORONA_STEPS - 1;
        for (int k = 0; k < count; k++) {
            float rn = sphereRn[k];
            int ang = (sphereAng[k] + shift) % FLAME_STEPS;
            if (sphereCover[k] == 0) {
                // The light outside the ball is HIS corona, read at this
                // pixel's own angle and distance from the edge. It has gaps
                // and tongues because his picture has them, so no ring is
                // ever drawn at a fixed radius.
                float out = (rn - 1f) / reach;
                if (out >= 1f) {
                    sunBallPixels[k] = 0;
                    continue;
                }
                float cell = out * cells;
                int near = (int) cell;
                int far = near + 1 < CORONA_STEPS ? near + 1 : near;
                float frac = cell - near;
                int a0 = coronaInk[near * FLAME_STEPS + ang];
                int a1 = coronaInk[far * FLAME_STEPS + ang];
                int alpha = (a0 >>> 24)
                        + (int) (((a1 >>> 24) - (a0 >>> 24)) * frac);
                if (alpha <= 1) {
                    sunBallPixels[k] = 0;
                    continue;
                }
                int red = mixChannel(a0, a1, frac, 16);
                int green = mixChannel(a0, a1, frac, 8);
                int blue = mixChannel(a0, a1, frac, 0);
                sunBallPixels[k] = (alpha << 24) | (red << 16)
                        | (green << 8) | blue;
                continue;
            }
            // His picture, read at the frame's own longitude, then again a
            // few rows away and a little slower: the fire churns.
            int rgb = sampleMap(sphereU[k] + spin, sphereV[k]);
            int churn = sampleMap(sphereU[k] + spin * 0.92f,
                    sphereV[k] + SUN_BOIL_ROW);
            rgb = mixInk(rgb, churn, SUN_BOIL_MIX);
            float v = sphereV[k];
            int red = (rgb >> 16) & 0xFF;
            int green = (rgb >> 8) & 0xFF;
            int blue = rgb & 0xFF;
            // The pole dissolve: where the sphere's mapping converges, his
            // fire gives way to the colour of its own row, so the ball has
            // no woven cap at either end.
            float pole = smoothstep(SUN_POLE_IN, 1f,
                    Math.abs(sphereY[k])) * SUN_POLE_MIX;
            if (pole > 0f) {
                int row = mapRowInk[clampInt((int) v, 0, SUN_MAP_H - 1)];
                red += (int) ((((row >> 16) & 0xFF) - red) * pole);
                green += (int) ((((row >> 8) & 0xFF) - green) * pole);
                blue += (int) (((row & 0xFF) - blue) * pole);
            }
            // His rim, per screen angle and turning with the surface: the
            // edge is as uneven as his picture's, never a drawn circle.
            float ring = smoothstep(SUN_RING_IN, 0.995f, rn)
                    * (SUN_RING_BASE + SUN_RING_FLAME * ringFlame[ang])
                    * SUN_RING;
            if (ring > 0f) {
                int ink = ringInk[ang];
                float k2 = ring > 1f ? 1f : ring;
                red += (int) ((((ink >> 16) & 0xFF) - red) * k2);
                green += (int) ((((ink >> 8) & 0xFF) - green) * k2);
                blue += (int) (((ink & 0xFF) - blue) * k2);
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
                float f = Math.min(1f, flare * SUN_FLARE);
                red = clampInt(red + (int) ((255 - red) * f), 0, 255);
                green = clampInt(green + (int) ((255 - green) * f), 0, 255);
                blue = clampInt(blue + (int) ((255 - blue) * f), 0, 255);
            }
            sunScratch[k] = 0xFF000000
                    | (clampInt(red, 0, 255) << 16)
                    | (clampInt(green, 0, 255) << 8)
                    | clampInt(blue, 0, 255);
        }
        bloomSun();
        synchronized (sunGate) {
            sunBallBack.setPixels(sunBallPixels, 0, SUN_RENDER, 0, 0,
                    SUN_RENDER, SUN_RENDER);
        }
    }

    /** One channel of a corona cell pair, moved toward the far cell. */
    private static int mixChannel(int near, int far, float frac, int shift) {
        int a = (near >> shift) & 0xFF;
        int b = (far >> shift) & 0xFF;
        return clampInt(a + (int) ((b - a) * frac), 0, 255);
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
                // Outside the disc: the corona is already there, carried
                // from his picture's own light. It is never blurred flat.
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

    private void buildSunSphere() {
        int count = SUN_RENDER * SUN_RENDER;
        sunBall = Bitmap.createBitmap(SUN_RENDER, SUN_RENDER,
                Bitmap.Config.ARGB_8888);
        // v2.3.8: the pass renders into the BACK bitmap; the visible one
        // is only ever swapped, so drawSun holds a complete frame.
        sunBallBack = Bitmap.createBitmap(SUN_RENDER, SUN_RENDER,
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
        sphereRn = new float[count];
        sphereAng = new int[count];
        sphereCover = new int[count];
        mapRowInk = new int[SUN_MAP_H];
        ringInk = new int[FLAME_STEPS];
        ringFlame = new float[FLAME_STEPS];
        coronaInk = new int[CORONA_STEPS * FLAME_STEPS];
        for (int e = 0; e < ERUPTIONS; e++) {
            float dx = ERUPT_DIR[e * 3];
            float dy = ERUPT_DIR[e * 3 + 1];
            float dz = ERUPT_DIR[e * 3 + 2];
            float len = (float) Math.sqrt(dx * dx + dy * dy + dz * dz);
            eruptDir[e * 3] = dx / len;
            eruptDir[e * 3 + 1] = dy / len;
            eruptDir[e * 3 + 2] = dz / len;
        }
        int[] photo = null;
        int photoW = 0;
        int photoH = 0;
        try {
            Bitmap bitmap = BitmapFactory.decodeResource(getResources(),
                    R.drawable.sun);
            if (bitmap != null) {
                photoW = bitmap.getWidth();
                photoH = bitmap.getHeight();
                photo = new int[photoW * photoH];
                bitmap.getPixels(photo, 0, photoW, 0, 0, photoW, photoH);
                bitmap.recycle();
            }
        } catch (RuntimeException ignored) {
            // No picture is no excuse to invent one (SO-3).
        }
        buildSunMap(photo, photoW, photoH);
        buildSunRing(photo, photoW, photoH);
        buildSunCorona(photo, photoW, photoH);
        float mid = SUN_RENDER / 2f;
        for (int j = 0; j < SUN_RENDER; j++) {
            float y = (j + 0.5f - mid) / SUN_BALL;
            for (int i = 0; i < SUN_RENDER; i++) {
                int k = j * SUN_RENDER + i;
                float x = (i + 0.5f - mid) / SUN_BALL;
                float d2 = x * x + y * y;
                float rn = (float) Math.sqrt(d2);
                sphereRn[k] = rn;
                // The screen angle: his rim is read there, so the light on
                // the edge travels with the fire it comes from.
                float turn = (float) (Math.atan2(y, x) / SUN_LAP);
                if (turn < 0f) {
                    turn += 1f;
                }
                sphereAng[k] = ((int) (turn * FLAME_STEPS)) % FLAME_STEPS;
                if (d2 >= 1f) {
                    continue;   // outside the disc: the corona's own work
                }
                float z = (float) Math.sqrt(1f - d2);
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
                sphereCover[k] = 255;
            }
        }
    }

    /**
     * His rim, baked once: one ink and one height per screen angle. The ink
     * is what his picture's edge actually burns, averaged over four radii so
     * a stray pixel cannot sparkle, and the height is its brightness,
     * smoothed around the disc and squared, so the rim has his own broad
     * tongues and his own gaps between them.
     */
    private void buildSunRing(int[] pixels, int w, int h) {
        if (pixels == null) {
            // A missing asset is reported as his flat disc, never as a rim
            // this file invented (SO-3).
            for (int i = 0; i < FLAME_STEPS; i++) {
                ringInk[i] = 0xFFB4420F;
                ringFlame[i] = 0.5f;
            }
            return;
        }
        float midX = w / 2f;
        float midY = h / 2f;
        float disc = Math.min(w, h) / 2f * SUN_BALL_EDGE;
        int bands = RING_BANDS.length;
        float[] lum = new float[FLAME_STEPS];
        for (int i = 0; i < FLAME_STEPS; i++) {
            float a = (i + 0.5f) / FLAME_STEPS * SUN_LAP;
            float cos = (float) Math.cos(a);
            float sin = (float) Math.sin(a);
            int red = 0;
            int green = 0;
            int blue = 0;
            for (int b = 0; b < bands; b++) {
                float r = disc * RING_BANDS[b];
                int ink = samplePhoto(pixels, w, h, midX + r * cos,
                        midY + r * sin);
                red += (ink >> 16) & 0xFF;
                green += (ink >> 8) & 0xFF;
                blue += ink & 0xFF;
            }
            red /= bands;
            green /= bands;
            blue /= bands;
            ringInk[i] = rimInk(red, green, blue);
            lum[i] = (red * 0.299f + green * 0.587f + blue * 0.114f)
                    / 255f;
        }
        int half = RING_SMOOTH / 2;
        float[] smooth = new float[FLAME_STEPS];
        float lo = 1f;
        float hi = 0f;
        for (int i = 0; i < FLAME_STEPS; i++) {
            float sum = 0f;
            for (int t = -half; t <= half; t++) {
                sum += lum[(i + t + FLAME_STEPS) % FLAME_STEPS];
            }
            smooth[i] = sum / (2 * half + 1);
            lo = Math.min(lo, smooth[i]);
            hi = Math.max(hi, smooth[i]);
        }
        float span = Math.max(0.001f, hi - lo);
        for (int i = 0; i < FLAME_STEPS; i++) {
            float f = clamp((smooth[i] - lo) / span, 0f, 1f);
            ringFlame[i] = f * f;
        }
    }

    /** One rim ink, warmed and lifted: his rim burns brighter than its own
     * average because the light of the disc is behind it. */
    private static int rimInk(int red, int green, int blue) {
        return (clampInt((int) (red * 1.25f + 30f), 0, 255) << 16)
                | (clampInt((int) (green * 1.20f + 26f), 0, 255) << 8)
                | clampInt((int) (blue * 1.05f + 20f), 0, 255);
    }

    /**
     * His corona, baked once: the light his picture throws past its own rim,
     * one cell per angle and radius. Its alpha is the picture's own
     * brightness there, so the flames end exactly where they end in the
     * photograph, and the strip is smoothed around the disc so the tongues
     * are lobes of flame rather than one ray per degree.
     */
    private void buildSunCorona(int[] pixels, int w, int h) {
        if (pixels == null) {
            return;     // nothing to read, nothing invented (SO-3)
        }
        float midX = w / 2f;
        float midY = h / 2f;
        float disc = Math.min(w, h) / 2f * SUN_BALL_EDGE;
        int[] raw = new int[CORONA_STEPS * FLAME_STEPS];
        for (int r = 0; r < CORONA_STEPS; r++) {
            float f = (r + 0.5f) / CORONA_STEPS;
            float radius = disc * (1f + CORONA_REACH * f);
            float fade = (float) Math.pow(1f - f, 1.5f);
            for (int i = 0; i < FLAME_STEPS; i++) {
                float a = (i + 0.5f) / FLAME_STEPS * SUN_LAP;
                int ink = samplePhoto(pixels, w, h,
                        midX + radius * (float) Math.cos(a),
                        midY + radius * (float) Math.sin(a));
                int red = (ink >> 16) & 0xFF;
                int green = (ink >> 8) & 0xFF;
                int blue = ink & 0xFF;
                float lum = (red * 0.299f + green * 0.587f + blue * 0.114f)
                        / 255f;
                // v2.3.6: the threshold and slope are the prototype's own
                // (sun-preview/emulate_v238.py), the two numbers the grid
                // showed carry the feathered orange fringe; the sixth
                // pass's 0.04/0.34 fired at a brightness of 4% and burned
                // out by 38%, which fattened the fade and crushed the
                // tongue gaps the owner's picture shows.
                float alpha = clamp((lum - 0.12f) / 0.55f, 0f, 1f)
                        * fade * CORONA_GAIN;
                // The prototype overexposes where the alpha passes 1 (the
                // hot inner cells push to white, not to the ink's own
                // level). The packed int cannot hold alpha above 1, so the
                // surplus lifts the ink itself toward white: the same
                // clamp the preview applies per channel.
                float clipped = Math.min(1f, alpha);
                float surplus = alpha - clipped;
                if (surplus > 0f) {
                    red = (int) Math.min(255f, red + surplus * (255f - red));
                    green = (int) Math.min(255f,
                            green + surplus * (255f - green));
                    blue = (int) Math.min(255f, blue + surplus * (255f - blue));
                }
                int a8 = (int) (clipped * 255f);
                raw[r * FLAME_STEPS + i] = (a8 << 24) | (red << 16)
                        | (green << 8) | blue;
            }
        }
        int half = CORONA_SMOOTH / 2;
        int n = 2 * half + 1;
        for (int r = 0; r < CORONA_STEPS; r++) {
            for (int i = 0; i < FLAME_STEPS; i++) {
                int alpha = 0;
                int red = 0;
                int green = 0;
                int blue = 0;
                for (int t = -half; t <= half; t++) {
                    int ink = raw[r * FLAME_STEPS
                            + (i + t + FLAME_STEPS) % FLAME_STEPS];
                    alpha += ink >>> 24;
                    red += (ink >> 16) & 0xFF;
                    green += (ink >> 8) & 0xFF;
                    blue += ink & 0xFF;
                }
                coronaInk[r * FLAME_STEPS + i] = ((alpha / n) << 24)
                        | ((red / n) << 16)
                        | ((green / n) << 8)
                        | (blue / n);
            }
        }
    }



    private void buildSunMap(int[] pixels, int w, int h) {
        int count = SUN_MAP_W * SUN_MAP_H;
        sunMap = new int[count];
        if (pixels == null) {
            // A missing asset is reported as a plain disc, never as a fake
            // photograph: his fire is his, and nothing here invents it.
            for (int i = 0; i < count; i++) {
                sunMap[i] = 0xFFB4420F;
            }
            for (int row = 0; row < SUN_MAP_H; row++) {
                mapRowInk[row] = 0xFFB4420F;
            }
            return;
        }
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
        sharpenMap();
        for (int row = 0; row < SUN_MAP_H; row++) {
            int red = 0;
            int green = 0;
            int blue = 0;
            for (int col = 0; col < SUN_MAP_W; col++) {
                int ink = sunMap[row * SUN_MAP_W + col];
                red += (ink >> 16) & 0xFF;
                green += (ink >> 8) & 0xFF;
                blue += ink & 0xFF;
            }
            mapRowInk[row] = 0xFF000000
                    | ((red / SUN_MAP_W) << 16)
                    | ((green / SUN_MAP_W) << 8)
                    | (blue / SUN_MAP_W);
        }
    }

    /**
     * His fire's own edges, put back. The crop is rescaled on its way to the
     * sphere and rescaling softens; the filaments and grains are exactly
     * what a fire has and a render lacks, so one light unsharp pass restores
     * them. Longitude wraps and latitude clamps, so no map edge is ever
     * sharpened against nothing.
     */
    private void sharpenMap() {
        int[] source = sunMap;
        int[] out = new int[source.length];
        for (int row = 0; row < SUN_MAP_H; row++) {
            int up = row > 0 ? row - 1 : row;
            int down = row < SUN_MAP_H - 1 ? row + 1 : row;
            for (int col = 0; col < SUN_MAP_W; col++) {
                int left = col > 0 ? col - 1 : SUN_MAP_W - 1;
                int right = col < SUN_MAP_W - 1 ? col + 1 : 0;
                int sumRed = 0;
                int sumGreen = 0;
                int sumBlue = 0;
                for (int r = 0; r < 3; r++) {
                    int rr = r == 0 ? up : (r == 1 ? row : down);
                    for (int c = 0; c < 3; c++) {
                        int cc = c == 0 ? left : (c == 1 ? col : right);
                        int pixel = source[rr * SUN_MAP_W + cc];
                        sumRed += (pixel >> 16) & 0xFF;
                        sumGreen += (pixel >> 8) & 0xFF;
                        sumBlue += pixel & 0xFF;
                    }
                }
                int pixel = source[row * SUN_MAP_W + col];
                out[row * SUN_MAP_W + col] = 0xFF000000
                        | (sharpenChannel((pixel >> 16) & 0xFF,
                                sumRed / 9) << 16)
                        | (sharpenChannel((pixel >> 8) & 0xFF,
                                sumGreen / 9) << 8)
                        | sharpenChannel(pixel & 0xFF, sumBlue / 9);
            }
        }
        sunMap = out;
    }

    /** One channel of the unsharp pass. */
    private static int sharpenChannel(int value, int blurred) {
        return clampInt((int) (value + (value - blurred) * SUN_SHARPEN),
                0, 255);
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
            // Owner order 2026-10-26, tenth pass: v2.3.7's one-fifth
            // swing read as "the animation is ruined" - the lines grew
            // and shrank without their life. The v2.3.3 swing is back over
            // the length, and the INK's swing is final now: the width's
            // own factor rides 0.96..1.12, so a filament's alpha stays
            // between 0.94 and 1.16 while it swells, thinning and
            // swimming the way the reference breathes - without ever
            // cycling near zero and flashing, which is the flicker law
            // of 2026-10-25/26. A line's phase still leads its ink by a
            // quarter turn, so a shrinking line stays bold (never so).
            float breathWave = (float) Math.sin(
                    seconds * 0.55f * MOTION_SCALE + linkPhase[l]);
            float widthBreath = 1f + 0.30f * breathWave;
            int alpha = (int) ((70f + 165f * toward) * wake
                    * (0.945f + 0.17f * widthBreath));
            linkPaint.setAlpha(Math.min(255, alpha));
            linkPaint.setStrokeWidth(linkWidth * (0.8f + 0.45f * toward)
                    * widthBreath);
            // The length swings around the filament's own MIDPOINT, so
            // both ends pool in and return together instead of the whole
            // line sliding off the nodes it joins.
            //
            // Owner order 2026-10-27 ("the moving big lines that are
            // revolving around the sun are coming out from their dots.
            // Make it not exceed those dots"): the v2.3.3 law let the
            // swing carry a filament's ends up to 30% BEYOND the dots it
            // joins. The swing is inward-only now: this factor rides
            // 0.70..1.00 over the wave, so the line shrinks toward its
            // own midpoint and stretches back exactly to the dots that
            // own it - and no end can ever leave the dot it is drawn
            // from, whatever the wave is doing.
            float breath = 1f - 0.15f * (1f - breathWave);
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

    @Override
    protected void onDetachedFromWindow() {
        stopSunLoop();
        super.onDetachedFromWindow();
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
     *
     * Owner order 2026-10-27, v2.3.16: the budget carries the same +20%
     * the mesh law above carries (26/5 * 1.2 = 31.2, floored to 31/5),
     * so the arrays hold every pair the four-neighbour join now asks
     * for, whatever the seed's lobes do.
     */
    private static int linkBudget() {
        return NODES * 31 / 5;
    }

    /** The frame's handover: visible sun = back bitmap, then swap. The
     *  swap stands under the pass's own commit monitor, and it is a HARD
     *  swap (v2.3.11, owner order removing the v2.3.9 ghost blend): the
     *  published frame is seen whole or not at all. */
    private void publishSun() {
        synchronized (sunGate) {
            Bitmap tmp = sunBall;
            sunBall = sunBallBack;
            sunBallBack = tmp;
        }
        if (isShown() && running) {
            postInvalidateOnAnimation();
        } else {
            invalidate();
        }
    }

    private float dp(float dp) {
        return dp * getResources().getDisplayMetrics().density;
    }
}
