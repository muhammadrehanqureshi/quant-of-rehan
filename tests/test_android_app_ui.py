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
        # layout holds the centring, and MainActivity holds no listener that
        # could move the control after a layout.
        self.assertEqual(button.get(f"{ANDROID_NS}layout_centerVertical"),
                         "true")
        self.assertIsNone(button.get(f"{ANDROID_NS}layout_alignTop"))
        self.assertNotIn("alignSettingsToBrandBaseline", self.main)
        self.assertNotIn("btnSettings.setTranslationY", self.main)
        self.assertNotIn("addOnLayoutChangeListener", self.main)
        self.assertNotIn("brandTitle", self.main)
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
        # that overhang above the line and half below it.
        root = layout_root()
        button = find_view(root, "@+id/btn_settings")
        row = find_view(root, "@+id/brand_row")
        self.assertIsNotNone(button)
        self.assertIsNotNone(row)
        self.assertEqual(row.get(f"{ANDROID_NS}clipChildren"), "false")
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

    def test_the_control_is_nudged_right_and_up_by_the_owners_fractions(self):
        """Owner orders 2026-10-15, stacked: 20% right, 5% up, then a
        further 70% right and a further 15% up.

        Both orders are of the control's own 42dp box, so the fractions sum:
        42 x 0.90 = 37.8dp right and 42 x 0.20 = 8.4dp up, which is the one
        shift the layout reads from dimens.xml. The anchors of the earlier
        orders still hold, so a stacked translation keeps the same shape on
        any screen and at any font scale.
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
            f'<dimen name="settings_shift_x">{box * 0.90:.1f}dp</dimen>',
            dimens)
        self.assertIn(
            f'<dimen name="settings_shift_y">-{box * 0.20:.1f}dp</dimen>',
            dimens)

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
        # longer swaps a background anywhere.
        self.assertEqual(self.main.count("setSettingsOpen("), 3)
        self.assertNotIn("gear_bg", self.main)
        self.assertNotIn("setBackgroundResource", self.main)

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
        self.assertIn("String line = phaseLine(c, healthMarket);", self.watcher)
        self.assertIn("d.append('\\n').append(line);", self.watcher)


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

    def test_the_estimate_mark_is_drawn_by_a_face_that_shows_it(self):
        """Owner order 2026-10-15: the sign must read as an approximation.

        LEMON MILK maps U+2248, but measured in the shipped face its two bars
        sit 131 of the font's own 2048 em units apart, so at card size they
        merge into one squiggle and the owner read the quantity fields as if
        the "=" had turned into a tilde. The two signs are drawn by the
        system face now, the same override the arrows already needed; the
        brand face keeps every character around them. Only an estimated row
        gets the override: a measured row's "=" is LEMON MILK's own.
        """
        self.assertTrue(has_codepoint(FONT_DIR / "lemonmilk_light.otf", ABOUT))
        self.assertIn('private static final String ARROW_FACE = "sans-serif"',
                      self.main)
        self.assertIn("if (estimated) {\n"
                      "                    glyphs.add(new int[]{buyFrom - 1, "
                      "buyFrom});\n                }", self.main)
        self.assertIn("if (estimated) {\n"
                      "                    glyphs.add(new int[]{sellFrom - 1, "
                      "sellFrom});\n                }", self.main)
        # And the mark itself: "=" for the tape's counted numbers, U+2248 for
        # the day's-range estimate.
        self.assertIn('String mark = estimated ? "\\u2248" : "=";',
                      self.main)

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

    CADENCE = ("Quant will be scanning the market every 30 seconds "
               "when the market is open.")

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
        value = self.resource_value("scan_cadence")
        self.assertEqual(value, self.CADENCE)
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
        lines = [line for line in self.strings.splitlines()
                 if "scanning the market every 30 seconds" in line]
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
        self.assertIn("breathIfOnline(online)", self.main[render:render + 3000])
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
        # breath stops, and the 30 second cadence loop is removed from the
        # main queue so a backgrounded app holds no poll; onResume re-arms
        # both. The window is 400 characters because the two reasons are
        # stated where they are done.
        self.assertIn("stopStatusBreath();", self.main)
        pause = self.main.index("protected void onPause()")
        body = self.main[pause:pause + 400]
        self.assertIn("stopStatusBreath()", body)
        self.assertIn("cadence.removeCallbacks(tick)", body)

    def test_the_console_repaints_at_the_live_scan_cadence(self):
        """Owner order 2026-10-16: the app follows the 30 second scan.

        The console used to repaint once per open, so a 30 second scan fed a
        card that could be a whole session behind. The loop lives on the main
        queue, is started in onResume and removed in onPause (above), and its
        interval is Watcher.REFRESH_MS, which is the cloud's own interval.
        """
        self.assertIn("cadence.postDelayed(tick, Watcher.REFRESH_MS)", self.main)
        self.assertIn("cadence.postDelayed(this, Watcher.REFRESH_MS)", self.main)
        resume = self.main.index("protected void onResume()")
        self.assertIn("cadence.postDelayed(tick, Watcher.REFRESH_MS)",
                      self.main[resume:resume + 600])
        watcher = (ROOT / "android" / "app" / "src" / "main" / "java"
                   / "pk" / "quantofrehan" / "Watcher.java").read_text(
            encoding="utf-8")
        self.assertIn("static final long REFRESH_MS = 30 * 1000;", watcher)
        # The background arm is a watchdog, not a poll, and says so.
        self.assertIn("static final long WATCHDOG_MS = 5 * 60 * 1000;", watcher)
        self.assertIn("System.currentTimeMillis() + WATCHDOG_MS", watcher)
        # And the app's interval is the scanner's own, not a second opinion.
        config_text = (ROOT / "src" / "config.py").read_text(encoding="utf-8")
        self.assertIn('SCAN_INTERVAL_SECONDS = _number("SCAN_INTERVAL_SECONDS", 30)',
                      config_text)

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
class VersionTest(unittest.TestCase):
    def test_the_version_is_the_one_that_ships_these_changes(self):
        manifest = MANIFEST.read_text(encoding="utf-8")
        self.assertIn('android:versionName="1.7.1"', manifest)
        self.assertIn('android:versionCode="25"', manifest)


if __name__ == "__main__":
    unittest.main()
