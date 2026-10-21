"""Owner-ordered interface changes for the phone app, v1.7.0 (2026-10-15).

Owner order 2026-10-15: the market card's quantity fields are restored to
B and S with the exact, raw numbers the feed produced (no projection onto
the exchange's total, no rounding), the approximation sign that marks an
estimated split is drawn by a face that shows it as one instead of LEMON
MILK's near-tilde, and the settings control moves 20% of its own box to the
right and 5% of that box higher than the 2026-10-14 centring put it.

Owner order 2026-10-13: the settings control is the owner's own settings.png
silhouette, tinted from the app's palette, on no plate at all and centred on
the "Quant of Rehan" line, with a quarter turn as the settings panel opens and
closes; every line inside the system status and the latest signal tiles is set
in the owner's faces; the "Trading resumes" sentence is retired from the status
tile; and a volume leader row brackets its grouped volumes.

Owner order 2026-10-13 (second note): a diamond rule divides the system status
tile from the latest signal tile; the rule that closed the market card from
inside it stands immediately after that tile's own boundary; and the ONLINE
indicator breathes, opacity and size, while the relay reports the market OPEN.

Owner order 2026-10-13 (third note): the settings control stops overflowing its
row (a header row that holds no clip, so a tall box cannot be shaved); the
cadence sentence leaves the market card and stands immediately after the final
diamond rule; and the status light's pulse is rebuilt so both states breathe,
the ONLINE beacon in the palette green and the OFFLINE one in the palette red,
on a hard 25 frames per second.

Owner order 2026-10-13 (fourth note): the settings control stands directly
beside the "Quant of Rehan" title instead of pinned to the row's far edge,
anchored to the title's own right edge, so the pair holds at any screen width
and at any font scale.

Owner order 2026-10-13 (fifth note): the cadence sentence's separation from
the final rule is the layout's own 12dp, the gap the tiles have below their
rules, so the two leading newlines leave the string resource; the sentence
itself stays byte-identical and stays the only place it appears.

Owner order 2026-10-14 (sixth note): the settings control is VERTICALLY
CENTRED on the "Quant of Rehan" title. The baseline rule of the second note
is retired with the layout listener that measured that baseline after every
layout, so "centred on the brand line" is the layout's own centreVertical
again: exact at any font scale, with no measured pixel at all.

Owner order 2026-10-14 (seventh note): the status light is a view now, its
own ImageView inside the badge, and the breath is a view property animation
on that view's alpha and scale, which the platform interpolates on the render
thread. The compound drawable of 2026-10-13 is retired with the 40ms grid
its update listener drew on, and only a live market breathes: ONLINE pulses,
and OFFLINE and CHECKING hold a light that is not moving.

Owner order 2026-10-14 (eighth note): the status tile's spacing is one
number, @dimen/status_gap, so SYSTEM STATUS to ONLINE and ONLINE to KARACHI
are the same air rather than two margins that could drift apart.

The app has no Java test runner in this repository (it is built with aapt2 and
D8, see android/README.md), so these assertions read the sources that ship the
contract, exactly as tests/test_android_card_copy.py does for the card's copy.

Three of the checks are measured rather than declared:

  * the bundled OTF files are read through their own cmap tables, because the
    free LEMON MILK maps every lowercase codepoint onto its uppercase glyph
    (which is why the settings paragraph keeps the system face), no bundled
    face carries U+25B2/U+25BC (the card's arrows, drawn with the system face
    by a span) and none carries U+25C6 (the brand diamond, so QorDiamond
    deliberately sets no fontFamily);
  * the bundled settings.png is decoded scanline by scanline, so the suite can
    assert that the silhouette really sits on transparency with a real
    aperture, instead of trusting the file name;
  * the header's alignment and the status tile's spacing are read from the
    layout tree and from dimens.xml, so "centred on the brand line" means the
    control and the brand text share one row AND one vertical centre, and
    "SYSTEM STATUS to ONLINE is ONLINE to KARACHI" means the two margins name
    the same resource rather than two numbers that happen to match today;
  * the two status beacons are read as resources, so "the online light is
    green and the offline light is red" is a comparison of values/colors.xml
    against the two drawables instead of a reading of the prose.

A future font or icon swap that breaks one of those facts fails this file
instead of shipping a row of empty boxes or a misaligned control to the phone.
"""

from __future__ import annotations

import struct
import unittest
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "android" / "app" / "src" / "main" / "res"
LAYOUT = RES / "layout" / "activity_main.xml"
RULE = RES / "layout" / "qor_rule.xml"
STYLES = RES / "values" / "styles.xml"
STRINGS = RES / "values" / "strings.xml"
COLORS = RES / "values" / "colors.xml"
DIMENS = RES / "values" / "dimens.xml"
ONLINE_DOT = RES / "drawable" / "ic_status_online.xml"
OFFLINE_DOT = RES / "drawable" / "ic_status_offline.xml"
SETTINGS_PNG = RES / "drawable-nodpi" / "settings.png"
SETTINGS_RIPPLE = RES / "drawable" / "settings_ripple.xml"
FONT_DIR = RES / "font"
LICENCES = ROOT / "android" / "LICENSES"
MAIN = (ROOT / "android" / "app" / "src" / "main" / "java" / "pk"
        / "quantofrehan" / "MainActivity.java")
WATCHER = (ROOT / "android" / "app" / "src" / "main" / "java" / "pk"
           / "quantofrehan" / "Watcher.java")
# v1.7.7: the signal tile's reader is its own plain-Java class so the JVM
# probe in tests/test_android_signal_text.py can run it rather than read it.
SIGNAL_TEXT = (ROOT / "android" / "app" / "src" / "main" / "java" / "pk"
               / "quantofrehan" / "SignalText.java")
STATUS_SERVICE = (ROOT / "android" / "app" / "src" / "main" / "java" / "pk"
                  / "quantofrehan" / "StatusService.java")
MANIFEST = ROOT / "android" / "app" / "src" / "main" / "AndroidManifest.xml"
README = ROOT / "android" / "README.md"

ANDROID_NS = "{http://schemas.android.com/apk/res/android}"
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"

DIAMOND = 0x25C6
ARROW_UP = 0x25B2
ARROW_DOWN = 0x25BC
ABOUT = 0x2248


def element(source: str, marker: str) -> str:
    """The self closing XML element that contains `marker`."""
    at = source.index(marker)
    start = source.rindex("<", 0, at)
    end = source.index("/>", at) + 2
    return source[start:end]


def layout_root():
    return ET.parse(LAYOUT).getroot()


def find_view(root, view_id: str):
    for node in root.iter():
        if node.get(f"{ANDROID_NS}id") == view_id:
            return node
    return None


def parent_of(root, node):
    for parent in root.iter():
        for child in parent:
            if child is node:
                return parent
    return None


def siblings_after(root, node):
    """The siblings that follow `node` in document order."""
    parent = parent_of(root, node)
    children = list(parent)
    return children[children.index(node) + 1:]


def png_header(path: Path) -> tuple[int, int, int, int]:
    """(width, height, bit depth, colour type) from the PNG's own IHDR."""
    data = path.read_bytes()
    assert data[:8] == PNG_MAGIC, f"{path.name} is not a PNG"
    assert data[12:16] == b"IHDR", f"{path.name} does not open with IHDR"
    return struct.unpack(">IIBB", data[16:26])


