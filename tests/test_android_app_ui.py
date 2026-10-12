"""Owner-ordered interface changes for the phone app, v1.6.4 (2026-10-12).

Owner order 2026-10-12 (third note): the settings icon on the top right is to
look better and more advanced, the bottom of the third tile carries the diamond
with a line either side just like the two places above it, "Quant of Rehan" is
drawn in the owner's Bonskin face, the rest of the interface uses LEMON MILK
Bold and Light, and the double space between a ticker and its buy volume is
gone.

The app has no Java test runner in this repository (it is built with aapt2 and
D8, see android/README.md), so these assertions read the sources that ship the
contract, exactly as tests/test_android_card_copy.py does for the card's copy.

The type assertions are stronger than "the layout mentions a font": they read
the codepoint tables out of the bundled OTF files and check that every face is
able to draw what it is asked to draw. That is not academic. Measured with the
fonts' own cmaps before they were wired in:

  * the free LEMON MILK maps every lowercase codepoint onto its uppercase
    glyph, which is why the long sentences keep the system face;
  * no bundled face carries U+25B2 or U+25BC (the card's arrows), which is why
    MainActivity draws those two characters with the system face by span;
  * no bundled face carries U+25C6 (the brand diamond), which is why
    QorDiamond deliberately sets no fontFamily.

A future font swap that breaks one of those three facts fails this file instead
of shipping a row of empty boxes to the phone.
"""

from __future__ import annotations

import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "android" / "app" / "src" / "main" / "res"
LAYOUT = RES / "layout" / "activity_main.xml"
RULE = RES / "layout" / "qor_rule.xml"
STYLES = RES / "values" / "styles.xml"
STRINGS = RES / "values" / "strings.xml"
GEAR = RES / "drawable" / "ic_gear.xml"
GEAR_BG = RES / "drawable" / "gear_bg.xml"
FONT_DIR = RES / "font"
LICENCES = ROOT / "android" / "LICENSES"
MAIN = (ROOT / "android" / "app" / "src" / "main" / "java" / "pk"
        / "quantofrehan" / "MainActivity.java")
MANIFEST = ROOT / "android" / "app" / "src" / "main" / "AndroidManifest.xml"

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
    """The gear is a drawn vector on a masked ripple, not a text glyph."""

    def setUp(self):
        self.layout = LAYOUT.read_text(encoding="utf-8")
        self.strings = STRINGS.read_text(encoding="utf-8")
        self.gear = GEAR.read_text(encoding="utf-8")
        self.plate = GEAR_BG.read_text(encoding="utf-8")

    def test_the_glyph_and_its_string_are_retired(self):
        self.assertNotIn("gear_glyph", self.layout)
        self.assertNotIn("gear_glyph", self.strings)
        self.assertNotIn("\u2699", self.strings)

    def test_the_button_is_a_vector_on_the_rippled_plate(self):
        button = element(self.layout, 'android:id="@+id/btn_settings"')
        self.assertIn("<ImageView", button)
        self.assertIn('android:src="@drawable/ic_gear"', button)
        self.assertIn('android:background="@drawable/gear_bg"', button)
        self.assertIn('android:contentDescription="@string/cd_settings"', button)

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

    def test_the_ripple_is_masked_to_the_plate_corners(self):
        self.assertIn("<ripple", self.plate)
        self.assertIn("@android:id/mask", self.plate)
        self.assertIn("@drawable/gear_plate", self.plate)

    def test_the_gear_is_eight_teeth_around_a_real_aperture(self):
        self.assertIn("<vector", self.gear)
        tooth = 'android:pathData="M10.8,4.9'
        self.assertEqual(self.gear.count(tooth), 8)
        # even-odd rings mean the ring and the collar have genuine holes rather
        # than overlays painted in the plate colour.
        self.assertEqual(self.gear.count('android:fillType="evenOdd"'), 2)

    def test_the_brand_law_of_two_states_is_still_one_place_per_state(self):
        main = MAIN.read_text(encoding="utf-8")
        self.assertIn("R.drawable.gear_bg_open", main)
        self.assertIn("R.drawable.gear_bg", main)


class BrandRuleTest(unittest.TestCase):
    """Line, diamond, line: defined once, used by all three tiles."""

    def setUp(self):
        self.layout = LAYOUT.read_text(encoding="utf-8")
        self.rule = RULE.read_text(encoding="utf-8")

    def test_the_rule_is_defined_once_and_included_three_times(self):
        self.assertIn("QorDiamond", self.rule)
        self.assertIn('android:text="@string/diamond"', self.rule)
        self.assertEqual(self.layout.count('layout="@layout/qor_rule"'), 3)

    def test_the_third_rule_is_the_last_thing_in_the_market_card(self):
        foot = self.layout.index('android:id="@+id/market_foot"')
        third = self.layout.index('layout="@layout/qor_rule"', foot)
        card_end = self.layout.index("</LinearLayout>", foot)
        self.assertLess(foot, third)
        self.assertLess(third, card_end)

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
                      element(self.layout, 'android:id="@+id/market_foot"'))
        self.assertIn('android:fontFamily="@font/lemonmilk_bold"',
                      element(self.layout, 'android:id="@+id/market_index"'))

    def test_the_sentences_keep_the_system_face(self):
        # By contract, not by accident: the free LEMON MILK draws lowercase
        # with its uppercase glyphs, so paragraphs drawn in it would shout.
        body = self.styles[self.styles.index('name="QorBody"'):]
        self.assertNotIn("@font/", body[:body.index("</style>")])
        self.assertIn('style="@style/QorBody"',
                      element(self.layout, 'android:id="@+id/status_detail"'))

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
                self.assertIn(name, (ROOT / "android" / "README.md")
                              .read_text(encoding="utf-8"))


class VersionTest(unittest.TestCase):
    def test_the_version_is_the_one_that_ships_these_changes(self):
        manifest = MANIFEST.read_text(encoding="utf-8")
        self.assertIn('android:versionName="1.6.4"', manifest)
        self.assertIn('android:versionCode="18"', manifest)


if __name__ == "__main__":
    unittest.main()
