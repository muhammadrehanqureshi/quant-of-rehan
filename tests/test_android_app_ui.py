"""Owner-ordered interface changes for the phone app, v1.6.6 (2026-10-13).

Owner order 2026-10-13: the settings control is the owner's own settings.png
silhouette, tinted from the app's palette, on no plate at all and centred on
the "Quant of Rehan" line, with a quarter turn as the settings panel opens and
closes; every line inside the system status and the latest signal tiles is set
in the owner's faces; the "Trading resumes" sentence is retired from the status
tile; and a volume leader row brackets its grouped volumes.

Owner order 2026-10-13 (second note): the settings control stands on the brand
line's baseline rather than centred on its row; a diamond rule divides the
system status tile from the latest signal tile; the rule that closed the market
card from inside it stands immediately after that tile's own boundary; and the
ONLINE indicator breathes, opacity and size, while the relay reports the market
OPEN.

Owner order 2026-10-13 (third note): the settings control stops overflowing its
row (a vertical margin for its box and a header row that holds no clip); the
cadence sentence leaves the market card and stands immediately after the final
diamond rule behind two line breaks; and the status light's pulse is rebuilt so
both states breathe, the ONLINE beacon in the palette green and the OFFLINE one
in the palette red, on a hard 25 frames per second.

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
  * the header's alignment is read from the layout tree, so "centred on the
    brand line" means the control and the brand text share one row, and the
    overflow margin is arithmetic on the declared box, the row's own metrics
    and Bonskin's hhea ascender rather than a promise about what a phone will
    draw;
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

    def test_the_control_stands_on_the_brand_baseline(self):
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
        # Owner order 2026-10-13 (second note): centred on the row is retired.
        # The control is anchored to the title, and MainActivity puts its
        # bottom edge on the title's own baseline, because that line's
        # position is a fact about Bonskin's metrics and the system font scale
        # rather than a margin that can be declared once.
        self.assertIsNone(button.get(f"{ANDROID_NS}layout_centerVertical"))
        self.assertEqual(button.get(f"{ANDROID_NS}layout_alignTop"),
                         "@id/brand_title")
        self.assertIn("alignSettingsToBrandBaseline", self.main)
        self.assertIn("brandTitle.getBaseline()", self.main)
        self.assertIn("brandTitle.getTop() + baseline", self.main)
        self.assertIn("line - btnSettings.getBottom()", self.main)
        self.assertIn("addOnLayoutChangeListener", self.main)
        # The tagline stays outside the row, so it cannot pull the control
        # down: the control is aligned to the brand text itself.
        self.assertIsNot(row, parent_of(root, tagline))

    def test_the_control_cannot_be_cropped_by_its_row(self):
        # Owner order 2026-10-13 (third note): the control's box is 42dp while
        # the brand line's baseline sits about 30dp down that line (Bonskin's
        # hhea ascender is 1006/1000 em at 30sp), so the translation that
        # stands it ON the baseline lifts about 9dp of the box above the row's
        # top edge, which a RelativeLayout clips by default. The margin is
        # that room, and the row also holds no clip, so the guarantee does not
        # rest on one number once the font scale moves the baseline.
        root = layout_root()
        button = find_view(root, "@+id/btn_settings")
        row = find_view(root, "@+id/brand_row")
        self.assertIsNotNone(button)
        self.assertIsNotNone(row)
        self.assertEqual(button.get(f"{ANDROID_NS}layout_marginTop"), "12dp")
        self.assertEqual(row.get(f"{ANDROID_NS}clipChildren"), "false")
        self.assertIs(row, parent_of(root, button))
        # The arithmetic the margin has to cover: box minus the baseline
        # offset, which is the overhang. 12dp covers the measured 9dp.
        box = int(button.get(f"{ANDROID_NS}layout_height")[:-2])
        margin = int(button.get(f"{ANDROID_NS}layout_marginTop")[:-2])
        padding = int(button.get(f"{ANDROID_NS}padding")[:-2])
        ascent = 30 * 1006 / 1000          # Bonskin hhea ascender at 30sp
        self.assertGreaterEqual(margin, round(box - ascent))
        # The ink sits `padding` inside the box, so the silhouette keeps clear
        # of the box edge as well.
        self.assertLessEqual(padding, 8)

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
        # Owner order 2026-10-13: every line inside these two tiles.
        pill = element(self.layout, 'android:id="@+id/status_pill"')
        self.assertIn('android:fontFamily="@font/lemonmilk_bold"', pill)
        # LEMON MILK Bold is already bold, so no synthesised weight on top.
        self.assertNotIn("textStyle", pill)
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

    def test_the_about_mark_needs_no_override_because_the_face_has_it(self):
        # The estimated split mark rides inside the brand face on purpose.
        self.assertTrue(has_codepoint(FONT_DIR / "lemonmilk_light.otf", ABOUT))
        self.assertNotIn("TypefaceSpan(ARROW_FACE), sellFrom", self.main)

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
    rule, separated from that rule by two line breaks. The layout is read as a
    tree, so "after the last rule" and "not inside the card" are positions
    rather than prose, and the breaks are counted in the string resource that
    holds the owner's sentence.
    """

    CADENCE = ("Quant will be scanning the market every 4 minutes "
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

    def test_the_separation_is_two_line_breaks_in_that_order(self):
        value = self.resource_value("scan_cadence")
        self.assertNotIn("\n", value, "the resource stays one source line")
        self.assertEqual(value, "\\n\\n" + self.CADENCE)
        # Exactly two, and no space smuggled in beside them: a third break or
        # an indent would be air the owner did not order.
        self.assertNotIn("\\n\\n\\n", value)
        self.assertNotIn(" ", value[:4])

    def test_the_sentence_still_appears_in_exactly_one_resource(self):
        lines = [line for line in self.strings.splitlines()
                 if "scanning the market every 4 minutes" in line]
        self.assertEqual(len(lines), 1, lines)


class StatusPulseTest(unittest.TestCase):
    """Owner order 2026-10-13 (third note): the pulse, rebuilt.

    Both states breathe now, so the word and the colour carry which state it
    is and the motion carries only that the console is awake. The rate is 25
    frames per second, hard: the animator carries the cycle's clock alone, its
    listener quantises the elapsed time to a 40ms grid, and it draws nothing
    when the step has not advanced, so the rate belongs to the app rather than
    to whatever refresh rate the phone happens to have.
    """

    def setUp(self):
        self.main = MAIN.read_text(encoding="utf-8")
        self.layout = LAYOUT.read_text(encoding="utf-8")

    def test_the_rate_is_twenty_five_frames_per_second(self):
        self.assertIn("private static final long FRAME_MS = 40L;", self.main)
        self.assertIn("1000 / 25", self.main)
        self.assertIn("a.getAnimatedFraction() * BREATH_MS) / FRAME_MS",
                      self.main)
        self.assertIn("if (frame == breathFrame)", self.main)
        # The platform's frame delay hint is documented as ignorable when the
        # animation system rides vsync, which is exactly this case, so the
        # rate is enforced in the animator's own clock instead.
        self.assertNotIn("setFrameDelay", self.main)

    def test_it_is_one_cycle_that_repeats_without_a_seam(self):
        self.assertIn("ValueAnimator.ofFloat(0f, 1f)", self.main)
        self.assertIn("setRepeatCount(ValueAnimator.INFINITE)", self.main)
        self.assertIn("new LinearInterpolator()", self.main)
        # A raised cosine: 0 at the start of a cycle, 1 at its half, 0 again
        # at its end, with the slope returning too, so the repeat cannot show
        # a seam.
        self.assertIn("0.5 - 0.5 * Math.cos(2.0 * Math.PI * phase)", self.main)
        self.assertIn("BREATH_MS", self.main)

    def test_it_pulses_the_dots_own_opacity_and_size(self):
        self.assertIn("getCompoundDrawablesRelative()[0]", self.main)
        self.assertIn("BREATH_MIN_ALPHA", self.main)
        self.assertIn("BREATH_MIN_SCALE", self.main)
        # The scale is applied about the dot's live centre, so it cannot
        # drift, and the pill's word never moves because the dot's layout box
        # is untouched.
        self.assertIn("dot.getBounds().centerX()", self.main)
        self.assertIn("drawBreathFrame", self.main)

    def test_both_states_breathe_and_the_colour_carries_the_state(self):
        # The old law (only a live session pulses) is retired: the owner chose
        # both states on 2026-10-13, so the market phase is no longer read
        # here. The one dot left still is CHECKING, where the app has no state
        # to show yet.
        self.assertNotIn('"OPEN".equals(market.phase)', self.main)
        self.assertNotIn("setStatusBreath", self.main)
        render = self.main.index("private void render(")
        self.assertIn("startStatusBreath();", self.main[render:render + 2400])
        self.assertIn('android:drawableStart="@drawable/ic_status_checking"',
                      self.layout)

    def test_a_hidden_console_leaves_it_still(self):
        self.assertIn("stopStatusBreath();", self.main)
        pause = self.main.index("protected void onPause()")
        self.assertIn("stopStatusBreath()", self.main[pause:pause + 240])

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


class VersionTest(unittest.TestCase):
    def test_the_version_is_the_one_that_ships_these_changes(self):
        manifest = MANIFEST.read_text(encoding="utf-8")
        self.assertIn('android:versionName="1.6.7"', manifest)
        self.assertIn('android:versionCode="21"', manifest)


if __name__ == "__main__":
    unittest.main()