def png_pixel(path: Path, x: int, y: int) -> tuple[int, int, int, int]:
    """One pixel's (red, green, blue, alpha) from the PNG's own scanlines.

    A deliberately small reader for the one image this app bundles: 8 bit
    RGBA, no interlace, filters 0 to 4, which is what the owner's settings.png
    is. It exists so the test can assert the silhouette's transparency, its
    aperture and its ink colour from the pixels themselves.
    """
    width, height, depth, colour = png_header(path)
    assert (depth, colour) == (8, 6), f"{path.name} is not 8 bit RGBA"
    data = path.read_bytes()
    idat = b""
    at = 8
    while at + 12 <= len(data):
        length, kind = struct.unpack(">I4s", data[at:at + 8])
        if kind == b"IDAT":
            idat += data[at + 8:at + 8 + length]
        at += 12 + length
    raw = zlib.decompress(idat)
    stride = width * 4
    previous = bytearray(stride)
    row = bytearray(stride)
    at = 0
    for row_index in range(height):
        filter_type = raw[at]
        at += 1
        row[:] = raw[at:at + stride]
        at += stride
        for i in range(stride):
            left = row[i - 4] if i >= 4 else 0
            up = previous[i]
            up_left = previous[i - 4] if i >= 4 else 0
            if filter_type == 1:
                row[i] = (row[i] + left) & 0xFF
            elif filter_type == 2:
                row[i] = (row[i] + up) & 0xFF
            elif filter_type == 3:
                row[i] = (row[i] + (left + up) // 2) & 0xFF
            elif filter_type == 4:
                p = left + up - up_left
                pa, pb, pc = abs(p - left), abs(p - up), abs(p - up_left)
                if pa <= pb and pa <= pc:
                    row[i] = (row[i] + left) & 0xFF
                elif pb <= pc:
                    row[i] = (row[i] + up) & 0xFF
                else:
                    row[i] = (row[i] + up_left) & 0xFF
        if row_index == y:
            return tuple(row[x * 4:x * 4 + 4])
        previous, row = row, previous
    raise AssertionError(f"{path.name} has no row {y}")


def has_codepoint(path: Path, codepoint: int) -> bool:
    """True when the font's own cmap maps `codepoint` to a real glyph.

    A deliberately small reader: this repository has no fontTools dependency
    and CI installs only requirements.txt, so the table is parsed here. It
    handles cmap format 4 (segment mapping, the format every face here uses
    for the BMP) and format 12 (grouped ranges), and it honours idRangeOffset,
    so a gap inside a segment is reported as unmapped rather than as present.
    """
    data = path.read_bytes()
    tables = {}
    for index in range(struct.unpack(">H", data[4:6])[0]):
        off = 12 + index * 16
        tables[data[off:off + 4]] = struct.unpack(">II", data[off + 8:off + 16])
    cmap_off = tables[b"cmap"][0]
    for index in range(struct.unpack(">H", data[cmap_off + 2:cmap_off + 4])[0]):
        record = cmap_off + 4 + index * 8
        sub = cmap_off + struct.unpack(">I", data[record + 4:record + 8])[0]
        fmt = struct.unpack(">H", data[sub:sub + 2])[0]
        if fmt == 4:
            if _format4_has(data, sub, codepoint):
                return True
        elif fmt == 12:
            groups = struct.unpack(">I", data[sub + 12:sub + 16])[0]
            for g in range(groups):
                at = sub + 16 + g * 12
                lo, hi = struct.unpack(">II", data[at:at + 8])
                if lo <= codepoint <= hi:
                    return True
    return False


def _format4_has(data: bytes, sub: int, codepoint: int) -> bool:
    if codepoint > 0xFFFF:
        return False
    seg_x2 = struct.unpack(">H", data[sub + 6:sub + 8])[0]
    segs = seg_x2 // 2
    ends_at = sub + 14
    starts_at = ends_at + seg_x2 + 2
    deltas_at = starts_at + seg_x2
    ranges_at = deltas_at + seg_x2
    for seg in range(segs):
        start = struct.unpack(">H", data[starts_at + 2 * seg:starts_at + 2 * seg + 2])[0]
        end = struct.unpack(">H", data[ends_at + 2 * seg:ends_at + 2 * seg + 2])[0]
        if not start <= codepoint <= end:
            continue
        delta = struct.unpack(">h", data[deltas_at + 2 * seg:deltas_at + 2 * seg + 2])[0]
        offset = struct.unpack(">H", data[ranges_at + 2 * seg:ranges_at + 2 * seg + 2])[0]
        if offset == 0:
            return (codepoint + delta) % 0x10000 != 0
        at = ranges_at + 2 * seg + offset + 2 * (codepoint - start)
        if at + 2 > len(data):
            return False
        glyph = struct.unpack(">H", data[at:at + 2])[0]
        return glyph != 0 and (glyph + delta) % 0x10000 != 0
    return False


class SettingsControlTest(unittest.TestCase):
    """The owner's own image, on no tile, centred on the brand line."""

    def setUp(self):
        self.layout = LAYOUT.read_text(encoding="utf-8")
        self.strings = STRINGS.read_text(encoding="utf-8")
        self.main = MAIN.read_text(encoding="utf-8")
        self.ripple = SETTINGS_RIPPLE.read_text(encoding="utf-8")

    def test_the_control_is_the_owners_own_image(self):
        button = element(self.layout, 'android:id="@+id/btn_settings"')
        self.assertIn("<ImageView", button)
        self.assertIn('android:src="@drawable/settings"', button)
        # The U+2699 glyph and the drawn gear that replaced it are both gone.
        self.assertNotIn("gear_glyph", self.layout)
        self.assertNotIn("ic_gear", self.layout)
        self.assertNotIn("\u2699", self.strings)
        self.assertFalse((RES / "drawable" / "ic_gear.xml").exists())

    def test_the_file_is_black_ink_on_transparency(self):
        # The file as the owner saved it: 512 square, 8 bit RGBA, no background
        # tile inside the file. Corners transparent, the ring's left edge opaque
        # at the measured bounding box, and the middle a real aperture.
        self.assertTrue(SETTINGS_PNG.is_file())
        self.assertEqual(png_header(SETTINGS_PNG), (512, 512, 8, 6))
        self.assertEqual(png_pixel(SETTINGS_PNG, 0, 0)[3], 0)
        self.assertEqual(png_pixel(SETTINGS_PNG, 511, 511)[3], 0)
        self.assertEqual(png_pixel(SETTINGS_PNG, 256, 256)[3], 0)
        # The ring is opaque at the measured bounding box, and the ink is
        # black: the layout's tint is the only colour the icon ever has.
        self.assertEqual(png_pixel(SETTINGS_PNG, 16, 256), (0, 0, 0, 255))
        self.assertEqual(png_pixel(SETTINGS_PNG, 128, 256), (0, 0, 0, 255))

    def test_the_tile_and_its_plates_are_removed(self):
        button = element(self.layout, 'android:id="@+id/btn_settings"')
        self.assertIn('android:background="@drawable/settings_ripple"', button)
        self.assertNotIn("gear_bg", self.layout)
        for name in ("gear_bg.xml", "gear_bg_open.xml", "gear_plate.xml",
                     "gear_plate_open.xml"):
            with self.subTest(drawable=name):
                self.assertFalse((RES / "drawable" / name).exists())
        self.assertIn("<ripple", self.ripple)
        self.assertIn("@android:id/mask", self.ripple)
        # No content item: the ripple is the press and nothing else, so the
        # control has no tile at rest.
        self.assertNotIn("android:drawable=", self.ripple)

    def test_the_icon_is_tinted_from_the_app_palette(self):
        button = element(self.layout, 'android:id="@+id/btn_settings"')
        self.assertIn('android:tint="@color/gold"', button)
        self.assertIn("btnSettings.setImageTintList", self.main)
        self.assertIn("R.color.gold_bright", self.main)

    def test_the_control_is_centred_on_the_title(self):
        root = layout_root()
        button = find_view(root, "@+id/btn_settings")
        title = find_view(root, "@+id/brand_title")
        tagline = find_view(root, "@+id/brand_tagline")
        self.assertIsNotNone(button)
        self.assertIsNotNone(title)
        self.assertIsNotNone(tagline)
        row = parent_of(root, button)
        self.assertTrue(row.tag.endswith("RelativeLayout"))
        self.assertIs(row, parent_of(root, title))
        # Owner order 2026-10-14 (sixth note): the control is centred
        # VERTICALLY on the title, so the box's own middle stands on the
        # line's middle at any font scale. The baseline rule of 2026-10-13
        # (second note) is retired, and with it every measured pixel: the
        # layout holds the centring, and MainActivity holds no layout listener
        # that could move the control after a layout.
        self.assertEqual(button.get(f"{ANDROID_NS}layout_centerVertical"),
                         "true")
        self.assertIsNone(button.get(f"{ANDROID_NS}layout_alignTop"))
        self.assertNotIn("alignSettingsToBrandBaseline", self.main)
        self.assertNotIn("addOnLayoutChangeListener", self.main)
        self.assertNotIn("brandTitle", self.main)
        # Owner order 2026-10-16 (fourth note): the one thing MainActivity now
        # writes on the control is the ORDERED offset, clamped to the room the
        # screen has. It reads that offset from the same two resources the
        # layout declares and never re-derives a position from the title, so
        # the centring is still the layout's fact and this cannot become the
        # old baseline measure by another name.
        shift = self.main[self.main.index("private void applySettingsShift()"):]
        shift = shift[:shift.index("private void setSettingsOpen")]
        self.assertIn("R.dimen.settings_shift_x", shift)
        self.assertIn("R.dimen.settings_shift_y", shift)
        self.assertNotIn("brand_title", shift)
        self.assertNotIn("getBaseline", shift)
        # The tagline stays outside the row, so it cannot pull the control
        # down: the control is centred on the brand text itself.
        self.assertIsNot(row, parent_of(root, tagline))
        # And it is still the title the control stands beside, so the pair
        # shares both axes rather than only the vertical one.
        self.assertEqual(button.get(f"{ANDROID_NS}layout_toEndOf"),
                         "@id/brand_title")

    def test_the_control_cannot_be_cropped_by_its_row(self):
        # Owner order 2026-10-13 (third note): the control's box is 42dp while
        # a 30sp Bonskin line stands only about 30dp of ink above its
        # baseline, so the box overhangs that line by about 9dp and a
        # RelativeLayout clips its children by default. The row therefore
        # holds no clip, which keeps the box whole at any font scale, and the
        # vertical margin that used to give the overhang a home is retired:
        # the box is centred on the line now (sixth note), which spends half of
        # that overhang above the line and half below it. Owner order
        # 2026-10-16 (fourth note): every ancestor, not only the row, holds no
        # clip, because the ordered translation moves the DRAWN box past three
        # of them as well.
        root = layout_root()
        button = find_view(root, "@+id/btn_settings")
        row = find_view(root, "@+id/brand_row")
        header = parent_of(root, row)
        self.assertIsNotNone(button)
        self.assertIsNotNone(row)
        self.assertEqual(row.get(f"{ANDROID_NS}clipChildren"), "false")
        self.assertEqual(header.get(f"{ANDROID_NS}clipChildren"), "false")
        self.assertIs(row, parent_of(root, button))
        self.assertIsNone(button.get(f"{ANDROID_NS}layout_marginTop"),
                          "the baseline overhang is retired with the rule")
        # The promise the no-clip row still has to keep: a box taller than the
        # line it is centred on.
        box = int(button.get(f"{ANDROID_NS}layout_height")[:-2])
        ascent = 30 * 1006 / 1000          # Bonskin hhea ascender at 30sp
        self.assertGreater(box, ascent)
        # The ink sits `padding` inside the box, so the silhouette keeps clear
        # of the box edge as well.
        padding = int(button.get(f"{ANDROID_NS}padding")[:-2])
        self.assertLessEqual(padding, 8)

    def test_the_ordered_offset_is_clamped_to_the_room_the_screen_has(self):
        """Owner order 2026-10-16 (fourth note): the press gradient was cut.

        The control hangs off the centred brand title and is translated by
        @dimen/settings_shift_x, which is what the owner ordered. On a narrow
        content area that translation can carry the control's box past the
        window's right edge, and the pixels outside the window are not clipped
        by a parent, they simply do not exist, which the owner saw as a sliced
        gradient. Two halves fix it, and this test pins both:

          * every ancestor of the control stops clipping (scroll view, content
            column, header, brand row), so a drawn box may overhang its own
            row;
          * MainActivity clamps the ordered offset to the pixels actually
            available between the control's right edge and the window's, read
            from real geometry after the first layout (posted, so a layout
            exists), and never to a guessed width.
        """
        root = layout_root()
        button = find_view(root, "@+id/btn_settings")
        clip_free = []
        node = button
        while node is not None:
            clip_free.append(node.tag)
            node = parent_of(root, node)
        # scroll view, content column, header, brand row: the chain above the
        # control, most of which used to clip.
        self.assertIn("ScrollView", clip_free)
        self.assertIn("LinearLayout", clip_free)
        self.assertIn("RelativeLayout", clip_free)
        layout = LAYOUT.read_text(encoding="utf-8")
        self.assertIn('android:clipToPadding="false"', layout)
        self.assertGreaterEqual(layout.count('android:clipChildren="false"'), 4)
        # The clamp itself: posted after the first layout, ordered magnitudes
        # from the layout's own dimens, bounded by measured room.
        self.assertIn("btnSettings.post(", self.main)
        self.assertIn("window.getLocationOnScreen(windowAt)", self.main)
        self.assertIn("room = windowAt[0] + window.getWidth() - naturalRight",
                      self.main)
        self.assertIn("Math.min(orderedX, Math.max(0f, room))", self.main)
        self.assertIn("btnSettings.setTranslationX(", self.main)
        # It never invents an offset of its own: the ordered one is the
        # ceiling, so a wide screen gets exactly what the owner asked for.
        self.assertIn("R.dimen.settings_shift_x", self.main)
        self.assertIn("R.dimen.settings_shift_y", self.main)

    def test_the_control_is_nudged_right_and_up_by_the_owners_fractions(self):
        """Owner orders, stacked: 20% right and 5% up, then a further 70%
        right and 15% up, then (2026-10-16) 15% right and 5% DOWN.

        Every order is a fraction of the control's own 42dp box and the shift
        is a translation, so the fractions simply sum: 20 + 70 + 15 = 105%
        right and 5 + 15 - 5 = 15% up, which is 42 x 1.05 = 44.1dp right and
        42 x 0.15 = 6.3dp up (a negative translation in Android's
        coordinates). The anchors of the earlier orders still hold, so a
        stacked translation keeps the same shape on any screen and at any
        font scale.
        """
        root = layout_root()
        button = find_view(root, "@+id/btn_settings")
        self.assertEqual(button.get(f"{ANDROID_NS}translationX"),
                         "@dimen/settings_shift_x")
        self.assertEqual(button.get(f"{ANDROID_NS}translationY"),
                         "@dimen/settings_shift_y")
        self.assertEqual(button.get(f"{ANDROID_NS}layout_toEndOf"),
                         "@id/brand_title")
        self.assertEqual(button.get(f"{ANDROID_NS}layout_centerVertical"),
                         "true")
        dimens = (RES / "values" / "dimens.xml").read_text(encoding="utf-8")
        box = int(button.get(f"{ANDROID_NS}layout_width")[:-2])
        self.assertIn(
            f'<dimen name="settings_shift_x">{box * 1.05:.1f}dp</dimen>',
            dimens)
        self.assertIn(
            f'<dimen name="settings_shift_y">-{box * 0.15:.1f}dp</dimen>',
            dimens)
        # Today's order is +15% right and +5% down FROM where the control
        # already stood, so the vertical shift must be SMALLER than the old
        # 20% up rather than larger: a sign error here would move the icon up
        # again and still satisfy a magnitude only check.
        self.assertLess(42 * 0.15, 42 * 0.20)
        self.assertLess(37.8, box * 1.05)

    def test_the_control_sits_beside_the_title(self):
        # Owner order 2026-10-13 (fourth note): adjacent to the brand name,
        # anchored to the title's own right edge rather than pinned to the
        # row's far corner: the pair holds at any width and any font scale,
        # and the title can never grow into the control.
        root = layout_root()
        button = find_view(root, "@+id/btn_settings")
        title = find_view(root, "@+id/brand_title")
        self.assertIsNotNone(button)
        self.assertIsNotNone(title)
        self.assertEqual(button.get(f"{ANDROID_NS}layout_toEndOf"),
                         "@id/brand_title")
        self.assertIsNone(button.get(f"{ANDROID_NS}layout_alignParentEnd"),
                          "the corner placement is retired")
        # 6dp of margin plus the control's own 6dp padding: 12dp of air
        # between the name and the ink, the grid's own unit.
        margin = int(button.get(f"{ANDROID_NS}layout_marginLeft")[:-2])
        padding = int(button.get(f"{ANDROID_NS}padding")[:-2])
        self.assertEqual(margin + padding, 12)
        # Clickability contract, unchanged: full-size box, masked ripple,
        # a button's name for the screen reader.
        self.assertEqual(button.get(f"{ANDROID_NS}layout_height"), "42dp")
        self.assertIn("settings_ripple",
                      button.get(f"{ANDROID_NS}background"))
        self.assertEqual(button.get(f"{ANDROID_NS}contentDescription"),
                         "@string/cd_settings")

    def test_the_quarter_turn_is_one_place_per_state(self):
        self.assertIn(".rotation(open ? -90f : 0f)", self.main)
        self.assertIn("GEAR_TURN_MS", self.main)
        self.assertIn("new DecelerateInterpolator()", self.main)
        # Every state change goes through the one helper, and the open no
        # longer swaps a background anywhere. Three call sites since owner
        # order 2026-10-20: the declaration, the gear tap, and the search menu
        # closing the panel so two menus can never be open at once.
        self.assertEqual(self.main.count("setSettingsOpen("), 3)
        self.assertNotIn("gear_bg", self.main)
        self.assertNotIn("setBackgroundResource", self.main)

    def test_the_settings_tile_carries_no_token_and_no_technical_clutter(self):
        """Owner order 2026-10-19: the phone holds no credential.

        The token field, its save button and the paste instructions are gone
        from the layout, and no Java reads an admin token any more. That is
        only safe because the relay serves the latest signal as a public read;
        tests/test_relay_worker_contracts.py pins that split (public GET,
        admin-gated POST).
        """
        layout = LAYOUT.read_text(encoding="utf-8")
        for gone in ("token_box", "btn_save", "field_bg"):
            with self.subTest(view=gone):
                self.assertNotIn(f'android:id="@+id/{gone}"', layout)
        for source in MAIN, WATCHER, STATUS_SERVICE:
            self.assertNotIn("admin_token", source.read_text(encoding="utf-8"))

    def test_the_content_description_is_a_button_name_not_the_help_text(self):
        self.assertIn('name="cd_settings"', self.strings)
        settings_hint = self.strings.index('name="settings_hint"')
        cd = self.strings.index('name="cd_settings"')
        hint_line = self.strings[settings_hint:self.strings.index("</string>", settings_hint)]
        cd_line = self.strings[cd:self.strings.index("</string>", cd)]
        # The button is named briefly; the paragraph stays help text, and the
        # two are different strings.
        self.assertNotEqual(hint_line, cd_line)
        self.assertLess(len(cd_line), len(hint_line))


class StatusTileCopyTest(unittest.TestCase):
    """Owner order 2026-10-13: the resume sentence leaves the first tile."""

    def setUp(self):
        self.strings = STRINGS.read_text(encoding="utf-8")
        self.watcher = WATCHER.read_text(encoding="utf-8")

    def test_the_resume_sentence_is_retired(self):
        self.assertNotIn("market_resume_hint", self.strings)
        self.assertNotIn("Trading resumes", self.strings)
        self.assertNotIn("resumeLine", self.watcher)
        self.assertNotIn("nextEvent", self.watcher)
        self.assertNotIn("next_event", self.watcher)

    def test_the_tile_still_carries_the_condition_sentence(self):
        # The relay's own phase sentence stays: only the resume line is gone.
        # v1.7.2 (owner order 2026-10-16) moved this reader into fetchHead, the
        # one place both fetch rounds read /health, so the phase holder is the
        # round's own `head.phase` rather than a local named healthMarket. The
        # behaviour is unchanged and is still pinned as behaviour: the sentence
        # is produced from the relay's phase and appended to the detail line.
        self.assertIn("String line = phaseLine(c, head.phase);", self.watcher)
        self.assertIn("d.append('\\n').append(line);", self.watcher)
        # And there is exactly ONE such reader, so the two cadences cannot
        # drift into two different sentences about the same session.
        self.assertEqual(self.watcher.count("phaseLine(c, head.phase)"), 1)
        self.assertIn("private static Head fetchHead(", self.watcher)


class BrandRuleTest(unittest.TestCase):
    """Line, diamond, line: defined once, used at every division.

    Owner order 2026-10-13 (second note): a rule now divides the system status
    tile from the latest signal tile, and the rule that closed the market card
    from inside it now stands immediately after that tile's own boundary. The
    layout is read as a tree here rather than as text, so "between the tiles"
    and "not inside one" are positions rather than prose.
    """

    def setUp(self):
        self.layout = LAYOUT.read_text(encoding="utf-8")
        self.rule = RULE.read_text(encoding="utf-8")

    def test_the_rule_is_defined_once_and_included_at_every_division(self):
        self.assertIn("QorDiamond", self.rule)
        self.assertIn('android:text="@string/diamond"', self.rule)
        self.assertEqual(self.layout.count('layout="@layout/qor_rule"'), 4)

    def test_the_rules_stand_between_the_tiles_and_never_inside_them(self):
        root = layout_root()

        def rule_after(view_id: str):
            view = find_view(root, view_id)
            following = siblings_after(root, parent_of(root, view))
            self.assertTrue(following, f"nothing follows the {view_id} tile")
            first = following[0]
            self.assertEqual(first.tag, "include", f"{view_id}: no rule after")
            self.assertEqual(first.get("layout"), "@layout/qor_rule")

        # Every tile is closed by the rule, and the third one from outside.
        # Owner order 2026-10-13 (third note): the card's last view is the
        # ranking itself now, because the cadence sentence it used to carry
        # has moved below the fourth rule.
        rule_after("@+id/status_pill")
        rule_after("@+id/signal_list")
        rule_after("@+id/market_leaders")

        # And no rule is drawn inside the market card any more: the divider
        # stands after its boundary, not as part of it.
        card = parent_of(root, find_view(root, "@+id/market_leaders"))
        for node in card.iter():
            if node.tag == "include":
                self.assertNotEqual(node.get("layout"), "@layout/qor_rule")

    def test_the_diamond_keeps_a_face_that_can_draw_it(self):
        block = STYLES.read_text(encoding="utf-8")
        diamond = block.index('name="QorDiamond"')
        body = block[diamond:block.index("</style>", diamond)]
        # No fontFamily ITEM: U+25C6 is in none of the bundled faces, so a
        # custom family here would draw a box. (The comment says the word,
        # which is why this checks the item, not the word.)
        self.assertNotIn('<item name="android:fontFamily">', body)
        self.assertFalse(has_codepoint(FONT_DIR / "bonskin.otf", DIAMOND))
        self.assertFalse(has_codepoint(FONT_DIR / "lemonmilk_light.otf", DIAMOND))


class TypefaceTest(unittest.TestCase):
    """The owner's faces, wired where each of them can actually render."""

    def setUp(self):
        self.layout = LAYOUT.read_text(encoding="utf-8")
        self.styles = STYLES.read_text(encoding="utf-8")
        self.main = MAIN.read_text(encoding="utf-8")

    def test_the_brand_face_is_bonskin_and_no_longer_synthesises_bold(self):
        brand = element(self.layout, 'android:text="@string/app_name"')
        self.assertIn('android:fontFamily="@font/bonskin"', brand)
        self.assertNotIn("textStyle", brand)
        self.assertNotIn("letterSpacing", brand)

    def test_the_brand_fits_the_narrowest_screen(self):
        # Measured advance: 6.677 em. A 24sp brand would be 160dp on a 320dp
        # content width, so 30sp (200dp) still leaves the header air.
        brand = element(self.layout, 'android:text="@string/app_name"')
        self.assertIn('android:textSize="30sp"', brand)

    def test_the_brand_is_never_measured_with_the_tight_font_box(self):
        # Bonskin's ink for "Quant of Rehan" reaches 779/1000 em, above its own
        # typographic ascender (730/1000), so includeFontPadding="false" would
        # clip the top of the Q. The default box uses the wider hhea metrics
        # (1006 / -288), which contain the ink. Measured, so not a style
        # preference.
        brand = element(self.layout, 'android:text="@string/app_name"')
        self.assertNotIn("includeFontPadding", brand)

    def test_the_status_and_signal_tiles_are_set_in_the_owners_faces(self):
        # Owner order 2026-10-13: every line inside these two tiles. The badge
        # is a container since 2026-10-14 (beacon plus word), so the word is
        # the element that carries the face, the size and the colour.
        word = element(self.layout, 'android:id="@+id/status_word"')
        self.assertIn('android:fontFamily="@font/lemonmilk_bold"', word)
        self.assertIn('android:textSize="13sp"', word)
        # LEMON MILK Bold is already bold, so no synthesised weight on top.
        self.assertNotIn("textStyle", word)
        badge = element(self.layout, 'android:id="@+id/status_pill"')
        self.assertIn("<LinearLayout", badge)
        self.assertIn("@+id/status_dot", badge)
        for view_id in ("status_detail", "signal_list"):
            with self.subTest(view=view_id):
                view = element(self.layout, f'android:id="@+id/{view_id}"')
                self.assertIn('style="@style/QorValue"', view)
        value = self.styles[self.styles.index('name="QorValue"'):]
        self.assertIn("@font/lemonmilk_light", value[:value.index("</style>")])

    def test_no_line_inside_those_tiles_falls_back_to_a_legacy_face(self):
        # The clock span used to force monospace and a synthesised bold; the
        # tiles are one face end to end now.
        self.assertNotIn('TypefaceSpan("monospace")', self.main)
        self.assertNotIn("StyleSpan", self.main)

    def test_the_settings_paragraph_keeps_the_system_face(self):
        # Out of the owner's scope on purpose: the hint is a paragraph, so it
        # stays readable as a sentence rather than as capitals.
        hint = element(self.layout, 'android:text="@string/settings_hint"')
        self.assertIn('style="@style/QorBody"', hint)
        body = self.styles[self.styles.index('name="QorBody"'):]
        self.assertNotIn("@font/", body[:body.index("</style>")])

    def test_the_caps_faces_are_wired_to_the_caps_text(self):
        self.assertEqual(self.styles.count("@font/lemonmilk_bold"), 2)
        self.assertIn('android:fontFamily="@font/lemonmilk_light"',
                      element(self.layout, 'android:text="@string/tagline"'))
        value = self.styles[self.styles.index('name="QorValue"'):]
        caption = self.styles[self.styles.index('name="QorCaption"'):]
        self.assertIn("@font/lemonmilk_light", value[:value.index("</style>")])
        self.assertIn("@font/lemonmilk_light", caption[:caption.index("</style>")])
        self.assertIn('style="@style/QorValue"',
                      element(self.layout, 'android:id="@+id/market_leaders"'))
        self.assertIn('style="@style/QorCaption"',
                      element(self.layout, 'android:id="@+id/scan_cadence"'))
        self.assertIn('android:fontFamily="@font/lemonmilk_bold"',
                      element(self.layout, 'android:id="@+id/market_index"'))

    def test_the_arrow_glyphs_are_drawn_by_a_face_that_has_them(self):
        light = FONT_DIR / "lemonmilk_light.otf"
        for arrow in (ARROW_UP, ARROW_DOWN):
            self.assertFalse(has_codepoint(light, arrow))
        # So the two ranges are overridden in code, arrow character only.
        self.assertIn('private static final String ARROW_FACE = "sans-serif"',
                      self.main)
        self.assertIn("new TypefaceSpan(ARROW_FACE), from, from + 1", self.main)

    def test_the_quantities_carry_no_estimate_tag(self):
        """Owner order 2026-10-20 (third note): EST leaves the phone.

        The tag was the last survivor of the split's labelling, and the owner
        read it as part of the quantity. Both sides now carry the plain "="
        and nothing follows the closing bracket, on the card and in the search
        answer. The relay still says which method it used in its own JSON
        (SO-3), and this app never invents a value for a field the relay left
        out.
        """
        self.assertNotIn('sb.append("  EST")', self.main)
        self.assertIn('sb.append(" (B=");', self.main)
        # v1.8.4 (owner 14:19): the separators inside the group are single
        # spaces, so a five million/share B and a twenty-seven million S
        # never wrap the T onto its own line again.
        self.assertIn('sb.append(" S=");', self.main)
        self.assertIn('" T=%,d)"', self.main)
        self.assertNotIn('sb.append("  S")', self.main)
        self.assertNotIn("\u2248", self.main)
        self.assertNotIn("estimatedSplit", self.main)
        watcher = WATCHER.read_text(encoding="utf-8")
        self.assertNotIn('sb.append("  EST")', watcher)
        self.assertNotIn("estimatedSplit", watcher)

    def test_the_bundled_faces_carry_their_licences(self):
        for name in ("Bonskin-PersonalUse.txt", "LEMONMILK-ReadMe.txt"):
            with self.subTest(licence=name):
                text = (LICENCES / name).read_text(encoding="utf-8").lower()
                self.assertIn("personal", text)

    def test_every_new_face_is_inside_the_apk_build(self):
        for name in ("bonskin.otf", "lemonmilk_bold.otf", "lemonmilk_light.otf"):
            with self.subTest(font=name):
                self.assertTrue((FONT_DIR / name).is_file())
                self.assertIn(name, README.read_text(encoding="utf-8"))

    def test_the_owners_icon_is_documented_where_the_faces_are(self):
        self.assertIn("settings.png", README.read_text(encoding="utf-8"))


class CadencePlacementTest(unittest.TestCase):
    """Owner order 2026-10-13 (third note): the sentence moves, verbatim.

    It leaves the market card and stands immediately after the final diamond
    rule. Fifth note: its separation from that rule is the layout's own 12dp,
    the gap every tile has below its rule, so the console's last line sits on
    the grid, and the two leading newlines are retired from the resource.
    The layout is read as a tree, so "after the last rule" and "not inside
    the card" are positions rather than prose, and the resource holds exactly
    the owner's sentence with no air smuggled into it.
    """

    # Owner order 2026-10-21 13:08 (v1.8.3): the exact replacement the owner
    # dictated, in caps, for the footer sentence.
    CADENCE = "QUANT WILL BE SCANNING THE LIVE, THE POST & THE PRE MARKET EVERY SECOND."

    def setUp(self):
        self.layout = LAYOUT.read_text(encoding="utf-8")
        self.strings = STRINGS.read_text(encoding="utf-8")
        self.main = MAIN.read_text(encoding="utf-8")
        self.root = layout_root()

    def resource_value(self, name: str) -> str:
        marker = f'name="{name}">'
        start = self.strings.index(marker) + len(marker)
        return self.strings[start:self.strings.index("</string>", start)]

    def test_the_sentence_stands_after_the_final_rule_as_the_last_view(self):
        rules = [node for node in self.root.iter() if node.tag == "include"
                 and node.get("layout") == "@layout/qor_rule"]
        self.assertEqual(len(rules), 4)
        following = siblings_after(self.root, rules[-1])
        self.assertEqual(len(following), 1, "the console ends at the sentence")
        view = following[0]
        self.assertEqual(view.tag, "TextView")
        self.assertEqual(view.get(f"{ANDROID_NS}id"), "@+id/scan_cadence")
        self.assertEqual(view.get(f"{ANDROID_NS}text"), "@string/scan_cadence")
        self.assertEqual(view.get("style"), "@style/QorCaption")

    def test_the_market_card_no_longer_carries_the_sentence(self):
        self.assertIsNone(find_view(self.root, "@+id/market_foot"))
        card = parent_of(self.root, find_view(self.root, "@+id/market_leaders"))
        for node in card.iter():
            self.assertNotIn("scan_cadence",
                             node.get(f"{ANDROID_NS}text") or "")
        # And nothing in the code sets it any more: the line is declarative.
        self.assertNotIn("marketFoot", self.main)
        self.assertNotIn("footText", self.main)

    def test_the_separation_is_the_grids_own_gap(self):
        # Fifth note: the air above the sentence is a layout fact now, the
        # same 12dp the tiles have below their rules, so the sentence sits
        # on the console's grid. The resource holds the words and nothing
        # else: no leading break, no smuggled indent.
        # The owner's dictated sentence, in caps, with &amp; as the XML
        # escape of the ampersand.
        value = self.resource_value("scan_cadence")
        self.assertEqual(
            value,
            "QUANT WILL BE SCANNING THE LIVE, THE POST &amp; THE PRE MARKET "
            "EVERY SECOND.")
        self.assertNotIn("\\n", value)
        view = find_view(self.root, "@+id/scan_cadence")
        margin = view.get(f"{ANDROID_NS}layout_marginTop")
        self.assertEqual(margin, "12dp")
        # And it is THE grid's gap, not a number picked for the footer: the
        # latest signal tile has exactly the same margin below its rule.
        signal_card = parent_of(self.root,
                                find_view(self.root, "@+id/signal_list"))
        self.assertEqual(margin,
                         signal_card.get(f"{ANDROID_NS}layout_marginTop"))

    def test_the_sentence_still_appears_in_exactly_one_resource(self):
        # v1.8.3 wording: the owner's dictated sentence, in caps.
        lines = [line for line in self.strings.splitlines()
                 if "SCANNING THE LIVE, THE POST &amp; THE PRE MARKET" in line]
        self.assertEqual(len(lines), 1, lines)


class StatusPulseTest(unittest.TestCase):
    """Owner order 2026-10-14 (seventh note): the breath, rebuilt again.

    The beacon is its own view inside the badge, and the pulse is a view
    property animation on its alpha and scale. That is this platform's
    equivalent of a CSS keyframe rule on opacity and transform: the platform
    keeps the two properties in the RenderNode and interpolates them on the
    render thread, so no frame of the breath measures, lays out or draws on
    the UI thread, and the pill's word cannot be disturbed by it. And only a
    live market breathes: ONLINE pulses, while OFFLINE and CHECKING hold a
    light that is not moving.
    """

    def setUp(self):
        self.main = MAIN.read_text(encoding="utf-8")
        self.layout = LAYOUT.read_text(encoding="utf-8")

    def test_the_pulse_is_a_view_property_animation(self):
        # Alpha and scale on the beacon's own view: the pair the render thread
        # interpolates. The drawable rewrite of 2026-10-13 is retired with its
        # frame budget, its ValueAnimator and its bounds arithmetic.
        self.assertIn("statusDot.animate()", self.main)
        self.assertIn(".alpha(alpha)", self.main)
        self.assertIn(".scaleX(scale)", self.main)
        self.assertIn(".scaleY(scale)", self.main)
        self.assertIn("new AccelerateDecelerateInterpolator()", self.main)
        self.assertNotIn("ValueAnimator", self.main)
        self.assertNotIn("FRAME_MS", self.main)
        self.assertNotIn("setFrameDelay", self.main)
        self.assertNotIn("getCompoundDrawablesRelative", self.main)
        self.assertNotIn("dot.setBounds", self.main)
        self.assertNotIn("drawBreathFrame", self.main)

    def test_the_beacon_is_its_own_view(self):
        # A compound drawable cannot be animated by the platform, which is why
        # the badge became a container: the beacon is an ImageView, the word is
        # a TextView, and the badge is the pill around them.
        badge = element(self.layout, 'android:id="@+id/status_pill"')
        self.assertIn("<LinearLayout", badge)
        self.assertIn("@+id/status_dot", badge)
        dot = element(self.layout, 'android:id="@+id/status_dot"')
        self.assertIn('android:layout_width="18dp"', dot)
        self.assertIn('android:src="@drawable/ic_status_checking"', dot)
        # One spoken state on the badge, and the two children are decoration for
        # the reader: the word alone would be read a second time against it.
        self.assertIn('android:importantForAccessibility="yes"', badge)
        self.assertIn('android:contentDescription="@string/cd_status_checking"',
                      badge)
        self.assertIn('android:importantForAccessibility="no"',
                      element(self.layout, 'android:id="@+id/status_word"'))
        # And MainActivity moves the two children with the state, exactly as it
        # moved the compound drawable and the text before.
        self.assertIn("statusDot.setImageResource(online", self.main)
        self.assertIn("statusWord.setText(getString(online", self.main)
        self.assertIn("statusWord.setTextColor(getColor(online", self.main)
        self.assertIn("statusBadge.setContentDescription(getString(online",
                      self.main)

    def test_only_a_live_market_breathes(self):
        # Owner order 2026-10-14: a closed market, its midday break and an
        # unreachable relay all hold a still light, and so does CHECKING, where
        # the app has no state to show yet. The state is carried by the word and
        # the colour, never by the motion, so a pulse cannot claim the market is
        # trading (SO-3).
        self.assertNotIn('"OPEN".equals(market.phase)', self.main)
        self.assertNotIn("setStatusBreath", self.main)
        render = self.main.index("private void render(")
        # The answer is painted through the gate since v1.7.5, so the breath is
        # reached in paint(): the slice runs to the fingerprint that follows it
        # rather than to a fixed width, which is what a comment edit breaks.
        self.assertIn("breathIfOnline(online)",
                      self.main[render:self.main.index("private static int marketFingerprint(",
                                                       render)])
        gate = self.main.index("private void breathIfOnline(")
        body = self.main[gate:gate + 400]
        self.assertIn("if (online)", body)
        self.assertIn("startStatusBreath();", body)
        self.assertIn("stopStatusBreath();", body)

    def test_the_breath_returns_to_rest_between_cycles(self):
        # Half a cycle out and half back, the return started when the first
        # direction lands, so the light never jumps and the breath repeats until
        # the state changes. 2.2 seconds a cycle: slow enough to read as alive
        # rather than as a blink.
        self.assertIn("private static final long BREATH_MS = 2200L;", self.main)
        self.assertIn(".setDuration(BREATH_MS / 2)", self.main)
        self.assertIn("withEndAction", self.main)
        self.assertIn("breatheBack", self.main)
        self.assertIn("this::startStatusBreath", self.main)
        self.assertIn("BREATH_MIN_ALPHA", self.main)
        self.assertIn("BREATH_MIN_SCALE", self.main)
        # Rest is full opacity at the beacon's own size, so a stopped breath
        # cannot leave the dot dim or shrunk.
        stop = self.main.index("private void stopStatusBreath(")
        body = self.main[stop:stop + 400]
        for line in ("statusDot.animate().cancel()", "statusDot.setAlpha(1f)",
                     "statusDot.setScaleX(1f)", "statusDot.setScaleY(1f)"):
            with self.subTest(line=line):
                self.assertIn(line, body)

    def test_a_hidden_console_leaves_it_still(self):
        # v1.7.1: a hidden console releases BOTH things onResume started. The
        # breath stops, and the cadence loop is removed from the main queue so
        # a backgrounded app holds no poll; onResume re-arms both. v1.7.2 adds
        # a third release to the same block (the resumed flag, so a round in
        # flight cannot paint or re-breath after the pause). The window is 700
        # characters because every reason is stated where it is done.
        self.assertIn("stopStatusBreath();", self.main)
        pause = self.main.index("protected void onPause()")
        body = self.main[pause:pause + 700]
        self.assertIn("resumed = false;", body)
        self.assertIn("cadence.removeCallbacks(tick)", body)
        self.assertIn("stopStatusBreath()", body)

    def test_the_console_repaints_at_the_live_scan_cadence(self):
        """Owner orders 2026-10-16: the console polls by itself.

        Both halves are pinned together here: the loop schedules itself (no
        manual refresh, no repaint only on open), and the idle interval is
        still the cloud's 30 second scan, which the relay's card cadence and
        the scanner's own config agree on.
        """
        resume = self.main.index("protected void onResume()")
        self.assertIn("scheduleNext();", self.main[resume:resume + 900])
        watcher = (ROOT / "android" / "app" / "src" / "main" / "java"
                   / "pk" / "quantofrehan" / "Watcher.java").read_text(
            encoding="utf-8")
        self.assertIn("static final long REFRESH_MS = 30 * 1000;", watcher)
        # The background arm is a watchdog, not a poll, and says so.
        self.assertIn("static final long WATCHDOG_MS = 1000;", watcher)
        self.assertIn("System.currentTimeMillis() + WATCHDOG_MS", watcher)
        # And the app's interval is the scanner's own, not a second opinion.
        config_text = (ROOT / "src" / "config.py").read_text(encoding="utf-8")
        self.assertIn('SCAN_INTERVAL_SECONDS = _number("SCAN_INTERVAL_SECONDS", 1)',
                      config_text)

    def test_a_live_market_is_polled_once_a_second(self):
        """Owner order 2026-10-16: one second while the market is open.

        The interval is chosen from the RELAY's own answer (`market_open`,
        carried into marketOpenSeen by render), never from the phone's clock
        (SO-8), and both the resume path and the tick itself schedule through
        the one method, so there is a single place where the cadence is
        decided.
        """
        watcher = (ROOT / "android" / "app" / "src" / "main" / "java"
                   / "pk" / "quantofrehan" / "Watcher.java").read_text(
            encoding="utf-8")
        self.assertIn("static final long FAST_POLL_MS = 1000;", watcher)
        self.assertIn("private void scheduleNext()", self.main)
        self.assertIn("marketOpenSeen = online;", self.main)
        self.assertIn("cadence.postDelayed(tick, marketOpenSeen", self.main)
        self.assertIn("? Watcher.FAST_POLL_MS : Watcher.REFRESH_MS);", self.main)
        # The tick itself goes through the same scheduling point, so a fast
        # round is followed by another fast round without a second loop.
        tick = self.main.index("private final Runnable tick")
        self.assertIn("scheduleNext();", self.main[tick:tick + 400])
        # The phone never derives the session from its own clock.
        self.assertNotIn("Calendar", self.main)
        self.assertNotIn("LocalTime", self.main)
        self.assertNotIn("System.currentTimeMillis()", self.main)

    def test_the_interval_is_re_decided_when_the_answer_lands(self):
        """Owner order 2026-10-16 (fourth note): the reported defect.

        The console was reported as never refreshing every second. The cause
        was an ordering bug, not a missing feature: onResume scheduled the
        next round BEFORE any answer had arrived, and the interval is chosen
        from the relay's own `market_open`, which is false on a fresh process.
        So an open market was polled at the 30 second idle interval until a
        whole idle round had completed, which is what the owner saw as "it
        never refreshes every second".

        The fix keeps the single scheduling point and calls it from render as
        well, the moment the answer lands: the interval now changes with the
        market rather than one idle interval later. scheduleNext removes the
        one runnable before re-posting it, so the extra call cannot stack a
        second loop.
        """
        render = self.main[self.main.index("private void render(boolean online"):]
        render = render[:render.index("private String latestSignalDisplay(")]
        # The state is taken from the answer before the cadence is re-decided:
        # the order of these two lines is the fix.
        self.assertLess(render.index("marketOpenSeen = online;"),
                        render.index("scheduleNext();"))
        self.assertIn("cadence.removeCallbacks(tick);", self.main)
        self.assertEqual(self.main.count("scheduleNext();"), 3,
                         "onResume, the tick and the answer: one method")

    def test_system_tile_has_quant_title_without_polling_status_copy(self):
        """The status tile reports relay data, not local polling cadence."""
        strings = STRINGS.read_text(encoding="utf-8")
        self.assertIn('name="label_system">QUANT STATUS</string>', strings)
        self.assertNotIn('name="app_live"', strings)
        self.assertNotIn("polling every", strings.lower())
        self.assertNotIn("live polling", strings.lower())
        render = self.main[self.main.index("private void render(boolean online"):]
        render = render[:render.index("private String latestSignalDisplay(")]
        self.assertIn("statusDetail.setText(clockSpans(actualDetail));", render)
        self.assertNotIn("liveLine()", render)
        self.assertNotIn("Watcher.FAST_POLL_MS", render)
        # The status sentence remains the relay's session-clock response.
        self.assertIn("Karachi: ", WATCHER.read_text(encoding="utf-8"))

    def test_the_settings_hint_separates_the_two_cadences(self):
        """Settings help must not masquerade as a live-poll status label."""
        strings = STRINGS.read_text(encoding="utf-8")
        hint = strings[strings.index('name="settings_hint">')
                       + len('name="settings_hint">'):]
        hint = hint[:hint.index("</string>")]
        # Owner order 2026-10-19: the hint no longer mentions a token or a
        # feed at all, and it must still never promise a poll cadence.
        self.assertIn("reads the relay by itself", hint)
        self.assertNotIn("every second", hint)
        self.assertNotIn("every 30 seconds", hint)
        self.assertNotIn("polling", hint.lower())
        self.assertNotIn("token", hint.lower())

    def test_one_round_at_a_time_so_the_poll_cannot_pile_up(self):
        """A one second poll must not queue a second round behind the first.

        The guard is one boolean: set by the round, cleared in its callback,
        and checked before a round starts. Every path of a round calls the
        callback (including the error path), so a failed request releases the
        loop instead of freezing the console.
        """
        poll = self.main.index("private void pollOnce()")
        self.assertIn("if (!liveInFlight) {", self.main[poll:poll + 600])
        self.assertEqual(self.main.count("liveInFlight = true;"), 2)
        self.assertEqual(self.main.count("liveInFlight = false;"), 2)
        # Owner order 2026-10-19: neither round carries a credential, because
        # the phone holds none.
        self.assertIn("Watcher.fetchLive(this, (online", self.main)
        self.assertIn("Watcher.fetchStatus(this, (online", self.main)
        self.assertNotIn("admin_token", self.main)

    def test_a_round_that_lands_after_a_pause_paints_nothing(self):
        """A hidden console holds no animation and no poll.

        A fetch started just before onPause can answer just after it, and
        rendering that answer would restart the status breath onPause had just
        stopped. The callback therefore always releases the in-flight flag and
        paints only while the console is resumed.
        """
        self.assertIn("private boolean resumed;", self.main)
        resume = self.main.index("protected void onResume()")
        self.assertIn("resumed = true;", self.main[resume:resume + 300])
        pause = self.main.index("protected void onPause()")
        self.assertIn("resumed = false;", self.main[pause:pause + 500])
        # Both rounds guard the paint, and both still release the flag first.
        # Since 2026-10-16 (fourth note) each callback also drops its
        # reference to a finished console before it looks at `resumed`, which
        # is the same rule one step further out: a round that outlived its
        # activity paints nothing and holds nothing.
        self.assertEqual(self.main.count("liveInFlight = false;"), 2)
        # A third callback joins in v1.7.8: the search's one-symbol read, which
        # guards its paint the same way the two refresh rounds do.
        # v1.7.9 adds the fourth: the per-tick price read that paints the
        # search rows, guarded exactly like the two rounds and the one-symbol
        # answer.
        self.assertEqual(self.main.count("isFinishing() || isDestroyed()"), 4)
        self.assertEqual(self.main.count("if (resumed) {"), 2)
        for marker in ("private void refresh()", "private void refreshLive()"):
            body = self.main[self.main.index(marker):][:800]
            self.assertLess(body.index("liveInFlight = false;"),
                            body.index("isFinishing() || isDestroyed()"))
            self.assertLess(body.index("isFinishing() || isDestroyed()"),
                            body.index("if (resumed) {"))

    def test_the_card_reads_the_live_broker_snapshot_without_a_third_read(self):
        """Owner orders 2026-10-19 and 2026-10-20 (third note).

        /quotes is the Durable Object's newest broker frame set, and the relay
        merges it into /market on every read (applyLiveQuotes in
        cloud/worker.js). The phone's one-second round therefore makes two
        reads, health and card, instead of three: the third cost a round trip
        on every tick and pushed the paint out to two or three seconds. The
        full round keeps the direct overlay as a fallback, and a stale quote
        never overwrites a card value in either place.
        """
        watcher = WATCHER.read_text(encoding="utf-8")
        worker = (ROOT / "cloud" / "worker.js").read_text(encoding="utf-8")
        self.assertIn("private static void applyLiveQuotes(Market market, String base)",
                      watcher)
        self.assertIn('get(base + "/quotes", null)', watcher)
        self.assertIn("if (index != null && index.optBoolean(\"fresh\", false))", watcher)
        self.assertIn("!quote.optBoolean(\"fresh\", false)", watcher)
        self.assertIn("function applyLiveQuotes(snapshot, quotes, now)", worker)
        full = watcher[watcher.index("static void fetchStatus("):][:1200]
        self.assertIn("applyLiveQuotes(market, base);", full)
        live = watcher[watcher.index("static void fetchLive("):]
        live = live[:live.index("static void fetchStatus(")]
        self.assertIn("Market market = fetchMarket(c, base);", live)
        self.assertNotIn("applyLiveQuotes(market, base);", live)

    def test_the_market_card_is_read_on_each_live_display_refresh(self):
        """The app polls the current relay card each second while open.

        This is a display read, not a new scan or an upstream-feed promise:
        the relay snapshot carries the broker timestamp and is published by
        the cloud session runner at its protected SO-13 cadence.
        """
        watcher = (ROOT / "android" / "app" / "src" / "main" / "java"
                   / "pk" / "quantofrehan" / "Watcher.java").read_text(
            encoding="utf-8")
        self.assertNotIn("CARD_EVERY_SECONDS", self.main)
        self.assertIn("static final long DISPLAY_REFRESH_MS = FAST_POLL_MS;",
                      watcher)
        live = watcher.index("static void fetchLive(")
        live_body = watcher[live:live + 1100]
        self.assertIn("Market market = fetchMarket(c, base);", live_body)
        self.assertIn("head.signals, market);", live_body)
        poll = self.main.index("private void pollOnce()")
        self.assertIn("refreshLive();", self.main[poll:poll + 700])
        self.assertIn("The card route is read from the relay's latest pushed broker snapshot",
                      self.main)

    def test_the_settings_menu_stands_alone_while_it_is_open(self):
        """Owner order 2026-10-16: the menu is exclusive.

        Tapping the gear leaves the settings menu as the only thing on the
        screen: the system status tile, the latest signal tile, the market
        card, the three rules between and after them and the cadence sentence
        all leave together. They leave as GONE rather than INVISIBLE, so the
        menu takes the space the console gave up (no hole to scroll past) and
        a screen reader announces the menu alone.
        """
        for name in ("tile_status", "rule_status_signal", "tile_signal",
                     "rule_after_signal", "tile_market", "rule_after_market",
                     "scan_cadence"):
            with self.subTest(view=name):
                self.assertIsNotNone(find_view(layout_root(), f"@+id/{name}"))
                self.assertIn(f"findViewById(R.id.{name})", self.main)
        self.assertIn("view.setVisibility(open ? View.GONE : View.VISIBLE);",
                      self.main)
        self.assertNotIn("View.INVISIBLE", self.main)
        # The three tiles the owner named are the three the array holds: the
        # market card is hidden with the other two rather than left behind.
        self.assertIn("findViewById(R.id.tile_market)", self.main)

    def test_the_settings_toggle_is_idempotent_and_reads_no_view(self):
        """Clean state, no re-render loop (owner order 2026-10-16).

        The state is one boolean and the views are drawn FROM it. The toggle
        returns early when the value has not changed, so a repeated tap, a
        restored activity or a stray second call cannot re-run the animations
        or thrash the view tree; and no listener reads a view's visibility
        back to decide what the state is.
        """
        self.assertIn("private boolean settingsOpen;", self.main)
        open_call = self.main.index("private void setSettingsOpen(boolean open)")
        body = self.main[open_call:open_call + 700]
        self.assertIn("if (open == settingsOpen) {", body)
        self.assertIn("settingsOpen = open;", body)
        listener = self.main.index("btnSettings.setOnClickListener")
        self.assertIn("setSettingsOpen(!settingsOpen)",
                      self.main[listener:listener + 220])
        self.assertNotIn("getVisibility() == View.GONE", self.main)

    def test_the_offline_light_is_the_online_light_in_red_and_it_is_still(self):
        """Owner order 2026-10-16 (fourth note), verbatim: "when the market is
        OFFLINE ... I want that icon exactly like the ONLINE icon just in red
        color but also not breathing ... there should be a round ball type
        structure should also be inside that thick line just like ONLINE icon
        has it".

        So the two beacons are compared layer by layer, by their own geometry
        rather than by their prose: same number of layers, same path data in
        the same order, same stroke widths. Anything that makes them differ by
        more than colour fails here. The stillness is the second half of the
        order and lives in MainActivity's gate, which starts the breath only
        for a live market.
        """
        def attr(dot, name):
            root = ET.parse(dot).getroot()
            return [p.get(f"{ANDROID_NS}{name}") for p in root.iter("path")]

        geometry = ("pathData", "strokeWidth")
        for name in geometry:
            with self.subTest(attribute=name):
                self.assertEqual(attr(OFFLINE_DOT, name), attr(ONLINE_DOT, name))
        # Three layers, and their fills are the SAME three slots: the halo
        # stays transparent (it is a stroked ring), the middle is the body,
        # the centre is the ball. Only the palette differs.
        self.assertEqual(attr(ONLINE_DOT, "fillColor"),
                         ["#00000000", "@color/green_glow", "@color/green_hi"])
        self.assertEqual(attr(OFFLINE_DOT, "fillColor"),
                         ["#00000000", "@color/red_core", "@color/red_hi"])
        self.assertEqual(attr(ONLINE_DOT, "strokeColor"),
                         ["@color/green_halo", None, None])
        self.assertEqual(attr(OFFLINE_DOT, "strokeColor"),
                         ["@color/red_ring", None, None])
        # The centre the owner asked for: a filled ball inside a filled disc,
        # never a hollow ring.
        offline_text = OFFLINE_DOT.read_text(encoding="utf-8")
        self.assertIn("@color/red_core", offline_text)
        self.assertIn("@color/red_hi", offline_text)
        self.assertIn("@color/red_ring", offline_text)
        # And the palette holds that third weight, next to the green one.
        colors = COLORS.read_text(encoding="utf-8")
        self.assertIn('<color name="red_hi">', colors)
        # The stillness: one gate, called with the relay's own answer, so the
        # offline light is never animated (SO-3: a pulse over a shut market
        # would claim trading there is none).
        self.assertIn("private void breathIfOnline(boolean online)", self.main)
        self.assertIn("breathIfOnline(online);", self.main)
        # Two animations touch the beacon and only two: the pulse's own chain
        # (started by the gate above) and the cancel in stopStatusBreath,
        # which is what a non-live state and onPause call. So an offline light
        # is never animated, it is only ever returned to rest.
        self.assertEqual(self.main.count("statusDot.animate()"), 2)
        gate = self.main[self.main.index("private void breathIfOnline"):]
        gate = gate[:gate.index("private void breatheTo")]
        self.assertIn("if (online) {", gate)
        self.assertIn("startStatusBreath();", gate)
        self.assertIn("stopStatusBreath();", gate)
        # The still branch is the else one: a state that is not live never
        # starts a breath, it only ever returns the light to rest.
        self.assertIn("} else {\n            stopStatusBreath();", gate)
        # And the gate is called from the one place the relay's answer is
        # painted, with that answer rather than with a view's state.
        render = self.main[self.main.index("private void render(boolean online"):]
        render = render[:render.index("private String latestSignalDisplay(")]
        self.assertIn("breathIfOnline(online);", render)

    def test_the_online_light_is_green_and_the_offline_light_is_red(self):
        colors = COLORS.read_text(encoding="utf-8")
        online = ONLINE_DOT.read_text(encoding="utf-8")
        offline = OFFLINE_DOT.read_text(encoding="utf-8")
        # The beacons carry palette references, not hex of their own.
        for ref in ("@color/green_halo", "@color/green_glow",
                    "@color/green_hi"):
            with self.subTest(ref=ref):
                self.assertIn(ref, online)
        for ref in ("@color/red_ring", "@color/red_core"):
            with self.subTest(ref=ref):
                self.assertIn(ref, offline)
        for gone in ("#FF43C98A", "#662FAE6F", "#3343C98A"):
            with self.subTest(hex=gone):
                self.assertNotIn(gone, online)
        for gone in ("#59C14A52", "#CCC14A52"):
            with self.subTest(hex=gone):
                self.assertNotIn(gone, offline)
        # And the palette itself is the brand green and the brand red.
        self.assertIn('<color name="green">#FF2FAE6F</color>', colors)
        self.assertIn('<color name="green_hi">#FF43C98A</color>', colors)
        self.assertIn('<color name="red">#FFC14A52</color>', colors)
        self.assertIn('<color name="green_halo">#662FAE6F</color>', colors)
        self.assertIn('<color name="red_core">#CCC14A52</color>', colors)


class StatusTileSpacingTest(unittest.TestCase):
    """Owner order 2026-10-14 (eighth note): one number for the tile's air.

    "SYSTEM STATUS to ONLINE matches ONLINE to KARACHI" is a fact about two
    margins naming the same resource, not about two numbers that happen to be
    equal today, so this reads the resource names rather than the lengths: an
    edit that changes one margin by hand fails here instead of shipping a tile
    with two different gaps.
    """

    def setUp(self):
        self.layout = LAYOUT.read_text(encoding="utf-8")
        self.dimens = DIMENS.read_text(encoding="utf-8")

    def test_the_two_gaps_are_one_resource(self):
        badge = element(self.layout, 'android:id="@+id/status_pill"')
        detail = element(self.layout, 'android:id="@+id/status_detail"')
        self.assertIn('android:layout_marginTop="@dimen/status_gap"', badge)
        self.assertIn('android:layout_marginTop="@dimen/status_gap"', detail)
        # Exactly two views name it, so a third gap cannot quietly join the
        # tile and a hand-written number cannot replace either of these two.
        self.assertEqual(
            self.layout.count('android:layout_marginTop="@dimen/status_gap"'), 2)

    def test_the_gap_is_declared_once(self):
        self.assertEqual(self.dimens.count('name="status_gap"'), 1)
        self.assertEqual(self.dimens.count('name="status_dot_gap"'), 1)
        self.assertIn('<dimen name="status_gap">10dp</dimen>', self.dimens)
        self.assertIn('<dimen name="status_dot_gap">8dp</dimen>', self.dimens)

    def test_the_badge_keeps_the_air_it_had_between_beacon_and_word(self):
        # The beacon to the word gap is the 8dp the pill used to carry as a
        # compound drawable's padding, and it is the word's own left margin now.
        self.assertNotIn("drawablePadding", self.layout)
        word = element(self.layout, 'android:id="@+id/status_word"')
        self.assertIn('android:layout_marginLeft="@dimen/status_dot_gap"',
                      word)

    def test_the_margins_are_both_top_margins_on_centred_content(self):
        # The gap only reads as one rhythm because both views are centred in the
        # same column: the badge centres itself, and the detail line is a
        # full-width centred value.
        root = layout_root()
        badge = find_view(root, "@+id/status_pill")
        detail = find_view(root, "@+id/status_detail")
        self.assertEqual(badge.get(f"{ANDROID_NS}layout_gravity"),
                         "center_horizontal")
        self.assertEqual(detail.get(f"{ANDROID_NS}layout_width"), "match_parent")
        self.assertEqual(badge.get(f"{ANDROID_NS}layout_marginTop"),
                         detail.get(f"{ANDROID_NS}layout_marginTop"))
class HeaderCopyTest(unittest.TestCase):
    """Owner order 2026-10-16 (fourth note): two changes to the brand line.

    The label "PSX KMIALL" becomes "PSX's KMIALL INDEX", and "KARACHI TIME"
    leaves the header entirely. The Karachi clock itself is not retired: it
    stands in the system status tile, which is where a reader looks for it,
    and SO-8 keeps every time in this app on Asia/Karachi.
    """

    def setUp(self):
        self.strings = STRINGS.read_text(encoding="utf-8")
        self.layout = LAYOUT.read_text(encoding="utf-8")

    def resource_value(self, name: str) -> str:
        marker = f'name="{name}">'
        start = self.strings.index(marker) + len(marker)
        return self.strings[start:self.strings.index("</string>", start)]

    def test_the_header_names_the_index_it_follows(self):
        # The apostrophe is escaped in the resource (a bare one is read as
        # punctuation to be stripped), so the escaped and the rendered forms
        # are both checked here.
        self.assertEqual(self.resource_value("tagline"),
                         "PSX\\'s KMIALL INDEX")
        self.assertIn("PSX's KMIALL INDEX",
                      self.resource_value("tagline").replace("\\", ""))

    def test_the_timezone_note_is_gone_from_the_header(self):
        self.assertNotIn("KARACHI TIME", self.resource_value("tagline"))
        # No resource VALUE carries it either. Comments are not checked here:
        # the order that removed the note is quoted in the resource file's own
        # comment, and a test that forbade the words would forbid the record of
        # why they left.
        for value in ET.parse(STRINGS).getroot().iter("string"):
            with self.subTest(resource=value.get("name")):
                self.assertNotIn("KARACHI TIME", value.text or "")
        # The header line is the only view that carries it, and the tagline is
        # still the caps face the v1.6.x orders put it in.
        self.assertIn('android:text="@string/tagline"', self.layout)
        brand = element(self.layout, 'android:id="@+id/brand_tagline"')
        self.assertIn("@font/lemonmilk_light", brand)
        # The clock itself stays, in the tile the reader looks at.
        self.assertIn("Karachi: ", WATCHER.read_text(encoding="utf-8"))
        self.assertIn("SO-8", self.strings)


class VersionTest(unittest.TestCase):
    def test_the_version_is_the_one_that_ships_these_changes(self):
        # v1.8.3 is the 2026-10-21 13:07-13:08 pass: the pinned search line
        # keeps one space before its price, the closed search panel's bottom
        # gap equals its top gap, and the footer is the owner's exact
        # LIVE/POST/PRE sentence.
        manifest = MANIFEST.read_text(encoding="utf-8")
        self.assertIn('android:versionName="1.8.4"', manifest)
        self.assertIn('android:versionCode="38"', manifest)
        # The changelog entry ties these user-visible changes to the build.
        readme = (ROOT / "android" / "README.md").read_text(encoding="utf-8")
        self.assertIn("v1.7.9, owner order 2026-10-20", readme)
        self.assertIn("Version 1.8.0, versionCode 34", readme)
        self.assertIn("Version 1.8.1, versionCode 35", readme)
        self.assertIn("Version 1.8.2, versionCode 36", readme)
        self.assertIn("Version 1.8.3, versionCode 37", readme)
        self.assertIn("Version 1.8.4, versionCode 38", readme)
        layout = LAYOUT.read_text(encoding="utf-8")
        strings = STRINGS.read_text(encoding="utf-8")
        main = MAIN.read_text(encoding="utf-8")
        watcher = WATCHER.read_text(encoding="utf-8")
        self.assertNotIn('android:id="@+id/market_feed_status"', layout)
        self.assertNotIn('name="market_feed_unknown"', strings)
        self.assertNotIn('name="market_feed_halted"', strings)
        # v1.7.6: the feed-status line is gone and the card shows the broker
        # stamp instead; the signal tile keeps three numbers and no metadata.
        self.assertNotIn("renderMarketFeedStatus", main)
        # v1.7.9 (owner order 2026-10-20, third note): the index line carries
        # no clock at all, so the stamp reader is gone with it.
        self.assertNotIn("brokerClock", main)
        self.assertIn("latestSignalBackground = s;", main)
        self.assertIn("signalList.setText(latestSignalDisplay(actualSignals));", main)
        # v1.7.7: the three numbers and the ticker live in SignalText, and the
        # console only maps its two word states onto resources.
        signal_text = SIGNAL_TEXT.read_text(encoding="utf-8")
        self.assertIn("String text = SignalText.compact(raw);", main)
        self.assertIn("SignalText.NO_TRADE.equals(text)", main)
        self.assertIn("SignalText.UNAVAILABLE.equals(text)", main)
        self.assertNotIn("Entry Time: ", main + signal_text)
        self.assertIn("Entry Price: ", signal_text)
        self.assertIn("Exit Price: ", signal_text)
        self.assertIn("Stop Loss: ", signal_text)
        self.assertIn('return value == null ? NOT_REPORTED : value;', signal_text)
        self.assertIn('afterLabel(line, "Target:")', signal_text)
        self.assertIn("private static String leadingPrice(String value)", signal_text)
        self.assertIn("String numeric = leadingPrice(value);", signal_text)
        self.assertIn('price > 0.0 && !Double.isNaN(price)', signal_text)
        self.assertIn("if (numeric != null) {", signal_text)
        # The tile is the numbers alone: no header, no date, no rule prose.
        self.assertNotIn("QoR intraday", signal_text.split("*/", 1)[1])
        self.assertNotIn("app_live", strings)
        self.assertNotIn("polling every", strings.lower())
        self.assertNotIn("market_feed_status", layout)
        self.assertNotIn("market_feed_unknown", strings)
        self.assertNotIn("session clock remains the market-hours authority", strings)
        # The REG status is still parsed for the halt sentence; it just no
        # longer has a line of its own on the card.
        self.assertIn("feedStatus.optBoolean(\"fresh\", false)", watcher)
        self.assertIn("market_halted_now", strings)


class EmptySignalCopyTest(unittest.TestCase):
    """One spelling of the empty signal tile (owner order 2026-10-20).

    The tile's static placeholder and the two code paths that blank it are the
    same sentence, so a phone that has not had an answer yet reads exactly what
    a phone holding another session's card reads. Two spellings would let the
    old "No signal right now." outlive the order that retired it.
    """

    def test_the_tile_has_one_empty_state(self):
        layout = LAYOUT.read_text(encoding="utf-8")
        strings = STRINGS.read_text(encoding="utf-8")
        main = MAIN.read_text(encoding="utf-8")
        self.assertIn('android:text="@string/signal_no_call"', layout)
        self.assertNotIn("no_signals", layout)
        self.assertNotIn('name="no_signals"', strings)
        self.assertIn('name="signal_no_call"', strings)
        # Both the empty answer and another session's card land on that string.
        self.assertEqual(main.count("getString(R.string.signal_no_call)"), 2)


class SearchPanelStabilityTest(unittest.TestCase):
    """The searched stock cannot vanish and cannot lose its colour
    (owner report 2026-10-20, 14:07 PKT).

    The per-second price refresh used to tear the whole result list down and
    draw it again, so the stock the owner had just tapped was on screen only
    until the next tick. The law now is: the rows are rebuilt only when what
    is VISIBLE changes, the tapped symbol stays pinned in its own line, and
    that line is restamped from the live quote in the colour of the move.
    """

    def test_ticks_restyle_rows_in_place_instead_of_rebuilding(self):
        main = MAIN.read_text(encoding="utf-8")
        # The teardown happens only inside the rebuild branch, never per tick:
        # one removeAllViews call covers the whole redraw cost.
        self.assertEqual(main.count("searchResults.removeAllViews();"), 1)
        self.assertIn("boolean rebuild = !q.equals(renderedQuery)", main)
        self.assertIn("styleSearchRow(entry.getValue(), entry.getKey());", main)

    def test_the_tapped_symbol_stays_pinned_across_ticks(self):
        main = MAIN.read_text(encoding="utf-8")
        self.assertIn("private String selectedSymbol;", main)
        # The selection is cleared only on purpose: when the stock falls out
        # of the visible set, or when the panel closes.
        self.assertIn("selectSymbol(null);", main)
        self.assertIn("if (!symbol.equals(selectedSymbol)) {", main)
        self.assertIn("selectedBase = \"\";", main)

    def test_the_pinned_line_is_restamped_in_the_colour_of_the_move(self):
        main = MAIN.read_text(encoding="utf-8")
        self.assertIn("private void paintSelectedLine() {", main)
        marker = "String tail = quote.changePct == null"
        first = main.index(marker)
        tail = main[first:]
        self.assertIn("quote.changePct >= 0 ? R.color.green_hi : R.color.red", tail)
        # A real sign, and only a real sign, colours the row (SO-3).
        self.assertIn("? R.color.text_soft", tail)
        self.assertIn("R.color.green_hi", tail)
        self.assertIn("R.color.red", tail)
        self.assertIn("R.color.text_soft", tail)

    def test_the_search_glass_stack_matches_every_owner_order(self):
        dimens = (ROOT / "android" / "app" / "src" / "main" / "res" / "values"
                  / "dimens.xml").read_text(encoding="utf-8")
        # The stack: 50.4 (2026-10-20 first), 57.96 (the 15% order), and
        # today's 62.16 from the 10% order. Each predecessor value is gone
        # from the LIVE dimen; the history lives in the comment above it.
        self.assertIn('<dimen name="search_shift_x">62.16dp</dimen>', dimens)
        self.assertNotIn('>57.96dp</dimen>', dimens)
        self.assertNotIn('>50.4dp</dimen>', dimens)

    def test_the_search_hint_names_a_scrip_not_a_symbol(self):
        strings = STRINGS.read_text(encoding="utf-8")
        # Owner order 2026-10-21: "Search for a KMIALL scrip".
        self.assertIn('name="search_hint">Search for a KMIALL scrip<', strings)
        self.assertNotIn('Search a KMIALL symbol<', strings)

    def test_the_no_match_sentence_is_gone_from_the_panel(self):
        strings = STRINGS.read_text(encoding="utf-8")
        main = MAIN.read_text(encoding="utf-8")
        # Owner order 2026-10-21: a prefix that matches nothing prints no
        # sentence under the box; the box and the rows are the whole answer.
        self.assertNotIn('name="search_empty"', strings)
        self.assertNotIn("R.string.search_empty", main)
        self.assertIn('searchStatus.setText("");', main)

    def test_the_volume_now_tile_label_is_gone(self):
        strings = STRINGS.read_text(encoding="utf-8")
        layout = LAYOUT.read_text(encoding="utf-8")
        # Owner order 2026-10-21: tapping the search icon shows no VOLUME
        # NOW tile above the box; the hint inside the box is the label.
        self.assertNotIn('name="search_volume_label"', strings)
        self.assertNotIn('@string/search_volume_label', layout)

    def test_the_search_answer_prints_its_price_once_in_colour(self):
        main = MAIN.read_text(encoding="utf-8")
        watcher = WATCHER.read_text(encoding="utf-8")
        # Owner order 2026-10-21: the price and the percentage appear ONE
        # time in the search answer, in the colour of the move (green up,
        # red down), never in the neutral ink a second time.
        # fetchStock no longer carries its own money line; the live restamp
        # is the only PKR line the pinned answer shows.
        self.assertNotIn('"\\nPKR %,.2f"', watcher)
        # The paint pass still owns the one(true) money line.
        marker = "String tail = quote.changePct == null"
        first = main.index(marker)
        self.assertIn("styled.append(tail);", main[first:main.index("private String latestSignalDisplay")])

    def test_the_search_answer_prints_buy_green_and_sell_red(self):
        watcher = WATCHER.read_text(encoding="utf-8")
        # Owner order 2026-10-21: B in green and S in red, the digits
        # themselves, inside the fetched line.
        self.assertIn("c.getColor(R.color.green)), buyFrom, buyTo, 0);", watcher)
        self.assertIn("c.getColor(R.color.red)), sellFrom, sellTo, 0);", watcher)
        self.assertIn("int buyFrom = sb.length();", watcher)
        self.assertIn("int sellFrom = sb.length();", watcher)


if __name__ == "__main__":
    unittest.main()
