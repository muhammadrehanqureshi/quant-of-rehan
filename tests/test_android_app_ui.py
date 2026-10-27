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

    Home, search and settings moved here from the brand row; since 2.0.0
    the tile is the bar alone, with no diamond rule above or below it
    (the owner's order the same day). Each
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

    def test_the_four_icons_sit_centred_in_equal_quarters(self):
        """Owner order 2026-10-24 ("the gap between all the icons are not
        the same, make the gap same between all four icons"): the tile
        takes four equal cells and each icon sits CENTRED in its own
        cell, so the air between any two neighbours is one width by
        construction - home is no longer pinned to the very left edge
        and settings to the very right edge (the thirds law that
        pinned them is retired with its pass).
        """
        root = layout_root()
        nav = find_view(root, "@+id/nav_tile")
        cells = [node for node in nav if node.tag == "FrameLayout"]
        self.assertEqual(len(cells), 4)
        for cell in cells:
            self.assertEqual(cell.get(f"{ANDROID_NS}layout_width"), "0dp")
            self.assertEqual(cell.get(f"{ANDROID_NS}layout_weight"), "1")
            icons = [node for node in cell
                     if node.tag == "ImageView"
                     and node.get(f"{ANDROID_NS}id", "").startswith(
                         "@+id/btn_nav_")]
            self.assertEqual(len(icons), 1)
            self.assertEqual(icons[0].get(f"{ANDROID_NS}layout_gravity"),
                             "center")
        # And the old edge pinning is retired: no icon carries the
        # start or end gravity any more.
        nav_text = self.layout[self.layout.index("@+id/nav_tile"):]
        nav_text = nav_text[:nav_text.index("</LinearLayout>")]
        self.assertNotIn('android:layout_gravity="start', nav_text)
        self.assertNotIn('android:layout_gravity="end', nav_text)

    def test_the_menu_tile_is_bracketed_by_rules_at_the_very_bottom(self):
        root = layout_root()
        nav = find_view(root, "@+id/nav_tile")
        self.assertIsNotNone(nav)
        self.assertEqual(nav.get("style"), "@style/QorPanel")
        # v2.2.0: the tile rides the 20dp side carrier (the bar's breadth
        # is the carrier's own construction), so the footer follows the
        # carrier, not the tile.
        carrier = parent_of(root, nav)
        self.assertIsNotNone(carrier)
        # Owner order 2026-10-23 (2.0.0): the tile's two bracket rules are
        # GONE. The owner read the diamond above and below the pinned menu
        # bar as clutter around a fixed bar, so neither id exists anywhere
        # in the layout any more and the tile follows the scroll directly.
        self.assertNotIn("@+id/rule_before_nav", self.layout)
        self.assertNotIn("@+id/rule_after_nav", self.layout)
        # The console scroll closes, the carrier follows (v2.2.0: the bar's
        # breadth is the carrier's own construction), and nothing follows
        # the carrier: v2.2.1 moved the version line ABOVE the bar, so it
        # now stands between the scroll and the bar as the root's middle
        # unit (see the root test below).
        self.assertLess(self.layout.index("@+id/console_scroll"),
                        self.layout.index("@+id/nav_tile"))
        following = siblings_after(root, carrier)
        self.assertEqual(
            [node.get(f"{ANDROID_NS}id") for node in following],
            [], "no footer follows the carrier any more", )

    def test_the_four_icons_are_the_owners_own_pngs(self):
        """Owner order 2026-10-24: the scanner page's icon (his own
        scanner.png from the Desktop) joins the bar beside home."""
        for view_id, name in (("btn_nav_home", "home"),
                              ("btn_nav_scanner", "scanner"),
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
        scanner = element(self.layout, 'android:id="@+id/btn_nav_scanner"')
        search = element(self.layout, 'android:id="@+id/btn_nav_search"')
        settings = element(self.layout, 'android:id="@+id/btn_nav_settings"')
        self.assertIn('android:background="@drawable/nav_circle"', home)
        self.assertIn('android:tint="@color/gold_bright"', home)
        for other in (scanner, search, settings):
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
        # Owner order 2026-10-24: home is the console's page only when all
        # three menus are closed, and the scanner page paints like the
        # rest of them.
        self.assertIn("setNavPage(navHome, !searchOpen && !settingsOpen && !scannerOpen);",
                      self.main)
        self.assertIn("setNavPage(navScanner, scannerOpen);", self.main)
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

    def test_the_gear_turns_left_on_open_and_right_on_close(self):
        # Owner order 2026-10-24, fourth note: the wheel moves again -
        # opening the settings page turns the icon LEFT (a negative
        # rotation, counterclockwise) and closing it turns the icon back
        # RIGHT home to zero. The v2.0.0 pass retired the gear's torque;
        # today's order brings it back with its own law, still in one
        # place (setSettingsOpen, beside the page toggle) and still no
        # shift constant.
        turn = self.main[
            self.main.index("navSettings.animate()"):
            self.main.index(".start();", self.main.index("navSettings.animate()"))]
        self.assertIn(".rotation(open ? -90f : 0f)", turn)
        self.assertIn("new DecelerateInterpolator()", turn)
        self.assertIn(".setDuration(", turn)
        # Two view-property rotations in the whole file: the dropdown
        # arrow's flip (inside rotateDropdownArrow) and this wheel's turn.
        rotations = self.main.count(".rotation(")
        self.assertEqual(rotations, 2,
                         "the dropdown arrow's flip and the gear's turn")
        arrow = self.main.index(".rotation(open ? 180f : 0f)")
        # v2.3.16: the flip's owner is the inline engine's own helper, one
        # view-property animation the two open states share - the arrow is
        # no longer driven by a platform window's own open/close edges.
        arrow_owner = self.main.index(
                "private void rotateDropdownArrow(ImageView arrow, "
                "boolean open)")
        arrow_extent = self.main.index("private void", arrow_owner + 30)
        self.assertLess(arrow_owner, arrow)
        self.assertLess(arrow, arrow_extent)
        self.assertNotIn("GEAR_TURN_MS", self.main)
        self.assertNotIn(
            "settings_shift",
            (RES / "values" / "dimens.xml").read_text(encoding="utf-8"))

    def test_the_search_toggle_closes_the_scanner_page(self):
        # Owner order 2026-10-24, third pass ("then I tap on search icon
        # it highlights with the scanner icon highlighted as well, so
        # when I am on the search page, search and scanner icons are
        # both being highlighted"): the v2.2.3 search toggle closed the
        # settings page but never the scanner one, so the scanner stayed
        # open under the search page. One page at a time, the same law
        # the settings and scanner toggles keep: an opening search
        # closes the scanner first.
        method0 = self.main.index("private void setSearchOpen(")
        method1 = self.main.index("private void renderSearchResults(",
                                  method0)
        method = self.main[method0:method1]
        self.assertIn("if (open && scannerOpen) {", method)
        self.assertLess(method.index("if (open && scannerOpen) {"),
                        method.index("if (consoleViews != null) {"))
        self.assertIn("setScannerOpen(false);", method)

    def test_the_themes_tile_lives_with_the_settings_page_alone(self):
        # Owner order 2026-10-24, third note: the THEMES tile left the
        # settings box; it is its OWN tile, a sibling of the settings
        # panel behind the settings page's diamond bracket (two
        # qor_rule includes inside the holder, one above and one
        # below the tile). The holder is drawn from the page truth
        # exactly like the panel: visible while the settings page is,
        # gone on home, search and scanner - one toggle owns it.
        root = layout_root()
        holder = find_view(root, "@+id/themes_holder")
        self.assertIsNotNone(holder)
        self.assertEqual(holder.get(f"{ANDROID_NS}visibility"), "gone")
        # Two diamond bracket rules and the tile: one rule above, one
        # below, the tile between them, all inside the holder and
        # nowhere else.
        holder_rules = [node.tag for node in holder.iter()
                        if node.tag == "include"]
        self.assertEqual(len(holder_rules), 2)
        for node in holder.iter():
            if node.tag == "include":
                self.assertEqual(node.get("layout"), "@layout/qor_rule")
        ids = [node.get(f"{ANDROID_NS}id") for node in holder.iter()
               if node.get(f"{ANDROID_NS}id")]
        self.assertIn("@+id/tile_themes", ids)
        # The holder is a sibling of the settings panel, never a child.
        self.assertIn("@+id/settings_panel",
                      self.layout[:self.layout.index("@+id/themes_holder")])
        # The code's one truth: setSettingsOpen toggles the holder with
        # the panel, and the search and scanner toggles take it off.
        block = self.main[self.main.index("private void setSettingsOpen(") :]
        block = block[:block.index("paintNavSelection();")]
        self.assertIn("themesHolder.setVisibility(open ? View.VISIBLE : View.GONE);",
                      block)
        self.assertIn("themesHolder.setVisibility(open ? View.GONE", self.main)
        self.assertIn("themesHolder = findViewById(R.id.themes_holder);", self.main)

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
        # Eight rules on the console since v2.2.4 (owner order 2026-10-24,
        # third pass): the brand rule under the header, the three the
        # home tiles carry, the TWO the THEMES tile wears of its own -
        # the qor_rule include again, one diamond rule above it and one
        # below it (owner order 2026-10-23, v2.2.1: "have separate diamond and
        # 2 lines around it, up side and down side") - the search
        # page's diamond rule above the search tile, back by the owner's
        # v2.2.3 order after the v1.9.13 cancellation took it away, and
        # the volume pair's own rule between the search tile and the
        # CUSTOM SCRIPS OF VOL. tile. The
        # pair that used to bracket the menu tile pinned at the very
        # bottom is still GONE (the owner read the diamond above and
        # below the pinned bar as clutter around a fixed bar), and the
        # SETTINGS page's own rule is still GONE (the owner read each
        # page's second diamond as an extra one; the themes bracket is
        # the diamond the settings page carries now). One rule per
        # division, never two, is the standing law the themes bracket
        # honours: there the owner ASKED for the bracket, and so does
        # the search-volume pair's own.
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
        # shelf, QorBrandTitle, and the size is a style fact. Owner order
        # 2026-10-23 (v1.9.13): the title GREW 20% from its own previous
        # size, its own law, not a ratio of the headings.
        # Owner order 2026-10-23 (second order, v1.9.14): ANOTHER 20% on
        # top of v1.9.13's 24.44754sp, landing on 29.337048sp.
        brand = element(self.layout, 'android:text="@string/app_name"')
        self.assertIn('style="@style/QorBrandTitle"', brand)
        self.assertNotIn("textSize", brand)
        style = self.styles[self.styles.index('name="QorBrandTitle"'):]
        style = style[:style.index("</style>")]
        self.assertIn('<item name="android:textSize">29.337048sp</item>', style)

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
    def test_the_sentence_stands_after_the_market_rule(self):
        rules = [node for node in self.root.iter() if node.tag == "include"
                 and node.get("layout") == "@layout/qor_rule"]
        # v1.9.13, then 2.0.0 (owner order 2026-10-23): the extras the
        # menu pages owned and the pair that used to bracket the pinned
        # menu bar were cancelled as the owner's clutter order. v2.2.1
        # then framed the THEMES tile the owner ordered for its
        # "separate diamond and 2 lines around it", and v2.2.3 put the
        # search page's own rule back above the search tile. v2.2.4:
        # eight rules now - the single brand rule under the header, the
        # three the home tiles carry, the two that frame the THEMES tile
        # above and below, the search page's own diamond, and the
        # division between the search tile and the volume tile.
        self.assertEqual(len(rules), 8)
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
        # stays exactly the pinned bar (v1.9.13). No other fixed unit
        # follows the market rule's sentence.
        self.assertEqual(following[1:], [])
        # v2.2.1: the version line left the root's end for the station
        # directly above the pinned menu bar. v2.2.4: it left THAT
        # station for the settings page itself, under the THEMES tile's
        # closing diamond, so the root's own order is scroll, bar - the
        # version line rides the scroll's settings page now.
        self.assertEqual(
            [n.get(f"{ANDROID_NS}id") or n.tag for n in list(self.root)],
            ["@+id/console_scroll", "@+id/nav_carrier"])

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

    def test_the_watch_window_is_gone(self):
        """Owner order 2026-10-23 (v2.2.1): "why do I need 1 second watch
        window? if it's not needed anymore then remove it, since I am
        already getting live feed and quant is already scanning every
        second"

        The button, its arm loop, the alarm receiver that re-armed it and
        the battery exemption that kept it alive are all removed: the
        quant already scans the market every second in the cloud and the
        relay delivers the feed and signals from there, so a closed app
        schedules nothing and the handset carries no second scanner.
        """
        self.assertNotIn("@+id/btn_arm", self.layout)
        self.assertNotIn("btn_arm", STRINGS.read_text(encoding="utf-8"))
        self.assertNotIn("1-second watch window", self.main)
        self.assertNotIn("armAlarms", self.main)
        self.assertNotIn("maybeRequestBatteryExemption", self.main)
        self.assertNotIn("asked_battery", self.main)
        watcher = WATCHER.read_text(encoding="utf-8")
        self.assertNotIn("WATCHDOG_MS", watcher)
        self.assertNotIn("armAlarms", watcher)
        self.assertNotIn("AlarmManager", watcher)
        # The receiver class is deleted with the loop it served, and the
        # manifest carries neither it nor its two permissions. The chords
        # are read from the PERMISSION ELEMENTS, not the raw file, so the
        # manifest's own historical note about why they left is not the
        # offence this refuses.
        self.assertFalse(
            (WATCHER.parent / "PollReceiver.java").exists())
        manifest_root = ET.parse(MANIFEST).getroot()
        permissions = [p.get("android:name")
                       for p in manifest_root.iter("uses-permission")]
        self.assertNotIn("android.permission.RECEIVE_BOOT_COMPLETED",
                         permissions)
        self.assertNotIn(
            "android.permission.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS",
            permissions)
        receivers = [r.get("android:name")
                     for r in manifest_root.iter("receiver")]
        self.assertNotIn(".PollReceiver", receivers)

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
        # v2.2.1: the idle 30 second cadence and the phone-side watchdog
        # arm are BOTH retired with the watch window they served - the
        # foreground tick is always the one-second FAST_POLL_MS, and a
        # closed app schedules nothing on the handset.
        self.assertNotIn("REFRESH_MS", watcher)
        self.assertNotIn("WATCHDOG_MS", watcher)
        self.assertIn("static final long FAST_POLL_MS = 1000;", watcher)
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
        # v2.2.1: the foreground tick is ALWAYS the one-second cadence, so
        # the INDEX tile repaints at the digital-clock read the owner
        # ordered, whatever the relay's market state says.
        self.assertIn("cadence.postDelayed(tick, Watcher.FAST_POLL_MS);",
                      self.main)
        self.assertNotIn("REFRESH_MS", self.main)
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
        # The answer is painted BEFORE the cadence is re-decided: the order
        # of these two calls is the fix's shape, kept through v2.2.1.
        self.assertLess(render.index("paint(online, d, s, market);"),
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
        # v2.2.1: the DISPLAY_REFRESH_MS alias is retired with the idle
        # cadence it served - the foreground tick is ALWAYS FAST_POLL_MS,
        # one second, open market or not (owner order 2026-10-23).
        self.assertNotIn("DISPLAY_REFRESH_MS", watcher)
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
        # v2.2.3 (owner order 2026-10-24, fourth note): the wheel's untap
        # closes, so the listener passes the state's flip - tap opens,
        # untap (a second tap while open) closes - and the toggle's own
        # early return is still what keeps a repeated call inert.
        self.assertIn("setSettingsOpen(!settingsOpen)",
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
        # v1.9.13 is the 2026-10-23 pass on the ruined look: the pinned menu
        # bar (home at the LEFT edge, search at the MIDDLE, settings at the
        # RIGHT edge, one tiled thirds row outside the console scroll), one
        # diamond rule per menu page (the second ones cancelled), every
        # heading 10% smaller at one style, QUANT OF REHAN 20% bigger on its
        # own size, the greeting in the brand face, round corners on every
        # plate, and the sun that stops burning when the market closes or
        # breaks. v1.9.12's themes, CUSTOM SCRIPS OF VOL., version line and
        # /prices B/S rows stand.
        # v1.9.14 is the 2026-10-23 second order on the pixel look: the AI
        # feature is the v1.9.9 sun again with MORE revolving lines and a
        # hotter burn, the park that stopped moving STAYS VISIBLE (frozen,
        # never blanked), the greeting grew 30% and the brand ANOTHER 20%,
        # the tapped nav icon is lifted and brightened, the pinned bar
        # carries the tiles' 20dp side air AND side margins, the app version
        # line is the settings page's own footer, and the dropdowns rank
        # THE OWNER'S OWN WORDS (v2.1.0): busy scrips and fast prices.
        # v1.9.13's pinned bar, one rule per page and the round plates stand.
        # v2.0.0 is the 2026-10-23 third order on the same day: the two
        # diamond rules around the pinned menu bar are gone (the bar is the
        # tile alone), every dropdown carries the pull-down, pull-up state
        # arrow, and the watch window tap says the one-second reality with
        # no "watchdog" jargon and no "5 minutes" figure. v1.9.14's sun,
        # nav lift and footer stand.
        # v2.1.0 is the 2026-10-23 fourth order on the same day: the orb is
        # the radial ice-burst of the reference the owner re-sent (rays and
        # nodes revolving around the sun), the greeting is ANOTHER 40%
        # bigger, the menu bar matches the other tiles' breadth with side
        # margins too, the selection ring is painted as the icon's
        # FOREGROUND so the png can never cover it, the two volume
        # dropdowns are "More buyers & sellers" and "Price moving fast",
        # and the version line shows on the settings page only.
        # v2.2.0 is the 2026-10-23 sixth pass, on the v2.1.0 screenshots
        # the owner sent back: the feature is the v1.8.9 LIVING PARTICLE
        # CLOUD again (105 nodes around five anchors, links, turning in
        # depth), the cloud's centre is the ALWAYS-BURNING SUN, the menu
        # tile's edges are the SAME 20dp carrier the scroll uses, and the
        # open dropdown popups wear the app's own panel, rows and gold
        # ticker, not the platform's grey.
        # v2.2.2 is owner order 2026-10-24: the four greeting windows
        # hardcoded with the 05:01 morning edge, the always-closed 9 Nov /
        # 25 Dec PSX law, market emails delivered on the event's own minute
        # with the Friday post-market crons and the 5-minute catch-up, and
        # the scanner page: a fourth nav icon beside home opening the moved
        # CUSTOM SCRIPS OF VOL. tile.
        # v2.2.3 is owner order 2026-10-24, second pass: the four menu icons
        # sit centred in equal quarters, the orb's centre is the owner's own
        # ORB.jpg sun, the settings wheel turns left on open and right on
        # close, the THEMES tile stands alone on its page behind its own
        # diamond bracket, the search page's diamond rule is back above the
        # tile, and the CUSTOM SCRIPS OF VOL. tile is off the search page.
        # v2.2.5 is owner order 2026-10-24, fourth pass: the sun actually
        # TURNS (the radians-vs-degrees bug), the orbiting lines breathe,
        # the version line can no longer fuse, the dropdowns and search
        # boxes follow the app's current theme, and the volume menu's
        # first entry is the scanner's fast risers with capped out.
        # v2.2.6 is owner order 2026-10-24, fifth pass continued: the sun's
        # revolve is a longitude travel (X-axis) under the owner's own
        # 10% cut, every rule line tapers with its fade, and the fused
        # version gap is closed with a quoted resource literal.
        # v2.2.7 is owner order 2026-10-24, sixth pass: the longitude
        # window's phase lands on the face's centre now - the v2.2.6
        # build showed half-faces and mirror wreckage.
        # v2.2.8 is owner order 2026-10-25: the centre is a rendered
        # SPHERE again, the picture projections are gone, and the ball
        # carries no pulsing term.
        # v2.2.9 is owner order 2026-10-25, second pass: the ball wears
        # the photograph's crown (amber band and white-hot edge) and the
        # thin revolving arcs are gone from the limb.
        # v2.3.0 is owner order 2026-10-25, third pass: the surface is a
        # photograph at 448x224 through a ten-stop ramp, the painted band
        # is a ragged noise crown, and the fake rays are deleted.
        # v2.3.1 is owner order 2026-10-25, fourth pass: one heat field
        # folded through the photograph's own twelve quantiles, the fire
        # boils, the eruptions blow, the bloom bleeds and the filaments
        # breathe in width and ink as well as length.
        # v2.3.13 is owner order 2026-10-27, sixteenth pass: the sun 10%
        # slower, every field on the one 32dp floor, and the theme's own
        # highlight hue (the white read WAS the purple panel lifted 42%
        # toward white). The animation renders whole frames and the
        # theme's own inks are named again.
        # v2.3.14 is owner order 2026-10-27, seventeenth pass: the custom
        # scrips and themes boxes really do shrink 15% (the cut on the
        # height the boxes wear, not on a floor nothing draws), the
        # search box grows 10% on its floor, the sun's fourth 10% cut,
        # and the cloud filaments can no longer leave their dots.
        # v2.3.15 is owner order 2026-10-27, eighteenth pass: the two
        # boxes shrink ANOTHER 20% (the heights they really wear), the
        # search box grows another 25% on its floor, the dropdown arrow
        # becomes plainly visible and centres on the themes box, and
        # the cloud's anchors and mesh are named so the lines fill every
        # side and no lobe can spend another's links.
        # v2.3.16 is owner order 2026-10-27, nineteenth pass ("make the
        # decrease the height of custom scrips of volume by another 30%
        # ... all these three boxes should have universal height", "when
        # I tap on custom scrips of volume, another window pops up which
        # is wrong, drop down menu should appear from the same box", and
        # "increase the number of LINES by 20% from the current
        # number, across the entire animating feautre"): the three field
        # boxes on ONE universal 23dp height, the platform spinner
        # retired with its popup window (the menus are the app's own
        # rows opening from their own box), and the cloud's mesh joins
        # K = 4 of its own nearest neighbours on the budget the same
        # +20% carries.
        manifest = MANIFEST.read_text(encoding="utf-8")
        self.assertIn('android:versionName="2.3.16"', manifest)
        self.assertIn('android:versionCode="83"', manifest)
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
        self.assertIn("Version 1.9.13, versionCode 54", readme)
        self.assertIn("Version 1.9.14, versionCode 55", readme)
        self.assertIn("Version 2.0.0, versionCode 56", readme)
        self.assertIn("Version 2.1.0, versionCode 57", readme)
        self.assertIn("Version 2.2.0, versionCode 58", readme)
        self.assertIn("Version 2.2.1, versionCode 59", readme)
        self.assertIn("Version 2.2.3, versionCode 61", readme)
        self.assertIn("Version 2.2.4, versionCode 62", readme)
        self.assertIn("Version 2.2.5, versionCode 63", readme)
        self.assertIn("Version 2.2.6, versionCode 64", readme)
        self.assertIn("Version 2.2.7, versionCode 65", readme)
        self.assertIn("Version 2.2.8, versionCode 66", readme)
        self.assertIn("Version 2.2.9, versionCode 67", readme)
        self.assertIn("Version 2.3.0, versionCode 68", readme)
        self.assertIn("Version 2.3.1, versionCode 69", readme)
        self.assertIn("Version 2.3.2, versionCode 70", readme)
        self.assertIn("Version 2.3.3, versionCode 71", readme)
        self.assertIn("Version 2.3.5, versionCode 72", readme)
        self.assertIn("Version 2.3.6, versionCode 73", readme)
        # v2.3.7 (owner order 2026-10-26, ninth pass): the flicker and the
        # tangle pass, versionCode 74.
        self.assertIn("Version 2.3.7, versionCode 74", readme)
        # v2.3.8 (owner order 2026-10-26, tenth pass): the clusters, the
        # breath and the sun's own thread, versionCode 75.
        self.assertIn("Version 2.3.8, versionCode 75", readme)
        # v2.3.9 (owner order 2026-10-26, twelfth pass): the split menu's
        # buyers-surplus law, the theme's own highlight lift, the blended
        # sun handover and the 15% cut, versionCode 76.
        self.assertIn("Version 2.3.9, versionCode 76", readme)
        # v2.3.10 (owner order 2026-10-26, thirteenth pass): the corona
        # deletion and the commit gate, versionCode 77.
        self.assertIn("Version 2.3.10, versionCode 77", readme)
        # v2.3.11 (owner order 2026-10-26, fourteenth pass): the animation
        # removed and rebuilt from v2.3.8, the placeholder cap, and the
        # snug dropdown boxes, versionCode 78.
        self.assertIn("Version 2.3.11, versionCode 78", readme)
        # v2.3.12 (owner order 2026-10-27, fifteenth pass): the hug retired
        # with its clipping, the height alone down 5%, and the whole-frame
        # law, versionCode 79.
        self.assertIn("Version 2.3.12, versionCode 79", readme)
        # v2.3.13 (owner order 2026-10-27, sixteenth pass): the sun 10%
        # slower, every dropdown 15% shorter onto the one 32dp field
        # floor the search box shares, and the purple theme's white
        # highlight lift, versionCode 80.
        self.assertIn("Version 2.3.13, versionCode 80", readme)
        # v2.3.14 (owner order 2026-10-27, seventeenth pass): the real
        # 15% on the custom scrips and themes boxes, the search box +10%,
        # the sun's fourth 10% cut, and the filaments' inward-only
        # breathing, versionCode 81.
        self.assertIn("Version 2.3.14, versionCode 81", readme)
        # v2.3.15 (owner order 2026-10-27, eighteenth pass): a further
        # 20% off the two dropdowns, the search box +25%, the visible
        # and centred dropdown arrow, and the cloud's even anchors and
        # neighbourhood mesh, versionCode 82.
        self.assertIn("Version 2.3.15, versionCode 82", readme)
        # v2.3.16 (owner order 2026-10-27, nineteenth pass): the three
        # field boxes on ONE universal 23dp height, the platform
        # spinner retired with its popup window, and the cloud's mesh
        # joined four-neighbour on the +20% budget, versionCode 83.
        self.assertIn("Version 2.3.16, versionCode 83", readme)
        manifest = MANIFEST.read_text(encoding="utf-8")
        self.assertIn('android:versionCode="83"', manifest)
        self.assertIn('android:versionName="2.3.16"', manifest)
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
        # v2.2.1: the greeting grew +10% from ITS OWN current size,
        # 23.7 x 1.10 = 26.07 => 26.1sp, the fourth growth of this one
        # line; the body is still the one 13sp.
        self.assertEqual(sizes, {"13sp", "26.1sp"})
        label = self.styles[self.styles.index('name="QorLabel"'):]
        self.assertIn('android:textSize">15.944049sp',
                      label[:label.index("</style>")])
        brand = self.styles[self.styles.index('name="QorBrandTitle"'):]
        # The title grew 20% on top of v1.9.13's own size (v1.9.14).
        self.assertIn('android:textSize">29.337048sp',
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
        # Owner order 2026-10-23 (v1.9.13): headings are 10% smaller than
        # their previous size; buttons stay body size.
        for style, size in (("QorLabel", "15.944049sp"), ("QorButton", "13sp")):
            block = self.styles[self.styles.index(f'name="{style}"'):]
            block = block[:block.index("</style>")]
            self.assertIn("lemonmilk_bold", block)
            self.assertIn(f'android:textSize">{size}', block)


class TileBracketingTest(unittest.TestCase):
    """Owner order 2026-10-23 (v1.9.13), then 2026-10-24 (v2.2.3): the menu
    pages' rules.

    The owner read the SECOND diamond on the settings page as an extra
    one, so `rule_after_settings` stays gone; and on the search page he
    first cancelled its own diamond and then asked for it back. The
    v2.2.3 rule carries the id `rule_search` above the search tile,
    drawn from the page state in MainActivity.setSearchOpen - visible
    while he searches, gone on home and on every other page.
    """

    def setUp(self):
        self.root = layout_root()
        self.layout = LAYOUT.read_text(encoding="utf-8")
        self.main = MAIN.read_text(encoding="utf-8")

    def test_the_search_rule_stands_above_the_search_tile(self):
        # v2.2.3: the rule that was cancelled on 2026-10-23 is BACK, and
        # it carries the id it drives from in MainActivity.
        rule = find_view(self.root, "@+id/rule_search")
        self.assertIsNotNone(rule)
        self.assertEqual(rule.get("layout"), "@layout/qor_rule")
        self.assertIn("@+id/rule_search", self.layout)
        self.assertLess(self.layout.index("@+id/rule_search"),
                        self.layout.index("@+id/search_panel"))

    def test_the_old_search_rule_id_is_not_back(self):
        # The cancelled v1.9.12 id stays retired; the new rule is ITS OWN
        # id, so the two can never be confused.
        self.assertIsNone(find_view(self.root, "@+id/rule_before_search"))
        self.assertNotIn("@+id/rule_before_search", self.layout)

    def test_the_volume_rule_stands_between_the_two_tiles(self):
        # Owner order 2026-10-24, third pass ("there should be diamond
        # line feature between the tiles of search and custom scrips of
        # volume, have that line there"): the rule is the two tiles' own
        # division, and it is drawn from the scanner page's state in
        # MainActivity.setScannerOpen beside the tile's own line, so the
        # pair lives and dies together.
        rule = find_view(self.root, "@+id/rule_volume")
        self.assertIsNotNone(rule)
        self.assertEqual(rule.get("layout"), "@layout/qor_rule")
        tile = (MAIN.parent / "MainActivity.java").read_text(
            encoding="utf-8")
        self.assertIn("ruleVolume = findViewById(R.id.rule_volume);", tile)
        method0 = tile.index("private void setScannerOpen(")
        method1 = tile.index("paintNavSelection();", method0)
        method = tile[method0:method1]
        self.assertIn("if (ruleVolume != null) {", method)
        self.assertIn(
            "ruleVolume.setVisibility(open ? View.VISIBLE : View.GONE);",
            method)

    def test_the_settings_page_has_no_rule_of_its_own(self):
        self.assertIsNone(find_view(self.root, "@+id/rule_after_settings"))
        self.assertNotIn("@+id/rule_after_settings", self.layout)

    def test_each_page_brand_rule_sits_after_the_search_rule(self):
        # The header's own brand rule stands after the home page's last of
        # the owner's four diamond stations (the search and volume tiles
        # open the home path) and before the settings tile, so the search
        # page reads with the one diamond the header owns and the
        # settings page no longer carries a second one of its own.
        # v2.2.3: the first rule that follows the orb is the search
        # page's own rule_search now, so the scan starts after IT.
        brand = self.layout.index("layout=\"@layout/qor_rule\"",
                                  self.layout.index("@+id/tile_volume"))
        self.assertLess(self.layout.index("@+id/rule_search"),
                        self.layout.index("@+id/search_panel"))
        # v2.2.4: the owner's own diamond stands BETWEEN the search tile
        # and the custom scrips of volume tile, so the first rule after
        # the search panel is the volume pair's own rule_volume, and the
        # brand rule sits after the tile it follows.
        self.assertLess(self.layout.index("@+id/search_panel"),
                        self.layout.index("@+id/rule_volume"))
        self.assertLess(self.layout.index("@+id/rule_volume"),
                        self.layout.index("@+id/tile_volume"))
        self.assertLess(self.layout.index("@+id/tile_volume"), brand)
        self.assertLess(brand, self.layout.index("@+id/settings_panel"))

    def test_drivers_of_the_lost_rules_are_gone(self):
        self.assertNotIn("ruleBeforeSearch", self.main)
        self.assertNotIn("ruleAfterSettings", self.main)


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
        # v2.3.13 (owner order 2026-10-27: "make the same size for the
        # search box on the search page"): the box carries the one 32dp
        # field floor the dropdowns carry, so the air is symmetric at the
        # smaller number - 7dp above and below the line, 10dp on the
        # sides - and the floor is named on the box itself. v2.3.14
        # (owner order 2026-10-27: "increase the height of search box by
        # another 10%") grows the floor alone, 32 * 1.1 = 35dp, so the
        # box's even air is untouched and the growth is exactly 10%.
        # v2.3.15 (owner order 2026-10-27: "for search box you need to
        # increase the height of its box by another 25%") grows the
        # floor alone again, 35 * 1.25 = 43.75 floored to 43dp, the air
        # still untouched.
        self.assertEqual(        self.box.get(f"{ANDROID_NS}paddingTop"), "3dp")
        self.assertEqual(self.box.get(f"{ANDROID_NS}paddingBottom"), "3dp")
        self.assertEqual(self.box.get(f"{ANDROID_NS}paddingLeft"), "10dp")
        self.assertEqual(self.box.get(f"{ANDROID_NS}paddingRight"), "10dp")
        # v2.3.16 (owner order 2026-10-27, nineteenth pass: "with that
        # same exact setting, make the changes for theme box and search
        # box as well ... all these three boxes should have universal
        # height"): the box is BY the universal height now - one exact
        # 23dp measure, the air 3dp above and below the line, the same
        # numbers the two dropdown boxes carry - and no floor is named
        # again under the height it retired.
        self.assertEqual(self.box.get(f"{ANDROID_NS}layout_height"),
                         "23dp")
        self.assertIsNone(self.box.get(f"{ANDROID_NS}minHeight"))
        self.assertIn('android:layout_height="23dp"',
                      LAYOUT.read_text(encoding="utf-8"))

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
    """Owner order 2026-10-23 (v1.9.13): every heading is 10% SMALLER
    than its previous size, and the QUANT OF REHAN title grew 20% from
    its own size the same day. The heading change lands on the one style
    every tile heading shares (QorLabel), so the titles move by one
    decision rather than five copies that could drift apart. The body's
    13sp is NOT a heading and stays at its size, and the headings are
    still carried by the style (no raw textSize appears next to them).
    """

    def test_the_label_style_shrank_by_exactly_ten_percent(self):
        # Headings are 10% smaller than their previous size.
        styles = STYLES.read_text(encoding="utf-8")
        block = styles[styles.index('name="QorLabel"'):]
        block = block[:block.index("</style>")]
        self.assertIn('android:textSize">15.944049sp', block)

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
        block = block[:block.index("private void buildThemeMenu()")]
        for resource in ("greeting_morning", "greeting_afternoon"):
            self.assertIn(f"R.string.{resource}", block)

    def test_the_flat_minute_05_00_is_the_night_its_tail(self):
        """Owner order 2026-10-24, the windows: 05:01-12:00 morning,
        12:01-17:00 afternoon, 17:01-19:00 evening, 19:01-05:00 night.
        A flat minute belongs to the window that ENDS there, so 05:00
        itself is still the night's tail and the morning opens at 05:01
        - the one edge the hour-based branch would otherwise claim too
        early (12:00, 17:00 and 19:00 already sat in their tails)."""
        block = self.main[self.main.index("private void refreshGreeting()") + 10:]
        block = block[:block.index("private void buildThemeMenu()")]
        # The boundary minute is one branch all its own, before the
        # morning's hour window can claim its hour.
        self.assertLess(block.index("if (hour == 5 && minute == 0) {"),
                        block.index("hour >= 5 && hour <= 11"))
        tail = block[block.index("if (hour == 5 && minute == 0) {") + 10:]
        tail = tail[:tail.index("} else if")]
        self.assertIn("R.string.greeting_night", tail)
        # Every sentence the windows name is a resource, never a string
        # typed in Java (SO-9).
        for resource in ("greeting_morning", "greeting_afternoon",
                         "greeting_evening", "greeting_night"):
            self.assertIn(f"R.string.{resource}", block)

    def test_the_themes_tile_carries_five_looks(self):
        self.assertIn('name="label_themes">THEMES<', self.strings)
        self.assertIn('name="theme_purple">PURPLE &amp; YELLOW<', self.strings)
        self.assertIn('name="theme_black">BLACK &amp; WHITE<', self.strings)
        self.assertIn('name="theme_green">GREEN &amp; YELLOW<', self.strings)
        self.assertIn('name="theme_navy">NAVY BLUE &amp; WHITE<', self.strings)
        self.assertIn('name="theme_orange">ORANGE &amp; WHITE<', self.strings)
        spinner = element(self.layout, 'android:id="@+id/theme_spinner"')
        # v2.3.16: the closed box is its own one-line TextView at the
        # universal height, and its menu is the box's OWN inline list
        # (theme_menu) - no platform spinner, no popup window anywhere.
        self.assertIn("<TextView", spinner)
        self.assertIn('android:layout_height="23dp"', spinner)
        menu = element(self.layout, 'android:id="@+id/theme_menu"')
        self.assertIn("<LinearLayout", menu)
        self.assertIn('android:visibility="gone"', menu)
        self.assertIn("private void buildThemeMenu() {", self.main)
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

    def test_every_dropdown_carries_a_state_arrow(self):
        """Owner order 2026-10-23 (2.0.0): the pull-down, pull-up arrow.

        "when I tell you to have a drop down menu type feature, I want to
        have the arrow down and up as well to pull up the menu, right now
        there is none." Each of the two dropdowns (the themes look and
        the ONE CUSTOM SCRIPS OF VOL menu) carries its arrow beside it:
        DOWN while the menu is closed, UP while it is open, carrying one
        drawable whose rotate the Dropdown's own edges drive.
        """
        # v2.3.16 (owner order "another window pops up which is wrong, drop
        # down menu should appear from the same box"): the platform Spinner
        # is retired with its popup window entirely, so the arrow's open
        # and close edges are MainActivity's OWN menu state, never a window
        # subclass's two callbacks. The class and its file stand retired.
        self.assertFalse(
            (ROOT / "android" / "app" / "src" / "main" / "java"
             / "pk" / "quantofrehan" / "Dropdown.java").exists(),
            "Dropdown.java is retired with the platform popup window")
        self.assertNotIn("onDropdownOpenChange", self.main)
        self.assertNotIn("extends Spinner", self.main)
        for view_id in ("volume_split_arrow", "theme_arrow"):
            with self.subTest(arrow=view_id):
                arrow = element(self.layout, f'android:id="@+id/{view_id}"')
                # Beside the field, at its right edge, facing down.
                self.assertIn('android:layout_gravity="end|center_vertical"',
                              arrow)
                self.assertIn('android:src="@drawable/dropdown_arrow"', arrow)
        self.assertIn("(ImageView) findViewById(R.id.volume_split_arrow);",
                      self.main)
        self.assertIn("(ImageView) findViewById(R.id.theme_arrow);",
                      self.main)
        # One wiring law: the box and the arrow beside it are the two taps
        # into the menu's own open state, and one helper flips every
        # arrow UP while open, DOWN while closed.
        self.assertIn("wireDropdownArrows();", self.main)
        self.assertIn("private void wireDropdownArrows() {", self.main)
        self.assertIn("private void rotateDropdownArrow(ImageView arrow, "
                      "boolean open) {", self.main)
        self.assertIn(".rotation(open ? 180f : 0f)", self.main)
        self.assertIn("arrow.animate()", self.main)
        self.assertIn("showVolumeMenu(!volumeMenuOpen)", self.main)
        self.assertIn("showThemeMenu(!themeMenuOpen)", self.main)

    def test_the_volume_tile_is_the_scanner_page(self):
        """Owner order 2026-10-24 ("move the custom scrips of volume in
        the scanner page"): the tile left the search page for its own
        page, opened by the nav icon beside home. The tile itself is the
        page's content: it lives and dies with `scannerOpen` in
        MainActivity the way the panels do, and nothing else about the
        v2.2.1 tile changed."""
        self.assertIn('name="label_volume">CUSTOM SCRIPS OF VOL.<',
                      self.strings)
        # v2.1.0: the two dropdowns are named the owner's own way, and the
        # ranking follows the words (see the ranking test below).
        # v2.2.1: the captions are the ONE dropdown's two menu options now,
        # in the owner's exact wording of the same day.
        # v2.1.0: the two dropdowns are named the owner's own way, and the
        # ranking follows the words (see the ranking test below).
        # v2.2.1: the captions are the ONE dropdown's two menu options now,
        # in the owner's exact wording of the same day.
        # v2.2.5: the scanner's own entry heads the menu (PRICES RISING
        # FAST), the B/S ranking second; the strings order is the pin.
        self.assertIn(
            'name="volume_speed_caption">PRICES RISING FAST<',
            self.strings)
        self.assertIn(
            'name="volume_split_caption">MORE BUYERS &amp; LESS SELLERS<',
            self.strings)
        self.assertLess(self.strings.index('"volume_speed_caption"'),
                        self.strings.index('"volume_split_caption"'))
        self.assertLess(self.layout.index("@+id/tile_volume"),
                        self.layout.index("@+id/tile_market"))
        # v2.2.1: ONE dropdown ("make only one drop down menu"), and BOTH
        # entries live in ITS menu; the second dropdown is deleted with
        # its caption spinner, arrow and prompt.
        self.assertNotIn("volume_speed_spinner", self.layout)
        self.assertNotIn("volume_speed_arrow", self.layout)
        self.assertNotIn("volume_split_caption\"", self.layout)
        self.assertNotIn("volume_speed_caption\"", self.layout)
        for resource in ("volume_split_prompt", "volume_speed_prompt"):
            self.assertNotIn(f'name="{resource}"', self.strings)
        spinner = element(self.layout, 'android:id="@+id/volume_split_spinner"')
        # v2.3.16: the closed box is its own one-line TextView at the
        # universal height and the menu is the box's OWN inline list
        # (volume_split_menu) standing directly below it - no platform
        # spinner, no popup window anywhere.
        self.assertIn("<TextView", spinner)
        self.assertIn('android:layout_height="23dp"', spinner)
        menu = element(self.layout, 'android:id="@+id/volume_split_menu"')
        self.assertIn("<LinearLayout", menu)
        self.assertIn('android:visibility="gone"', menu)
        self.assertIn("private void buildVolumeMenu() {", self.main)
        # The reveal: the three scrips of the chosen menu, hidden until he
        # picks one.
        reveal = element(self.layout, 'android:id="@+id/volume_reveal"')
        self.assertIn('android:visibility="gone"', reveal)
        # The single dropdown is still ranked from the map the search
        # already refreshes, so it costs no request of its own.
        self.assertIn("Watcher.quotes()", self.main)
        self.assertIn("rankedSplitSymbols(", self.main)
        self.assertIn("rankedSpeedSymbols(", self.main)
        self.assertIn("private void paintVolumeReveal()", self.main)
        # v2.3.11: row 0 is the SELECT CUSTOM SCRIPS placeholder, so the
        # riser ranking moved to row 1 and the B/S split to row 2.
        self.assertIn("volumeSplitChoice == 2", self.main)
        self.assertIn("volumeSplitChoice < 1", self.main)
        # The tile is the scanner page's own content now: one boolean owns
        # its visibility, in the one scanner toggle, and the search toggle
        # no longer touches it.
        self.assertEqual(self.main.count("tileVolume.setVisibility"), 1,
                         "the tile's visibility is one call, in one toggle")
        block = self.main[self.main.index(
            "private void setScannerOpen(boolean open) {") + 100:]
        block = block[:block.index("The status light's pulse")]
        self.assertIn("scannerOpen = open;", block)
        self.assertIn("tileVolume.setVisibility(open ? View.VISIBLE : View.GONE);",
                      block)
        self.assertIn("renderVolumeSpinners();", block)
        # And the pricing tick covers the scanner page alike: one read, one
        # rank pass per tick, on either page.
        self.assertEqual(self.main.count("if (searchOpen || scannerOpen) {"),
                         2, "the tick and its paint, for both pages")

    def test_the_dropdowns_rank_their_own_names(self):
        """v2.1.0: the names are the ranking. "More buyers & sellers" is
        the busiest scrips by the relay's own combined B/S activity.
        v2.2.5 re-scopes the speed menu to the owner's own law ("don't
        show me the stocks that are already capped, instead show those
        stocks whose prices are increasing really fast ... that is the
        point of the scanner"): rising only, capped out, biggest move
        first, at most three rows. Null data is skipped, never ranked
        as zero (SO-3)."""
        split = self.main[self.main.index(
            "private List<String> rankedSplitSymbols"):]
        split = split[:split.index("private List<String> rankedSpeedSymbols")]
        speed = self.main[self.main.index(
            "private List<String> rankedSpeedSymbols"):]
        # v2.3.7: the row builder is the reveal; the slice ends at it.
        speed = speed[:speed.index(
            "private SpannableStringBuilder volumeRevealText(")]
        # Split: complete ranges only. v2.3.9 (owner order 2026-10-26,
        # "look at the current data on the drop down", with MACFL's
        # B=212k against S=9.1M at the top of the menu): the label names
        # the dominance, so a scrip whose sellers outweigh its buyers is
        # not a row at all, and the rows rank by the buyers' own SURPLUS
        # (buy minus sell) - never back to the buy+sell activity that
        # put a sellers-flooded scrip first.
        self.assertIn("quote.buy != null && quote.sell != null", split)
        self.assertIn("return q.buy <= q.sell;", split)
        self.assertIn("Long.compare(qb.buy - qb.sell, qa.buy - qa.sell);", split)
        self.assertNotIn("byLowestSell", split)
        self.assertNotIn("qa.buy + qa.sell", split)
        # Speed (v2.2.5): a move earns the row, RISING moves only; a
        # scrip at or past the cap mark is out; no absolute-value
        # ranking can return (a falling price is not a rising one).
        self.assertIn("move == null", speed)
        self.assertIn("move <= 0d", speed)
        self.assertIn("CAPPED_MOVE_MARK", speed)
        self.assertIn("private static final double CAPPED_MOVE_MARK", self.main)
        self.assertIn("Double.compare(moveB, moveA)", speed)
        self.assertNotIn("Math.abs(moveB)", speed)
        self.assertNotIn("Math.abs(moveA)", speed)
        # The riser rows carry the owner's own six numbers.
        # Owner order 2026-10-26 ("there is no consistency, no = sign,
        # no , sign, no green and red colors"): the volume reveal prints
        # the leaders card's own sentence, both menus, one shape. The
        # riser's "B %,d  S %,d  T %,d" and the ranking's bare quote
        # lines are both retired: one spannable builder serves them.
        self.assertIn("private SpannableStringBuilder volumeRevealText(", self.main)
        self.assertNotIn("quoteLinesRiser", self.main)
        self.assertNotIn("List<String> quoteLines(", self.main)
        block = self.main[self.main.index(
            "private SpannableStringBuilder volumeRevealText(") :]
        block = block[:block.index("/** One coloured quantity")]
        # The leaders card's own bracket, comma after B, ampersand before T.
        self.assertEqual(block.count("\\u00A0(B="), 1)
        self.assertEqual(block.count(",\\u00A0S="), 1)
        self.assertEqual(block.count("\\u00A0&\\u00A0T="), 1)
        # The buy digits in green and the sell digits in red, the money
        # line with the coloured arrow and the glyph face.
        self.assertIn("colorQuantity(sb, quote.buy, R.color.green)", block)
        self.assertIn("colorQuantity(sb, quote.sell, R.color.red)", block)
        self.assertIn("TypefaceSpan(ARROW_FACE)", block)
        self.assertIn("R.color.green : R.color.red", block)
        self.assertIn("private void colorQuantity(SpannableStringBuilder sb, long value, int res)", self.main)
        reveal = self.main[self.main.index("private void paintVolumeReveal"):]
        reveal = reveal[:reveal.index("/** One coloured quantity")]
        self.assertIn("volumeRevealText(quotes, ranked)", reveal)
        self.assertIn("volumeReveal.setText(styled)", reveal)

    def test_the_version_line_names_the_manifest(self):
        version = element(self.layout, 'android:id="@+id/app_version"')
        self.assertIn('style="@style/QorCaption"', version)
        # Owner order 2026-10-24, third pass: the wording is HIS OWN
        # ("change the wording like this APP VERSION IS (VERSION NUMBER)").
        # v2.2.6: the gap was fused AGAIN on the sent-back v2.2.5 build
        # ("it's like this right now 'APP VERSION IS2.5.5'") because
        # aapt2 trims UNQUOTED leading/trailing whitespace of a string
        # resource at build time; the prefix literal is QUOTED now, and
        # the quoted gap is its own pin, so the gap can never be lost
        # again.
        prefix_block = self.strings[self.strings.index(
            'name="app_version_prefix"'):]
        prefix_block = prefix_block[:prefix_block.index("</string>")]
        self.assertIn('name="app_version_prefix">"APP VERSION IS "',
                      self.strings)
        self.assertTrue(prefix_block.rstrip("\r\n").endswith('IS "'),
                        "the prefix pads its own space: it ends in 'IS '")
        # The number is the manifest's own versionName, the same one the
        # build prints: the page and the APK cannot disagree.
        self.assertIn("getPackageInfo(getPackageName(), 0).versionName;",
                      self.main)
        # v2.1.0: it is the settings page's own footer - visible while that
        # menu is open, gone on home and search, set from the page truth
        # inside paintNavSelection, the one place the page state repaints.
        self.assertIn("settingsOpen ? View.VISIBLE : View.GONE);", self.main)
        self.assertGreater(
            self.main.index("private void paintNavSelection()"), 0)
        paint_end = self.main.index("private void refreshGreeting()")
        self.assertIn("appVersion != null",
                      self.main[self.main.index("private void paintNavSelection()"):paint_end])

    def test_the_version_line_sits_below_the_themes_tiles_closing_diamond(self):
        # Owner order 2026-10-24, third pass ("move app version position
        # just below the diamond line feature of the bottom part of
        # themes tile"): the line left the station above the pinned menu
        # bar for the THEMES holder, after the tile's closing rule, so
        # the number sits under the bracket it closes.
        root = layout_root()
        version = find_view(root, "@+id/app_version")
        self.assertIsNotNone(version)
        holder = parent_of(root, version)
        assert holder is not None
        self.assertEqual(holder.get(f"{ANDROID_NS}id"), "@+id/themes_holder")
        # Inside the holder: the tile, its TWO diamond includes, then the
        # version line as the holder's own last child - under the bottom
        # diamond, the station the owner named.
        children = list(holder)
        self.assertEqual(children[-1], version)
        includes = [n for n in children if n.get("layout") == "@layout/qor_rule"]
        self.assertEqual(len(includes), 2, "the tile's open and close diamonds")
        self.assertLess(children.index(includes[-1]), children.index(version))



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
    """Owner orders, stacked: 2026-10-22 gave the typing matches their
    light and made it a fact of the QUERY; 2026-10-26 ("it should be
    highlighted in the theme's own colors") moved the light to the
    theme's own family, and the SAME owner hour ("I can't even tell the
    highlighted colour, at least make it look highlighted") sent it
    back: the theme's panel ink over the field's dark is a step the eye
    cannot see, and the owner wants a highlight HE CAN SEE. The light is
    the brand gold again - the family the clock, the headings and the
    nav ring already wear.

    A prefix match wears the translucent gold PRESS plate, and the exact
    match closes with the brighter gold MATCH plate and a hairline in
    gold_bright. The matched symbol keeps the body's ink; the green/red
    price tail is the quote's own and survives untouched.
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
        # The brand gold, back on the matched rows (owner order above):
        # the plate carries the family, and the gold hairline only on the
        # exact match.
        self.assertIn("row.setBackground(highlightPlate(exactMatch));", block)
        self.assertIn("private GradientDrawable highlightPlate(boolean exact)", block)
        self.assertIn("row.setBackground(null);", block)

    def test_the_highlight_plates_are_the_brand_gold_again(self):
        main = MAIN.read_text(encoding="utf-8")
        start = main.index("private GradientDrawable highlightPlate(")
        block = main[start:main.index("/** One symbol's B, S and T", start)]
        # v2.3.9 (owner order 2026-10-26, twelfth pass: "HUBC is still
        # getting highlighted in orange in purple theme"): the highlight
        # is a LIFT of the THEME'S OWN panel ink, never an invented wash.
        # The v2.3.8 gold plates were theme-blind and read orange over
        # the violet field. v2.3.13 (owner order 2026-10-27: "on the
        # purple theme, the search box is highlighting the search results
        # in white colour, make them match the theme's color") has the
        # WHITE part of that lift as the culprit - the purple panel is
        # near-black, so the 42% exact lift read as a white rectangle -
        # and the lift drops to 26% exact / 14% prefix, which keeps every
        # plate inside its own theme's colour family.
        self.assertIn("lighten(getColor(panelInkFor(themeIndex)),", block)
        self.assertIn("exact ? 0.26f : 0.14f", block)
        self.assertNotIn("0.42f", block)
        self.assertIn("if (exact) {", block)
        self.assertIn(
            "plate.setStroke(1, getColor(accentInkFor(themeIndex)));", block)
        # The lift is panel + lift * white, written by hand because the
        # app compiles against android.jar alone.
        self.assertIn(
            "+ (255 - ((ink >> 16) & 0xFF)) * lift", block)
        self.assertIn(
            "+ (255 - ((ink >> 8) & 0xFF)) * lift", block)
        self.assertIn(
            "+ (255 - (ink & 0xFF)) * lift", block)
        # The theme's own inks are named per theme, through the same
        # panel ink every tile of that theme wears.
        self.assertIn("case 1: return R.color.theme_black_panel;", block)
        self.assertIn("case 2: return R.color.theme_green_panel;", block)
        self.assertIn("case 3: return R.color.theme_navy_panel;", block)
        self.assertIn("case 4: return R.color.theme_orange_panel;", block)
        self.assertIn("default: return R.color.bg_panel;", block)
        self.assertIn("case 1: return R.color.theme_black_accent;", block)
        self.assertIn("case 2: return R.color.theme_green_accent;", block)
        self.assertIn("case 3: return R.color.theme_navy_accent;", block)
        self.assertIn("case 4: return R.color.theme_orange_accent;", block)
        self.assertIn("default: return R.color.gold;", block)
        colors = COLORS.read_text(encoding="utf-8")
        for name in ("theme_black_panel", "theme_green_panel",
                     "theme_navy_panel", "theme_orange_panel",
                     "theme_black_accent", "theme_green_accent",
                     "theme_navy_accent", "theme_orange_accent"):
            self.assertIn(f'name="{name}"', colors)
        for name in ("gold_press", "gold_match", "gold_bright"):
            self.assertIn(f'name="{name}"', colors)

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
    """Owner orders, stacked: the owner sent the reference look he wanted
    (a living mover under the brand) and the first HUD pass's movers (the
    diag line's words and the sweeping beam) are retired in favour of the
    ONE mover that earns the claim: the ThinkingOrb under the brand, on
    the SEARCH and SETTINGS pages too, running ONLY while the console is
    resumed. Owner order 2026-10-23 (fourth pass, v1.9.13), after the
    owner sent the v1.9.9 screenshot back: the feature is the reference's
    constellation once more, MORE lines revolving around the core than
    any pass before it, and the white orb at the centre is a sun-looking
    ball of the SAME size, a lit 3D sphere that burns without pause. The
    classic frame's tiles, rules and copy stand untouched beneath it.
    Owner order 2026-10-23 (seventh pass, v2.2.0), on the v2.1.0
    screenshots the owner sent back: the feature is the v1.8.9 LIVING
    PARTICLE CLOUD again, the look he first approved, and the cloud's
    centre is the sun ("I want the center as the sun"), so the organism
    circles a star.
    """

    def test_the_orb_sits_where_the_beam_lay(self):
        layout = LAYOUT.read_text(encoding="utf-8")
        self.assertIn("<pk.quantofrehan.ThinkingOrb", layout)
        self.assertIn("@+id/thinking_orb", layout)
        # Under the brand, ahead of both menu panels: the beam's former
        # station. The menu page's own rule the v1.9.13 pass removed no
        # longer divides the orb from the panel; the single brand rule
        # under the header does.
        self.assertLess(layout.index("@+id/thinking_orb"),
                        layout.index("@+id/search_panel"))
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
        # Its station precedes both panels, which is the exact spot it
        # holds on the front page; the menu pages' own rules are the ones
        # the v1.9.13 pass removed, so the single brand rule under the
        # header is the orb's only division on every page.
        self.assertLess(layout.index("@+id/thinking_orb"),
                        layout.index("@+id/search_panel"))
        self.assertLess(layout.index("@+id/thinking_orb"),
                        layout.index("@+id/settings_panel"))
        # One orb, not a copy inside a panel: the custom view appears as a
        # tag exactly once in the layout.
        self.assertEqual(layout.count("pk.quantofrehan.ThinkingOrb"), 2)

    def test_the_cloud_is_the_v189_organism_around_the_sun(self):
        orb = (MAIN.parent / "ThinkingOrb.java").read_text(
            encoding="utf-8")
        """Owner order 2026-10-23 (seventh pass, v2.2.0): the feature is
        the v1.8.9 LIVING PARTICLE CLOUD the owner first approved - NODES
        joined by fine links, turning rigidly in yaw with a breathing
        pitch and projected in perspective, every node breathing radially
        on its own phase. The radial burst of v2.1.0 and the rings of
        v1.9.13/v1.9.14 are retired, and the cloud circles its own SUN.
        v2.3.7 retuned the gather to an even shell and the SAME owner hour
        sent it back ("you ruined the animating feature, the LINES are
        looking absolute horseshit, change them back"): v2.3.8 restores
        the v1.8.9 CLUSTER law as it was. v2.3.15 keeps the gather and
        walks its FIVE ANCHORS on the even golden-angle path instead of
        five random spots, because the owner read the build on the
        phone and the random anchors were the tangled lobe he sent back
        (see the v2.3.15 tests).
    """
        # Populations are named constants, so the count is one decision.
        # v2.3.8 restores CLUSTERS with the gather it owned.
        self.assertIn("private static final int NODES = 105;", orb)
        self.assertIn("MOTION_SCALE = 1.3f", orb)
        self.assertIn("private static final int NODE_STRIDE = 5;", orb)
        # The retired machinery may not come back.
        for retired in ("RAYS", "RAY_NODES", "RAY_FRACTION",
                        "spokeEdgeCount", "drawBurst", "drawRings",
                        "RING_NODES", "RING_FACTOR", "RING_SPEED",
                        "RING_TILT", "buildCloud", "restRing"):
            self.assertNotIn(retired, orb)
        # The cloud is built once per size, never on the frame path.
        # v2.2.4 (owner order 2026-10-24, third pass): the tangle is out
        # - a link is a SHORT filament inside its own neighbourhood and
        # never a chord across the ball, the fade steepens at the ends,
        # and the stroke narrows as a link recedes. The v2.2.1 +30% cap
        # and the fire ink stand; the filaments simply no longer cross.
        self.assertIn("private void buildGeometry() {", orb)
        self.assertIn("float linkAt = 0.42f;", orb)
        # v2.3.8 (owner order 2026-10-26, tenth pass, on the v2.3.7
        # screenshots: "you ruined the animating feature, the LINES are
        # looking absolute horseshit, change them back"): the even shell
        # is RETIRED with the pass that built it, and the v1.8.9 CLUSTER
        # law is back AS IT WAS - seeded anchors between the sun and the
        # shell (never Math.random; the build is one decision), a jitter
        # pulled and re-normalised against each anchor, the four- node
        # break-outs, the escapees that keep the rim ragged.
        self.assertIn("private static final int CLUSTERS = 5;", orb)
        self.assertIn("anchorX[c] = s * (float) Math.cos(theta) * 0.55f;", orb)
        self.assertIn("float pulled = (n % 4 == 0) ? 1.05f : 0.78f;", orb)
        self.assertIn("if (n % 9 == 0) {", orb)
        self.assertIn("long seed = 20261022L;", orb)
        # The even walk's own machinery may not come back.
        self.assertNotIn("radiusSeed", orb)
        self.assertNotIn("float theta = 2.39996f * n;", orb)
        # v2.3.3: the fade bottoms out above zero, because a link at the cap
        # painted at alpha zero is the invisible thread that left its nodes
        # looking like the owner's "independent dots without any lines".
        self.assertIn("return 1f - 0.80f * clamp((dist - 0.14f) / 0.28f, "
                      "0f, 1f);", orb)
        # And no node may sit without a filament: every orphan joins its
        # nearest neighbour at build time.
        self.assertIn("boolean[] joined = new boolean[NODES];", orb)
        self.assertIn("linkDist[linkCount] = nearestDist;", orb)
        # v2.3.1: the stroke's own breath rides on top of the depth's
        # narrowing, so a filament swells as well as lengthens.
        self.assertIn("linkPaint.setStrokeWidth(linkWidth * (0.8f + 0.45f * "
                      "toward)", orb)
        self.assertIn("* widthBreath);", orb)
        # The organism turns rigidly in yaw with a breathing pitch, and
        # the perspective divide projects the far side smaller and dimmer.
        self.assertIn("float yaw = seconds * 0.22f * MOTION_SCALE;", orb)
        self.assertIn("float pitch = 0.16f * (float) Math.sin(", orb)
        self.assertIn("float persp = distance / (distance - rz * orbRadius);",
                      orb)
        # The links brighten as their ends come forward; the nodes breathe
        # on their own phase.
        self.assertIn("float toward = clamp((midway - 1f) / 0.6f, 0f, 1f)",
                      orb)
        self.assertIn("float toward = clamp((depth[n] - 1f) / 0.6f, 0f, 1f);",
                      orb)
        self.assertIn("int o = n * NODE_STRIDE;", orb)
        # The cloud draws FIRST, the sun after it: the organism reads as
        # circling its star. v2.2.3: the call order in drawScene is the
        # pin - the photo sun's own build sits between these methods, so
        # the definition order is no longer the draw order.
        self.assertIn("drawCloud(canvas, seconds, wake);", orb)
        self.assertIn("drawSun(canvas, seconds, wake);", orb)
        scene_index = orb.index("private void drawScene(")
        scene = orb[scene_index:scene_index + 700]
        self.assertIn("drawCloud(canvas, seconds, wake);", scene)
        self.assertLess(scene.index("drawCloud(canvas, seconds, wake);"),
                        scene.index("drawSun(canvas, seconds, wake);"))
        # The wake ramp is the v1.8.9 number, so the organism grows out of
        # the dark instead of popping in.
        self.assertIn("WAKE_SECONDS = 4f", orb)
        # The one sleep belongs to the sun's own render thread (v2.3.8),
        # pacing its 60ms cadence on its own back; with that single pinned
        # call removed, NO other sleep may appear anywhere in the file
        # (the HUD loop stays the view's own paced invalidate), and no
        # animator may animate the organism.
        self.assertNotIn("Thread.sleep",
                         orb.replace("Thread.sleep(wait);", ""))
        self.assertNotIn("ValueAnimator", orb)

    def test_the_sun_is_his_photograph_on_a_revolving_sphere(self):
        orb = (MAIN.parent / "ThinkingOrb.java").read_text(
            encoding="utf-8")
        """Owner order 2026-10-25, sixth and seventh passes: "you made the
        sun transparent, SUN is a solid entity, make it solid", "the very
        left one is my own uploaded photo, and I would really love to have
        that same exact render, and then you can make it revolve just like
        the Earth does", then "there is this one outline on the SUN and even
        the render of SUN looks really cheap, make it look very realistic".

        The surface is the owner's own picture (drawable-nodpi/sun.jpg), its
        fire crop wrapped onto the sphere on a triangle wrap, and v2.3.5
        takes his RIM and his CORONA from the same picture: one ink and one
        height per screen angle, one alpha per angle and radius. Nothing in
        this file is a function of the screen radius any more, because a
        function of the screen radius is a circle by construction. The
        sphere's poles, which converge by geometry, dissolve into their own
        map row so the ball has no woven cap.
        """
        self.assertIn("private void buildSunSphere() {", orb)
        self.assertIn("private void buildSunMap(int[] pixels, int w, int h) {",
                      orb)
        self.assertIn("private void buildSunRing(int[] pixels, int w, int h) {",
                      orb)
        self.assertIn("private void sharpenMap() {", orb)
        self.assertIn("private void renderSunBall(float phi) {", orb)
        self.assertIn("private int sampleMap(float u, float v) {", orb)
        # His picture is the source, decoded from the asset.
        self.assertIn("BitmapFactory.decodeResource(getResources(),", orb)
        self.assertIn("R.drawable.sun", orb)
        self.assertIn("private static int samplePhoto(int[] pixels, int w, "
                      "int h,", orb)
        self.assertIn("sunMap[row * SUN_MAP_W + col] =", orb)
        self.assertIn("mapRowInk[row] = 0xFF000000", orb)
        self.assertIn("gradeInk(samplePhoto(pixels, w, h, px, py))", orb)
        # The drawn ring is gone, with the table and the blend that made it.
        for retired in ("SUN_CROWN", "sunCrown", "crownInk", "sphereRim",
                        "sphereCrown", "SUN_HALO", "buildSunHalo",
                        "SUN_RAMP", "SUN_STOP", "sunHeat", "sampleSun",
                        "mirrorRow", "SUN_CHURN_TURN", "sphereGain",
                        "buildSunHeat", "buildSunSurface", "sampleDetail",
                        "rampMix", "fbm3", "noise3", "hash3",
                        # v2.3.5: the radius brightening, the white-hot
                        # band and the exponential glow were the outline he
                        # kept sending back. His own rim and corona replace
                        # all three.
                        "SUN_LIMB", "SUN_HOT", "SUN_GLOW", "sunGlow",
                        "glowInk"):
            with self.subTest(retired=retired):
                self.assertNotIn(retired, orb)
        # One bitmap holds the ball and its glow: the disc is 96 of its 128
        # pixels, which is what removes every possible seam.
        self.assertIn("SUN_RENDER = 256", orb)
        self.assertIn("SUN_BALL = 96f", orb)
        self.assertIn("SUN_REACH = SUN_RENDER / 2f / SUN_BALL", orb)
        self.assertIn("float r = ballR * (SUN_RENDER / 2f) / SUN_BALL;", orb)
        self.assertIn("sunBallPixels[k] = (cover << 24)", orb)
        # His numbers: the disc at 0.86 of the picture's half side, the crop
        # at 0.62 of the disc, the limb curve and the white-hot edge.
        self.assertIn("SUN_MAP_W = 512", orb)
        self.assertIn("SUN_MAP_H = 256", orb)
        self.assertIn("SUN_BALL_EDGE = 0.86f", orb)
        self.assertIn("SUN_CROP = 0.75f", orb)
        self.assertIn("SUN_BOIL_ROW = 5f", orb)
        self.assertIn("SUN_BOIL_MIX = 0.07f", orb)
        self.assertIn("SUN_SHARPEN = 1.05f", orb)
        self.assertIn("SUN_CONTRAST = 1.30f", orb)
        # His rim: one ink and one height per screen angle, both from the
        # picture, both turning with the surface.
        self.assertIn("SUN_RING_IN = 0.87f", orb)
        self.assertIn("SUN_RING = 1.55f", orb)
        self.assertIn("SUN_RING_BASE = 0.30f", orb)
        self.assertIn("SUN_RING_FLAME = 1.35f", orb)
        self.assertIn("float ring = smoothstep(SUN_RING_IN, 0.995f, rn)", orb)
        self.assertIn("ringFlame[ang]", orb)
        self.assertIn("ringInk[ang]", orb)
        # His rim: alpha and ink per angle, baked from his picture.
        self.assertIn("FLAME_STEPS = 512", orb)
        # The corona is restored THIN (v2.3.11 owner order: the entire
        # feature removed and readded from v2.3.8, whose sun he named
        # good; the eighth pass's 1.75 bulge was the thick orange
        # outline, so the gain stands at the v2.3.6 blend).
        self.assertIn("CORONA_STEPS = 28", orb)
        self.assertIn("CORONA_REACH = 0.20f", orb)
        self.assertIn("CORONA_GAIN = 1.45f", orb)
        self.assertIn("CORONA_SMOOTH = 19", orb)
        self.assertIn("buildSunCorona(photo, photoW, photoH);", orb)
        self.assertIn("coronaInk[r * FLAME_STEPS + i] = ((alpha / n) << 24)",
                      orb)
        self.assertIn("sunBallPixels[k] = 0;", orb)
        # The pole dissolve.
        self.assertIn("SUN_POLE_IN = 0.64f", orb)
        self.assertIn("SUN_POLE_MIX = 0.92f", orb)
        self.assertIn("int row = mapRowInk[clampInt((int) v, 0, SUN_MAP_H - 1)];",
                      orb)
        # The revolve: one shared longitude shift, the owner's 10% cut
        # kept, his 2026-10-26 order a further 15%, and his two
        # 2026-10-27 orders a further 10% each - each cut on the rate
        # itself, the place the earlier cuts sit:
        # 0.35 * 0.85 * 0.9 * 0.9 = 0.240975 rad/s.
        self.assertIn("SUN_SPIN_RATE = 0.240975f", orb)
        self.assertIn("SUN_SLOWDOWN = 0.9f", orb)
        self.assertIn("SUN_AXIS_TILT = 10f", orb)
        # v2.3.8 (owner order 2026-10-26: "the SUN is still
        # flickering/phasing"): the revolve carries the render thread's
        # OWN elapsed time, scaled by HIS spin law, so the turn never
        # jumps behind a stale phi line and never stop.
        self.assertIn(
            "* SUN_SPIN_RATE * MOTION_SCALE * SUN_SLOWDOWN;", orb)
        self.assertIn("renderSunBall(phi);", orb)
        self.assertIn("float spin = phi / SUN_LAP * SUN_MAP_W;", orb)
        self.assertIn("sampleMap(sphereU[k] + spin, sphereV[k])", orb)
        # The thread (v2.3.8): its own cadence, double buffered, parked
        # when the market stops, warm before the first paint. v2.3.11
        # (owner order 2026-10-26, fourteenth pass: "remove the entire
        # feature then add it again, and fix it"): the handover is the
        # v2.3.8 HARD SWAP again - v2.3.9's half-alpha blend was the
        # ghosting he kept seeing - and the v2.3.10 commit gate stands:
        # the render thread signs its bitmap and the swap runs under one
        # monitor, so a torn half-pass can never become the picture.
        self.assertIn("long SUN_CADENCE_MS = 60L", orb)
        self.assertIn("sunThread.setPriority(Thread.NORM_PRIORITY - 1);", orb)
        self.assertIn("sunThread.setDaemon(true);", orb)
        self.assertIn("sunThread.start();", orb)
        self.assertIn("Thread.sleep(wait);", orb)
        self.assertIn("sunBallBack.setPixels", orb)
        self.assertIn("p.post(this::publishSun);", orb)
        self.assertIn("Bitmap tmp = sunBall;", orb)
        self.assertIn("sunBall = sunBallBack;", orb)
        self.assertIn("sunBallBack = tmp;", orb)
        self.assertIn("private final Object sunGate = new Object();", orb)
        self.assertEqual(orb.count("synchronized (sunGate) {"), 2,
                         "one gate at the commit, one at the handover")
        ball = orb[orb.index("private void renderSunBall("):
                   orb.index("private void bloomSun()") + 2000]
        self.assertIn("synchronized (sunGate) {", ball)
        self.assertIn("renderSunBall(phi);", orb)
        self.assertIn("startSunLoop();", orb)
        self.assertIn("stopSunLoop();", orb)
        self.assertIn("warmSunOnce();", orb)
        self.assertIn("onDetachedFromWindow();", orb)
        # The triangle wrap: linear across the visible half turn, mirrored
        # behind it, so a quarter turn is a quarter turn.
        self.assertIn("float swing = (float) Math.asin(Math.sin(longitude));",
                      orb)
        self.assertIn("float px = midX + swing * (2f / (float) Math.PI) "
                      "* crop;", orb)
        # SOLID: every pixel inside the disc is opaque (owner order: "SUN is
        # a solid entity").
        self.assertIn("sphereCover[k] = 255;", orb)
        self.assertIn("sunScratch[k] = 0xFF000000", orb)
        # The rim comes from his picture, not from a radius.
        self.assertIn("* (SUN_RING_BASE + SUN_RING_FLAME * ringFlame[ang])",
                      orb)
        # The frame draws it under the standing tilt.
        method0 = orb.index("private void drawSun(")
        method1 = orb.index("private void renderSunBall(", method0)
        method = orb[method0:method1]
        self.assertIn("canvas.save();", method)
        tilt = method.index("canvas.rotate(SUN_AXIS_TILT, cx, cy);")
        self.assertLess(method.index("canvas.save();"), tilt)
        self.assertGreater(method.index("canvas.restore();"), tilt)
        self.assertIn("canvas.drawBitmap(sunBall, null, ballDst, sunPaint);",
                      method)
        self.assertIn("ballR = orbRadius * 0.26f", orb)

    def test_v2_2_5_the_ball_is_steady_and_the_lines_breathe(self):
        orb = (MAIN.parent / "ThinkingOrb.java").read_text(
            encoding="utf-8")
        """v2.2.5, on the sent-back v2.2.4 build: "the SUN is not
        revolving and it's just flickering now". The flicker WAS the
        fire's alpha pumps; v2.3.0 deleted the fire that pumped at all, so
        the ball's ink is the wake and nothing else. The breathe is the
        NLINES' own law: "the lines will get a bit short and then will get
        long" - one breath period on each filament, around its own
        midpoint, no two in step.
        """
        # The ball's ink is the wake alone: no fire term can pump it.
        self.assertIn("sunPaint.setAlpha((int) (255f * wake));", orb)
        self.assertNotIn("sunFlame", orb)
        self.assertNotIn("0.82f + 0.18f * (float) Math.sin(", orb)
        self.assertNotIn("0.72f + 0.28f * (float) Math.sin(", orb)
        # The breathe: a phase per link (golden-angle step, so no two
        # lines pulse in step), one breath period, and the swing NEVER
        # detaches the filament from the nodes it joins.
        self.assertIn("private final float[] linkPhase = new float[linkBudget()];",
                      orb)
        self.assertIn("linkPhase[linkCount] = 2.39996f * linkCount;", orb)
        self.assertIn("seconds * 0.55f * MOTION_SCALE + linkPhase[l]", orb)
        # v2.3.3 (owner order 2026-10-25: "the outside revolving lines are
        # still not breathing") tripled the swing. v2.3.7 (owner order
        # 2026-10-26: "the SUN and the LINES every thing is flickering,
        # make it fucking stop") cut it to one fifth, and the SAME owner
        # hour sent that back ("you ruined the animating feature"). The
        # v2.3.8 tenth pass is the final law: the v2.3.3 swing is back
        # over the LENGTH, and the INK breathes with the width on the one
        # shared wave - its own factor (0.945f + 0.17f * widthBreath) -
        # so a filament's alpha rides a narrow band above its trough and
        # can never hollow out into the 0.1x..1.4x flashing he called
        # flicker, however deep its side of the ball.
        self.assertIn("float breathWave = (float) Math.sin(", orb)
        self.assertIn("float widthBreath = 1f + 0.30f * breathWave;", orb)
        # v2.3.14 (owner order 2026-10-27: "the moving big lines that are
        # revolving around the sun are coming out from their dots. Make
        # it not exceed those dots") made the length swing inward-only:
        # the old 0.70..1.30 factor is gone, and the 0.70..1.00 law
        # keeps the v2.3.3-sized swing without ever hanging an end past
        # the dot it is drawn from.
        self.assertIn("float breath = 1f - 0.15f * (1f - breathWave);", orb)
        self.assertIn("* (0.945f + 0.17f * widthBreath));", orb)
        self.assertIn("* widthBreath);", orb)
        self.assertIn("float midX = (ax + bx) / 2f;", orb)
        self.assertIn("float midY = (ay + by) / 2f;", orb)
        self.assertIn("midX + (ax - midX) * breath,", orb)

    def test_v2_2_5_the_theme_paints_the_inputs(self):
        """v2.2.5 (owner order 2026-10-24, fourth pass, "when I change the
        theme the theme changes but the drop down and the search boxes
        are still purple, make them match the app's current theme"). One
        place (applyThemeToInputs) paints the closed dropdown rows, their
        popup plates and the search box from the theme's own plate, at
        selection time AND on start. The theme spinner itself is exempt:
        as the owner said on 2026-10-24, it already sits inside the plate
        it is choosing."""
        main = MAIN.read_text(encoding="utf-8")
        # One place, all three paints.
        self.assertIn("private void applyThemeToInputs(int index) {", main)
        # v2.3.16: the popup plates moved onto the two inline menus, and
        # the closed boxes paint their plates through paintField - the
        # Spinner-only painting is retired with the popup window.
        self.assertIn("private android.graphics.drawable.Drawable "
                      "popupPlate(int index) {", main)
        self.assertIn("private void paintField(View field, int index) {", main)
        # On selection, and on the remembered theme at start.
        self.assertIn("applyTheme(index);", main)
        self.assertLess(main.index("applyThemeToInputs(themeIndex)"),
                        main.index("wireDropdownArrows();"))
        # The theme box is exempt by the owner's own sentence.
        self.assertIn("if (input == themeSpinner) continue;", main)
        # The two inline menus carry the theme's own popup plate.
        self.assertIn("volumeSplitMenu.setBackground(popupPlate(index));",
                      main)
        self.assertIn("themeMenu.setBackground(popupPlate(index));", main)
        # Each theme's popup is a plate of its own family, named once.
        for suffix in ("black", "green", "navy", "orange"):
            self.assertTrue((RES / "drawable"
                             / f"dropdown_popup_{suffix}.xml").exists())
        self.assertIn("R.drawable.dropdown_popup_black", main)
        self.assertIn("R.drawable.dropdown_popup_green", main)
        self.assertIn("R.drawable.dropdown_popup_navy", main)
        self.assertIn("R.drawable.dropdown_popup_orange", main)
        # The field law's own corners travel with the theme, built once.
        self.assertIn("private final GradientDrawable[] themeFieldPlates",
                      main)
        self.assertIn("cached.setCornerRadius(dp(12));", main)
        # The search box rides the same pass.
        self.assertIn("themedInputs.add(searchInput);", main)

    def test_v2_2_5_no_purple_stencil_under_a_themed_input(self):
        """v2.2.5: the volume dropdown no longer carries a purple
        popupBackground in the layout (the popup plate is stamped from
        Java per theme), so no themed input can keep a colour its tile
        does not declare."""
        layout = LAYOUT.read_text(encoding="utf-8")
        spinner = element(layout, 'android:id="@+id/volume_split_spinner"')
        self.assertNotIn("android:popupBackground", spinner)

    def test_v2_3_16_all_three_boxes_carry_the_one_universal_height(self):
        """Owner orders 2026-10-27, nineteenth pass ("make the decrease
        the height of custom scrips of volume by another 30%, and with
        that same exact setting, make the changes for theme box and
        search box as well, I mean all these three boxes should have
        universal height"). The universal height is the custom scrips
        box's own new one: 33 * 0.7 = 23.1, floored to EXACTLY 23dp, and
        all three field boxes (the two closed dropdown boxes and the
        search box) are BY that one height - one exact 23dp measure,
        the 3dp air above and below the line, the 10dp sides, one
        centre_vertical gravity, the font's own padding out of the
        measure. No floor is named again: the box now names its height
        in one place, layout_height, so the retired 32dp/38dp/40dp/43dp
        floors stay retired under the content they used to name.
        """
        layout = LAYOUT.read_text(encoding="utf-8")
        for view_id in ("volume_split_spinner", "theme_spinner",
                        "search_input"):
            with self.subTest(view_id=view_id):
                box = element(layout, f'android:id="@+id/{view_id}"')
                # Tile's width, one exact height, the universal numbers,
                # the same law three times.
                self.assertIn('android:layout_width="match_parent"', box)
                self.assertIn('android:layout_height="23dp"', box)
                self.assertNotIn("minHeight", box)
                self.assertIn('android:paddingTop="3dp"', box)
                self.assertIn('android:paddingBottom="3dp"', box)
                self.assertIn('android:paddingLeft="10dp"', box)
                self.assertIn('android:paddingRight="10dp"', box)
                self.assertIn('android:gravity="center_vertical"', box)
                self.assertIn('android:includeFontPadding="false"', box)

    def test_v2_3_16_the_dropdown_menu_opens_from_the_box_itself(self):
        """Owner order 2026-10-27, nineteenth pass: "when I tap on
        custom scrips of volume, another window pops up which is wrong,
        drop down menu should appear from the same box, not as a
        completely separate window".

        The platform Spinner is retired with its popup window
        entirely: every closed dropdown box is its own one-line
        TextView, and every menu is a LinearLayout of the app's own
        rows standing DIRECTLY below the box it belongs to, in the
        page's own scroll, drawn from MainActivity's own open state -
        no popup window, no platform spinner, no adapter, anywhere.
        The theme menu carries the same exact setting, since the two
        dropdowns keep one law.
        """
        layout = LAYOUT.read_text(encoding="utf-8")
        main = MAIN.read_text(encoding="utf-8")
        # The platform dropdown class is retired with its file.
        self.assertNotIn("pk.quantofrehan.Dropdown", layout)
        self.assertFalse(
            (ROOT / "android" / "app" / "src" / "main" / "java"
             / "pk" / "quantofrehan" / "Dropdown.java").exists())
        for view_id, menu_id in (("volume_split_spinner",
                                  "volume_split_menu"),
                                 ("theme_spinner", "theme_menu")):
            with self.subTest(view_id=view_id):
                box = element(layout, f'android:id="@+id/{view_id}"')
                menu = element(layout, f'android:id="@+id/{menu_id}"')
                # The closed box is a plain TextView; nothing of the
                # platform spinner's own attributes survives on it.
                self.assertIn("<TextView", box)
                self.assertNotIn("popupBackground", box)
                self.assertNotIn("android:prompt", box)
                self.assertNotIn("extends Spinner", main)
                # The menu stands DIRECTLY after the box's own holder,
                # in the page's own flow, until the state opens it.
                self.assertIn("<LinearLayout", menu)
                self.assertIn('android:layout_marginTop="2dp"', menu)
                self.assertIn('android:visibility="gone"', menu)
        # The engine: rows built by the app, open states drawn between
        # the menu's visibility, the arrow and the one-menu-at-a-time
        # law; the adapter machinery is retired with the popup window.
        self.assertIn("private void buildVolumeMenu() {", main)
        self.assertIn("private void buildThemeMenu() {", main)
        self.assertIn("private TextView menuRow(String line) {", main)
        self.assertIn("private void showVolumeMenu(boolean open) {", main)
        self.assertIn("private void showThemeMenu(boolean open) {", main)
        self.assertIn("private void rotateDropdownArrow(ImageView arrow, "
                      "boolean open) {", main)
        self.assertNotIn("ArrayAdapter", main)
        self.assertNotIn("AdapterView", main)
        self.assertNotIn("android.widget.Spinner", main)
        self.assertNotIn("styledSpinnerAdapter", main)
        self.assertNotIn("styleSpinnerRow", main)
        self.assertNotIn("setOnItemSelectedListener", main)
        # Both menus open FROM their own box and their own arrow: four
        # taps, one toggle each.
        self.assertEqual(main.count("showVolumeMenu(!volumeMenuOpen)"), 2)
        self.assertEqual(main.count("showThemeMenu(!themeMenuOpen)"), 2)
        # One menu at a time, served by the states themselves.
        self.assertIn("        if (open) {\n"
                      "            showThemeMenu(false);\n        }", main)
        self.assertIn("        if (open) {\n"
                      "            showVolumeMenu(false);\n        }", main)

    def test_v2_3_15_the_themes_arrow_aims_at_the_box_itself(self):
        """Owner order 2026-10-27, eighteenth pass: "the drop down is
        not even aligned on the centre for themes box.

        The themes dropdown's own 10dp top margin sat on the Dropdown
        INSIDE its holder, so the holder was 10dp taller than the box
        and the arrow's center_vertical aimed at the holder - the box's
        line sat low in its own frame and the arrow sat high beside it.
        The margin moves onto the holder now, so the holder is exactly
        the box and both arrows aim at the box's own centre by
        construction.
        """
        layout = LAYOUT.read_text(encoding="utf-8")
        for view_id in ("volume_split_spinner", "theme_spinner"):
            with self.subTest(view_id=view_id):
                box = element(layout, f'android:id="@+id/{view_id}"')
                start = layout.rindex("<FrameLayout", 0, layout.index(box))
                holder = layout[start:layout.index("</FrameLayout>", start)]
                # The box itself carries no top margin; the holder does,
                # so the holder is exactly the box and the arrow's
                # center_vertical aims at the box's own centre.
                self.assertNotIn('android:layout_marginTop', box)
                self.assertIn('android:layout_marginTop="10dp"', holder)
        # Both arrows name a plain 20dp size, so the cue is visible
        # whatever a drawable's own intrinsic later says.
        for view_id in ("volume_split_arrow", "theme_arrow"):
            with self.subTest(arrow=view_id):
                arrow = element(layout, f'android:id="@+id/{view_id}"')
                self.assertIn('android:layout_width="20dp"', arrow)
                self.assertIn('android:layout_height="20dp"', arrow)
                self.assertNotIn('wrap_content', arrow)

    def test_v2_3_16_the_search_box_joins_the_universal_height(self):
        """Owner order 2026-10-27, nineteenth pass ("with that same
        exact setting, make the changes for theme box and search box as
        well, I mean all these three boxes should have universal
        height"). The search box was allowed to grow twice (10% on
        v2.3.14, 25% on v2.3.15); today's order names the universal
        height from the custom scrips box's own side and the search box
        is BY it: the box is one exact 23dp measure (33 * 0.7 = 23.1,
        floored to 23dp), the air reads 7dp to 3dp above and below the
        line, and nothing of the grown floors (35dp, 43dp) survives
        under their own name.
        """
        box = element(LAYOUT.read_text(encoding="utf-8"),
                      'android:id="@+id/search_input"')
        self.assertIn('android:layout_height="23dp"', box)
        self.assertNotIn("minHeight", box)
        self.assertNotIn('android:layout_height="35dp"', box)
        self.assertNotIn('android:layout_height="43dp"', box)
        self.assertIn('android:paddingTop="3dp"', box)
        self.assertIn('android:paddingBottom="3dp"', box)

    def test_v2_3_14_the_sun_is_ten_percent_slower_the_fourth_time(self):
        """Owner order 2026-10-27: "Decrease the sun's revolving speed by
        another 10%". The cut lands on SUN_SPIN_RATE itself, the place
        every earlier cut sat: 0.26775 * 0.9 = 0.240975 rad/s.
        """
        orb = (MAIN.parent / "ThinkingOrb.java").read_text(
            encoding="utf-8")
        self.assertIn("SUN_SPIN_RATE = 0.240975f", orb)
        self.assertNotIn("SUN_SPIN_RATE = 0.26775f", orb)
        self.assertIn("0.26775 * 0.9 = 0.240975 rad/s", orb)

    def test_v2_3_14_no_line_ever_leaves_its_dot(self):
        """Owner order 2026-10-27: "the moving big lines that are
        revolving around the sun are coming out from their dots. Make it
        not exceed those dots". The v2.3.3 law synced a filament's
        length 0.70..1.30 of the distance its two dots own, so at the
        top of every wave each end hung up to 30% BEYOND its dot. The
        breathing is inward-only now: the law's factor rides 0.70..1.00
        over the wave, so the line shrinks toward its own midpoint and
        stretches back exactly to the dots that own it, at its longest
        end to end and not one pixel past them.
        """
        orb = (MAIN.parent / "ThinkingOrb.java").read_text(
            encoding="utf-8")
        # The outward-breathing factor is retired with its excuse.
        self.assertNotIn("float breath = 1f + 0.30f * breathWave;", orb)
        # The inward-only law is named, and its ceiling is 1.00.
        self.assertIn("float breath = 1f - 0.15f * (1f - breathWave);", orb)
        self.assertIn("0.70..1.00", orb)

    def test_v2_3_15_the_anchors_walk_an_even_path_and_the_mesh_is_a_neighbourhood(self):
        """Owner order 2026-10-27, eighteenth pass, on the v2.3.14
        build: "the LINES that are revolving around the SUN looks really
        tangled and very over lapping to me, and they don't even connect
        on one side of the entire feature".

        Two causes, named and cut:

        1. The v2.3.8 anchors sat on FIVE RANDOM seeded spots, so the
           lobes were five random fists - anchors that happened to sit
           near each other made one crowded, overlapped mass (his
           tangled side) and the stretches between anchors had almost
           nothing to link (his unconnected side). The anchors walk the
           golden angle's EVEN path around the sphere now - one latitude
           band per cluster, one 2.39996 turn apart - so the lobes stand
           apart everywhere in every direction and the web fills all the
           way around the sun by construction, never by luck. The nodes'
           own seeded jitter, the break-outs and the escapees stand.
        2. The pair sweep walked FIRST COME, FIRST SERVED and died at
           the link budget, so wherever the nodes crowded, the budget
           was spent there and the far side of the sweep reached no
           pairs at all. The mesh is a NEIGHBOURHOOD mesh now: every
           node joins K = 3 of its own nearest neighbours under the one
           0.42 cap, each pair once, so every side of the ball carries
           its own filaments and no lobe can spend another's links. The
           orphan law stands; every node still wears a filament.
        """
        orb = (MAIN.parent / "ThinkingOrb.java").read_text(
            encoding="utf-8")
        # The even anchor walk: one band per cluster, the golden angle's
        # own turn apart, between the sun and the shell.
        self.assertIn("float v = (c + 0.5f) / CLUSTERS * 2f - 1f;", orb)
        self.assertIn("float theta = c * 2.39996f;", orb)
        # The seeded gather stands: the nodes still jitter, break out and
        # escape, one decision.
        self.assertIn("long seed = 20261022L;", orb)
        self.assertIn("float pulled = (n % 4 == 0) ? 1.05f : 0.78f;", orb)
        # The neighbourhood mesh: K = 4 own nearest neighbours, each pair
        # once, still under the one 0.42 cap. v2.3.16 (owner order 2026-10-27,
        # nineteenth pass, "the animating lines are less as of now, make
        # more LINES ... increase the number of LINES by 20% from the
        # current number, across the entire animating feautre") takes the
        # join up from 3, and the mesh's own pair budget carries the same
        # 20% (3 per node / 1.2 = 2.5 floored to 2 net, 31/5 up
        # granularity), so the arrays hold every pair the four-neighbour
        # join now asks for.
        self.assertIn("final int K = 4;", orb)
        # The pair budget the arrays are sized on carries the same +20%
        # (26/5 * 1.2 = 31.2, floored to 31/5), so the four-neighbour
        # join can never outrun it.
        self.assertIn("return NODES * 31 / 5;", orb)
        self.assertIn("for (int take = 0; take < K; take++) {", orb)
        self.assertIn("boolean[] linked = new boolean[NODES * NODES];", orb)
        self.assertIn("linked[i * NODES + nearest] = true;", orb)
        self.assertIn("linked[nearest * NODES + i] = true;", orb)
        # The link budget the arrays are sized on is unchanged.
        self.assertEqual(orb.count("linkBudget()"), 6)
        # The orphan law stands.
        self.assertIn("boolean[] joined = new boolean[NODES];", orb)
        self.assertIn("linkDist[linkCount] = nearestDist;", orb)

    def test_v2_3_12_every_vsync_carries_a_whole_picture(self):
        """Owner order 2026-10-27: "the entire animating feature is still
        flickering, make it stop flickering/phasing". The flicker was the
        33ms gate's own empty return: an early Choreographer frame
        returned WITHOUT drawing, so that vsync carried whatever the
        surface already held while the next carried a redraw, and the
        alternation showed at the screen's own rate as phasing (the sun's
        publish rides the same scheduler). The law: a short frame is
        REPAINTED WHOLE at the pose the loop last drew, so every vsync
        carries one complete picture and the picture still changes only
        at the loop's own 33ms pace.
        """
        orb = (MAIN.parent / "ThinkingOrb.java").read_text(
            encoding="utf-8")
        gate = orb[orb.index("if (lastFrameAt >= 0"):
                   orb.index("lastFrameAt = now;")]
        # The early frame paints the LAST DRAWN pose, not a held surface.
        self.assertIn("drawScene(canvas, lastSeconds,", gate)
        # It never returns empty, and it keeps the cadence alive.
        self.assertLess(gate.index("drawScene(canvas, lastSeconds,"),
                        gate.index("postInvalidateOnAnimation();"))
        self.assertIn("return;", gate)
        # The full frame still assigns the pose the early frames repaint.
        full = orb[orb.index("lastFrameAt = now;"):
                   orb.index("drawScene(canvas, seconds, wake);")]
        self.assertIn("lastSeconds = seconds;", full)

    def test_the_sun_never_flickers(self):
        orb = (MAIN.parent / "ThinkingOrb.java").read_text(
            encoding="utf-8")
        """Owner order 2026-10-25, closing sentence: "also don't flicker my
        SUN". Flicker is a PICTURE WIDE alpha pump: a hot ball that dims
        and brightens as a whole reads as a stutter, whatever is animating
        inside it. The law that answers it, and that v2.3.1 keeps while it
        adds the boil and the eruptions: every alpha on this path is the
        wake alone, so no term can pump the ball or the glow. The motion
        lives in the heat (the counter-turning read), in the eruptions'
        smooth attack and decay, and in the palette lookup - never in an
        opacity.
        """
        frame = orb[orb.index("private void drawSun("):
                    orb.index("private void renderSunBall(")]
        self.assertIn("sunPaint.setAlpha((int) (255f * wake));", frame)
        # Every alpha written on this path is the wake's, with no other
        # factor in it: no sine, no phase, no pulse term. v2.3.4 folds the
        # glow into the ball's own bitmap, so there is one alpha, not two.
        alphas = [line.strip() for line in frame.splitlines()
                  if "setAlpha" in line]
        self.assertEqual(len(alphas), 1, alphas)
        for line in alphas:
            self.assertIn("wake", line)
            self.assertNotIn("Math.sin", line)
            self.assertNotIn("Math.random", line)
        self.assertNotIn("setShader", frame)
        self.assertNotIn("PorterDuff", frame)
        # The eruptions are deterministic and smooth: a fixed period and
        # phase each, an attack and a decay, never a random flash.
        step = orb[orb.index("private void stepEruptions("):
                   orb.index("private void buildSunSphere(")]
        self.assertIn("float attack = smoothstep(0f, 0.20f, t);", step)
        self.assertIn("float decay = 1f - smoothstep(0.34f, 1f, t);", step)
        self.assertNotIn("Math.random", step)
        self.assertNotIn("Random", orb)
        # v2.3.7 (owner order 2026-10-26: "the SUN ... is flickering"): a
        # 256x256 surface pass with two map reads, seven eruptions, bloom
        # and blur refiring inside every 33ms frame dropped whole frames
        # on a busy phone, and the dropped frames are what read as the
        # ball jumping. v2.3.8 ("the SUN is still flickering/phasing") is
        # the final law: the pass runs on a DEDICATED thread - its own
        # 60ms cadence, a low priority rank, double buffered - so it
        # can never drop a UI frame and the fire's own speed is never
        # throttled by it. The cloud keeps its 30fps.
        self.assertIn("private static final long SUN_CADENCE_MS = 60L;", orb)
        self.assertIn("boolean sunLoop;", orb)
        self.assertIn("startSunLoop();", orb)
        self.assertIn("stopSunLoop();", orb)
        # The handover is the swap, not a re-tinted, re-graded pass: the
        # pass fills the BACK bitmap and publishSun swaps the two whole.
        self.assertIn("sunBallBack.setPixels", orb)

    def test_the_balls_texture_is_his_picture_and_its_limb_is_his_curve(self):
        orb = (MAIN.parent / "ThinkingOrb.java").read_text(
            encoding="utf-8")
        """The owner's own sun photograph shipped on 2026-10-24
        (drawable-nodpi/sun.jpg, the SUN ONLY of the picture he sent) and
        has been the source of this ball ever since. v2.3.4 reads it for
        the surface AND for the limb: his picture's radial brightening is
        applied at render time, so the ball carries his own light instead of
        a painted crown, and one unsharp pass keeps his filaments.
        """
        self.assertTrue((RES / "drawable-nodpi" / "sun.jpg").is_file())
        self.assertIn("R.drawable.sun", orb)
        # The crop, its grade, its sharpen and the map built from his texels.
        self.assertIn("float disc = Math.min(w, h) / 2f * SUN_BALL_EDGE;",
                      orb)
        self.assertIn("float crop = disc * SUN_CROP;", orb)
        self.assertIn("float py = midY + crop * (float) Math.sin(latitude);",
                      orb)
        self.assertIn("private static int gradeInk(int ink) {", orb)
        self.assertIn("private static int gradeChannel(int value) {", orb)
        self.assertIn("float v = (value / 255f - 0.5f) * SUN_CONTRAST "
                      "+ 0.52f;", orb)
        self.assertIn("private static int sharpenChannel(int value, "
                      "int blurred) {", orb)
        # The rim is read off his picture at build. The corona beside it
        # stands again at the owner's newest order (2026-10-26: "remove
        # the entire feature then add it again"): the feature is the
        # v2.3.8 build he named good, whose corona is the thin v2.3.6
        # blend, gain 1.45 and reach 0.20 - NOT the 1.75 bulge of
        # 2026-10-25, which was the thick orange outline he sent back.
        # v2.3.11 pins that difference on its own value.
        self.assertIn("private void buildSunRing(int[] pixels, int w, int h) {",
                      orb)
        self.assertIn("float r = disc * RING_BANDS[b];", orb)
        self.assertIn("CORONA_GAIN = 1.45f", orb)
        self.assertNotIn("CORONA_GAIN = 1.75f", orb)
        # The bake's own edge sampling reads the photo: only its NUMBERS
        # say the threshold (the same two numbers the prototype grid
        # sat down on), and the white surplus lift stays the prototype's
        # per-channel clamp, never a shader.
        self.assertIn("float surplus = alpha - clipped;", orb)
        # A shader may not repaint his picture, and nothing may draw a ring.
        for retired in ("setShader", "PorterDuff", "GRANULES",
                        "SUN_LIMB_FLOOR", "SUN_EDGE_IN", "SUN_CROWN_INK",
                        "drawCloudHeart"):
            with self.subTest(retired=retired):
                self.assertNotIn(retired, orb)

    def test_the_painted_rays_are_deleted_with_their_book_keeping(self):
        orb = (MAIN.parent / "ThinkingOrb.java").read_text(
            encoding="utf-8")
        """Owner order 2026-10-25, third pass: "the ray that are on the sun
        right now looks absolute fake and ugly". The twelve radial flame
        tongues and the seven spark streaks are what that sentence caught:
        a radial gradient blob at a fixed angle can only ever read as a
        drawn ray, never as fire. Both are DELETED with their angles,
        lengths, phases, rates, paints and methods, and the limb carries
        the fire the same way the photograph's does - in the surface and
        the ragged crown. The big straight HUD rules are untouched: they
        are drawCloud's, and the owner exempted them by name.
        """
        for retired in ("FLAMES", "FLARES", "flameAngle", "flameLength",
                        "flamePhase", "flameRate", "flareAngle",
                        "flarePeriod", "flarePhase", "buildSun(",
                        "drawFlames", "drawFlares", "sunFlame", "sunFlare",
                        "SUN_RING_OUT", "SUN_RING_LIFT",
                        "sphereRing", "sphereEdge"):
            with self.subTest(retired=retired):
                self.assertNotIn(retired, orb)
        # v2.3.1's eruptions are NOT the deleted rays come back: they are
        # heat added to the ball's own surface (the same pixel loop that
        # folds the palette), travel with it, and never draw a shape of
        # their own. No canvas call knows they exist.
        self.assertIn("private static final int ERUPTIONS = 7;", orb)
        self.assertNotIn("drawErupt", orb)
        self.assertNotIn("eruptPaint", orb)
        # One scene, two draws: the cloud, then its sun.
        scene = orb[orb.index("private void drawScene("):
                    orb.index("private void drawSun(")]
        self.assertIn("drawCloud(canvas, seconds, wake);", scene)
        self.assertIn("drawSun(canvas, seconds, wake);", scene)
        self.assertEqual(scene.count("canvas"), 3,
                         "drawScene draws the cloud and the sun, nothing else")
        # The cloud and its laws stand: the rays he exempted are these.
        self.assertIn("float linkAt = 0.42f;", orb)
        self.assertIn("private void drawCloud(", orb)
        self.assertNotIn("Path", orb)

    def test_the_burn_reads_alone_and_the_palettes_ahead_of_it_are_retired(self):
        orb = (MAIN.parent / "ThinkingOrb.java").read_text(
            encoding="utf-8")
        """Owner order 2026-10-23 (fourth pass, v1.9.13): the burn carries
        the sun and nothing else; the stacked v1.9.6-v1.9.9 brightness
        constants are retired with the passes that grew them.
        """
        # The sun draws at one woken alpha; the heart and every fire mood
        # ride the same wake, so a closed market parks the picture whole.
        self.assertIn("sunPaint.setAlpha((int) (255f * wake));", orb)
        # The cloud keeps the v1.8.9 reference's icy family on the deep
        # field, two declared constants so the palette is one decision
        # (the v2.1.0 six-stop re-ink is retired with its burst).
        # v2.2.1: the cloud wears the owner's fire family now - warm gold
        # nodes and the orangish/yellow links he named - one decision each.
        self.assertIn("NODE_COLOR = 0xFFFFD166", orb)
        self.assertIn("LINK_COLOR = 0xFFFFA62B", orb)
        self.assertNotIn("GLOW_SCALE", orb)
        self.assertNotIn("BRIGHT_SCALE", orb)
        self.assertNotIn("P1 = 1.3f", orb)
        self.assertNotIn("P2 = 1.3f", orb)
        self.assertNotIn("FIRE_MODE", orb)
        self.assertNotIn("FIELD_COLOR", orb)

    def test_the_orb_is_one_budget(self):
        orb = (MAIN.parent / "ThinkingOrb.java").read_text(encoding="utf-8")
        # Zero allocations on the frame path: constellation, sun geometry
        # and inks are all built once, on the size change, never on the
        # frame; the ball's destination rect is shared and reused, and the
        # sphere's tables and bitmap are built beside the rest (v2.2.8).
        self.assertIn("buildGeometry();", orb)
        self.assertIn("buildInks();", orb)
        # v2.3.0: the flame and spark build is gone with the rays it drew;
        # the sphere's own bake is the sun's whole build now.
        self.assertNotIn("buildSun();", orb)
        self.assertIn("buildSunSphere();", orb)
        self.assertIn("onSizeChanged", orb)
        self.assertIn("private final RectF ballDst = new RectF();", orb)
        self.assertIn("ballDst.set(cx - r, cy - r, cx + r, cy + r);", orb)
        # The HUD frame loop is still the view's own paced invalidate, not
        # a sleep or a background service: nothing HUD-side runs while the
        # view is parked. The sun's dedicated render thread (v2.3.8) owns
        # the file's ONE sleep - the pacing of its own 60ms cadence - and
        # with that single pinned call removed, no other sleep is legal
        # anywhere in this file.
        self.assertIn("FPS_MS = 33L", orb)
        self.assertIn("postInvalidateOnAnimation()", orb)
        self.assertNotIn("Thread.sleep",
                         orb.replace("Thread.sleep(wait);", ""))
        self.assertNotIn("Service", orb)
        # start() and stop() are still the only public controls, wired to
        # MainActivity's startHud, stopHud and the market gate.
        self.assertEqual(orb.count("public void "), 2)

    def test_the_orb_stops_when_the_market_stops(self):
        # Owner order 2026-10-23 (v1.9.13): the feature stops animating
        # whenever the market is closed or on a break. The gate is the
        # ON badge's own boolean, read from the relay answer in the one
        # render pass, so a closed market, a break or an unreachable
        # relay all park the view (SO-3).
        main = MAIN.read_text(encoding="utf-8")
        self.assertIn("private void orbGate(boolean online) {", main)
        self.assertIn("orbBurning = online;", main)
        # The render pass calls the gate with the relay's truth.
        render = main[main.index("private void render(boolean online") :]
        render = render[:render.index("private String latestSignalDisplay(")]
        self.assertIn("orbGate(online);", render)
        # The one state survives a rebuild, so a resume onto a closed
        # market wakes PARKED and never flashes an open session.
        self.assertIn("if (orbBurning) {", main)


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
        # v1.9.13, then 2.0.0 (owner order 2026-10-23): the extras the
        # menu pages owned and the pair that used to bracket the pinned
        # menu bar were cancelled. v2.2.1 then framed the THEMES tile the
        # owner ordered for its "separate diamond and 2 lines around it",
        # and v2.2.3 put the search page's own rule back above the search
        # tile. v2.2.4 adds the pair's own division between the search
        # tile and the custom scrips of volume tile: EIGHT rules - four
        # on the home path, the THEMES tile's two, the search page's own
        # diamond, and the volume pair's own.
        self.assertEqual(len(rules), 8)
        for rule in rules:
            with self.subTest(rule=rule.get(f"{ANDROID_NS}id")):
                self.assertEqual(rule.get(f"{ANDROID_NS}layout_marginTop"),
                                 "12dp")

    def test_every_tile_that_follows_a_rule_carries_the_same_gap(self):
        for view_id in ("tile_status", "tile_signal", "tile_market",
                        "search_panel", "settings_panel"):
            with self.subTest(tile=view_id):
                tile = find_view(self.root, f"@+id/{view_id}")
                self.assertEqual(tile.get(f"{ANDROID_NS}layout_marginTop"),
                                 "12dp")
        # v2.2.0: the menu tile's one gap rides the carrier that owns its
        # 20dp side air, one construction for both laws.
        carrier = parent_of(self.root,
                            find_view(self.root, "@+id/nav_tile"))
        self.assertEqual(carrier.get(f"{ANDROID_NS}layout_marginTop"),
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


class V19SecondOrderTest(unittest.TestCase):
    """Owner order 2026-10-23 (second order, v1.9.14): the pixel orders
    above, each pinned so no later pass can retire one quietly.
    """

    def setUp(self):
        self.orb = (MAIN.parent / "ThinkingOrb.java").read_text(
            encoding="utf-8")
        self.main = MAIN.read_text(encoding="utf-8")
        self.layout = LAYOUT.read_text(encoding="utf-8")

    def test_the_park_is_frozen_but_visible(self):
        # "it will stop moving, it should not disappear completely":
        # stop() freezes the CLOCK (the pose the loop last drew), the
        # parked onDraw REPIINTS that pose fully awake, and a resume
        # replays from the frozen second, so a closed market, a break or
        # a theme repaint can never blank the feature.
        for pin in ("private float lastSeconds;",
                    "private float frozenSeconds = -1f;",
                    "frozenSeconds = lastSeconds;",
                    "frozenSeconds >= 0f ? frozenSeconds",
                    ": PARKED_SECONDS, 1f);",
                    "PARKED_SECONDS = 2.0f",
                    "(long) (frozenSeconds * 1000f);"):
            self.assertIn(pin, self.orb)

    def test_the_selected_nav_icon_is_highlighted_whole(self):
        # "the circle should be in the highlighted form, right now the
        # circle is getting cut off and also the entire icon only should
        # be highlighted in the entire circle" (owner order 2026-10-23,
        # v2.2.1): the lift and the foreground both grew the highlight
        # past the icon's own 42dp bounds, so the circle read as cut off.
        # There is no scale and no foreground any more: the whole
        # highlight is one filled translucent gold disc at exactly the
        # icon's bounds, brighter ink rides with it, and the state is
        # re-set on every paint.
        self.assertNotIn("NAV_SELECTED_SCALE", self.main)
        self.assertNotIn("navRingForeground", self.main)
        self.assertNotIn("navRing", self.main)
        self.assertNotIn("icon.setForeground(", self.main)
        self.assertNotIn("icon.setScaleX(", self.main)
        self.assertNotIn("icon.setScaleY(", self.main)
        self.assertIn("selected ? R.drawable.nav_circle : R.drawable.settings_ripple",
                      self.main)
        self.assertIn("icon.setImageTintList(ColorStateList.valueOf(getColor(",
                      self.main)
        self.assertIn("selected ? R.color.gold_bright : R.color.gold)));",
                      self.main)
        # The highlight itself: a translucent gold FILL inside the thin
        # gold ring, so the entire icon reads as highlighted.
        circle = (RES / "drawable" / "nav_circle.xml").read_text(
            encoding="utf-8")
        self.assertIn("solid", circle)
        self.assertIn("#4DFFC24B", circle)
        self.assertIn("@color/gold_bright", circle)

    def test_the_nav_tile_has_the_app_tile_breadth(self):
        # v2.2.0, on the owner's own words ("for the menu tile you only
        # need to match the width of the tile with the other tiles on the
        # app"): the bar's edges are the SAME 20dp side carrier the
        # scroll's padded column uses, so the plate's outer edge lands
        # where every other tile's does by construction, and no two
        # numbers of side air are kept in step by hand.
        carrier_start = self.layout.index(
            'android:id="@+id/nav_tile"')
        carrier = self.layout[self.layout.rindex("<FrameLayout", 0,
                                                  carrier_start):]
        self.assertIn('android:paddingLeft="20dp"',
                      carrier[:carrier.index(">")])
        self.assertIn('android:paddingRight="20dp"',
                      carrier[:carrier.index(">")])
        # The tile itself carries no side air of its own: the carrier is
        # the one owner of it.
        tile = self.layout[carrier_start:carrier_start + 700]
        self.assertNotIn("android:paddingLeft", tile[:tile.index(">")])
        self.assertNotIn("android:layout_marginLeft",
                         tile[:tile.index(">")])


if __name__ == "__main__":
    unittest.main()
