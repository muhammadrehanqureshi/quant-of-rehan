# The classic v1.8.7 console, kept for undo

Owner order 2026-10-22 (the HUD order): the console is refined into a
JARVIS-style "thinking" interface, and this UI has to stay in the repository's
memory until he has seen v1.8.8 on the phone, because if he does not like the
new one he will undo it.

## What is here

Byte-exact copies of the five resource files as they shipped in v1.8.7
(versionCode 41, the merge of #76):

* `layout/activity_main.xml` - the whole console layout
* `values/styles.xml` - QorLabel at 11sp and every other type style
* `values/colors.xml` - the palette
* `values/strings.xml` - every sentence
* `values/dimens.xml` - the shifts and gaps

## How to undo

Two paths, both end on the same screen the owner already knows:

1. The git tag `ui-v1.8.7-classic` points at the v1.8.7 master commit
   (0d1647a) *before* any HUD work. The layout, styles, colours, strings,
   dimens, MainActivity and Watcher of the classic console are all part of
   that tree.
2. If only the look (not the search or post-close answers) is being
   reverted, restore these five files over
   `android/app/src/main/res/...` and keep the newer Java. That is possible
   because the JARVIS pass adds view ids and resources but changes no id the
   v1.8.7 code relied on. Update for v1.8.9 (the owner's second pass of the
   2026-10-22 order): v1.8.8's `sys_diag` line and sweeping beam are retired,
   and the HUD mover is now the `ThinkingOrb` view under the brand
   (`<pk.quantofrehan.ThinkingOrb android:id="@+id/thinking_orb"/>`), a
   member of MainActivity's consoleViews. A partial revert on the v1.8.9
   Java would leave the orb flat with the newer layouts, so a look-only
   revert today should RESTORE THE v1.8.9 RESOURCES and remove only the
   orb block in the layout and its lines in MainActivity if ever needed;
   a full-UI revert still uses path 1 with the v1.8.7 tag AND returns the
   current Java's HUD wiring to no-op.
