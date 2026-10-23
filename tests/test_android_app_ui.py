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

import re
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
WORKER = ROOT / "cloud" / "worker.js"
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


def font_tables(data: bytes) -> dict:
    """{tag: (offset, length)} from the face's own table directory."""
    tables = {}
    for index in range(struct.unpack(">H", data[4:6])[0]):
        off = 12 + index * 16
        tables[data[off:off + 4]] = struct.unpack(">II", data[off + 8:off + 16])
    return tables


def _format4_glyph(data: bytes, sub: int, codepoint: int) -> int:
    """The glyph id format 4 maps this codepoint onto, or 0."""
    if codepoint > 0xFFFF:
        return 0
    seg_x2 = struct.unpack(">H", data[sub + 6:sub + 8])[0]
    ends_at = sub + 14
    starts_at = ends_at + seg_x2 + 2
    deltas_at = starts_at + seg_x2
    ranges_at = deltas_at + seg_x2
    for seg in range(seg_x2 // 2):
        start = struct.unpack(">H", data[starts_at + 2 * seg:starts_at + 2 * seg + 2])[0]
        end = struct.unpack(">H", data[ends_at + 2 * seg:ends_at + 2 * seg + 2])[0]
        if not start <= codepoint <= end:
            continue
        delta = struct.unpack(">h", data[deltas_at + 2 * seg:deltas_at + 2 * seg + 2])[0]
        offset = struct.unpack(">H", data[ranges_at + 2 * seg:ranges_at + 2 * seg + 2])[0]
        if offset == 0:
            return (codepoint + delta) % 0x10000
        at = ranges_at + 2 * seg + offset + 2 * (codepoint - start)
        if at + 2 > len(data):
            return 0
        glyph = struct.unpack(">H", data[at:at + 2])[0]
        return 0 if glyph == 0 else (glyph + delta) % 0x10000
    return 0


def cmap_glyph(data: bytes, tables: dict, codepoint: int) -> int:
    """The glyph id for a codepoint, through format 4 or format 12."""
    cmap_off = tables[b"cmap"][0]
    for index in range(struct.unpack(">H", data[cmap_off + 2:cmap_off + 4])[0]):
        record = cmap_off + 4 + index * 8
        sub = cmap_off + struct.unpack(">I", data[record + 4:record + 8])[0]
        fmt = struct.unpack(">H", data[sub:sub + 2])[0]
        if fmt == 4:
            glyph = _format4_glyph(data, sub, codepoint)
            if glyph:
                return glyph
        elif fmt == 12:
            groups = struct.unpack(">I", data[sub + 12:sub + 16])[0]
            for g in range(groups):
                at = sub + 16 + g * 12
                lo, hi, first = struct.unpack(">III", data[at:at + 12])
                if lo <= codepoint <= hi:
                    return first + (codepoint - lo)
    return 0


def text_width_dp(path: Path, text: str, sp: float, tracking: float = 0.0) -> float:
    """How wide `text` advances at `sp`, read from the face's own metrics.

    The card's widest row is the reason this exists: 13sp either fits the
    tile or it does not, and that is a fact about the bundled face's advance
    widths, not a matter of reading the layout. Android adds the tracking
    after every character, hence the last term.
    """
    data = path.read_bytes()
    tables = font_tables(data)
    head = tables[b"head"][0]
    units_per_em = struct.unpack(">H", data[head + 18:head + 20])[0]
    hhea = tables[b"hhea"][0]
    metrics = struct.unpack(">H", data[hhea + 34:hhea + 36])[0]
    hmtx = tables[b"hmtx"][0]

    def advance(codepoint: int) -> int:
        glyph = cmap_glyph(data, tables, codepoint)
        index = min(glyph, metrics - 1)
        return struct.unpack(">H", data[hmtx + index * 4:hmtx + index * 4 + 2])[0]

    units = sum(advance(ord(ch)) for ch in text)
    return units / units_per_em * sp + tracking * sp * len(text)


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
    """The menu tile at the very bottom (owner order 2026-10-23).

    Home, search and settings moved here from the brand row, bracketed by
    the same diamond rule the console uses at every change of subject. Each
    icon is the owner's own png (home.png and search.png were copied from
    his Desktop, settings.png was already bundled), tinted into the palette,
    and the page he is currently on is circled in a gold ring: the ring is
    the selection, and a masked ripple is only the press. The header is the
    name alone.
    """

    def setUp(self):
        self.layout = LAYOUT.read_text(encoding="utf-8")
        self.strings = STRINGS.read_text(encoding="utf-8")
        self.main = MAIN.read_text(encoding="utf-8")
        self.dimens = DIMENS.read_text(encoding="utf-8")

    def test_the_menu_tile_is_bracketed_by_rules_at_the_very_bottom(self):
        root = layout_root()
        nav = find_view(root, "@+id/nav_tile")
        self.assertIsNotNone(nav)
        self.assertEqual(nav.get("style"), "@style/QorPanel")
        bracket = [node for node in root.iter() if node.tag == "include"
                   and node.get(f"{ANDROID_NS}id") in
                   ("@+id/rule_before_nav", "@+id/rule_after_nav")]
        self.assertEqual([node.get(f"{ANDROID_NS}id") for node in bracket],
                         ["@+id/rule_before_nav", "@+id/rule_after_nav"])
        # Above the tile and below it: the same diamond rule as every other
        # change of subject, declared once in qor_rule.xml.
        for rule in bracket:
            self.assertEqual(rule.get("layout"), "@layout/qor_rule")
        # Nothing comes after the lower rule: it closes the console.
        self.assertLess(self.layout.index("@+id/rule_before_nav"),
                        self.layout.index("@+id/nav_tile"))
        self.assertLess(self.layout.index("@+id/nav_tile"),
                        self.layout.index("@+id/rule_after_nav"))
        following = siblings_after(root, bracket[1])
        self.assertFalse(following, "the lower rule closes the console")

    def test_the_three_icons_are_the_owners_own_pngs(self):
        for view_id, name in (("btn_nav_home", "home"),
                              ("btn_nav_search", "search"),
                              ("btn_nav_settings", "settings")):
            with self.subTest(icon=name):
                button = element(self.layout, f'android:id="@+id/{view_id}"')
                self.assertIn("<ImageView", button)
                self.assertIn(f'android:src="@drawable/{name}"', button)
                self.assertTrue(
                    (RES / "drawable-nodpi" / f"{name}.png").is_file())
                # One box, the ink padded inside it: the tint does the
                # colour, the png does the shape.
                self.assertIn('android:layout_width="42dp"', button)
                self.assertEqual(
                    re.search(r'android:contentDescription="\S+"',
                              button).group(0),
                    f'android:contentDescription="@string/cd_{name}"')

    def test_the_open_page_is_circled_and_the_rest_are_rippled(self):
        home = element(self.layout, 'android:id="@+id/btn_nav_home"')
        search = element(self.layout, 'android:id="@+id/btn_nav_search"')
        settings = element(self.layout, 'android:id="@+id/btn_nav_settings"')
        self.assertIn('android:background="@drawable/nav_circle"', home)
        self.assertIn('android:tint="@color/gold_bright"', home)
        for other in (search, settings):
            with self.subTest(other=other[:other.index("/>")]):
                self.assertIn(
                    'android:background="@drawable/settings_ripple"',
                    other)
                self.assertIn('android:tint="@color/gold"', other)
        # The state machine is the one helper MainActivity calls with the
        # page's truth, never a view's own state.
        self.assertIn("? R.drawable.nav_circle : R.drawable.settings_ripple",
                      self.main)
        self.assertIn("selected ? R.color.gold_bright : R.color.gold",
                      self.main)
        self.assertIn("setNavPage(navHome, !searchOpen && !settingsOpen);",
                      self.main)
        self.assertIn("setNavPage(navSearch, searchOpen);", self.main)
        self.assertIn("setNavPage(navSettings, settingsOpen);", self.main)

    def test_the_header_is_the_name_alone(self):
        # The gear and the glass left the brand row for the menu tile; no
        # control shares the name's row any more.
        self.assertNotIn('android:id="@+id/btn_settings"', self.layout)
        self.assertNotIn("applySettingsShift", self.main)
        self.assertNotIn("settings_shift_x", self.dimens)
        self.assertNotIn("search_shift_x", self.dimens)
        root = layout_root()
        title = find_view(root, "@+id/brand_title")
        row = parent_of(root, title)
        self.assertEqual(row.get(f"{ANDROID_NS}id"), "@+id/brand_row")
        children = [node.tag for node in row if node.tag != "Comment"]
        self.assertEqual(children, ["TextView"])

    def test_the_quarter_turn_is_retired_with_the_gear(self):
        # The icon no longer rotates: nav state is the background and the
        # tint, so no open/close torque needs an interpolator.
        self.assertNotIn(".rotation(", self.main)
        self.assertNotIn("GEAR_TURN_MS", self.main)
        self.assertNotIn(
            "settings_shift",
            (RES / "values" / "dimens.xml").read_text(encoding="utf-8"))

    def test_the_settings_tile_carries_no_token_and_no_technical_clutter(self):
        """Owner order 2026-10-19: the phone holds no credential.

        The token field, its save button and the paste instructions are gone
        from the layout, and no Java reads an admin token any more. That is
        only safe because the relay serves the latest signal as a public read;
        tests/test_relay_worker_contracts.py pins that split (public GET,
        admin-gated POST).
        """
        for gone in ("token_box", "btn_save", "field_bg"):
            with self.subTest(view=gone):
                self.assertNotIn(f'android:id="@+id/{gone}"', self.layout)
        for source in MAIN, WATCHER, STATUS_SERVICE:
            self.assertNotIn("admin_token",
                             source.read_text(encoding="utf-8"))

    def test_the_content_description_is_a_button_name_not_the_help_text(self):
        for name in ("cd_home", "cd_search", "cd_settings"):
            with self.subTest(resource=name):
                self.assertIn(f'name="{name}"', self.strings)
        settings_hint = self.strings.index('name="settings_hint"')
        cd = self.strings.index('name="cd_settings"')
        hint_line = self.strings[settings_hint:self.strings.index("</string>",
                                                                  settings_hint)]
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
        # Eight rules on the console (owner order 2026-10-23): the ones the
        # tiles own, the two the menus carry, and the pair that brackets the
        # menu tile at the very bottom.
        self.assertEqual(self.layout.count('layout="@layout/qor_rule"'), 8)

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
        # The brand carries no inline size: the layout points at the one
        # shelf, QorBrandTitle, and the size is a style fact. The title is
        # the headings' own 17.71561sp times 1.15, the owner's ordered 15%.
        brand = element(self.layout, 'android:text="@string/app_name"')
        self.assertIn('style="@style/QorBrandTitle"', brand)
        self.assertNotIn("textSize", brand)
        style = self.styles[self.styles.index('name="QorBrandTitle"'):]
        style = style[:style.index("</style>")]
        self.assertIn('<item name="android:textSize">20.37295sp</item>', style)

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

    def test_the_settings_paragraph_no_longer_paints_on_the_tile(self):
        # Owner order 2026-10-22 (second pass on the tile): the SETTINGS
        # heading is back and the help paragraph below it is gone from the
        # screen. The hint string keeps its declaration in strings.xml, but
        # no layout paints it.
        self.assertNotIn('android:text="@string/settings_hint"', self.layout)
        self.assertIn('name="settings_hint"',
                      STRINGS.read_text(encoding="utf-8"))
        heading = element(self.layout, 'android:id="@+id/settings_heading"')
        self.assertIn('android:text="@string/label_settings"', heading)

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
        # v1.8.5 (owner 14:51): the group's separators are NON-BREAKING
        # spaces, so a wide row can never wrap mid group.
        self.assertIn('sb.append("\\u00A0(B=");', self.main)
        self.assertIn('"\\u00A0(T=%,d)"', self.main)
        # v1.8.7 (owner 15:35): the three quantities read as a sentence, a
        # comma after B and an ampersand before T, both non-breaking.
        self.assertIn('sb.append(",\\u00A0S=");', self.main)
        self.assertIn('"\\u00A0&\\u00A0T=%,d)"', self.main)
        # v1.8.6 (owner 15:15): and that row keeps the body's 13sp. It wins
        # its width from the tile (6dp of each 16dp panel padding, through the
        # negative side margins) and from its own tracking, never from a
        # smaller size, which was the owner's complaint about v1.8.5.
        layout = LAYOUT.read_text(encoding="utf-8")
        leaders = layout[layout.index("@+id/market_leaders"):]
        leaders = leaders[:leaders.index("/>\n")]
        self.assertNotIn("textSize", leaders)
        self.assertIn('android:letterSpacing="-0.035"', leaders)
        self.assertIn('android:layout_marginLeft="-10dp"', leaders)
        self.assertIn('android:layout_marginRight="-10dp"', leaders)
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

    def test_the_sentence_stands_after_the_market_rule(self):
        rules = [node for node in self.root.iter() if node.tag == "include"
                 and node.get("layout") == "@layout/qor_rule"]
        self.assertEqual(len(rules), 8)
        # The market card's rule: the two rules the menus own travel with
        # their panels, and the nav pair closes the console.
        market_rule = next(
            rule for rule in rules
            if rule.get(f"{ANDROID_NS}id") == "@+id/rule_after_market")
        following = siblings_after(self.root, market_rule)
        self.assertTrue(following, "the sentence follows the rule")
        view = following[0]
        self.assertEqual(view.tag, "TextView")
        self.assertEqual(view.get(f"{ANDROID_NS}id"), "@+id/scan_cadence")
        self.assertEqual(view.get(f"{ANDROID_NS}text"), "@string/scan_cadence")
        self.assertEqual(view.get("style"), "@style/QorCaption")
        # Owner order 2026-10-23: the menu tile comes after the sentence,
        # at the very bottom, with its own diamond rules around it. The
        # sentence is the console's last WORD, not its last view.
        self.assertIsNotNone(find_view(self.root, "@+id/nav_tile"))
        self.assertLess(self.layout.index("@+id/scan_cadence"),
                        self.layout.index("@+id/rule_before_nav"))
        # And after the sentence, the nav bracket and nothing else: the
        # rule before the menu tile, the tile itself, the closing rule.
        self.assertEqual(
            [node.get(f"{ANDROID_NS}id") for node in following[1:]],
            ["@+id/rule_before_nav", "@+id/nav_tile", "@+id/rule_after_nav"])

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
        # The pulse is strictly a view-property animation. The second pass
        # of the 2026-10-22 HUD (the owner's reference look, v1.8.9) moved
        # the beam's ValueAnimator out for good: the breath itself still
        # holds no animator at all, checked on its own two methods.
        breath = self.main[self.main.index("private void startStatusBreath("):]
        breath = breath[:breath.index("private void breathIfOnline(")]
        stop_block = self.main[self.main.index("private void stopStatusBreath("):]
        stop_block = stop_block[:stop_block.index("The HUD's cycle")]
        self.assertNotIn("ValueAnimator", breath)
        self.assertNotIn("ValueAnimator", stop_block)
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
        # v1.8.8: the HUD's startHU joins the same block before the poll is
        # re-armed, so the window reads past its own order comment.
        self.assertIn("scheduleNext();", self.main[resume:resume + 1400])
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
        # The phone never derives the SESSION from its own clock: no wall
        # time decides a cadence (SO-8). The greeting is the one exception,
        # owner order 2026-10-23, and even it reads Karachi's zone and
        # never the handset's.
        greeting_start = self.main.index("private void refreshGreeting()")
        themes_start = self.main.index("THEMES (owner order 2026-10-23)")
        for slice_ in (self.main[:greeting_start],
                       self.main[themes_start:]):
            self.assertNotIn("Calendar", slice_)
            self.assertNotIn("LocalTime", slice_)
            self.assertNotIn("System.currentTimeMillis()", slice_)
        # The greeting reads Karachi's zone, and it is the only reader.
        greeting = self.main[greeting_start:themes_start]
        self.assertIn('TimeZone.getTimeZone("Asia/Karachi")', greeting)
        self.assertIn("HOUR_OF_DAY", greeting)
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
        self.assertIn("if (!liveInFlight) {", self.main[poll:poll + 1200])
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
        # Owner order 2026-10-22 (second report on the lag): the card read is
        # RACED against the health read, so a tick costs one round trip of
        # wait, not two stacked ones.
        self.assertIn("marketJob = CARD_POOL.submit(() -> fetchMarket(c, base));",
                      live)
        self.assertIn("Market market = marketJob.get(20, TimeUnit.SECONDS);", live)
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
        live_body = watcher[live:live + 1400]
        self.assertIn("marketJob = CARD_POOL.submit(() -> fetchMarket(c, base));",
                      live_body)
        self.assertIn("head.signals, market);", live_body)
        poll = self.main.index("private void pollOnce()")
        self.assertIn("refreshLive();", self.main[poll:poll + 1200])
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
        listener = self.main.index("navSettings.setOnClickListener")
        self.assertIn("setSettingsOpen(true)",
                      self.main[listener:listener + 120])
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
        # Exactly two views name it: the badge and the detail line. The
        # HUD's diagnostics line, which briefly rode the same air under
        # the Karachi clock in v1.8.8's first pass, is retired in v1.8.9,
        # so a hand-written number still cannot replace either of these
        # two, and no THIRD gap can quietly join the tile.
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
        # v1.9.12 is the 2026-10-23 day: the menu tile at the very bottom with
        # the owner's own home.png and search.png and a circle on the page he
        # is on, a THEMES dropdown on the settings page, CUSTOM SCRIPS OF
        # VOL. on the search page, the greeting above QUANT STATUS, the app
        # version on the settings page, and /prices rows that carry the
        # relay's own B/S split. v1.9.10's tile heading, ten solar lines and
        # one body size stand.
        manifest = MANIFEST.read_text(encoding="utf-8")
        self.assertIn('android:versionName="1.9.12"', manifest)
        self.assertIn('android:versionCode="53"', manifest)
        # The changelog entry ties these user-visible changes to the build.
        readme = (ROOT / "android" / "README.md").read_text(encoding="utf-8")
        self.assertIn("v1.7.9, owner order 2026-10-20", readme)
        self.assertIn("Version 1.8.0, versionCode 34", readme)
        self.assertIn("Version 1.8.1, versionCode 35", readme)
        self.assertIn("Version 1.8.2, versionCode 36", readme)
        self.assertIn("Version 1.8.3, versionCode 37", readme)
        self.assertIn("Version 1.8.4, versionCode 38", readme)
        self.assertIn("Version 1.8.5, versionCode 39", readme)
        self.assertIn("Version 1.8.6, versionCode 40", readme)
        self.assertIn("Version 1.8.7, versionCode 41", readme)
        self.assertIn("Version 1.8.8, versionCode 42", readme)
        self.assertIn("Version 1.8.9, versionCode 43", readme)
        self.assertIn("Version 1.9.0, versionCode 44", readme)
        self.assertIn("Version 1.9.4, versionCode 45", readme)
        self.assertIn("Version 1.9.5, versionCode 46", readme)
        self.assertIn("Version 1.9.6, versionCode 47", readme)
        self.assertIn("Version 1.9.7, versionCode 48", readme)
        self.assertIn("Version 1.9.8, versionCode 49", readme)
        self.assertIn("Version 1.9.9, versionCode 50", readme)
        self.assertIn("Version 1.9.10, versionCode 51", readme)
        self.assertIn("Version 1.9.11, versionCode 52", readme)
        self.assertIn("Version 1.9.12, versionCode 53", readme)
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
        # Both the empty answer and another session's card land on that string,
        # and since 2026-10-21 the ink check compares against the same
        # resource rather than a literal, so the sentence still has ONE
        # spelling in the whole app (owner order 15:35).
        self.assertEqual(main.count("getString(R.string.signal_no_call)"), 3)


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
        self.assertIn("styleSearchRow(entry.getValue(), entry.getKey(), q);", main)

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

    def test_the_search_icon_lives_on_the_nav_tile(self):
        # Owner order 2026-10-23: the glass moved to the menu tile at the
        # very bottom; the old header glass, its 42dp shift box and its
        # shift resources are retired with the placement.
        layout = LAYOUT.read_text(encoding="utf-8")
        icon = layout[layout.index("@+id/btn_nav_search"):]
        icon = icon[:icon.index("/>")]
        self.assertIn('android:src="@drawable/search"', icon)
        self.assertFalse((RES / "drawable" / "ic_search.xml").exists())
        self.assertNotIn(
            "search_shift",
            (ROOT / "android" / "app" / "src" / "main" / "res" / "values"
             / "dimens.xml").read_text(encoding="utf-8"))
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


class UniversalSizeTest(unittest.TestCase):
    """Owner order 2026-10-21 (15:15): one size for every line.

    The owner read v1.8.5's KSE100 rows as smaller than the rest of the app,
    because they were: the tile carried its own 11.5sp to force one line.
    From this version the body has ONE size, the 13sp "NO SIGNAL AVAILABLE
    RIGHT NOW" is set in, the search box and its rows match it, and only the
    bold headings keep a size of their own. The leader row wins its width
    from the tile instead (see LeaderLineTest).
    """

    def setUp(self):
        self.layout = LAYOUT.read_text(encoding="utf-8")
        self.styles = STYLES.read_text(encoding="utf-8")
        self.main = MAIN.read_text(encoding="utf-8")

    def test_the_layout_declares_the_body_size_inline(self):
        # The owner's 2026-10-23 type law in the resources: every line that
        # is not a heading is THE body's 13sp, the footer's own number, and
        # the layout carries that one size inline. The headings declare
        # their sizes through their styles, so the law is one decision.
        sizes = set(re.findall(r'android:textSize="([0-9.]+sp)"', self.layout))
        self.assertEqual(sizes, {"13sp"})
        label = self.styles[self.styles.index('name="QorLabel"'):]
        self.assertIn('android:textSize">17.71561sp',
                      label[:label.index("</style>")])
        brand = self.styles[self.styles.index('name="QorBrandTitle"'):]
        # The title is its own heading, 15% bigger than the other headings.
        self.assertIn('android:textSize">20.37295sp',
                      brand[:brand.index("</style>")])
        # Body, buttons and captions are the one size round.
        for style in ("QorBody", "QorButton", "QorCaption"):
            block = self.styles[self.styles.index(f'name="{style}"'):]
            self.assertIn('android:textSize">13sp',
                          block[:block.index("</style>")])
        # QorValue declares no size of its own: it inherits the body's 13sp.
        value = self.styles[self.styles.index('name="QorValue"'):]
        self.assertNotIn("textSize", value[:value.index("</style>")])
        self.assertNotIn("11.5sp", self.layout)
        self.assertNotIn("39.675sp", self.layout)
    def test_the_search_box_is_body_size(self):
        box = self.layout[self.layout.index("@+id/search_input"):]
        self.assertIn('android:textSize="13sp"', box[:box.index("/>")])

    def test_the_search_rows_are_body_size(self):
        self.assertIn("row.setTextSize(13f);", self.main)
        self.assertNotIn("row.setTextSize(15f);", self.main)

    def test_the_tagline_and_the_footer_are_body_size(self):
        tagline = self.layout[self.layout.index("@+id/brand_tagline"):]
        self.assertIn('android:textSize="13sp"', tagline[:tagline.index("/>")])
        caption = self.styles[self.styles.index('name="QorCaption"'):]
        self.assertIn('android:textSize">13sp', caption[:240])

    def test_the_body_style_is_the_one_size(self):
        body = self.styles[self.styles.index('name="QorBody"'):]
        self.assertIn('android:textSize">13sp', body[:body.index("</style>")])

    def test_the_headings_keep_a_size_of_their_own_and_are_bold(self):
        # Headings are 10% bigger than current, buttons are body size.
        for style, size in (("QorLabel", "17.71561sp"), ("QorButton", "13sp")):
            block = self.styles[self.styles.index(f'name="{style}"'):]
            block = block[:block.index("</style>")]
            self.assertIn("lemonmilk_bold", block)
            self.assertIn(f'android:textSize">{size}', block)


class TileBracketingTest(unittest.TestCase):
    """Owner order 2026-10-21 (15:35): a menu tile has a rule on each side.

    He opened the search and saw the diamond below that tile but not above
    it, and opened the settings and saw its diamond above but not below. Each
    menu now owns the rule on the side the console's brand rule does not
    cover: `rule_before_search` above the search panel, `rule_after_settings`
    below the settings panel. Both start GONE and travel with their panel, so
    a closed menu leaves no rule behind.
    """

    def setUp(self):
        self.root = layout_root()
        self.layout = LAYOUT.read_text(encoding="utf-8")
        self.main = MAIN.read_text(encoding="utf-8")

    def test_the_search_tile_has_a_rule_above_it(self):
        rule = find_view(self.root, "@+id/rule_before_search")
        self.assertIsNotNone(rule)
        self.assertEqual(rule.get(f"{ANDROID_NS}visibility"), "gone")
        self.assertLess(self.layout.index("@+id/rule_before_search"),
                        self.layout.index("@+id/search_panel"))

    def test_the_search_tile_keeps_the_brand_rule_below_it(self):
        self.assertLess(self.layout.index("@+id/search_panel"),
                        self.layout.index("<!-- brand rule:"))

    def test_the_settings_tile_has_a_rule_below_it(self):
        rule = find_view(self.root, "@+id/rule_after_settings")
        self.assertIsNotNone(rule)
        self.assertEqual(rule.get(f"{ANDROID_NS}visibility"), "gone")
        self.assertLess(self.layout.index("@+id/settings_panel"),
                        self.layout.index("@+id/rule_after_settings"))

    def test_each_rule_travels_with_its_menu(self):
        self.assertIn("ruleBeforeSearch.setVisibility(open ? View.VISIBLE : View.GONE);",
                      self.main)
        self.assertIn("ruleAfterSettings.setVisibility(open ? View.VISIBLE : View.GONE);",
                      self.main)


class SearchBoxGapTest(unittest.TestCase):
    """Owner order 2026-10-21 (15:35): the box's air is the same on both sides."""

    def setUp(self):
        self.root = layout_root()
        self.box = find_view(self.root, "@+id/search_input")

    def test_the_box_centres_its_one_line(self):
        self.assertEqual(self.box.get(f"{ANDROID_NS}gravity"), "center_vertical")

    def test_the_font_padding_is_out_of_the_box_height(self):
        self.assertEqual(self.box.get(f"{ANDROID_NS}includeFontPadding"), "false")

    def test_the_box_padding_stays_symmetric(self):
        self.assertEqual(self.box.get(f"{ANDROID_NS}padding"), "10dp")

    def test_the_hidden_rows_start_hidden_in_the_layout(self):
        # An empty panel must not draw a 6dp or 8dp margin before its first
        # render, which is the extra air he could see under the box.
        self.assertEqual(
            find_view(self.root, "@+id/search_results").get(
                f"{ANDROID_NS}visibility"), "gone")
        self.assertEqual(
            find_view(self.root, "@+id/search_status").get(
                f"{ANDROID_NS}visibility"), "gone")


class SignalPlaceholderInkTest(unittest.TestCase):
    """Owner order 2026-10-21 (15:35): the placeholder is body ink."""

    def setUp(self):
        self.main = MAIN.read_text(encoding="utf-8")

    def test_the_ink_follows_the_sentence_on_screen(self):
        self.assertIn("private void paintSignalInk(String display) {", self.main)
        block = self.main[self.main.index("private void paintSignalInk"):]
        block = block[:block.index("private String latestSignalDisplay")]
        self.assertIn("R.color.text_soft : R.color.text_bright", block)
        self.assertIn("signalList.setAlpha(1.0f);", block)

    def test_no_dimmed_placeholder_survives(self):
        self.assertNotIn("signalList.setAlpha(0.65f)", self.main)

    def test_soft_is_the_body_ink(self):
        styles = STYLES.read_text(encoding="utf-8")
        body = styles[styles.index('name="QorBody"'):]
        self.assertIn("@color/text_soft", body[:body.index("</style>")])


class LeaderRowFitsAtBodySizeTest(unittest.TestCase):
    """The measurement, not the intent: 13sp really fits the KSE100 tile.

    The panel in the owner's 2026-10-21 15:15 screenshot is 666 of the image's
    738 px wide, and the same image puts the 20dp content padding at 36.5 px,
    which is 1.81 px per dp, so his tile is 370dp wide. The leaders row spends
    6dp of each 16dp panel padding (its -10dp side margins), which leaves
    358dp of line for 13sp text.
    """

    TILE_DP = 370.0
    SIDE_INSET_DP = 6.0
    PANEL_PADDING_DP = 16.0
    TRACKING = -0.035

    def width(self, row: str, tracking: float = TRACKING) -> float:
        return text_width_dp(FONT_DIR / "lemonmilk_light.otf", row, 13.0,
                             tracking)

    def available(self) -> float:
        return self.TILE_DP - 2 * self.SIDE_INSET_DP

    def test_the_widest_row_the_card_has_shown_fits_at_13sp(self):
        row = "2. CNERGY (B=12,626,814, S=25,253,629 & T=37,880,443)"
        self.assertLess(self.width(row), self.available())

    def test_nine_digit_counts_fit_too(self):
        row = "2. CNERGY (B=12,626,814, S=25,253,629 & T=101,880,443)"
        self.assertLess(self.width(row), self.available())

    def test_the_tracking_is_what_makes_13sp_fit(self):
        # Without it the same row overshoots the line, which is exactly why
        # v1.8.5 shrank the type instead of using the tile's width.
        row = "2. CNERGY (B=12,626,814, S=25,253,629 & T=37,880,443)"
        self.assertGreater(self.width(row, 0.0), self.available())

    def test_the_shipped_tracking_and_inset_are_the_measured_ones(self):
        layout = LAYOUT.read_text(encoding="utf-8")
        leaders = layout[layout.index("@+id/market_leaders"):]
        leaders = leaders[:leaders.index("/>\n")]
        self.assertIn(f'android:letterSpacing="{self.TRACKING}"', leaders)
        margin = self.PANEL_PADDING_DP - self.SIDE_INSET_DP
        self.assertIn(f'android:layout_marginLeft="-{margin:g}dp"', leaders)
        self.assertIn(f'android:layout_marginRight="-{margin:g}dp"', leaders)


class HeadingGrowthTest(unittest.TestCase):
    """Owner order 2026-10-22: every heading is 10% bigger, and the two
    tiles that never had a heading now carry his exact words.

    The 10% lands on the one style every tile heading shares (QorLabel), so
    QUANT STATUS, LATEST SIGNAL, SETTINGS and the two new headings grow by
    one decision rather than five copies that could drift apart. The
    body's 13sp is NOT a heading and stays at its size, and the headings
    are still carried by the style (no raw textSize appears next to them).
    """

    def test_the_label_style_grew_by_exactly_ten_percent(self):
        # Headings are 10% bigger than current size.
        styles = STYLES.read_text(encoding="utf-8")
        block = styles[styles.index('name="QorLabel"'):]
        block = block[:block.index("</style>")]
        self.assertIn('android:textSize">17.71561sp', block)

    def test_the_body_kept_its_size(self):
        styles = STYLES.read_text(encoding="utf-8")
        body = styles[styles.index('name="QorBody"'):]
        self.assertIn('android:textSize">13sp', body[:body.index("</style>")])

    def test_the_search_tile_carries_the_ordered_heading(self):
        layout = LAYOUT.read_text(encoding="utf-8")
        strings = STRINGS.read_text(encoding="utf-8")
        head = layout.index("@+id/search_heading")
        self.assertLess(head, layout.index("@+id/search_input"))
        block = layout[head:layout.index("/>", head)]
        self.assertIn('android:text="@string/label_search"', block)
        self.assertIn('style="@style/QorLabel"', block)
        self.assertIn('name="label_search">SEARCH<', strings)

    def test_the_market_tile_carries_the_ordered_heading(self):
        layout = LAYOUT.read_text(encoding="utf-8")
        strings = STRINGS.read_text(encoding="utf-8")
        head = layout.index("@+id/market_heading")
        self.assertLess(head, layout.index("@+id/market_index"))
        block = layout[head:layout.index("/>", head)]
        self.assertIn('android:text="@string/label_market"', block)
        self.assertIn('style="@style/QorLabel"', block)
        self.assertIn(
            'name="label_market">THE INDEX &amp; THE TOP 3 SCRIPS OF VOL.<',
            strings)

    def test_the_existing_headings_keep_their_words(self):
        strings = STRINGS.read_text(encoding="utf-8")
        self.assertIn('name="label_system">QUANT STATUS<', strings)
        self.assertIn('name="label_signal">LATEST SIGNAL<', strings)


class MenuOrdersTest(unittest.TestCase):
    """Owner order 2026-10-23: the greeting, the THEMES dropdown, the
    CUSTOM SCRIPS OF VOL. dropdowns and the version line. Each new
    contract is pinned on the resources and the one Java decision that
    carries it.
    """

    def setUp(self):
        self.layout = LAYOUT.read_text(encoding="utf-8")
        self.strings = STRINGS.read_text(encoding="utf-8")
        self.main = MAIN.read_text(encoding="utf-8")
        self.colors = COLORS.read_text(encoding="utf-8")

    def resource_value(self, name: str) -> str:
        marker = f'name="{name}">'
        start = self.strings.index(marker) + len(marker)
        return self.strings[start:self.strings.index("</string>", start)]

    def test_the_greeting_precedes_the_status_tile(self):
        self.assertLess(self.layout.index("@+id/greeting"),
                        self.layout.index("@+id/tile_status"))
        self.assertEqual(self.resource_value("greeting_morning"),
                         "Good morning, Mr. Rehan!")
        self.assertEqual(self.resource_value("greeting_afternoon"),
                         "Good afternoon, sir!")
        # It is a line, not a heading: the body's one size.
        greeting = element(self.layout, 'android:id="@+id/greeting"')
        self.assertIn('style="@style/QorValue"', greeting)
        block = self.main[self.main.index("private void refreshGreeting()"):]
        block = block[:block.index("private void buildThemeSpinner()")]
        for resource in ("greeting_morning", "greeting_afternoon"):
            self.assertIn(f"R.string.{resource}", block)

    def test_the_themes_tile_carries_five_looks(self):
        self.assertIn('name="label_themes">THEMES<', self.strings)
        self.assertIn('name="theme_purple">PURPLE &amp; YELLOW<', self.strings)
        self.assertIn('name="theme_black">BLACK &amp; WHITE<', self.strings)
        self.assertIn('name="theme_green">GREEN &amp; YELLOW<', self.strings)
        self.assertIn('name="theme_navy">NAVY BLUE &amp; WHITE<', self.strings)
        self.assertIn('name="theme_orange">ORANGE &amp; WHITE<', self.strings)
        spinner = element(self.layout, 'android:id="@+id/theme_spinner"')
        self.assertIn("<Spinner", spinner)
        # The five looks are declared colours, not hex in Java.
        for theme in ("black", "green", "navy", "orange"):
            for weight in ("bg", "panel", "accent"):
                self.assertIn(f'name="theme_{theme}_{weight}"', self.colors)
        # One switch paints the look, and the selection is remembered.
        self.assertIn('prefs.edit().putInt("theme", index).apply();',
                      self.main)
        for theme in ("black", "green", "navy", "orange"):
            self.assertIn(f"R.color.theme_{theme}_bg", self.main)
        self.assertIn("THEME_LABELS.length", self.main)

    def test_the_volume_tile_sits_on_the_search_page(self):
        self.assertIn('name="label_volume">CUSTOM SCRIPS OF VOL.<',
                      self.strings)
        self.assertIn('name="volume_split_caption">HIGHEST B &amp; LOWEST S.<',
                      self.strings)
        self.assertIn('name="volume_speed_caption">FASTEST PRICE.<',
                      self.strings)
        self.assertLess(self.layout.index("@+id/tile_volume"),
                        self.layout.index("@+id/tile_market"))
        for view_id in ("volume_split_spinner", "volume_speed_spinner"):
            with self.subTest(spinner=view_id):
                spinner = element(self.layout,
                                  f'android:id="@+id/{view_id}"')
                self.assertIn("<Spinner", spinner)
        # Both dropdowns are ranked from the map the search already
        # refreshes, so neither costs a request of its own.
        self.assertIn("Watcher.quotes()", self.main)
        self.assertIn("rankedSplitSymbols(", self.main)
        self.assertIn("rankedSpeedSymbols(", self.main)

    def test_the_version_line_names_the_manifest(self):
        version = element(self.layout, 'android:id="@+id/app_version"')
        self.assertIn('style="@style/QorCaption"', version)
        self.assertIn('name="app_version_prefix">APP VERSION ', self.strings)
        # The number is the manifest's own versionName, the same one the
        # build prints: the page and the APK cannot disagree.
        self.assertIn("getPackageInfo(getPackageName(), 0).versionName;",
                      self.main)



class KarachiInkTest(unittest.TestCase):
    """Owner order 2026-10-22: the clock rides the UP-percentage green,
    read by the same resource name the card's up marks use, so the two
    facts cannot drift into two different greens."""

    def test_the_clock_spans_colour_the_time_in_the_card_green(self):
        main = MAIN.read_text(encoding="utf-8")
        colors = COLORS.read_text(encoding="utf-8")
        block = main[main.index("private SpannableString clockSpans(String d) {"):]
        block = block[:block.index("/** The third card")]
        self.assertIn("getColor(R.color.green)", block)
        self.assertNotIn("R.color.teal_bright", block)
        # One green resource serves both duties; near-miss names are
        # refused so the card's up marks and the clock cannot diverge.
        self.assertNotIn('name="green_up"', colors)
        self.assertNotIn('name="up_green"', colors)
        self.assertIn('name="green"', colors)


class SearchHighlightTest(unittest.TestCase):
    """Owner order 2026-10-22: as the owner types, the rows that match
    light up, and the row that says the whole answer lights hardest.

    Typing H lights every H... scrip; typing HU narrows the light; the
    moment HUBC is complete its row carries the strongest gold of the
    list. Both plate intensities come from the palette by name, and the
    highlight is a fact of the QUERY, never of the selection.
    """

    def test_every_row_is_styled_against_the_live_query(self):
        main = MAIN.read_text(encoding="utf-8")
        self.assertIn(
            "private void styleSearchRow(TextView row, String symbol, String q) {",
            main)
        # Both draw paths restyle against the SAME live query, so a
        # keystroke and a price tick light the same rows.
        self.assertIn("styleSearchRow(row, symbol, q);", main)
        self.assertIn("styleSearchRow(entry.getValue(), entry.getKey(), q);", main)

    def test_a_prefix_match_lights_and_an_exact_match_lights_hardest(self):
        main = MAIN.read_text(encoding="utf-8")
        block = main[main.index("private void styleSearchRow") :]
        block = block[:block.index("/** One symbol's B, S and T")]
        self.assertIn("boolean exactMatch = symbol.length() == q.length();", block)
        self.assertIn("symbol.startsWith(q)", block)
        self.assertIn("R.color.gold_match", block)
        self.assertIn("R.color.gold_press", block)
        self.assertIn("row.setBackground(null);", block)

    def test_the_match_plates_are_the_brand_gold_at_two_intensities(self):
        colors = COLORS.read_text(encoding="utf-8")
        # D9A441 at 20% (a prefix match) and at 35% (the exact one): one
        # brand ink, two how-loud answers, declared in values/colors.xml
        # rather than invented in Java.
        self.assertIn('<color name="gold_press">#33D9A441</color>', colors)
        self.assertIn('<color name="gold_match">#59D9A441</color>', colors)

    def test_the_highlight_rides_the_keystroke_render_not_a_request(self):
        main = MAIN.read_text(encoding="utf-8")
        # The owner's 2026-10-20 instant-search law still holds: one
        # TextWatcher, a render per keystroke, zero relay requests.
        self.assertIn('renderSearchResults(e == null ? "" : e.toString());', main)
        # The highlight is restyled on every visible-set tick as well, so a
        # price refresh cannot leave a row lit that no longer matches (the
        # tick path re-renders with the box's LIVE query).
        self.assertIn("renderSearchResults(searchInput.getText().toString());", main)


class ThinkingOrbPlanTest(unittest.TestCase):
    """Owner orders 2026-10-22, stacked: the owner sent the reference look
    he wanted (a living mover under the brand) and the first HUD pass's
    movers (the diag line's words and the sweeping beam) are retired in
    favour of the ONE mover that earns the claim: the ThinkingOrb under
    the brand, on the SEARCH and SETTINGS pages too, running ONLY while
    the console is resumed. Owner order 2026-10-22 (third pass, v1.9.9),
    after the owner sent a screenshot of v1.9.8 and rejected it: "sun is
    like a 3D ball that is burning every second". So the orb is THE SUN:
    one big three dimensional ball that fills its box, built of a lit
    sphere, convection cells on its face, flame tongues on its limb,
    prominence arcs that roll around it and flare sparks that burst on a
    seconds cadence. The classic frame's tiles, rules and copy stand
    untouched beneath it.
    """

    def test_the_orb_sits_where_the_beam_lay(self):
        layout = LAYOUT.read_text(encoding="utf-8")
        self.assertIn("<pk.quantofrehan.ThinkingOrb", layout)
        self.assertIn("@+id/thinking_orb", layout)
        # Under the brand, ahead of the rule before the search tile: the
        # beam's former station. The first pass's 3dp restoration of the
        # pre-HUD 12dp air stands.
        self.assertLess(layout.index("@+id/thinking_orb"),
                        layout.index("@+id/rule_before_search"))
        block = layout[layout.index("@+id/thinking_orb"):
                       layout.index("@+id/thinking_orb") + 400]
        self.assertIn("android:importantForAccessibility=\"no\"", block)
        # The beam and the diag line are gone, and nothing pretends to
        # be them: the retired ids and resources may not come back.
        self.assertNotIn("@+id/scan_beam", layout)
        self.assertNotIn("@+id/sys_diag", layout)

    def test_the_first_pass_movers_are_retired(self):
        main = MAIN.read_text(encoding="utf-8")
        strings = STRINGS.read_text(encoding="utf-8")
        styles = STYLES.read_text(encoding="utf-8")
        # No rotating words, no sweeping beam: the class, the string array
        # and the style that carried them are gone from the console.
        self.assertNotIn("R.array.sys_diag_lines", main)
        self.assertNotIn('name="sys_diag_lines"', strings)
        self.assertNotIn('name="QorDiag"', styles)
        res = RES / "drawable"
        self.assertFalse((res / "scan_beam.xml").exists())

    def test_the_orb_runs_only_while_the_console_is_resumed(self):
        main = MAIN.read_text(encoding="utf-8")
        self.assertIn("private void startHud() {", main)
        self.assertIn("private void stopHud() {", main)
        self.assertIn("thinkingOrb.start();", main)
        self.assertIn("thinkingOrb.stop();", main)
        resume = main[main.index("protected void onResume()") :]
        resume = resume[:resume.index("protected void onPause()")]
        self.assertIn("startHud();", resume)
        pause = main[main.index("protected void onPause()") :]
        pause = pause[:pause.index("/** The foreground refresh loop. */")]
        self.assertIn("stopHud();", pause)
        # A hidden console holds no animation: the orb's loop is the only
        # runner and MainActivity starts and stops it, never polls it.
        self.assertNotIn("postDelayed(diagStep", main)
        self.assertNotIn("ValueAnimator", main)

    def test_the_orb_stays_on_the_search_and_settings_pages(self):
        layout = LAYOUT.read_text(encoding="utf-8")
        main = MAIN.read_text(encoding="utf-8")
        """Owner order 2026-10-22 (v1.9.5): the orb is on the SEARCH and
        SETTINGS pages as well, at the SAME exact placement it holds on the
        front page. The panels open BELOW the orb, exactly where the tiles
        sat, so the orb keeps its station under the brand on every page
        rather than a second copy being stamped into each panel.
        """
        # The orb is NOT a member of consoleViews any more: a menu no
        # longer takes its space.
        self.assertNotIn("findViewById(R.id.thinking_orb),", main)
        # Its station precedes the panel's own top rule and both panels,
        # which is the exact spot it holds on the front page.
        self.assertLess(layout.index("@+id/thinking_orb"),
                        layout.index("@+id/rule_before_search"))
        self.assertLess(layout.index("@+id/thinking_orb"),
                        layout.index("@+id/search_panel"))
        self.assertLess(layout.index("@+id/thinking_orb"),
                        layout.index("@+id/settings_panel"))
        # One orb, not a copy inside a panel: the custom view appears as a
        # tag exactly once in the layout.
        self.assertEqual(layout.count("pk.quantofrehan.ThinkingOrb"), 2)

    def test_the_thinking_is_advanced_and_thirty_percent_faster(self):
        orb = (MAIN.parent / "ThinkingOrb.java").read_text(
            encoding="utf-8")
        """Owner order 2026-10-22 (v1.9.5): the sun moves at 30% more
        speed than v1.8.9's mover, and it burns - the surface never still.
        """
        # The owner's 30% is ONE named constant that every rate multiplies,
        # so the order is one decision rather than ten edits.
        self.assertIn("MOTION_SCALE = 1.3f", orb)
        for snippet in (
                "seconds * 0.12f * MOTION_SCALE",
                "seconds * 0.13f * MOTION_SCALE",
                "seconds * 0.9f * MOTION_SCALE",
                "seconds * 1.1f * MOTION_SCALE",
                "seconds * 0.31f * MOTION_SCALE",
                "seconds * 0.47f * MOTION_SCALE",
                "seconds * flameRate[f] * MOTION_SCALE",
                "seconds * cells[o + 5] * MOTION_SCALE"):
            with self.subTest(snippet=snippet):
                self.assertIn(snippet, orb)
        self.assertGreaterEqual(orb.count("MOTION_SCALE"), 9)
        # The sun is up when the owner looks: the wake ramp is 1.2
        # seconds, not v1.9.8's four.
        self.assertIn("WAKE_SECONDS = 1.2f", orb)
        self.assertNotIn("Thread.sleep", orb)
        self.assertNotIn("ValueAnimator", orb)

    def test_the_nucleus_is_one_3d_ball(self):
        orb = (MAIN.parent / "ThinkingOrb.java").read_text(
            encoding="utf-8")
        """Owner order 2026-10-22 (v1.9.7, carried through v1.9.9): the
        sun is ONE 3D ball, and v1.9.9's order makes it a REAL burning
        ball that fills its box.
        """
        # One shaded sphere that fills the view: the hotspot sits up and
        # to the LEFT of the centre, the body runs white-hot through the
        # solar golds to a deep burning orange, and the limb falls to
        # transparent. v1.9.5/6's stacked discs and separate ring are all
        # gone, name and draw alike.
        self.assertIn("ballPaint", orb)
        self.assertIn("SUN_WHITE", orb)
        self.assertIn("0xFFFFF3B0", orb)
        self.assertIn("0xFFFFC107", orb)
        self.assertIn("0xFFE65100", orb)
        self.assertIn("cx - sunR * 0.18f", orb)
        self.assertIn("cy - sunR * 0.22f", orb)
        for gone in ("ringPaint", "haloPaint", "corePaint",
                     "coreRadius", "heart * 0.72f", "coreRadius * 2.1f"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, orb)
        # It fills the box: the radius is the view's own, minus one breath
        # of air, never a small nucleus inside it.
        self.assertIn("sunR = Math.min(w, h) / 2f - dp(4f)", orb)
        # Draw order: corona UNDER the fire and the ball, flames and
        # prominences on the limb, then the ball over their inner halves,
        # then the white-hot heart, the convection cells and the flares.
        self.assertLess(orb.index(
                "canvas.drawCircle(cx, cy, sunR * 1.6f, coronaPaint)"),
            orb.index(
                "canvas.drawCircle(cx, cy, sunR, ballPaint)"))
        self.assertLess(orb.index(
                "canvas.drawCircle(cx, cy, sunR, ballPaint)"),
            orb.index("sunR * 0.24f, heartPaint"))
        # The corona and the ball cross instead of pulsing together.
        self.assertIn("OUT of phase", orb)
        # Fire fuses: overlapping glows add, they do not stack as discs.
        self.assertIn("FIRE_MODE", orb)
        # The limb is ragged fire, the prominences roll around it and the
        # flare sparks carry the seconds cadence the owner ordered.
        self.assertIn("FLAMES = 22", orb)
        self.assertIn("flameLength", orb)
        self.assertIn("flamePhase", orb)
        self.assertIn("flameRate", orb)
        # More lines revolve around the ball.
        self.assertIn("PROMINENCES = 42", orb)
        self.assertIn("FLARES = 28", orb)
        self.assertIn("seconds * (0.05f + p * 0.008f) * MOTION_SCALE", orb)
        self.assertIn("flarePeriod", orb)
        self.assertIn("flarePhase", orb)
        self.assertIn("0.9f + frac(seed) * 0.7f", orb)
        # The surface burns: convection cells ON the sphere, culled past
        # the limb, dimming as they reach it. The ball turns.
        self.assertIn("GRANULES = 26", orb)
        self.assertIn("GRANULE_STRIDE = 6", orb)
        self.assertIn("if (rz <= 0.08f)", orb)

    def test_the_whole_feature_is_30_percent_brighter(self):
        orb = (MAIN.parent / "ThinkingOrb.java").read_text(
            encoding="utf-8")
        """Owner orders 2026-10-22 (v1.9.6 through v1.9.8, stacked): the
        ENTIRE animated feature grew 25%, then 30%, then 30%, then 30%
        brighter at every ink and not the nucleus alone.
        """
        # The four orders are each ONE named constant here, and the frame
        # runs them as ONE combined per-frame factor at every ink, so the
        # stacking is one decision that can never drift.
        self.assertIn("private static final float GLOW_SCALE = 1.25f;", orb)
        self.assertIn("private static final float BRIGHT_SCALE = 1.3f;", orb)
        self.assertIn("private static final float P1 = 1.3f;", orb)
        self.assertIn("private static final float P2 = 1.3f;", orb)
        self.assertIn(
            "float bright = wake * GLOW_SCALE * BRIGHT_SCALE * P1 * P2;",
            orb)
        # Every ink layer carries the boost: the corona, the limb flames,
        # the prominences, the ball, its heart, the convection cells and
        # the flare sparks.
        self.assertGreaterEqual(orb.count("* bright"), 6,
                                "every ink layer must carry the boost")
        for ink in ("coronaPaint.setAlpha", "flamePaint.setAlpha",
                    "prominencePaint.setAlpha", "ballPaint.setAlpha",
                    "heartPaint.setAlpha", "cellPaint.setAlpha",
                    "flarePaint.setColor"):
            with self.subTest(ink=ink):
                self.assertIn(ink, orb)
        # And the flat grey disc the owner saw in the screenshot is gone:
        # the ball's limb falls off to transparent instead.
        self.assertNotIn("heart * 0.72f", orb)

    def test_the_orb_is_one_budget(self):
        orb = (MAIN.parent / "ThinkingOrb.java").read_text(encoding="utf-8")
        # Zero allocations on the frame path: geometry built once.
        self.assertIn("buildGeometry()", orb)
        self.assertIn("onSizeChanged", orb)
        # The frame loop is the view's own paced invalidate, not a sleep
        # or a background service: nothing runs while the view is parked.
        self.assertIn("postInvalidateOnAnimation()", orb)
        self.assertNotIn("Thread.sleep", orb)
        self.assertNotIn("Service", orb)
        # The solar family is declared beside the drawing that owns it;
        # the console palette is untouched by the HUD, and the field is
        # exactly the console's own deep background.
        self.assertIn("FIELD_COLOR = 0xFF0B070D", orb)
        self.assertIn("0xFFFFF3B0", orb)
        self.assertIn("0xFFE65100", orb)


class UniversalRuleGapTest(unittest.TestCase):
    """Owner order 2026-10-22 (the gap law): the diamond and the two lines
    around it stand the SAME distance from the tiles around them in every
    case on the console. The air above every rule and the air above every
    tile that follows one is 12dp, the grid gap the console already used
    under its rules, so a rule that once sat 3dp, 16dp, 14dp or 18dp from
    its neighbours is brought onto the one number and can never drift
    back: every include and every tile is read here, and one hand-written
    exception fails this test instead of shipping a second rhythm.
    """

    def setUp(self):
        self.root = layout_root()

    def test_every_rule_carries_the_grid_gap_above_it(self):
        rules = [node for node in self.root.iter()
                 if node.tag == "include"
                 and node.get("layout") == "@layout/qor_rule"]
        self.assertEqual(len(rules), 8)
        for rule in rules:
            with self.subTest(rule=rule.get(f"{ANDROID_NS}id")):
                self.assertEqual(rule.get(f"{ANDROID_NS}layout_marginTop"),
                                 "12dp")

    def test_every_tile_that_follows_a_rule_carries_the_same_gap(self):
        for view_id in ("tile_status", "tile_signal", "tile_market",
                        "search_panel", "settings_panel", "nav_tile"):
            with self.subTest(tile=view_id):
                tile = find_view(self.root, f"@+id/{view_id}")
                self.assertEqual(tile.get(f"{ANDROID_NS}layout_marginTop"),
                                 "12dp")

    def test_the_footer_stands_on_the_same_gap(self):
        footer = find_view(self.root, "@+id/scan_cadence")
        self.assertEqual(footer.get(f"{ANDROID_NS}layout_marginTop"), "12dp")


class MarketHeadingWordTest(unittest.TestCase):
    """Owner order 2026-10-22, exact wording: the market card's heading says
    "THE INDEX & THE TOP 3 SCRIPS OF VOL.", so the definite articles are
    part of the resource and no other resource carries the old shorter
    form. The heading test above pins the layout facts; this one pins the
    words only, so a later order can lose the ampersand's escape without
    touching two tests.
    """

    def test_the_words_are_exactly_the_owners(self):
        strings = STRINGS.read_text(encoding="utf-8")
        self.assertIn(
            'name="label_market">THE INDEX &amp; THE TOP 3 SCRIPS OF VOL.<',
            strings)
        self.assertNotIn('INDEX &amp; TOP 3 SCRIPS', strings)


if __name__ == "__main__":
    unittest.main()
