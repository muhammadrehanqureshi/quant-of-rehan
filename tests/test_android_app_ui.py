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
        # Owner order 2026-11-04: ORDER FLOW is the fifth slot, between the
        # scanner and the search glass.
        self.assertEqual(len(cells), 5)
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

    def test_the_order_flow_slot_sits_between_scanner_and_search(self):
        """Owner order 2026-11-04: the new page's slot is the third in the
        row, after the scanner and before the search glass, and it draws the
        owner's icon.

        The icon is a vector here rather than a png, because it is stroke
        art the nav tints, and a bitmap would need one file per state.
        """
        nav = find_view(layout_root(), "@+id/nav_tile")
        ids = [node.get(f"{ANDROID_NS}id") for cell in nav
               if cell.tag == "FrameLayout" for node in cell
               if node.tag == "ImageView"]
        self.assertEqual(ids, ["@+id/btn_nav_home", "@+id/btn_nav_scanner",
                               "@+id/btn_nav_flow", "@+id/btn_nav_search",
                               "@+id/btn_nav_settings"])
        # Owner order 2026-11-05 (fifth pass): his picture path for path as
        # a vector in one ink, so the nav's tint recolors it with every
        # theme and it stays crisp at any density. A raster trace was the
        # fourth pass and it read wrong.
        button = element(self.layout, 'android:id="@+id/btn_nav_flow"')
        self.assertIn('android:src="@drawable/orderflow"', button)
        self.assertIn('android:tint="@color/gold"', button)
        self.assertIn('android:contentDescription="@string/cd_order_flow"',
                      button)
        flow = RES / "drawable" / "orderflow.xml"
        self.assertTrue(flow.is_file())
        self.assertFalse((RES / "drawable-nodpi" / "orderflow.png").is_file())
        self.assertFalse((RES / "drawable" / "ic_nav_flow.xml").is_file())
        text = flow.read_text(encoding="utf-8")
        self.assertIn('android:viewportWidth="500"', text)
        self.assertIn('android:viewportHeight="500"', text)
        # Owner order 2026-11-05 (sixth pass): his new picture. One ledger
        # above, a stem that splits into two arms, and two ledgers below,
        # every stroke in the one ink the nav's tint recolors.
        for square in ('android:pathData="M212,30',
                       'android:pathData="M54,318',
                       'android:pathData="M358,318'):
            self.assertIn(square, text)
        for line in ('M250,164 L250,214',
                     'M250,214 C250,246 236,258 204,258',
                     'M250,214 C250,246 264,258 296,258',
                     'android:strokeWidth="26"'):
            self.assertIn(line, text)

    def test_the_flow_page_owns_two_seams_and_no_extra_one(self):
        """Owner order 2026-11-04, fourth pass ("there are two diamond
        line feature below the tile of BIG BUYING & SELLING, remove the
        extra one"): the page keeps the seam above ORDER FLOW and the one
        between ORDER FLOW and BIG BUYING & SELLING, and it carries NO
        include after the page's second tile - the extra diamond the
        owner counted below the tile is gone with rule_after_flow.
        """
        self.assertIn('android:id="@+id/rule_order_flow"', self.layout)
        self.assertIn('android:id="@+id/rule_between_flow"', self.layout)
        self.assertNotIn("rule_after_flow", self.layout)
        self.assertNotIn("ruleAfterFlow", self.main)
        self.assertGreater(
            self.layout.index("@+id/rule_between_flow"),
            self.layout.index("@+id/order_flow_panel"))
        self.assertGreater(
            self.layout.index("@+id/big_prints_panel"),
            self.layout.index("@+id/rule_between_flow"))

    def test_the_big_prints_board_centres_every_order(self):
        """Owner order 2026-11-17: every print on the BIG BUYING &
        SELLING board is centred, heading and numbers alike."""
        order = element(self.layout, 'android:id="@+id/big_prints_list"')
        self.assertIn('android:gravity="center"', order)

    def test_the_big_prints_board_scrolls_the_whole_day(self):
        """Owner order 2026-11-05 ("add a scrolling feature on BIG BUYING
        & SELLING tile so I can scroll and look for the complete BIG
        BUYING & SELLING during the day"): the tile's list lives in its
        own ScrollView, every print the relay served joins the text (the
        twenty line cap is gone), a touch on the list scrolls the list
        and never the page underneath it, and a freshly opened page
        reads the board from its top.
        """
        scroll_at = self.layout.index("@+id/big_prints_scroll")
        list_at = self.layout.index("@+id/big_prints_list")
        self.assertLess(scroll_at, list_at)
        self.assertIn("<ScrollView", self.layout[scroll_at - 200:scroll_at])
        self.assertLess(list_at, self.layout.index("</ScrollView>", list_at))
        # Owner order 2026-11-11: the platform bar is replaced by the
        # diamond with two fading lines, drawn in the theme's own ink.
        self.assertIn('pk.quantofrehan.OrnamentScroller', self.layout)
        self.assertIn('@+id/big_prints_scroller',
                      self.layout[list_at:list_at + 800])
        self.assertNotIn('android:scrollbars="vertical"',
                         self.layout[scroll_at:list_at])
        self.assertIn('android:layout_height="176dp"',
                      self.layout[scroll_at:list_at])
        scroller = (ROOT / "android" / "app" / "src" / "main" / "java"
                    / "pk" / "quantofrehan" / "OrnamentScroller.java"
                    ).read_text(encoding="utf-8")
        self.assertIn('private static final String DIAMOND = "\\u25C6";',
                      scroller)
        self.assertIn("DIAMOND_SP = 10f", scroller)
        self.assertIn("COMPLEX_UNIT_SP, DIAMOND_SP", scroller)
        self.assertNotIn("dp(9f)", scroller)
        # Owner order 2026-11-21: six complete orders, measured through
        # the sixth order's own wrapped line instead of a guessed count.
        self.assertIn("private static final int BIG_PRINTS_ORDERS = 6;",
                      self.main)
        self.assertIn("private static final int BIG_PRINTS_ROWS = 6;",
                      self.main)
        self.assertIn("fitBigPrintsWindow();", self.main)
        self.assertIn("int height = rows * row", self.main)
        self.assertIn("bigPrintEnds.add(sb.length());", self.main)
        self.assertIn("text.getLineForOffset(end) + 1", self.main)
        self.assertIn("lp.height = height;", self.main)
        self.assertIn("bigPrintsScroll = findViewById(R.id.big_prints_scroll);",
                      self.main)
        self.assertIn("requestDisallowInterceptTouchEvent(true)", self.main)
        self.assertIn("bigPrintsScroll.scrollTo(0, 0);", self.main)
        self.assertNotIn("BIG_PRINTS_SHOWN", self.main)
        self.assertIn("Owner order 2026-11-05: EVERY print the relay holds",
                      self.main)

    def test_an_order_flow_row_is_the_scrip_alone(self):
        """Owner order 2026-11-25 (latest): "I don't want to see the details
        while I'm still searching and haven't selected any scrip." The ORDER
        FLOW list row is the scrip alone, the CUSTOM SCRIPS OF VOL. menu's own
        option, and a tap opens that scrip's own answer from the same
        /orderflow read the page already holds. The four-column quote row and
        its header are retired with it.
        """
        self.assertIn("orderFlowResults.addView(flowTableRow(row, query));",
                      self.main)
        self.assertIn("private View flowTableRow(", self.main)
        row = self.main[self.main.index("private View flowTableRow("):]
        row = row[:row.index("private void pickFlow(")]
        self.assertIn("TextView line = menuRow(scripMatchSpans(row.symbol, query));",
                      row)
        self.assertIn("line.setOnClickListener(v -> pickFlow(row.symbol));", row)
        self.assertNotIn("PKR", row, "no quote in the list")
        self.assertNotIn("flowCell", row)
        self.assertNotIn("private View flowTableHeader()", self.main)
        self.assertNotIn("FLOW_COLUMNS", self.main)
        self.assertNotIn("private void paintFlowRow(", self.main)
        self.assertIn("flowSplitText(found)", self.main)
        # Owner order 2026-11-07: the selected scrip's book is the two
        # column one below, so the old single line " & " sentence is gone.
        self.assertIn("fillFlowBook(found);", self.main)


        # The numbers travel from the relay's rows, which carry bid and
        # ask; the Watcher parses both beside the price and the volume.
        watcher = (ROOT / "android" / "app" / "src" / "main" / "java"
                   / "pk" / "quantofrehan" / "Watcher.java").read_text(
            encoding="utf-8")
        self.assertIn("out.bid = number(row, \"bid\");", watcher)
        self.assertIn("out.ask = number(row, \"ask\");", watcher)
        self.assertIn("out.bidSize = whole(row, \"bid_size\");", watcher)
        self.assertIn("out.askSize = whole(row, \"ask_size\");", watcher)
        self.assertIn("Long bidSize;", watcher)
        self.assertIn("Long askSize;", watcher)
        self.assertIn("Double bid;", watcher)
        self.assertIn("Double ask;", watcher)
        self.assertIn('out.changePct = number(row, "change_pct");', watcher)
        self.assertIn("Double changePct;", watcher)

    def test_the_search_row_carries_the_scrip_and_its_quote(self):
        """Owner order 2026-11-27: "Make the SEARCH tile also like the ORDER
        FLOW tile. When I will tap on a scrip only then I will be able to see
        the details of that scrip." The option is the scrip alone, so no
        option prints a price, a range or a split while he types; the tapped
        scrip's answer carries the day's range, H in the green of a high and L
        in the red of a low."""
        row = self.main[self.main.index("private void styleSearchRow("):]
        row = row[:row.index("private GradientDrawable highlightPlate")]
        self.assertIn("row.setText(scripMatchSpans(symbol, q));", row)
        self.assertNotIn("appendSearchQuote", row)
        self.assertNotIn("Watcher.quotes()", row)
        answer = self.main[self.main.index("private CharSequence liveSelectedLine("):]
        answer = answer[:answer.index("private CharSequence signalInk")]
        self.assertIn('"\\nH="', answer)
        self.assertIn('" & L="', answer)
        self.assertIn("highFrom, highTo, 0", answer)
        self.assertIn("lowFrom, lowTo, 0", answer)
        self.assertLess(answer.index("highFrom, highTo, 0"),
                        answer.index("lowFrom, lowTo, 0"))
        watcher = (ROOT / "android" / "app" / "src" / "main" / "java"
                   / "pk" / "quantofrehan" / "Watcher.java").read_text(
            encoding="utf-8")
        self.assertIn("Double high;", watcher)
        self.assertIn("Double low;", watcher)
        self.assertIn('row.optDouble(7, Double.NaN)', watcher)
        self.assertIn('row.optDouble(8, Double.NaN)', watcher)

    def test_a_row_without_a_measured_pair_prints_its_unclear_total(self):
        """B/S null must not hide U: the known total is printed as U."""
        watcher = (ROOT / "android" / "app" / "src" / "main" / "java"
                   / "pk" / "quantofrehan" / "Watcher.java").read_text(
            encoding="utf-8")
        start = watcher.index("static void fetchStock")
        body = watcher[start:start + 8000]
        self.assertIn("else if (unclear != null || total != null)", body)
        self.assertIn('" (U=%,.0f"', body)
        self.assertNotIn('" & T=', body)
        # A missing pair still keeps U and T on separate lines.
        self.assertIn("} else if (quote.unclassified != null || quote.volume != null) {",
                      self.main)
        self.assertIn("} else if (row.unclassified != null || row.hasVolume()) {",
                      self.main)
        self.assertIn("quote.unclassified != null", self.main)
        self.assertIn("row.unclassified != null", self.main)
        self.assertNotIn("quote.unclassified > 0", self.main)
        self.assertNotIn("row.unclassified > 0", self.main)

    def test_both_boards_share_the_print_sentence_and_theme_time(self):
        """Owner order 2026-11-13: ORDER FLOW and BIG BUYING & SELLING use
        one sentence, and the time wears the theme's body ink rather than
        the side's green or red."""
        self.assertIn("appendPrintSentence(sb, print);", self.main)
        self.assertEqual(self.main.count("appendPrintSentence(sb, print);"), 2)
        self.assertIn('"%,d SHARES OF %s WERE %s AT PKR %,.2f"', self.main)
        self.assertIn('sale ? "SOLD" : "BOUGHT"', self.main)
        self.assertIn('sb.append(" AT ");', self.main)
        self.assertIn("new ForegroundColorSpan(themeBodyInk)", self.main)
        self.assertIn("printTime(print.at)", self.main)
        self.assertIn("raw.substring(t + 1, t + 9)", self.main)
        # Owner order 2026-11-15: the print clock is normalized to Karachi
        # regular-session time and an impossible hour is refused.
        watcher = (ROOT / "android" / "app" / "src" / "main" / "java"
                   / "pk" / "quantofrehan" / "Watcher.java").read_text(
            encoding="utf-8")
        self.assertIn("private static String normalizedPrintAt(String at)",
                      watcher)
        self.assertIn("out.at = normalizedPrintAt(print.optString(\"at\", \"\"));",
                      watcher)
        self.assertIn("Asia/Karachi", watcher)
        self.assertNotIn('"(%s=%,d) "', self.main)

    def test_net_delta_follows_the_total_on_every_volume_line(self):
        """Owner order 2026-11-13: NET DELTA follows T wherever volume
        prints, with no sign or arrow, green when positive and red when
        falling."""
        self.assertIn("private void appendNetDelta(SpannableStringBuilder",
                      self.main)
        self.assertIn("appendNetDelta(sb, quote.buy, quote.sell);", self.main)
        self.assertIn("appendNetDelta(sb, row.buy, row.sell);", self.main)
        self.assertIn("appendNetDelta(sb, spans, row.buy, row.sell);",
                      self.main)
        self.assertIn('sb.append("  NET DELTA=");', self.main)
        # Owner order 2026-11-15: every builder closes the bracket first.
        flow = self.main[self.main.index("private SpannableStringBuilder flowSplitText("):]
        flow = flow[:flow.index("private CharSequence flowRowText")]
        self.assertLess(flow.index("sb.append(')');"),
                        flow.index("appendNetDelta(sb, row.buy"))
        self.assertIn("Math.abs(delta)", self.main)
        self.assertIn("delta >= 0 ? R.color.green : R.color.red", self.main)
        self.assertNotIn("NET DELTA=+", self.main)
        self.assertNotIn("NET DELTA=-", self.main)
        watcher = (ROOT / "android" / "app" / "src" / "main" / "java"
                   / "pk" / "quantofrehan" / "Watcher.java").read_text(
            encoding="utf-8")
        self.assertIn('sb.append("  NET DELTA=");', watcher)
        self.assertIn("c.getColor(delta >= 0 ? R.color.green : R.color.red)",
                      watcher)

    def test_the_large_print_window_keeps_the_whole_day(self):
        """Owner report 2026-11-13: prints before noon vanished once the
        relay's 200 print window filled. The window is the day now."""
        worker = (ROOT / "cloud" / "worker.js").read_text(encoding="utf-8")
        self.assertIn("const LARGE_PRINT_MAX = 2000;", worker)
        self.assertNotIn("const LARGE_PRINT_MAX = 200;", worker)
        # Owner order 2026-11-19: the big board is 100k shares and above.
        self.assertIn("const LARGE_PRINT_SHARES = 100_000;", worker)
        self.assertIn("if (measured.delta < LARGE_PRINT_SHARES) return null;",
                      worker)
        self.assertIn(
            "private static final long BIG_PRINT_FLOOR_SHARES = 100_000L;",
            self.main)
        self.assertIn("if (print.shares < BIG_PRINT_FLOOR_SHARES)", self.main)
        watcher = (ROOT / "android" / "app" / "src" / "main" / "java"
                   / "pk" / "quantofrehan" / "Watcher.java").read_text(
            encoding="utf-8")
        self.assertIn("MAX_BODY_CHARS = 2 * 1024 * 1024;", watcher)

    def test_the_big_prints_run_latest_first_by_clock(self):
        """Owner order 2026-11-11, third pass: the board is a clock, not a
        size ranking, so the latest print leads and the earliest closes it.
        LAST EIGHT FILLED ORDERS reads the same list and keeps the same order.
        """
        watcher = (ROOT / "android" / "app" / "src" / "main" / "java"
                   / "pk" / "quantofrehan" / "Watcher.java").read_text(
            encoding="utf-8")
        self.assertIn("private static String flowClock(String at)", watcher)
        self.assertIn(
            "int byClock = flowClock(b.at).compareTo(flowClock(a.at));",
            watcher)
        self.assertIn("return Long.compare(b.value, a.value);", watcher)
        self.assertNotIn("prints.sort((a, b) -> Long.compare(b.value, a.value));",
                         watcher)
        self.assertIn("for (Watcher.BigPrint print : lastPrints)", self.main)

    def test_the_selected_book_is_two_coloured_columns(self):
        """Owner order 2026-11-07 ("make two columns, one would contain
        BID & QTY get a vertical line after that then make another column
        for ASK & QTY ... you should have the price and the qty in
        color")."""
        selected = self.main[self.main.index("private void selectFlow("):]
        selected = selected[:selected.index("private void showSectorMenu(")]
        self.assertIn('flowBookColumn("BID"', selected)
        self.assertIn('flowBookColumn("ASK"', selected)
        self.assertIn("R.color.red, true)", selected)
        self.assertIn(
            "int align = alignRight ? Gravity.END : Gravity.START;",
            selected)
        self.assertIn("column.setGravity(align);", selected)
        self.assertIn("LinearLayout.HORIZONTAL", selected)
        self.assertIn("divider.setBackgroundColor(themeAccentInk);", selected)
        self.assertIn("head.setTextColor(themeBodyInk);", selected)
        self.assertIn(
            "value.setTextColor(price != null ? getColor(colorRes) : themeBodyInk);",
            selected)
        self.assertIn(
            "quantity.setSpan(new ForegroundColorSpan(getColor(colorRes))",
            selected)
        # The split line still travels with the book, and the selected
        # scrip's own fills stand at most eight.
        self.assertIn("SpannableStringBuilder split = flowSplitText(found);",
                      selected)
        self.assertIn("fillFlowPrints(symbol);", selected)
        self.assertIn("LAST EIGHT FILLED ORDERS", selected)
        self.assertNotIn("dp(64)", selected)
        self.assertIn("Math.max(1, dp(1)), LinearLayout.LayoutParams.MATCH_PARENT);",
                      selected)
        self.assertIn("bidColumn.addOnLayoutChangeListener(", selected)
        self.assertIn("columns.post(() -> {", selected)
        self.assertIn("lp.height = height;", selected)
        self.assertIn("shown >= FLOW_RESULTS_SHOWN", selected)
        self.assertNotIn("found.unclassified > 0", selected)

    def test_the_leaders_card_closes_after_the_total(self):
        """Owner order 2026-11-07 ("remove the bracket just after U,
        instead of the bracket, put & there, and have the bracket after
        T")."""
        leaders = self.main[self.main.index(
            "private SpannableString leadersText("):]
        leaders = leaders[:leaders.index("private void toast(")]
        # Owner order 2026-11-10 (later): the KSE100 tile's T starts its own
        # line, the first line ending on the ampersand.
        self.assertIn('sb.append(" &\\nT=");', leaders)
        self.assertNotIn('sb.append(" & T=");', leaders)
        self.assertIn("spans.add(new int[]{unclearFrom, sb.length(), "
                      "R.color.yellow});", leaders)
        # The other surfaces keep their own shape; only this card moved the
        # closing bracket.
        self.assertIn('append("T=");', self.main)
        self.assertIn("row.unclassified != null", self.main)
        self.assertIn("quote.unclassified != null", self.main)
        # Owner order 2026-11-15: T closes the bracket, then NET DELTA.
        self.assertLess(leaders.index("sb.append(')');"),
                        leaders.index("appendNetDelta(sb, spans"))
        # Both print boards share the one sentence now, not the old bracket.
        self.assertIn("appendPrintSentence(sb, print);", self.main)

    def test_the_empty_big_prints_board_is_sentence_height(self):
        """Owner order 2026-11-06 ("the BIG BUYING & SELLING tile is too
        large when there is no print, so make it fit/normal when there is
        nothing"): an empty board wraps its one sentence, and the eight
        print window comes back with the first print.
        """
        self.assertIn("wrapBigPrintsWindow();", self.main)
        self.assertIn("lp.height = ViewGroup.LayoutParams.WRAP_CONTENT;",
                      self.main)
        empty = self.main[self.main.index("private void renderBigPrints("):]
        empty = empty[:empty.index("private void fitBigPrintsWindow(")]
        self.assertIn("wrapBigPrintsWindow();", empty)
        self.assertIn("fitBigPrintsWindow();", empty)
        self.assertIn("int height = rows * row", self.main)

    def test_the_sectors_tile_lists_only_the_kmi_all_scrips(self):
        """Owner order 2026-11-06: the SEARCH page carries a SECTORS tile,
        its box drops a menu of the broker's own sectors down inside the
        tile, and the chosen sector prints every KMIALL scrip it holds with
        price, move and the one quantities bracket. A scrip outside KMIALL
        is filtered out on the relay before the phone ever sees it.
        """
        self.assertIn('android:text="@string/label_sectors"', self.layout)
        for view in ("@+id/tile_sectors", "@+id/sectors_spinner",
                     "@+id/sectors_menu", "@+id/sectors_scroll",
                     "@+id/sectors_scroller", "@+id/sectors_reveal",
                     "@+id/rule_sectors"):
            self.assertIn(view, self.layout)
        # Owner order 2026-11-21: the caret left the tile. The diamond
        # scroller is its scroll cue and the sector rows are its face.
        self.assertNotIn("@+id/sectors_arrow", self.layout)
        self.assertNotIn("sectorsArrow", self.main)
        self.assertGreater(self.layout.index("@+id/tile_sectors"),
                           self.layout.index("@+id/big_prints_panel"))
        strings = STRINGS.read_text(encoding="utf-8")
        self.assertIn('name="label_sectors">SECTORS<', strings)
        self.assertIn('name="sectors_placeholder"', strings)
        self.assertIn('name="sectors_unavailable"', strings)
        self.assertIn("private void showSectorMenu(boolean open)", self.main)
        self.assertIn("private void refreshSectors()", self.main)
        self.assertIn("private void renderSectorReveal()", self.main)
        self.assertIn("Watcher.fetchSectors(this", self.main)
        self.assertIn("row.setOnClickListener(v -> chooseSector(name));",
                      self.main)
        # Owner report 2026-11-06: one 1dp line between each pair of sector
        # rows, exactly the line every other dropdown draws.
        self.assertIn("sectorsMenu.addView(menuDivider());", self.main)
        # Owner order 2026-11-13: the menu is a scrolling window with the big
        # prints board's diamond scroller, sorted by the sector's own
        # percentage, and every known percentage carries its arrow.
        # Owner order 2026-11-27 (third pass): "make the SECTORS tile display
        # all 8 sectors name properly, right now the 8th one is getting cut
        # off" - the window measures the broker's WHOLE list (eight is its
        # floor for an empty answer), so no sector stands out of sight.
        self.assertIn("private static final int SECTOR_ROWS = 8;", self.main)
        self.assertIn("int rows = Math.max(SECTOR_ROWS, sectorRows.size());",
                      self.main)
        self.assertIn("sectorsMenu.post(this::fitSectorWindow);", self.main)
        # Owner order 2026-11-16: the window includes the menu's own edge air,
        # so its first and last rows are never clipped.
        self.assertIn("height += sectorsMenu.getPaddingTop()"
                      " + sectorsMenu.getPaddingBottom();", self.main)
        self.assertIn('android:paddingLeft="14dp"',
                      element(self.layout, 'android:id="@+id/sectors_scroll"'))
        # Owner order 2026-11-15: the closed scroll must not cover the face.
        self.assertIn('android:visibility="gone"',
                      element(self.layout, 'android:id="@+id/sectors_scroll"'))
        self.assertIn('android:visibility="gone"',
                      element(self.layout, 'android:id="@+id/sectors_scroller"'))
        self.assertIn("!sectorMenuOpen", self.main)
        # Owner order 2026-11-15: a missing KSE100 B/S asks ORDER FLOW once.
        self.assertIn("private void refreshMissingLeaderSplits(", self.main)
        self.assertIn("lastMarket = market;", self.main)
        self.assertIn("renderMarket(lastMarket);", self.main)
        self.assertIn("names.sort((a, b) -> {", self.main)
        self.assertIn("Double.compare(pb, pa)", self.main)
        self.assertIn("TextView row = menuRow(sectorMenuLabel(++number, name,",
                      self.main)
        self.assertIn("performance.get(name)));", self.main)
        self.assertIn('move >= 0 ? "\\u25B2" : "\\u25BC"', self.main)
        self.assertIn("private Double sectorPerformance(", self.main)
        # Owner order 2026-11-06, eleventh pass: the sectors and their
        # stocks carry their numbers in sequence.
        self.assertIn('String.format(Locale.US, "%d. %s", i + 1, symbol)',
                      self.main)
        # Owner order 2026-11-21: the sector list is the tile's permanent
        # face, left aligned, and no sector is chosen for him. A tap is the
        # only thing that reveals scrips, and the list never jumps back.
        spinner = element(self.layout, 'android:id="@+id/sectors_spinner"')
        self.assertIn('android:gravity="center"', spinner)
        self.assertIn("fillSectorMenu();", self.main)
        self.assertNotIn("sectorChoice.isEmpty() && best != null", self.main)
        self.assertIn('sectorChoice = "";', self.main)
        self.assertIn("sectorMenuPending = false;", self.main)
        self.assertIn("showSectorMenu(true);", self.main)
        self.assertIn("row.setGravity(Gravity.START | Gravity.CENTER_VERTICAL);",
                      self.main)
        sector_pick = self.main[self.main.index("private void chooseSector("):]
        sector_pick = sector_pick[:sector_pick.index("private void renderSectorReveal(")]
        self.assertNotIn("showSectorMenu(true);", sector_pick)
        # No scrips show until that tap: the landing list hides the reveal.
        refresh = self.main[self.main.index("private void refreshSectors()"):]
        refresh = refresh[:refresh.index("private String fillSectorMenu()")]
        self.assertNotIn("renderSectorReveal();", refresh)
        self.assertIn("sectorsReveal.setVisibility(View.GONE);", refresh)
        # The diamond's range is read after the six-row window lays out.
        self.assertIn("sectorsScroll.post(this::updateSectorScroller);",
                      self.main)
        # Owner order 2026-11-13: a tapped sector centres like KSE100.
        reveal = element(self.layout, 'android:id="@+id/sectors_reveal"')
        self.assertIn('android:gravity="center"', reveal)
        # And a tapped sector always lists its stocks: a scrip with no live
        # quote yet says so instead of vanishing.
        self.assertIn("R.string.sector_waiting", self.main)
        self.assertIn('name="sector_waiting">NO LIVE QUOTE YET<', strings)
        self.assertIn("sectorsReveal.setText(sb);", self.main)
        # The tile and its rule follow the search page, and close with it.
        self.assertIn("tileSectors.setVisibility(open ? View.VISIBLE",
                      self.main)
        self.assertIn("ruleSectors.setVisibility(open ? View.VISIBLE",
                      self.main)
        # The relay groups the broker's own master, KMIALL only.
        worker = (ROOT / "cloud" / "worker.js").read_text(encoding="utf-8")
        self.assertIn('path === "/sectors"', worker)
        self.assertIn("const wanted = new Set(KMIALL_UNIVERSE);", worker)
        self.assertIn("if (!wanted.has(symbol)) continue;", worker)
        self.assertIn("row.approved !== \"Approved\"", worker)
        self.assertIn("sectorMaster = { at: now, answer };", worker)
        # The app reads that route and skips a scrip with no live quote.
        watcher = WATCHER.read_text(encoding="utf-8")
        self.assertIn("static void fetchSectors(", watcher)
        self.assertIn('relayUrl(c) + "/sectors"', watcher)
        self.assertIn('SECTOR_TTL_MS = 6 * 60 * 60 * 1000L', watcher)

    def test_the_order_flow_prompt_is_retired(self):
        """Owner order 2026-11-05, tenth pass: the sentence under the
        order-flow search box is gone."""
        strings = STRINGS.read_text(encoding="utf-8")
        layout = LAYOUT.read_text(encoding="utf-8")
        self.assertNotIn('name="order_flow_pick"', strings)
        self.assertNotIn("@string/order_flow_pick", layout)
        self.assertNotIn("R.string.order_flow_pick", self.main)

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
        flow = element(self.layout, 'android:id="@+id/btn_nav_flow"')
        self.assertIn('android:background="@drawable/nav_circle"', home)
        self.assertIn('android:tint="@color/gold_bright"', home)
        for other in (scanner, flow, search, settings):
            with self.subTest(other=other[:other.index("/>")]):
                self.assertIn(
                    'android:background="@drawable/settings_ripple"',
                    other)
                self.assertIn('android:tint="@color/gold"', other)
        # The state machine is the one helper MainActivity calls with the
        # page's truth, never a view's own state. v3.4.0: the disc is the
        # worn theme's own law (navDisc); the unselected face is still
        # the ripple.
        self.assertIn("icon.setBackground(navDisc());", self.main)
        self.assertIn("setBackgroundResource(R.drawable.settings_ripple);",
                      self.main)
        self.assertIn("selected ? R.color.gold_bright : R.color.gold",
                      self.main)
        # Owner order 2026-10-24: home is the console's page only when all
        # three menus are closed, and the scanner page paints like the
        # rest of them.
        # Owner order 2026-11-04: the ORDER FLOW page is the fifth page, so
        # home is the console only when it is closed as well.
        self.assertIn("setNavPage(navHome, !searchOpen && !settingsOpen && !scannerOpen",
                      self.main)
        self.assertIn("&& !orderFlowOpen);", self.main)
        self.assertIn("setNavPage(navScanner, scannerOpen);", self.main)
        self.assertIn("setNavPage(navFlow, orderFlowOpen);", self.main)
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

    def test_the_first_status_word_is_processing(self):
        self.assertIn('name="status_checking">PROCESSING...</string>',
                      self.strings)
        self.assertNotIn('name="status_checking">CHECKING</string>',
                         self.strings)
        self.assertIn("System status: processing.", self.strings)

    def test_the_unavailable_signal_reads_no_signal_right_now(self):
        self.assertIn('name="signal_unavailable">NO SIGNAL RIGHT NOW</string>',
                      self.strings)

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
        # Owner order 2026-11-01: the QUANT STATUS and W/L tiles gained
        # their own diamond rule between them, and the greeting gained
        # one before QUANT STATUS, so the console carried ten of the one
        # include. Owner order 2026-11-04 (second pass): the ORDER FLOW
        # page owns a division of its own, bracketed above and below, so
        # the console carried twelve. Owner order 2026-11-04 (third pass):
        # the pair under BIG BUYING & SELLING loses one and that one
        # stands between the ORDER FLOW and BIG BUYING & SELLING tiles.
        # Owner order 2026-11-04 (fourth pass): the page gets NO diamond
        # after the BIG BUYING & SELLING tile - the extra one he read as
        # two seams below the tile is gone with the include - so the
        # console carried twelve. Owner order 2026-11-06: the SEARCH page's
        # SECTORS tile is a division of its own, so the console carries
        # THIRTEEN - the new rule stands above it and nothing else moves.
        self.assertEqual(self.layout.count('layout="@layout/qor_rule"'), 13)

    def test_the_rules_stand_between_the_tiles_and_never_inside_them(self):
        root = layout_root()

        def rule_after(view_id: str, through=None):
            view = find_view(root, view_id)
            following = siblings_after(root, parent_of(root, view))
            self.assertTrue(following, f"nothing follows the {view_id} tile")
            first = following[0]
            if through:
                # Owner order 2026-10-31: the W/L = W/L RATE tile sits
                # between two tiles, so the change of subject reaches the
                # rule THROUGH it - the named view stands first and the
                # rule stands after it, and nothing else intervenes.
                self.assertEqual(first.tag, "LinearLayout", f"{view_id}: *")
                self.assertEqual(first.get(ANDROID_NS + "id"),
                                 "@+id/" + through,
                                 f"{view_id}: no tile before the rule")
                rest = following[1:]
                self.assertTrue(rest, f"{view_id}: the rule is missing")
                first = rest[0]
            self.assertEqual(first.tag, "include", f"{view_id}: no rule after")
            self.assertEqual(first.get("layout"), "@layout/qor_rule")

        # Every tile is closed by the rule, and the third one from outside.
        # Owner order 2026-10-13 (third note): the card's last view is the
        # ranking itself now, because the cadence sentence it used to carry
        # has moved below the fourth rule. Owner order 2026-11-01: the
        # seam between QUANT STATUS and the W/L tile carries a diamond
        # rule of its own, so that third seam reads rule, tile, rule:
        # both edges of the new tile are marked, nothing else intervenes.
        after_status = siblings_after(
            root, parent_of(root, find_view(root, "@+id/status_pill")))
        self.assertEqual(after_status[0].tag, "include",
                         "status: no rule between status and W/L")
        self.assertEqual(after_status[0].get("layout"), "@layout/qor_rule")
        self.assertEqual(after_status[0].get(ANDROID_NS + "id"),
                         "@+id/rule_status_winloss")
        self.assertEqual(after_status[1].tag, "LinearLayout",
                         "status: no W/L tile after its rule")
        self.assertEqual(after_status[1].get(ANDROID_NS + "id"),
                         "@+id/tile_winloss")
        self.assertEqual(after_status[2].tag, "include",
                         "status: no rule after the W/L tile")
        self.assertEqual(after_status[2].get("layout"), "@layout/qor_rule")
        # Owner order 2026-11-01: the greeting is closed by the same rule
        # before the QUANT STATUS tile, so the page's first change of
        # subject is marked like every other one.
        greeting = siblings_after(root, find_view(root, "@+id/greeting"))
        self.assertEqual(greeting[0].tag, "include",
                         "greeting: no rule before QUANT STATUS")
        self.assertEqual(greeting[0].get(ANDROID_NS + "id"),
                         "@+id/rule_greeting")
        self.assertEqual(greeting[1].get(ANDROID_NS + "id"),
                         "@+id/tile_status")
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
        # Owner order 2026-11-27: the typed letters inside a matching scrip
        # are the one bold run this console draws, and they take the real
        # face's bold, never a legacy fallback.
        self.assertIn("new StyleSpan(Typeface.BOLD)", self.main)

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
        # Owner order 2026-11-05, eighth pass: three lines per scrip. The
        # measured B and S stand on their own line with the unclear U beside
        # them, then T with the money line; nothing is folded into a side.
        self.assertIn("sb.append('\\n').append(\"(B=\");", self.main)
        self.assertIn('sb.append(", S=");', self.main)
        self.assertIn('sb.append(", U=");', self.main)
        # Owner order 2026-11-06: T takes the next line, not the split's.
        self.assertIn('append("T=");', self.main)
        self.assertNotIn('sb.append(any ? " & T=" : "T=");', self.main)
        self.assertNotIn("completePair", self.main)
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
        # search page's own rule back above the search tile. v2.2.4
        # made eight; owner order 2026-11-01 makes NINE - the same four
        # and the W/L tile's own seam rule above it. Owner order
        # 2026-11-04 (second pass) makes TWELVE: the ORDER FLOW page is a
        # division of its own, bracketed above and below. Owner order
        # 2026-11-04 (third pass): the seam between the page's two tiles
        # carries the diamond that left the pair under BIG BUYING &
        # SELLING, and the console carried THIRTEEN. Owner order
        # 2026-11-04 (fourth pass): the extra seam below BIG BUYING &
        # SELLING is gone with the include, so the console carried
        # TWELVE. Owner order 2026-11-06: the SECTORS tile's own rule above
        # it makes THIRTEEN.
        self.assertEqual(len(rules), 13)
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

        The fix keeps one scheduling point in the tick itself. A response
        that lands inside the second does not push the next poll out, and
        scheduleNext removes the runnable before re-posting it.
        """
        render = self.main[self.main.index("private void render(boolean online"):]
        render = render[:render.index("private String latestSignalDisplay(")]
        # The tick owns the cadence: a response that lands inside the
        # one-second window must not push the next poll another second out.
        self.assertNotIn("scheduleNext();", render)
        self.assertIn("cadence.removeCallbacks(tick);", self.main)
        self.assertEqual(self.main.count("scheduleNext();"), 2,
                         "onResume and the tick: one scheduling point")

    def test_system_tile_has_quant_title_without_polling_status_copy(self):
        """The status tile reports relay data, not local polling cadence."""
        strings = STRINGS.read_text(encoding="utf-8")
        self.assertIn('name="label_system">QUANT STATUS</string>', strings)
        self.assertNotIn('name="app_live"', strings)
        self.assertNotIn("polling every", strings.lower())
        self.assertNotIn("live polling", strings.lower())
        render = self.main[self.main.index("private void render(boolean online"):]
        render = render[:render.index("private String latestSignalDisplay(")]
        # Owner order 2026-11-25: the Karachi seconds advance once per
        # second from the relay's own last stamp, so the face reads like a
        # clock between health answers instead of jumping every five.
        self.assertIn("statusDetail.setText("
                      "clockSpans(advanceRelayClock(actualDetail)));", render)
        clock = self.main[self.main.index("private String advanceRelayClock("):]
        clock = clock[:clock.index("private SpannableString clockSpans(")]
        self.assertIn("SystemClock.elapsedRealtime()", clock)
        self.assertIn("relayClockMillis + (now - relayClockAt)", clock)
        self.assertIn('"Asia/Karachi"', clock)
        self.assertIn('"dd MMM yyyy HH:mm:ss"', clock)
        self.assertNotIn("liveLine()", render)
        self.assertNotIn("Watcher.FAST_POLL_MS", render)
        # Owner order 2026-11-26: the word KARACHI left the tile, so the
        # status sentence is the relay's stamp alone.
        watcher = WATCHER.read_text(encoding="utf-8")
        self.assertNotIn("Karachi: ", watcher)
        self.assertIn("new StringBuilder(clockLine(karachi))", watcher)

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
        # Owner order 2026-11-04: the guard is unchanged, and it now sits
        # behind the one-request-a-tick page rule, so a page that already
        # asked for its own numbers never spends the card read as well.
        self.assertIn("if (!pageOwnsTheTick && !liveInFlight) {",
                      self.main[poll:poll + 1600])
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
        # Owner order 2026-11-06: the SECTORS read is the fifth callback
        # that releases its reference instead of painting a finished page.
        self.assertEqual(self.main.count("isFinishing() || isDestroyed()"), 5)
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
        self.assertIn(
            "private static void applyLiveQuotes(Context c, Market market, String base)",
            watcher)
        self.assertIn('get(c, base + "/quotes", null)', watcher)
        self.assertIn("if (index != null && index.optBoolean(\"fresh\", false))", watcher)
        self.assertIn("!quote.optBoolean(\"fresh\", false)", watcher)
        self.assertIn(
            "async function applyLiveQuotes(env, snapshot, quotes, now, "
            "ackDay)", worker)
        full = watcher[watcher.index("static void fetchStatus("):][:1200]
        self.assertIn("applyLiveQuotes(c, market, base);", full)
        live = watcher[watcher.index("static void fetchLive("):]
        live = live[:live.index("static void fetchStatus(")]
        # Owner order 2026-10-22 (second report on the lag): the card read is
        # RACED against the health read, so a tick costs one round trip of
        # wait, not two stacked ones.
        self.assertIn("marketJob = CARD_POOL.submit(() -> fetchMarket(c, base));",
                      live)
        self.assertIn("Market market = marketJob.get(9, TimeUnit.SECONDS);", live)
        self.assertNotIn("applyLiveQuotes(c, market, base);", live)
        # Owner order 2026-11-05 (seventh pass, the relay's daily Durable
        # Object budget): the status and signal read rides every fifth tick,
        # so one phone tick is one relay request for the card alone.
        self.assertIn("static final long HEAD_GAP_MS = 5000;", watcher)
        self.assertIn("headDue ? HEALTH_POOL.submit", live)
        self.assertIn("head = lastHead;", live)

    def test_the_phone_stops_itself_at_its_share_of_the_daily_allowance(self):
        """Owner order 2026-11-09: the phone keeps the console's hard stop.

        The Windows console already refuses every request at 90,000 a day
        (reqHardCap). Two processes that each capped at 90,000 could still
        spend 180,000 of a 100,000 allowance, so the phone takes the share
        that keeps the total under the line: 8,000 for the app and 2,000 for
        the relay. The count is per UTC day and it is written to the app's own
        preferences BEFORE the socket opens, so a restart cannot hand back
        requests the day has already spent.
        """
        watcher = WATCHER.read_text(encoding="utf-8")
        console = (ROOT / "windows" / "app.go").read_text(encoding="utf-8")
        self.assertIn("const reqHardCap = 90000", console)
        self.assertIn("static final long DAILY_REQUEST_CAP = 8000;", watcher)
        console_cap = int(console.split("const reqHardCap = ")[1].split("\n")[0])
        phone_cap = int(watcher.split("DAILY_REQUEST_CAP = ")[1].split(";")[0])
        self.assertLess(console_cap + phone_cap, 100000,
                        "the two caps together must stay under the free allowance")
        # Every relay read in the class leaves through one door, and that door
        # refuses before it opens a socket.
        door = watcher[watcher.index("private static JSONObject get("):
                       watcher.index("private static JSONObject healthWithRetry(")]
        self.assertIn("if (!reserveRequest(c)) {", door)
        self.assertIn("throw new DailyCapSpent();", door)
        self.assertLess(door.index("throw new DailyCapSpent();"),
                        door.index("openConnection()"))
        # The count is written before the request leaves, keyed by the UTC day.
        reserve = watcher[watcher.index("static boolean reserveRequest(Context c) {"):
                          watcher.index("private static JSONObject get(")]
        self.assertIn("putString(CAP_DAY_KEY, capDay)", reserve)
        self.assertIn("putLong(CAP_COUNT_KEY, capCount)", reserve)
        self.assertIn('java.util.TimeZone.getTimeZone("UTC")', watcher)
        # A spent cap is never worded as a relay fault, and the retrying health
        # read does not keep knocking on a door the cap has closed.
        self.assertIn("if (cause instanceof DailyCapSpent) {", watcher)
        self.assertIn("allowance is spent", watcher)
        self.assertIn("if (e instanceof DailyCapSpent) {", watcher)

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
        live_body = watcher[live:live + 2000]
        self.assertIn("marketJob = CARD_POOL.submit(() -> fetchMarket(c, base));",
                      live_body)
        self.assertIn("head.signals, market);", live_body)
        poll = self.main.index("private void pollOnce()")
        # Owner order 2026-11-04: still one card read a tick on the deck,
        # skipped only when another page owns that tick's single request.
        self.assertIn("refreshLive();", self.main[poll:poll + 1600])
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
        # Owner order 2026-11-01: the W/L tile's own rule hides with the
        # console too (a fourth seam of the same group).
        for name in ("rule_greeting", "tile_status", "rule_status_winloss",
                     "rule_status_signal", "tile_signal",
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
        # Owner order 2026-11-26: the clock stays; only its KARACHI label left
        # the tile.
        self.assertNotIn("Karachi: ", WATCHER.read_text(encoding="utf-8"))
        self.assertIn("clockLine(karachi)", WATCHER.read_text(encoding="utf-8"))
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
        # v2.3.17 is owner order 2026-10-27, twenty-first pass ("increase
        # all the drop down and search box heights by 30% from their
        # current height", and "I don't like the LINES right now,
        # increase the length of all the LINES by 20%"): all three
        # field boxes carry one universal 29dp now (23 * 1.3 = 29.9,
        # floored to 29dp, the same exact setting) and every filament's
        # swing floor lifts exactly 20% (0.70 * 1.2 = 0.84) with the
        # ceiling still pinned at the dots by the standing inward law.
        # v2.3.18 is owner order 2026-10-27, twenty-second pass ("increase
        # all the dropdown/search boxes heigh by another 50% from their
        # current height", and "the animating LINES, some of them are
        # open, I mean to say that while moving, some of the LINES just
        # end with the dots, all the LINES should be interconnected with
        # each other"): all three field boxes carry one universal 43dp
        # now (29 * 1.5 = 43.5, floored to 43dp, the same exact setting)
        # and the cloud's mesh is made WHOLE - the web's parts named by
        # union-find, the shortest pair across two parts joined until
        # one mesh remains, so no line can end at a dot no other thread
        # carries on from.
        # v3.7.4 (owner order 2026-11-01, after the 3.7.3 screenshot of
        # BLACK & WHITE): each themed plate is copied per view, the
        # diamond rules wear the second colour, versionCode 104.
        manifest = MANIFEST.read_text(encoding="utf-8")
        # Owner order 2026-11-04: v4.0.0, the ORDER FLOW page. v4.0.1 is
        # the big prints relay side; v4.0.2 is the third-pass page; v4.0.3
        # is the fourth pass; v4.0.4 is the fifth pass. v4.0.5 is the sixth
        # pass: his new ORDER FLOW picture, the bracketed top three, the
        # eight-print board with its visible bar, and the search-only
        # ORDER FLOW tile.
        # Owner report 2026-11-06: the sector menu's dividers, the always
        # listed sector stocks and the U+T bracket ship as 4.0.14.
        # Owner order 2026-11-07: the KSE100 closing bracket after T, yellow
        # U everywhere, the two column BID/ASK book with eight fills, the
        # themed ORDER FLOW page and the search H/L ship as 4.0.15.
        # Owner order 2026-11-07, second pass: the themed SECTORS tile, the
        # far-right ASK column and the blue total volume ship as 4.0.16.
        # Owner order 2026-11-09: the phone's own hard daily relay request
        # stop ships as 4.0.17. Owner order 2026-11-11: the themed caret,
        # the diamond scroller and the always-moving orb ship as 4.0.18.
        # The second pass on 2026-11-11 ships as 4.0.19; the third pass
        # ships as 4.0.20. Owner order 2026-11-12: the phone's CUSTOM
        # SCRIPS OF VOL. menu names all six sorts the console carries, and
        # it ships as 4.0.21.
        # Owner order 2026-11-16: the uniform centred menu rows and the
        # uncut SECTORS window ship as 4.4.1. Owner order 2026-11-17: the
        # centred closed dropdown faces, the centred print board and the
        # populated, scrolling SECTORS tile ship as 4.4.2, versionCode 135.
        # Owner order 2026-11-19: the two-theme menu, the 43dp RELAY STATUS
        # box, numbered sub menus, H & L, the always-listed SECTORS tile,
        # the 100k board and its five complete orders ship as 4.4.3,
        # versionCode 136.
        # Owner order 2026-11-23: an empty SEARCH or ORDER FLOW box lists
        # nothing, and a search option is the volume tile's own scrip.
        # Owner order 2026-11-24: the SEARCH and ORDER FLOW menus wear the
        # volume drop down's own law with no caret, the QUANT STATUS clock
        # carries seconds and the date as "24 Nov 2026", and the KSE100
        # leaders put the price and its percentage in front of the scrip.
        # Owner order 2026-11-25 (latest): the scrip leads, then its price,
        # then its percentage, on the KSE100 tile and in the same exact way
        # on CUSTOM SCRIPS OF VOLUME; the SECTORS menu prints its
        # percentages on the first price tick instead of only after a page
        # round trip; and the SEARCH and ORDER FLOW instant searches list
        # the scrip alone, with the details waiting on a pick.
        # Owner order 2026-11-25 (evening): the SEARCH and ORDER FLOW boxes
        # are the CUSTOM SCRIPS OF VOL. box itself - one plate, the centred
        # face, the caret at its trailing edge, the options as the volume
        # menu's own rows without a pill or a track - and the QUANT STATUS
        # seconds advance every second between relay answers.
        # Owner order 2026-11-27: the SEARCH tile is the ORDER FLOW tile until
        # a tap, the tapped answer prints H green and L red, and the Jarvis
        # core replaces the photographed sun. Second pass that day: both
        # search boxes take their 43dp plate back, a match is a scrip that
        # STARTS with the typed letters, the frames and the scan line leave
        # the orb, and the greeting wears the tagline's face. Third pass that
        # day: the greeting is 18.3sp, the compass circle takes the outside
        # start of the ticks, the SECTORS tile lists all eight, and the two
        # search boxes are the scrip row's 32dp.
        # They ship as 4.5.3, versionCode 147.
        self.assertIn('android:versionName="4.5.3"', manifest)
        self.assertIn('android:versionCode="147"', manifest)
        # Owner order 2026-11-24: no part of either build's version reads above
        # ten, so 3.10.10 is followed by 4.0.0 and .11 never exists.
        shipped = manifest.split('android:versionName="', 1)[1].split('"', 1)[0]
        for part in shipped.split("."):
            self.assertLessEqual(int(part), 10, shipped)
        self.assertNotIn('android:versionName="4.0.15"', manifest)
        self.assertNotIn('android:versionName="4.0.14"', manifest)
        self.assertNotIn('android:versionName="3.7.5"', manifest)
        self.assertNotIn('android:versionName="3.7.4"', manifest)
        self.assertNotIn('android:versionName="3.7.3"', manifest)
        self.assertNotIn('android:versionName="3.7.2"', manifest)
        self.assertNotIn('android:versionName="3.7.1"', manifest)
        self.assertNotIn('android:versionName="3.6.3"', manifest)
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
        # v3.3.0 (owner order 2026-10-30): one feed / one truth, the tick
        # never stalls, the dropdown rows move up into the mount, the
        # four-icon tile 4% down, versionCode 93.
        self.assertIn("Version 3.3.0, versionCode 93", readme)
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
        # v2.3.17 (owner order 2026-10-27, twenty-first pass): the three
        # field boxes 30% taller onto the one universal 29dp, and every
        # filament's swing floor 20% longer with the ceiling at its
        # dots, versionCode 84.
        self.assertIn("Version 2.3.17, versionCode 84", readme)
        # v2.3.18 (owner order 2026-10-27, twenty-second pass): the
        # three field boxes 50% taller onto the one universal 43dp, and
        # the cloud's mesh made whole by the shortest bridge across
        # every two parts, versionCode 85.
        self.assertIn("Version 2.3.18, versionCode 85", readme)
        # v2.3.19 (owner order 2026-10-28, twenty-third pass): the sun
        # drawn BETWEEN the cloud's two depth halves so the star stands
        # inside the revolving lines, every orphan node tied into the
        # one mesh so no filament ends at an unlinked dot, the menu
        # reveal walks its page scroll to the opened menu (no window
        # over the fold), and the search menus' quote tail carries the
        # comma after B, the ampersand before T and the arrows, not
        # plus and minus, versionCode 86.
        self.assertIn("Version 2.3.19, versionCode 86", readme)
        # v2.3.20 (owner order 2026-10-28, twenty-fourth pass): the
        # relay status button joins the themed fields, the closed
        # themes box restamps its label every pass, and both inline
        # menus retire their bordered popup plate with the 2dp gap -
        # an open menu is the box's own expansion now, versionCode 87.
        self.assertIn("Version 2.3.20, versionCode 87", readme)
        # v2.3.21 (owner order 2026-10-28, twenty-fifth pass): the drop
        # down box expands itself (one group, one plate, no seam), the
        # menu bar's icons and the dropdown arrows ink from the worn
        # theme's accent, and the themed tiles carry the shipped plate's
        # two-tone depth with the theme's OWN edge, versionCode 88.
        self.assertIn("Version 2.3.21, versionCode 88", readme)
        # v2.3.22 (owner order 2026-10-29, twenty-sixth pass): the open
        # menu is its option rows alone - the closed box's own label
        # steps out while the menu is open, the dropdown icon is the
        # roll-up, the THEMES box carries the same law, versionCode 89.
        self.assertIn("Version 2.3.22, versionCode 89", readme)
        # v3.0.0 (owner order 2026-10-29): the app's version law itself
        # moves to the 3 series - "from now on make sure you start with
        # version 3 for the app" - so this build is versionCode 90 /
        # versionName 3.0.0 and no 2.x number is stamped again.
        self.assertIn("Version 3.0.0, versionCode 90", readme)
        # v3.3.0 (owner order 2026-10-30, the numbers order): the dropdowns
        # open above the boxes, the icon tile rides 4% down, and every row
        # of the card prints ONE truth from one frame, versionCode 93. Each
        # release stamps its heading into the running changelog, so every
        # shipped heading keeps its own pin (SO-3).
        self.assertIn("Version 3.3.0, versionCode 93", readme)
        # v3.4.0 (owner order 2026-10-30): the caret keeps the mount's
        # own top station, the open menu's rows carry the 43dp field
        # law, the theme highlight is its own ring (white on navy, black
        # and orange), and the icons tile's height is a law of 74dp;
        # versionCode 94.
        self.assertIn("Version 3.4.0, versionCode 94", readme)
        # v3.5.0 (owner order 2026-10-31): a divider line between two
        # adjacent sub menu options, equal air above and below it, in
        # both open menus; versionCode 95.
        self.assertIn("Version 3.5.0, versionCode 95", readme)
        # v3.6.0 (owner order 2026-10-31, the data's own build): one
        # acknowledged frame per stock across the app, the B/S pair that
        # can never decrease in the day, versionCode 96.
        self.assertIn("Version 3.6.0, versionCode 96", readme)
        # v3.6.1 (owner's orders of 2026-10-31): the balanced edge air in
        # both dropdown menus, the nav tile's re-pinned size laws, and the
        # W/L = W/L RATE tile between the quant status and latest signal
        # tiles, versionCode 97.
        self.assertIn("Version 3.6.1, versionCode 97", readme)
        # v3.6.2 (owner's orders of 2026-11-01): the caret at the exact
        # vertical middle of its face in both dropdowns, the W/L tile's
        # own diamond rule, the "&" heading and the digits-only
        # "0/1 & 100%" line coloured by the leading side, versionCode 98.
        self.assertIn("Version 3.6.2, versionCode 98", readme)
        # v3.6.3 (owner's orders of 2026-11-01, later that day): the
        # greeting's own diamond rule, the open caret at the exact centre
        # of the whole plate, one newest frame per symbol on every
        # surface, and the pinned answer rebuilt from the live quote,
        # versionCode 99.
        self.assertIn("Version 3.6.3, versionCode 99", readme)
        # v3.7.0 (owner order 2026-11-01, the day's closing build): the
        # APK that followed the engine fixes, versionCode 100.
        self.assertIn("Version 3.7.0, versionCode 100", readme)
        # v3.7.1 (owner order 2026-11-01, after the 3.7.0 build): the
        # carets centred on the first option's wording, versionCode 101.
        self.assertIn("Version 3.7.1, versionCode 101", readme)
        # v3.9.0 (owner order 2026-11-02): W/L counts a stop or target hit
        # immediately, versionCode 108.
        self.assertIn("Version 3.9.0, versionCode 108", readme)
        # v3.7.7 (owner order 2026-11-02, after 3.7.6): the relay quote store
        # is monotone for total volume and the B/S pair, the signal tile
        # says Target Price, and the tick owns the one-second cadence.
        self.assertIn("Version 3.7.7, versionCode 107", readme)
        # v3.7.6 (owner order 2026-11-02, on the active CNERGY signal):
        # the ticker, its real entry time and three prices, with Exit
        # green and Stop Loss red, versionCode 106.
        self.assertIn("Version 3.7.6, versionCode 106", readme)
        self.assertIn("Version 3.7.5, versionCode 105", readme)
        self.assertIn("Version 3.7.4, versionCode 104", readme)
        self.assertIn("Version 3.7.3, versionCode 103", readme)
        self.assertIn("Version 3.7.2, versionCode 102", readme)
        # v3.1.0 (owner order 2026-10-29, twenty-eighth pass): the open
        # menu keeps its anchored line and the rows type in the box's
        # own column, and the menu tile rides 7% of the screen higher.
        self.assertIn("Version 3.1.0, versionCode 91", readme)
        # v3.2.0 (owner order 2026-10-29, the photo order): the open menu's
        # rows move up into the closed face's empty strip, both dropdowns.
        self.assertIn("Version 3.2.0, versionCode 92", readme)
        manifest = MANIFEST.read_text(encoding="utf-8")
        # v4.0.1 (owner order 2026-11-04, second pass): the ORDER FLOW page
        # rebuilt as a scrip search plus the big buying and selling tile.
        # v4.0.2 (owner order 2026-11-04, third pass): the page's seam
        # between its two tiles. v4.0.3 (owner order 2026-11-05, fourth
        # pass): the owner's own icon, no seam after the page's second
        # tile, the live book in the search rows, and the scrollable big
        # prints board. v4.0.4 (fifth pass) is that pass minus the split
        # rows; v4.0.5 (sixth pass) is his new ORDER FLOW picture, the
        # bracketed top three, the eight-print scrolling board with its
        # visible bar, and the search-only ORDER FLOW tile.
        # Owner order 2026-11-07, second pass: the themed SECTORS tile, the
        # far-right ASK column and the blue total volume ship as 4.0.16.
        # Owner order 2026-11-09: the phone's own hard daily relay request
        # stop ships as 4.0.17. Owner order 2026-11-11: the themed caret,
        # the diamond scroller and the always-moving orb ship as 4.0.18.
        # The second pass on 2026-11-11 ships as 4.0.19; the third pass
        # ships as 4.0.20. Owner order 2026-11-12: the phone's CUSTOM
        # SCRIPS OF VOL. menu names all six sorts and ships as 4.0.21.
        # Owner order 2026-11-13: the shared print sentence, themed print
        # time, retained large prints, the six-row sorted SECTORS window and
        # NET DELTA ship as 4.3.8. Owner order 2026-11-15: the theme-inked
        # orb, the 1M board, the Karachi print clock and the shorter menus
        # ship as 4.3.9. Owner order 2026-11-15: the tappable SECTORS face
        # and the KSE100 B/S fallback ship as 4.4.0. Owner order
        # 2026-11-16: the balanced, centred menu rows ship as 4.4.1.
        # 2026-11-17: the centred closed faces and the SECTORS fix ship as
        # 4.4.2, versionCode 135. The owner's 2026-11-19 order ships as
        # 4.4.3, versionCode 136.
        # Owner order 2026-11-24: the SEARCH and ORDER FLOW menus wear the
        # volume drop down law with no caret, QUANT STATUS reads seconds and
        # the owner's date shape, and the leaders' money group stands in
        # front of the scrip. Owner order 2026-11-25: the scrip leads then
        # the money on both tiles, the SECTORS menu stamps its percentages on
        # the first tick, and the instant searches list the scrip alone until
        # a pick. Owner order 2026-11-25 (evening): the two searches wear the
        # CUSTOM SCRIPS OF VOL. box and its caret, and the QUANT STATUS clock
        # moves every second. Owner order 2026-11-26: KARACHI leaves the tile,
        # the clock steps on the tick, both search boxes type from the left
        # with no caret and a hairline over their first option, and an option
        # carries its quote with the day range. Owner order 2026-11-27: the
        # SEARCH option is the scrip alone until a tap, H green and L red
        # print on the tap, and the Jarvis core replaces the sun. Second pass
        # that day: the two boxes are 43dp, only a scrip STARTING with the
        # typed letters matches, the orb loses its frames and its scan line,
        # and the greeting wears the PSX's KMIALL INDEX face. Third pass that
        # day: the greeting is 18.3sp, the compass circle takes the outside
        # start of the ticks, the SECTORS tile lists all eight, and the two
        # search boxes are the scrip row's 32dp. They ship as 4.5.3,
        # versionCode 147.
        self.assertIn('android:versionCode="147"', manifest)
        self.assertIn('android:versionName="4.5.3"', manifest)
        self.assertNotIn('android:versionName="4.0.15"', manifest)
        self.assertNotIn('android:versionName="3.7.5"', manifest)
        self.assertNotIn('android:versionName="3.7.4"', manifest)
        self.assertNotIn('android:versionName="3.7.3"', manifest)
        self.assertNotIn('android:versionName="3.7.2"', manifest)
        self.assertNotIn('android:versionName="3.7.1"', manifest)
        self.assertNotIn('android:versionName="3.6.3"', manifest)
        self.assertNotIn('android:versionName="3.5.0"', manifest)
        self.assertNotIn('android:versionName="3.3.0"', manifest)
        layout = LAYOUT.read_text(encoding="utf-8")
        strings = STRINGS.read_text(encoding="utf-8")
        main = MAIN.read_text(encoding="utf-8")
        watcher = WATCHER.read_text(encoding="utf-8")
        self.assertNotIn('android:id="@+id/market_feed_status"', layout)
        self.assertNotIn('name="market_feed_unknown"', strings)
        self.assertNotIn('name="market_feed_halted"', strings)
        # v1.7.6: the feed-status line is gone and the card shows the broker
        # stamp instead; the signal tile keeps the ticker, entry time and
        # three prices, with no header metadata.
        self.assertNotIn("renderMarketFeedStatus", main)
        # v1.7.9 (owner order 2026-10-20, third note): the index line carries
        # no clock at all, so the stamp reader is gone with it.
        self.assertNotIn("brokerClock", main)
        self.assertIn("latestSignalBackground = s;", main)
        self.assertIn("signalList.setText(signalInk(latestSignalDisplay(actualSignals)));", main)
        # v1.7.7: the three numbers, the entry time and the ticker live in
        # SignalText, and the console only maps its two word states onto
        # resources.
        signal_text = SIGNAL_TEXT.read_text(encoding="utf-8")
        self.assertIn("String text = SignalText.compact(raw, remembered);", main)
        self.assertIn("SignalText.entryTime(raw)", main)
        self.assertIn("signal_entry_time_", main)
        self.assertIn("SignalText.NO_TRADE.equals(text)", main)
        self.assertIn("SignalText.UNAVAILABLE.equals(text)", main)
        self.assertIn("Entry Time: ", signal_text)
        self.assertLess(signal_text.index('"Entry Time: "'),
                        signal_text.index('"Entry Price: "'))
        self.assertIn("Entry Price: ", signal_text)
        self.assertIn("Target Price: ", signal_text)
        self.assertIn("Stop Loss: ", signal_text)
        self.assertIn('return value == null ? NOT_REPORTED : value;', signal_text)
        self.assertIn('afterLabel(line, "Target:")', signal_text)
        self.assertIn("private static String leadingPrice(String value)", signal_text)
        self.assertIn("String numeric = leadingPrice(value);", signal_text)
        self.assertIn('price > 0.0 && !Double.isNaN(price)', signal_text)
        self.assertIn("if (numeric != null) {", signal_text)
        # The tile is the ticker, time and numbers: no header, no date, no
        # rule prose.
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

    def test_an_empty_box_lists_nothing_until_he_types(self):
        """Owner order 2026-11-23: the SEARCH page opens on an empty box that
        lists no scrip at all, and the ORDER FLOW tile does the same. Build
        155 printed the whole list on an empty box, which is the regression
        this guards: the first letter opens the matches and clearing the box
        closes the list again."""
        main = MAIN.read_text(encoding="utf-8")
        start = main.index("private void renderSearchResults(")
        block = main[start:main.index("private void styleSearchRow(", start)]
        self.assertIn("if (q.isEmpty()) {", block)
        self.assertIn("searchResults.setVisibility(View.GONE);", block)
        # Owner order 2026-11-27 (second pass): a match is a scrip whose
        # symbol STARTS with the typed letters, so PR lists the PR names and
        # never FPRM.
        self.assertIn("if (symbol.toUpperCase(Locale.US).startsWith(q)) {", block)
        self.assertNotIn("symbol.toUpperCase(Locale.US).contains(q)", block)
        flow = main[main.index("private void renderFlowResults("):
                    main.index("private View flowTableRow(")]
        self.assertIn("if (query.isEmpty()) {", flow)
        self.assertIn("row.symbol.toUpperCase(Locale.US).startsWith(query)",
                      flow)
        self.assertNotIn("row.symbol.contains(query)", flow)
        # Owner order 2026-11-25 (evening): the box and its own caret are the
        # CUSTOM SCRIPS OF VOL. box's, and the tall six-row window with its
        # diamond track left the tile with the list he struck out.
        self.assertNotIn("fitSearchWindow", main)
        self.assertNotIn("fitFlowWindow", main)
        self.assertNotIn("searchScroll.scrollTo", main)
        layout = LAYOUT.read_text(encoding="utf-8")
        # Owner order 2026-11-26: both carets are hidden, not drawn.
        for view_id in ("search_arrow", "order_flow_arrow"):
            with self.subTest(arrow=view_id):
                self.assertIn('android:visibility="gone"',
                              element(layout, 'android:id="@+id/%s"' % view_id))
        self.assertNotIn("@+id/search_scroll", layout)
        self.assertNotIn("@+id/search_scroller", layout)
        self.assertNotIn("@+id/order_flow_scroll", layout)
        self.assertNotIn("@+id/order_flow_scroller", layout)

    def test_a_search_option_is_the_scrip_alone(self):
        """Owner order 2026-11-25 (latest): "I don't want to see the details
        while I'm still searching and haven't selected any scrip." The SEARCH
        option is the scrip alone. CUSTOM SCRIPS OF VOLUME keeps its own
        builder and its own order: the scrip, its current price, its
        percentage, then the quantities."""
        main = MAIN.read_text(encoding="utf-8")
        self.assertIn("private void appendScripQuote(SpannableStringBuilder sb,",
                      main)
        self.assertIn("appendScripQuote(sb, quote);", main)
        reveal = main[main.index("private SpannableStringBuilder volumeRevealText("):
                      main.index("private void appendScripQuote(")]
        self.assertIn("appendScripQuote(sb, quote);", reveal)
        row = main[main.index("private void styleSearchRow("):
                   main.index("private GradientDrawable highlightPlate(")]
        # Owner order 2026-11-27: the tile is the ORDER FLOW tile, so the
        # option is the scrip alone and its details wait for the tap.
        self.assertIn("row.setText(scripMatchSpans(symbol, q));", row)
        self.assertNotIn("appendSearchQuote", row)
        self.assertNotIn("appendScripQuote", row)
        self.assertNotIn("PKR %,.2f", row)
        # The volume tile's own order (owner order 2026-11-25): the price and
        # the percentage stand on the scrip's line, ahead of the B line.
        scrip = main[main.index("private void appendScripQuote("):
                     main.index("private void colorQuantity")]
        self.assertLess(scrip.index('"PKR %,.2f"'), scrip.index('"(B="'))

    def test_the_search_menu_is_the_apps_own_dropdown(self):
        """Owner order 2026-11-21: the results are the same dropdown every
        other box on the console opens: one field plate around the box and
        its options, divided rows, the app's own option geometry."""
        layout = LAYOUT.read_text(encoding="utf-8")
        group = element(layout, 'android:id="@+id/search_field_group"')
        self.assertIn('android:background="@drawable/field_bg"', group)
        self.assertIn('android:orientation="vertical"', group)
        box = element(layout, 'android:id="@+id/search_input"')
        self.assertIn('android:background="@null"', box)
        # Owner order 2026-11-26: the typed letter and the hint read from the
        # LEFT edge now, and the drop-down/up icon is gone from both boxes.
        self.assertIn('android:gravity="center_vertical|start"', box)
        arrow = element(layout, 'android:id="@+id/search_arrow"')
        self.assertIn('@drawable/dropdown_arrow', arrow)
        self.assertIn('android:visibility="gone"', arrow)
        flow_box = element(layout, 'android:id="@+id/order_flow_input"')
        self.assertIn('android:gravity="center_vertical|start"', flow_box)
        main = MAIN.read_text(encoding="utf-8")
        self.assertIn('TextView row = menuRow("");', main)
        # Owner order 2026-11-24: the search options are the volume menu's
        # own rows and its own divider now, not the tighter list line.
        self.assertIn("searchResults.addView(menuDivider());", main)
        self.assertIn("searchResults.setVisibility(visible.isEmpty() || !searchListOpen",
                      main, "a pick closes the menu, the dropdown's own law")
        self.assertIn("searchFieldGroup.setBackground(fieldPlate(index));", main)

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
        paint = main[main.index("private void paintSelectedLine() {"):
                     main.index("private void paintSignalInk(")]
        marker = 'PKR %,.2f'
        first = paint.index(marker)
        tail = paint[first:]
        # v2.3.19 (owner order 2026-10-28, "there should be up or down
        # sign for percentage for search box"): the pinned line's move
        # carries the UP and DOWN arrows, never a plus or a minus, and
        # the number is the move's magnitude - the arrow IS the sign.
        self.assertIn("R.color.green_hi\n                            : R.color.red", tail)
        self.assertIn('"\\u25B2" : "\\u25BC"', tail)
        self.assertIn("Math.abs(quote.changePct)", tail)
        # A line with no move keeps the soft ink (SO-3: no fake arrow).
        self.assertIn("themeBodyInk", paint)
        # The drawn sign is retired with its colour law.
        self.assertNotIn("%+.2f%%", paint)

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
        # fetchStock no longer carries its own money line; the restamps
        # are the ONLY PKR lines the pinned answer shows.
        self.assertNotIn('"\\nPKR %,.2f"', watcher)
        self.assertLess(watcher.index("paintSelectedLine"),
                        watcher.index("restamps the live quote"))
        # The one money line lives in both restamps (v2.3.19's arrow law).
        marker = 'PKR %,.2f'
        window = main[main.index("private void styleSearchRow("):
                      main.index("private void paintSignalInk(")]
        # Owner order 2026-11-25 (latest): the list row carries no money at
        # all, so this window's only PKR lines are the two restamps (the
        # picked scrip's pinned base and its live rebuild).
        self.assertNotIn("appendScripQuote", window)
        self.assertEqual(window.count(marker), 2, window.count(marker))
        scrip = main[main.index("private void appendScripQuote("):
                    main.index("private void colorQuantity")]
        self.assertEqual(scrip.count(marker), 1, scrip.count(marker))

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
        # Owner order 2026-11-27 (third pass): "reduce the font size of the
        # greeting by 30% from its current font size" - 26.1 x 0.70 = 18.27,
        # rounded where every growth of this line rounded, to 18.3sp; the
        # body is still the one 13sp.
        self.assertEqual(sizes, {"13sp", "18.3sp"})
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
        # Owner order 2026-11-26: the box types from the LEFT edge, hint and
        # cursor alike, and still centres vertically in its 43dp plate.
        self.assertEqual(self.box.get(f"{ANDROID_NS}gravity"),
                         "center_vertical|start")

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
        # Owner order 2026-11-27 (second pass): "you have reduced the height
        # of search boxes for SEARCH and ORDER FLOW tiles." The 32dp drop of
        # that morning read as a shortened box, so the 43dp field plate is
        # back on both searches, the height every other field carries, with
        # the same 3dp air above and below the line.
        # Owner order 2026-11-27 (third pass): "make that space's height same
        # as the height of the search results scrips" - the box is the 32dp
        # every scrip row wears, the plate measure again, with the same air.
        self.assertEqual(self.box.get(f"{ANDROID_NS}paddingTop"), "3dp")
        self.assertEqual(self.box.get(f"{ANDROID_NS}paddingBottom"), "3dp")
        self.assertEqual(self.box.get(f"{ANDROID_NS}paddingLeft"), "10dp")
        self.assertEqual(self.box.get(f"{ANDROID_NS}paddingRight"), "10dp")
        # v2.3.18 (owner order 2026-10-27, twenty-second pass: "increase
        # all the dropdown/search boxes heigh by another 50% from their
        # current height"): the growth lands on the height the box
        # wears - 29 * 1.5 = 43.5, floored to 43dp - and the air stays
        # 3dp above and below the line, the same numbers every other
        # field box carries - and no floor is named again under the
        # height it retired.
        self.assertEqual(self.box.get(f"{ANDROID_NS}layout_height"),
                         "32dp")
        self.assertIsNone(self.box.get(f"{ANDROID_NS}minHeight"))
        self.assertIn('android:layout_height="32dp"',
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
        self.assertIn("themeBodyInk : brighten(themeBodyInk)", block)
        self.assertIn("signalList.setAlpha(1.0f);", block)

    def test_no_dimmed_placeholder_survives(self):
        self.assertNotIn("signalList.setAlpha(0.65f)", self.main)

    def test_soft_is_the_body_ink(self):
        styles = STYLES.read_text(encoding="utf-8")
        body = styles[styles.index('name="QorBody"'):]
        self.assertIn("@color/text_soft", body[:body.index("</style>")])


class SignalTradeInkTest(unittest.TestCase):
    """Owner order 2026-11-02, on the active CNERGY signal: the entry
    time stands between the ticker and the entry price, Target Price is
    green and Stop Loss is red, and an unreported field keeps body ink."""

    def test_exit_is_green_and_stop_is_red(self):
        main = MAIN.read_text(encoding="utf-8")
        block = main[main.index(
            "private CharSequence signalInk(String display) {"):]
        block = block[:block.index("private void paintSignalInk")]
        self.assertIn('paintSignalLine(styled, "Target Price: ", R.color.green);',
                      block)
        self.assertIn('paintSignalLine(styled, "Stop Loss: ", R.color.red);',
                      block)
        self.assertIn("SignalText.NOT_REPORTED", block)
        self.assertIn(
            "signalList.setText(signalInk(latestSignalDisplay(actualSignals)));",
            main)

    def test_entry_time_stands_before_the_entry_price(self):
        source = SIGNAL_TEXT.read_text(encoding="utf-8")
        self.assertLess(source.index('"Entry Time: "'),
                        source.index('"Entry Price: "'))
        self.assertIn("Matcher when = ENTRY_TIME.matcher(raw);", source)
        self.assertIn("entryStamp = entryTime(text);", source)
        self.assertIn("symbolName(value)", source)


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
        row = "B 12,626,814, S 25,253,629, U 1,234,567"
        self.assertLess(self.width(row), self.available())

    def test_nine_digit_counts_fit_too(self):
        row = "T 1,101,880,443  PKR 1,234.56 \u25B2 9.72%"
        self.assertLess(self.width(row), self.available())

    def test_the_tracking_is_what_makes_13sp_fit(self):
        # The three-line rows are shorter than the old bracket, so the tile
        # keeps its measured negative tracking rather than shrinking type.
        self.assertLess(self.TRACKING, 0.0)
        layout = LAYOUT.read_text(encoding="utf-8")
        leaders = layout[layout.index("@+id/market_leaders"):]
        leaders = leaders[:leaders.index("/>\n")]
        self.assertIn(f'android:letterSpacing="{self.TRACKING}"', leaders)

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
        # Owner order 2026-11-04: the tile names the index it follows by its
        # own name, KSE100, in place of the generic word THE INDEX.
        self.assertIn('name="label_market">KSE100 INDEX &amp; THE TOP 3 '
                      'SCRIPS OF VOLUME<', strings)

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
        # Owner order 2026-11-27 (second pass): "change the greeting font to
        # the same font that is for the PSX'S KMIALL INDEX" - LEMON MILK
        # Light, the tagline's face, and only the face: same 26.1sp, same
        # seam, same ink.
        self.assertIn('android:fontFamily="@font/lemonmilk_light"', greeting)
        self.assertNotIn('@font/bonskin', greeting)
        # Owner order 2026-11-27 (third pass): the same face, 30% smaller -
        # 26.1 x 0.70 = 18.27, rounded to 18.3sp.
        self.assertIn('android:textSize="18.3sp"', greeting)
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

    def test_the_themes_tile_carries_two_looks(self):
        """Owner order 2026-11-19: GREEN & YELLOW, NAVY BLUE & WHITE and
        ORANGE & WHITE are removed, leaving purple and black."""
        self.assertIn('name="label_themes">THEMES<', self.strings)
        self.assertIn('name="theme_purple">PURPLE &amp; YELLOW<', self.strings)
        self.assertIn('name="theme_black">BLACK &amp; WHITE<', self.strings)
        self.assertNotIn('name="theme_green"', self.strings)
        self.assertNotIn('name="theme_navy"', self.strings)
        self.assertNotIn('name="theme_orange"', self.strings)
        spinner = element(self.layout, 'android:id="@+id/theme_spinner"')
        # v2.3.16: the closed box is its own one-line TextView at the
        # universal height, and its menu is the box's OWN inline list
        # (theme_menu) - no platform spinner, no popup window anywhere.
        # v2.3.18 grows that universal height 50% onto 43dp.
        self.assertIn("<TextView", spinner)
        self.assertIn('android:layout_height="43dp"', spinner)
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
        # The owner's 2026-11-19 order leaves two rows in the menu.
        self.assertIn("R.string.theme_purple, R.string.theme_black};",
                      self.main)
        self.assertIn("if (themeIndex > 1) {", self.main)

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
        # Owner order 2026-11-21: SECTORS has no caret any more; only the
        # two choosing dropdowns keep one.
        for view_id in ("volume_split_arrow", "theme_arrow"):
            with self.subTest(arrow=view_id):
                arrow = element(self.layout, f'android:id="@+id/{view_id}"')
                # v3.7.2 (owner order 2026-11-01): the caret is back at
                # the trailing edge, 14dp in, so the wording reads from
                # the plate's own 10dp column in the faces and menuRow.
                self.assertIn('android:layout_gravity="end|top"',
                              arrow)
                self.assertIn('android:layout_marginEnd="14dp"', arrow)
                self.assertIn('android:layout_marginTop="11dp"', arrow)
                self.assertNotIn("android:layout_marginStart", arrow)
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

    def test_every_dropdown_caret_wears_the_themes_second_colour(self):
        """Owner order 2026-11-01: the dropdown's colour follows the
        theme's second colour. Purple and yellow and green and yellow
        keep the brand gold; black and white, navy and white and orange
        and white wear white. Every caret re-inks in the theme pass, and
        since owner order 2026-11-25 (evening) the SEARCH and ORDER FLOW
        carets stand beside the volume and theme ones."""
        start = self.main.index("private void repaintDropdownArrows() {")
        block = self.main[start:start + 1200]
        self.assertEqual(
            block.count("ColorStateList.valueOf(themeAccentInk)"), 4)
        self.assertIn("volumeSplitArrow.setImageTintList", block)
        self.assertNotIn("sectorsArrow", block)
        self.assertIn("themeArrow.setImageTintList", block)
        self.assertIn("searchArrow.setImageTintList", block)
        self.assertIn("orderFlowArrow.setImageTintList", block)
        theme_pass = self.main[self.main.index(
            "private void applyTheme(int index) {"):]
        theme_pass = theme_pass[:theme_pass.index(
            "private final GradientDrawable[] themePlates")]
        self.assertIn("repaintDropdownArrows();", theme_pass)
        inputs = self.main[self.main.index(
            "private void applyThemeToInputs(int index) {"):]
        inputs = inputs[:inputs.index("private void paintField")]
        self.assertIn("repaintDropdownArrows();", inputs)
        for pair in (
            '<color name="gold">#FFD9A441</color>',
            '<color name="theme_black_accent">#FFFFFFFF</color>',
            '<color name="theme_green_accent">#FFD9A441</color>',
            '<color name="theme_navy_accent">#FFFFFFFF</color>',
            '<color name="theme_orange_accent">#FFFFFFFF</color>',
        ):
            self.assertIn(pair, self.colors)

    def test_every_cached_plate_is_copied_per_view(self):
        """Owner order 2026-11-01, after the black and white screenshot:
        one cached GradientDrawable shared by every tile and field lets
        one view's bounds and callback clip or stretch another, which is
        what mixed and enlarged the plates. Each caller gets a copy."""
        for signature in (
            "private GradientDrawable themePlate(int index, int panelColorId,",
            "private GradientDrawable fieldPlate(int index) {",
            "private android.graphics.drawable.Drawable navDisc() {",
        ):
            start = self.main.index(signature)
            self.assertIn("return freshPlate(cached);",
                          self.main[start:start + 1200])
        helper = self.main[self.main.index(
            "private static GradientDrawable freshPlate("):]
        helper = helper[:500]
        self.assertIn("cached.getConstantState().newDrawable()", helper)
        self.assertIn("copy.mutate();", helper)

    def test_every_diamond_rule_wears_the_themes_second_colour(self):
        """Owner order 2026-11-01: the diamond line feature follows the
        theme's second colour across the entire app, both hairlines and
        the diamond. Purple and green keep gold; black, navy and orange
        wear white."""
        rule = RULE.read_text(encoding="utf-8")
        self.assertIn('android:tag="qor_rule"', rule)
        self.assertEqual(rule.count('android:tag="qor_rule_line"'), 2)
        self.assertIn('android:tag="qor_rule_diamond"', rule)
        theme_pass = self.main[self.main.index(
            "private void applyTheme(int index) {"):]
        theme_pass = theme_pass[:theme_pass.index(
            "private final GradientDrawable[] themePlates")]
        self.assertIn("repaintRules(findViewById(R.id.scroll_root));",
                      theme_pass)
        helper = self.main[self.main.index(
            "private void repaintRules(View view) {"):]
        helper = helper[:900]
        self.assertIn('"qor_rule_line".equals(tag)', helper)
        self.assertIn('"qor_rule_diamond".equals(tag)', helper)
        self.assertIn("ColorStateList.valueOf(themeAccentInk)", helper)
        self.assertIn("setTextColor(themeAccentInk)", helper)

    def test_body_wording_wears_the_themes_first_colour(self):
        """Owner order 2026-11-01: the purple wording follows the worn
        theme's FIRST colour, while the title, the PSX header, headings
        and every red or green state keep their own ink."""
        for theme in ("black", "green", "navy", "orange"):
            self.assertIn(f'<color name="theme_{theme}_body">', self.colors)
            self.assertIn(f"R.color.theme_{theme}_body", self.main)
        self.assertIn("private int themeBodyInk", self.main)
        self.assertIn("themeBodyInk = getColor(body);", self.main)
        theme_pass = self.main[self.main.index(
            "private void applyTheme(int index) {"):]
        theme_pass = theme_pass[:theme_pass.index(
            "private final GradientDrawable[] themePlates")]
        self.assertIn("paintBodyInk(findViewById(R.id.scroll_root));",
                      theme_pass)
        block = self.main[self.main.index(
            "private void paintBodyInk(View view) {"):]
        block = block[:1200]
        for own in ("R.id.brand_title", "R.id.brand_tagline",
                    "R.id.status_word"):
            self.assertIn(own, block)
        self.assertIn("COMPLEX_UNIT_SP, 13f", block)
        self.assertIn("body * 0.96f", block)
        self.assertNotIn("R.color.green", block)
        self.assertNotIn("R.color.red", block)
        self.assertIn("bodyInkFor(index)", self.main)

    def test_every_price_wears_the_moves_colour(self):
        """Owner order 2026-11-01: the current price is green in profit
        and red in loss, both the PKR label and the number, on the index,
        the leaders, the custom scrips reveal and the picked scrip's answer.
        A price with no percentage stays body ink."""
        search = self.main[self.main.index("private void styleSearchRow("):]
        search = search[:search.index("private GradientDrawable highlightPlate")]
        # Owner order 2026-11-26: the option's money is built in
        # appendSearchQuote, which stands ABOVE this builder; the builder
        # itself still adds none, and that builder inks the price too.
        self.assertNotIn("PKR %,.2f", search,
                         "the option is the scrip alone, the money waits for the tap")
        live = self.main[self.main.index(
            "private CharSequence liveSelectedLine("):]
        live = live[:live.index("private void paintSignalInk")]
        self.assertIn("highFrom, highTo, 0", live)
        self.assertIn("lowFrom, lowTo, 0", live)
        scrip = self.main[self.main.index("private void appendScripQuote("):]
        scrip = scrip[:scrip.index("private void colorQuantity")]
        self.assertIn("priceFrom, sb.length(), 0", scrip)
        pinned = self.main[self.main.index("private void paintSelectedLine() {"):]
        pinned = pinned[:pinned.index("private CharSequence liveSelectedLine")]
        self.assertIn("from, moveFrom, 0", pinned)
        live = self.main[self.main.index(
            "private CharSequence liveSelectedLine("):]
        live = live[:live.index("private void paintSignalInk")]
        self.assertIn("tailFrom, moveFrom, 0", live)
        volume = self.main[self.main.index(
            "private SpannableStringBuilder volumeRevealText("):]
        volume = volume[:volume.index("private void colorQuantity")]
        self.assertIn("priceFrom, sb.length(), 0", volume)
        leaders = self.main[self.main.index(
            "private SpannableString leadersText("):]
        leaders = leaders[:leaders.index("private void toast")]
        self.assertIn("spans.add(new int[]{priceFrom, sb.length(),", leaders)
        market = self.main[self.main.index("private void renderMarket("):]
        market = market[:market.index("private SpannableString leadersText")]
        self.assertIn('"KSE100  ".length(), line.length(), 0', market)
        for source in (scrip, pinned, live, volume, leaders, market):
            self.assertIn("R.color.green", source)
            self.assertIn("R.color.red", source)

    def test_the_menu_rows_stand_at_one_displacement_each(self):
        """Owner order 2026-10-31 ("the top option and the bottom option
        are not balanced, the other options they all are exactly in the
        middle except for the top and the bottom option, have the same
        displacement for each option on every drop down menu, same goes
        for custom scrips of volume"), restated 2026-11-16: every option,
        the first and last included, carries the same 5dp top and bottom
        padding, and the menu's own 5dp top and bottom air gives the edge
        rows the same 10dp displacement an interior row gets from its
        divider. No edge row is taller or shorter than the middle ones.
        """
        self.assertIn("private TextView menuRow(String line, "
                      "boolean first, boolean last) {", self.main)
        self.assertIn("return menuRow(line);", self.main)
        self.assertIn("menu.setPadding(0, dp(5), 0, dp(5));", self.main)
        self.assertIn("row.setGravity(Gravity.CENTER);", self.main)
        self.assertNotIn("first ? dp(10) : dp(5)", self.main)
        self.assertNotIn("last ? dp(10) : dp(5)", self.main)
        self.assertIn('String numbered = String.format(Locale.US, "%d. %s",',
                      self.main)
        self.assertIn("i + 1, volumeChoices[index]);", self.main)
        for builder in ("buildThemeMenu", "buildVolumeMenu"):
            with self.subTest(menu=builder):
                start = self.main.index(f"private void {builder}() {{")
                block = self.main[start:start + 2500]
                self.assertIn("padMenu(", block, builder)
        # Both builders pass the row's edge position: the first option is
        # row 0 and the last is the final row of its own menu.
        for builder, count in (("buildThemeMenu",
                                "THEME_LABELS.length - 1"),
                               ("buildVolumeMenu",
                                "volumeChoices.length - 1")):
            with self.subTest(menu=builder):
                start = self.main.index(f"private void {builder}() {{")
                block = self.main[start:start + 2500]
                self.assertIn("i == 0, i == " + count + ");", block, builder)

    def test_the_wl_tile_reads_one_relay_ledger(self):
        """Owner order 2026-10-31 ("a new tile on the home page between
        quant status tile and latest signal tile"), sharpened 2026-11-01
        ("change the W/L tile heading, instead of = sign, have & sign. "
        "Also, only show the Winning & losing number like this, 0/1 &
        100%"): the tile sits between the two, its heading is exactly
        "W/L & W/L RATE", its one line is the owner's own digits 0/1 &
        100% (PRL's first Kalman Trend call hit its stop on
        2026-10-30), the win digit green, the loss digit red, and the
        rate in the colour of whatever side is higher, and the ledger is
        the relay's answer, never a local guess with nothing reported
        yet (SO-3).
        """
        self.assertIn('android:text="@string/label_winloss"', self.layout)
        self.assertIn('android:id="@+id/tile_winloss"', self.layout)
        # Between the two tiles: tile_status, the W/L tile's own rule,
        # the W/L tile, the rule and then the latest signal tile
        # (2026-11-01: the diamond line the owner ordered between
        # quant status and this tile stands in the first seam).
        self.assertLess(
            self.layout.index('android:id="@+id/tile_status"'),
            self.layout.index('android:id="@+id/rule_status_winloss"'))
        self.assertLess(
            self.layout.index('android:id="@+id/rule_status_winloss"'),
            self.layout.index('android:id="@+id/tile_winloss"'))
        self.assertLess(
            self.layout.index('android:id="@+id/tile_winloss"'),
            self.layout.index('android:id="@+id/rule_status_signal"'))
        self.assertLess(
            self.layout.index('android:id="@+id/rule_status_signal"'),
            self.layout.index('android:id="@+id/tile_signal"'))
        self.assertIn(
            '<string name="label_winloss">W/L &amp; W/L RATE</string>',
            self.strings)
        self.assertIn(">NO CLOSED SIGNAL RIGHT NOW<", self.strings)
        self.assertIn("private TextView winlossValue;", self.main)
        self.assertIn("winlossValue = findViewById(R.id.winloss_value);",
                      self.main)
        self.assertIn("renderWinLoss(market);", self.main)
        self.assertIn('String.format(Locale.US, "%d/%d & %d%%",',
                      self.main)
        # The rate's own ink is the ahead side's: green exactly while the
        # wins strictly lead the losses, red every other close.
        self.assertIn("market.wins > market.losses"
                      " ? R.color.green : R.color.red;", self.main)
        # And the tile is a console citizen: it hides with the group and
        # wears the theme's own plate.
        self.assertIn("findViewById(R.id.tile_winloss),", self.main)
        self.assertIn("findViewById(R.id.rule_status_winloss),", self.main)
        # The relay carries the ledger in the market answer.
        watcher = (ROOT / "android" / "app" / "src" / "main" / "java"
                   / "pk" / "quantofrehan" / "Watcher.java").read_text(
                       encoding="utf-8")
        self.assertIn("body.optJSONObject(\"win_loss\")", watcher)
        self.assertIn("market.loseRatePct = winLoss.optInt", watcher)

    def test_the_nav_tile_holds_its_laws_in_every_theme_pass(self):
        """Owner order 2026-10-31, on orange and white ("the nav tile gets
        stretched to the bottom, and I can't even see it end" and "latest
        signal tile gets on the quant status tile"): the tile's 74dp
        height and the carrier's 3% screen-share lift are pinned in ONE
        helper, called from onCreate AND from applyTheme, so a theme's
        repaint can never walk the tile past the screen's bottom edge or
        press the tiles above onto each other. The layout itself pins the
        74dp too.
        """
        self.assertIn("private void pinNavTile() {", self.main)
        self.assertIn("lift.bottomMargin = Math.max(0, "
                      "(int) (screen * 0.03f));", self.main)
        self.assertIn("navTile.getLayoutParams().height = (int) dp(74);",
                      self.main)
        # Both passes call the one helper.
        self.assertIn("pinNavTile();", self.main)
        self.assertGreaterEqual(self.main.count("pinNavTile();"), 2,
                                "onCreate AND the theme pass both pin it")
        # The layout pins the same law, so even the first measure holds it.
        nav_tile = element(self.layout, 'android:id="@+id/nav_tile"')
        self.assertIn('android:layout_height="74dp"', nav_tile)

    def test_the_selected_answer_moves_with_the_tape(self):
        """Owner order 2026-11-01 ("I am not seeing the volume moving in
        real time in my app"): the pinned answer is rebuilt from the LIVE
        quote on every tick, pair and total included, so B, S and T move
        with the card's own rows instead of freezing at the tap's numbers.
        The relay's /prices row carries the acknowledged total as its sixth
        column, and Watcher keeps it in Quote.volume so no second sum is
        computed on the phone.
        """
        watcher = WATCHER.read_text(encoding="utf-8")
        main = MAIN.read_text(encoding="utf-8")
        self.assertIn("Object volumeVal = row.opt(5);", watcher)
        self.assertIn("final Long volume;", watcher)
        self.assertIn("Double.isNaN(pct) ? null : pct, buy, sell,", watcher)
        self.assertIn("private CharSequence liveSelectedLine(Watcher.Quote quote) {",
                      main)
        self.assertIn("searchStatus.setText(liveSelectedLine(quote));", main)
        live = main[main.index("private CharSequence liveSelectedLine("):
                    main.index("private void paintSignalInk(")]
        self.assertIn("R.color.green", live)
        self.assertIn("R.color.red", live)
        self.assertIn('append("T=");', live)
        # Owner order 2026-11-07: U is captured as its own range and painted
        # yellow; the digits still come from the live quote.
        self.assertIn('sb.append(", U=");', live)
        self.assertIn("unclearFrom = sb.length();", live)
        self.assertIn("R.color.yellow", live)
        self.assertNotIn('" & T=%,d"', live)

    def test_the_dropdown_caret_stands_at_its_face_middle(self):
        """Owner order 2026-11-01 ("have the drop down/up icon at the
        middle... Make it at the exact center", then "the drop up icon is
        little to the up side when the sub menu is tapped down. Have the
        drop up icon in the exact center"): the caret re-centres in code
        onto its mount's TOP FACE in both states - the closed box's own
        face while closed and the WHOLE open plate while open - read after
        the layout pass and never a fixed 11dp margin carried by hand; the
        same law lands from onCreate and onResume, so a theme's taller air
        can never leave the arrow high again.
        """
        self.assertIn(
            "private void centerDropdownCaret(ImageView arrow, TextView face,",
            self.main)
        self.assertIn("private void centerDropdownCarets() {", self.main)
        # Both dropdowns stand in the one call's own two lines.
        self.assertIn(
            "centerDropdownCaret(volumeSplitArrow, volumeSplitSpinner,\n"
            "                volumeSplitMenu);", self.main)
        self.assertIn("centerDropdownCaret(themeArrow, themeSpinner, themeMenu);",
                      self.main)
        # Both state toggles land their caret too, after the rotation.
        self.assertIn("rotateDropdownArrow(volumeSplitArrow, open);\n"
                      "        // Owner order 2026-11-01", self.main)
        self.assertIn(
            "rotateDropdownArrow(themeArrow, open);\n"
            "        // The same re-centre the volume caret lands on",
            self.main)
        # The centre is read after the layout pass, on the view's own post.
        self.assertIn("arrow.post(() -> {", self.main)
        self.assertIn("arrow.getLayoutParams()", self.main)
        # Owner order 2026-11-01, after the 3.7.0 build: the open state's
        # anchor is the FIRST option row, and its vertical station is that
        # row's text line (the padding above and below the line is taken
        # out before the middle is read), never the middle of the plate.
        self.assertIn("menu.getChildAt(0) : null);", self.main)
        self.assertIn("anchor.getHeight() - anchor.getPaddingTop()",
                      self.main)
        centre = self.main.index("private void centerDropdownCaret(")
        self.assertIn("anchor.getPaddingTop() + content / 2",
                      self.main[centre:centre + 2600])
        # Landed from onCreate after the menus build, and from onResume
        # too: count == 2 exactly, no third site has grown in.
        self.assertEqual(self.main.count("centerDropdownCarets();"), 2,
                         "onCreate AND onResume, and no site besides")
        """Owner order 2026-10-31 ("when I tap on the drop down menus,
        make sure you have a line between 2 separate sub menu options,
        the difference between the line and all the sub menus should be
        exactly the same"): BOTH open menus draw one 1dp line between
        each pair of adjacent options, and the line's top and bottom
        air are equal, so the gap above it is exactly the gap below it.
        No line above the first option and none under the last: the
        list's own edges already bound it.
        """
        self.assertIn("private View menuDivider() {", self.main)
        self.assertIn("LinearLayout.LayoutParams.MATCH_PARENT, dp(1));",
                      self.main)
        self.assertIn("params.setMargins(dp(14), dp(5), dp(14), dp(5));",
                      self.main,
                      "the line matches the centred row's 14dp side air")
        # A row's own padding is the matching 5dp top and bottom, so the
        # line-to-option distance is the same 10dp on both sides.
        self.assertIn("row.setPadding(dp(14), dp(5), dp(14), dp(5));",
                      self.main)
        # Both menus obey one law: every option with an option above it
        # gains the line first.
        for builder, menu in (("buildThemeMenu", "themeMenu"),
                              ("buildVolumeMenu", "volumeSplitMenu")):
            start = self.main.index(f"private void {builder}() {{")
            block = self.main[start:start + 2500]
            block = block[:block.index("\n    /**") if "\n    /**" in block[:2500]
                    else 2500]
            self.assertIn("addView(menuDivider());", block, builder)
            self.assertIn("if (i > 0) {", block, builder)
            self.assertIn(f"{menu}.addView(row);", block, builder)
            self.assertIn("menuDividers.clear();", block, builder)
        # The divider list is one surface piece: a theme pass re-inks it.
        self.assertIn("private final List<View> menuDividers", self.main)
        self.assertIn("private void repaintMenuDividers() {", self.main)
        self.assertIn("repaintMenuDividers();", self.main)

    def test_the_volume_tile_is_the_scanner_page(self):
        """Owner order 2026-10-24 ("move the custom scrips of volume in
        the scanner page"): the tile left the search page for its own
        page, opened by the nav icon beside home. The tile itself is the
        page's content: it lives and dies with `scannerOpen` in
        MainActivity the way the panels do, and nothing else about the
        v2.2.1 tile changed."""
        self.assertIn('name="label_volume">CUSTOM SCRIPS OF VOLUME<',
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
        # Owner order 2026-11-12: the console's four sorts are the menu's
        # rows 3 to 6, in the console's own order, each named in the
        # console's own words.
        for caption in (
                'name="volume_seller_caption">MORE SELLERS &amp; LESS BUYERS<',
                'name="volume_quiet_caption">ALMOST NO VOLUME AT ALL<',
                'name="volume_lower_lock_caption">SCRIPS WITH LOWER LOCK<',
                'name="volume_upper_lock_caption">SCRIPS WITH UPPER LOCK<'):
            self.assertIn(caption, self.strings)
        order = ['"volume_speed_caption"', '"volume_split_caption"',
                 '"volume_seller_caption"', '"volume_quiet_caption"',
                 '"volume_lower_lock_caption"',
                 '"volume_upper_lock_caption"']
        for earlier, later in zip(order, order[1:]):
            self.assertLess(self.strings.index(earlier),
                            self.strings.index(later))
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
        # spinner, no popup window anywhere. v2.3.18 grows that
        # universal height 50% onto 43dp.
        self.assertIn("<TextView", spinner)
        self.assertIn('android:layout_height="43dp"', spinner)
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
        # riser ranking moved to row 1 and the B/S split to row 2. Owner
        # order 2026-11-12: the four console sorts join them as rows 3 to
        # 6, and one helper maps a row to its ranking.
        self.assertIn("volumeSplitChoice < 1", self.main)
        self.assertIn("rankedVolumeSymbols(volumeSplitChoice, quotes)",
                      self.main)
        for call in ("case 2:", "case 3:", "case 4:", "case 5:",
                     "case 6:"):
            self.assertIn(call, self.main)
        for call in ("rankedSplitSymbols(quotes)",
                     "rankedSellerSymbols(quotes)",
                     "rankedQuietSymbols(quotes)",
                     "rankedLockSymbols(quotes, true)",
                     "rankedLockSymbols(quotes, false)",
                     "rankedSpeedSymbols(quotes)"):
            self.assertIn(call, self.main)
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
        # Owner order 2026-11-05, eighth pass: the scanner's three read as
        # three lines, measured B and S with the unclear U beside them, then
        # T on the money line; no remainder is folded into a side.
        self.assertIn('append("(B=");', block)
        self.assertIn('sb.append(", S=");', block)
        self.assertIn('sb.append(", U=");', block)
        self.assertIn('append("T=");', block)
        self.assertNotIn('sb.append(any ? " & T=" : "T=");', block)
        self.assertIn("sb.append(')');", block)
        self.assertIn("colorQuantity(sb, quote.buy, R.color.green)", block)
        self.assertIn("colorQuantity(sb, quote.sell, R.color.red)", block)
        self.assertNotIn("pair[0]", block)
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

    def test_an_option_wears_nothing_of_its_own(self):
        """Owner order 2026-11-25 (evening): the SEARCH and ORDER FLOW options
        are the CUSTOM SCRIPS OF VOL. menu's own rows. The matched row's lift,
        its hairline and the grey pill around a ticker are all struck out with
        the tall list he circled: an option is plain text inside the one field
        plate, divided like every other menu row."""
        main = MAIN.read_text(encoding="utf-8")
        block = main[main.index("private void styleSearchRow") :]
        block = block[:block.index("/** One highlight plate")]
        self.assertIn("row.setBackground(null);", block)
        self.assertNotIn("highlightPlate(", block)
        flow = main[main.index("private View flowTableRow("):
                    main.index("private void pickFlow(")]
        self.assertIn("line.setBackground(null);", flow)
        self.assertNotIn("highlightPlate(", flow)
        layout = LAYOUT.read_text(encoding="utf-8")
        for tile_id in ("@+id/search_results", "@+id/order_flow_results"):
            menu = element(layout, 'android:id="%s"' % tile_id)
            self.assertIn('android:orientation="vertical"', menu)
            self.assertNotIn("ScrollView", menu)
            self.assertNotIn("OrnamentScroller", menu)

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
    """Owner order 2026-11-27: the sun and its wireframe cloud are retired.

    "remove this ORB feature. It's boring me... Give it a new ORB type/Jarvis
    type feature." The station under the brand is an instrument now: a compass
    of ticks that ignite under a radar sweep, three arc rings turning at their
    own speeds, two orbiting satellites with their trails and a breathing
    reactor core. Owner order 2026-11-27 (second pass) stripped the frame off
    it: the scan line and the four corner brackets are gone, both satellites
    travel the same way round, and the compass circle rides the exact radius
    the ticks begin on. The photograph, its sphere tables and its bloom
    buffers left with the picture they built.
    """

    def setUp(self):
        self.orb = (MAIN.parent / "ThinkingOrb.java").read_text(encoding="utf-8")
        self.main = MAIN.read_text(encoding="utf-8")
        self.layout = LAYOUT.read_text(encoding="utf-8")

    def test_the_sun_and_its_cloud_are_retired(self):
        for gone in ("sunBall", "sunMap", "buildSunSphere", "buildSunCorona",
                     "drawCloud", "projectCloud", "NODES", "CLUSTERS"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, self.orb)

    def test_the_instrument_is_a_jarvis_core(self):
        for mark in ("private void drawTicks(", "private void drawSweep(",
                     "private void drawArcs(", "private void drawOrbiters(",
                     "private void drawCore(", "TICKS = 96"):
            with self.subTest(mark=mark):
                self.assertIn(mark, self.orb)

    def test_the_sweep_ignites_the_ticks_it_passes(self):
        ticks = self.orb[self.orb.index("private void drawTicks("):]
        ticks = ticks[:ticks.index("private void drawArcs(")]
        self.assertIn("float behind = ((sweep - angle) % 360f + 360f) % 360f;",
                      ticks)
        self.assertIn("float heat = Math.max(0f, 1f - behind / 130f);", ticks)
        self.assertIn("i % 8 == 0", ticks)

    def test_the_core_breathes(self):
        core = self.orb[self.orb.index("private void drawCore("):]
        core = core[:core.index("private float dp(float value)")]
        self.assertIn("coreGradient", core)
        self.assertIn("Color.WHITE", core)

    def test_the_frames_and_the_scan_line_are_retired(self):
        # "the four corners/picture frames you got on the ORB, remove them"
        # and "there is a line type thing that is going above and below on the
        # ORB remove that line": both readings are gone from the source, and
        # the scene draws neither of them any more.
        for gone in ("drawBrackets", "bracketPaint", "drawScan", "scanPaint"):
            with self.subTest(gone=gone):
                self.assertNotIn(gone, self.orb)
        scene = self.orb[self.orb.index("private void drawScene("):]
        scene = scene[:scene.index("private void drawRing(")]
        self.assertIn("drawCore(canvas, wake, pulse, seconds);", scene)
        self.assertNotIn("drawScan(", scene)
        self.assertNotIn("drawBrackets(", scene)

    def test_both_satellites_travel_the_same_way_round(self):
        # "one is moving forward and one is moving backward, make the
        # backwards moving sperm move forward as well": neither orbit turns
        # against the clock any more, each keeps its own speed.
        orbiters = self.orb[self.orb.index("private void drawOrbiters("):]
        orbiters = orbiters[:orbiters.index("private void orbit(")]
        self.assertIn("seconds * 26f", orbiters)
        self.assertIn("seconds * 44f", orbiters)
        self.assertNotIn("-seconds", orbiters)

    def test_the_compass_circle_rides_the_start_of_every_tick(self):
        # "the circle at the very outside of the ORB is not sitting exactly on
        # the small lines, make that outside circle sit on the exact starting
        # of the little lines": one radius, tickOuter, serves both the circle
        # and the first point of every tick.
        # Owner order 2026-11-27 (third pass): "make the circle sit at the
        # exact starting of those little lines ... on the other side of those
        # little circular lines, on the exact starting point from outside" -
        # the circle keeps its one radius but that radius is now the OUTSIDE
        # end of the ticks, so every line runs inward from the ring.
        ring = self.orb[self.orb.index("private void drawRing("):]
        ring = ring[:ring.index("private void drawTicks(")]
        self.assertIn("canvas.drawCircle(cx, cy, tickOuter, ringPaint);", ring)
        self.assertNotIn("canvas.drawCircle(cx, cy, reach, ringPaint);", ring)
        ticks = self.orb[self.orb.index("private void drawTicks("):]
        ticks = ticks[:ticks.index("private void drawArcs(")]
        self.assertIn("float to = tickOuter;", ticks)
        self.assertIn("float from = to - dp(major ? 11f : 6f);", ticks)
        self.assertNotIn("tickInner", self.orb)

    def test_the_park_is_frozen_but_visible(self):
        # "it will stop moving, it should not disappear completely":
        # stop() freezes the CLOCK (the pose the loop last drew), a parked
        # onDraw repaints that pose fully lit, and a resume replays from the
        # frozen second, so a closed market can never blank the station.
        for pin in ("private float lastSeconds;",
                    "private float frozenSeconds = -1f;",
                    "frozenSeconds = lastSeconds;",
                    "frozenSeconds >= 0f ? frozenSeconds",
                    "PARKED_SECONDS = 2.0f",
                    "(long) (frozenSeconds * 1000f)"):
            self.assertIn(pin, self.orb)
        parked = self.orb[self.orb.index("protected void onDraw("):]
        self.assertIn("drawScene(canvas, frozenSeconds >= 0f ? frozenSeconds",
                      parked)

    def test_every_vsync_carries_a_whole_picture(self):
        # A short frame repaints the pose it last drew rather than holding
        # the surface, so the instrument can never phase against the vsync.
        self.assertIn("FPS_MS = 33L", self.orb)
        self.assertIn("drawScene(canvas, lastSeconds);", self.orb)

    def test_the_theme_paints_the_whole_instrument(self):
        self.assertIn("public void setThemeInk(int color) {", self.orb)
        for paint in ("ringPaint.setColor(ink);", "arcPaint.setColor(ink);",
                      "tickPaint.setColor(ink);", "sweepPaint.setColor(ink);",
                      "satellitePaint.setColor(ink);"):
            with self.subTest(paint=paint):
                self.assertIn(paint, self.orb)

    def test_the_station_keeps_its_seat_under_the_brand(self):
        self.assertIn("<pk.quantofrehan.ThinkingOrb", self.layout)
        orb = element(self.layout, 'android:id="@+id/thinking_orb"')
        self.assertIn('android:layout_height="210dp"', orb)
        self.assertIn("thinkingOrb.start();", self.main)
        self.assertIn("thinkingOrb.stop();", self.main)
        self.assertIn("thinkingOrb.setThemeInk(themeAccentInk);", self.main)


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
        # tile and the custom scrips of volume tile; owner 2026-11-01
        # adds the W/L tile's own seam above itself and the greeting's
        # seam before QUANT STATUS; owner order 2026-11-04 (second pass)
        # gives the ORDER FLOW page a division of its own: TWELVE rules
        # now (seven on the home path, the THEMES tile's two, the search
        # page's own diamond, the ORDER FLOW page's bracket of two, and
        # the volume pair's own). Owner order 2026-11-04 (third pass): the
        # pair under BIG BUYING & SELLING loses one and that one stands
        # between the page's two tiles, and THIRTEEN rules then. Owner
        # order 2026-11-04 (fourth pass): the extra seam below BIG BUYING
        # & SELLING is gone with the include, so TWELVE rules now.
        # Owner order 2026-11-06: the SECTORS tile's own rule above it makes
        # THIRTEEN, every one of them carrying the grid's 12dp gap.
        self.assertEqual(len(rules), 13)
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
        # Owner order 2026-11-04: the tile names the index it follows by its
        # own name, KSE100, in place of the generic word THE INDEX.
        self.assertIn('name="label_market">KSE100 INDEX &amp; THE TOP 3 '
                      'SCRIPS OF VOLUME<', strings)
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
                    "PARKED_SECONDS = 2.0f",
                    "(long) (frozenSeconds * 1000f)"):
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
        # v3.4.0: the selected disc is the worn theme's own accent pair
        # (navDisc), so navy's highlight is white and purple's the
        # shipped gold; the old theme-blind gold ternary is retired.
        self.assertNotIn("selected ? R.drawable.nav_circle",
                         self.main)
        self.assertIn("icon.setBackground(navDisc());", self.main)
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


class Build174Test(unittest.TestCase):
    """Owner order 2026-11-26: the phone pass on the clock and the searches."""

    def test_the_status_tile_drops_the_karachi_word(self):
        watcher = WATCHER.read_text(encoding="utf-8")
        self.assertNotIn("Karachi: ", watcher)
        self.assertIn("new StringBuilder(clockLine(karachi))", watcher)
        main = MAIN.read_text(encoding="utf-8")
        clock = main[main.index("private String advanceRelayClock("):]
        clock = clock[:clock.index("private SpannableString clockSpans(")]
        self.assertIn("int start = 0;", clock)
        self.assertIn("detail.indexOf('\\n')", clock)

    def test_the_clock_steps_on_the_foreground_tick(self):
        main = MAIN.read_text(encoding="utf-8")
        tick = main[main.index("private final Runnable tick = new Runnable()"):]
        tick = tick[:tick.index("private void scheduleNext()")]
        self.assertIn("repaintClock();", tick)
        self.assertIn("statusDetailRaw = actualDetail;", main)
        self.assertIn("private void repaintClock() {", main)

    def test_both_search_boxes_type_from_the_left(self):
        layout = LAYOUT.read_text(encoding="utf-8")
        for view_id in ("search_input", "order_flow_input"):
            with self.subTest(box=view_id):
                box = element(layout, 'android:id="@+id/%s"' % view_id)
                self.assertIn('android:gravity="center_vertical|start"', box)

    def test_the_two_search_carets_are_gone(self):
        layout = LAYOUT.read_text(encoding="utf-8")
        for view_id in ("search_arrow", "order_flow_arrow"):
            with self.subTest(arrow=view_id):
                arrow = element(layout, 'android:id="@+id/%s"' % view_id)
                self.assertIn('android:visibility="gone"', arrow)
        main = MAIN.read_text(encoding="utf-8")
        self.assertIn(
            "searchInput.setOnClickListener(v -> showSearchList(true));", main)
        self.assertIn(
            "orderFlowInput.setOnClickListener(v -> showFlowList(true));", main)

    def test_a_hairline_stands_over_the_first_option(self):
        main = MAIN.read_text(encoding="utf-8")
        search = main[main.index("private void renderSearchResults("):]
        search = search[:search.index("private CharSequence scripMatchSpans(")]
        self.assertIn("padMenu(searchResults);", search)
        self.assertLess(search.index("padMenu(searchResults);"),
                        search.index("searchResults.addView(menuDivider());"))
        self.assertLess(search.index("searchResults.addView(menuDivider());"),
                        search.index("searchResults.addView(row);"))
        flow = main[main.index("private void renderFlowResults("):]
        flow = flow[:flow.index("private View flowTableRow(")]
        self.assertIn("orderFlowResults.addView(menuDivider());", flow)

    def test_a_search_option_is_the_scrip_alone_and_its_letters_bold(self):
        """Owner order 2026-11-27: "as I keep typing for example I type E then
        every scrip containing E letter would be bold, and as I keep typing all
        the letters then each letter in the search results will get bold." The
        matching run inside the symbol is the bold one, the rest of the scrip
        keeps the body's weight, and no option prints a quote."""
        main = MAIN.read_text(encoding="utf-8")
        span = main[main.index("private CharSequence scripMatchSpans("):]
        span = span[:span.index("private void styleSearchRow(")]
        self.assertIn("new StyleSpan(Typeface.BOLD)", span)
        self.assertIn("int to = Math.min(symbol.length(), at + query.length());",
                      span)
        self.assertIn("themeAccentInk", span)
        row = main[main.index("private void styleSearchRow("):]
        row = row[:row.index("private GradientDrawable highlightPlate")]
        self.assertIn("row.setText(scripMatchSpans(symbol, q));", row)
        self.assertNotIn("Watcher.Quote quote = Watcher.quotes().get(symbol);",
                         row)


if __name__ == "__main__":
    unittest.main()
