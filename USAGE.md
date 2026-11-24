# Nib – Usage

Every control and setting explained, plus tips for safe operation.
Installation and first start are covered in the [README](README.md).

**Layout:** controls on the left, the preview in the middle with the console below it, and
placement, optimization, layers and plot on the right. **Open SVG** and the info about the loaded
file sit in the bar above the preview. Drag the dividers to resize the side panels and the console;
double-click a divider to restore the default. The layout is remembered.

**Preview ink** (bar above the preview): **Ink: fineliner** shows transparent inks that mix where
they overlap, like real fineliners. **Ink: opaque** shows gel or paint pens that cover what was
plotted before, so the layer order matters. The field next to it is the **pen tip width** in mm;
lines are drawn exactly this wide. Both only change the preview, not the plot.

**Light/dark:** the button next to **STOP** at the top right cycles through *System* (follows Windows or macOS),
*Light* and *Dark*. **Collapsing:** sections with an arrow in their title (e.g. *Speed & pen*, *Machine*,
*Optimization*) open and close when you click the title; their state is remembered.
**Status bar** (bottom): machine state, X/Y/Z position, whether an origin is set and, while plotting,
a short progress summary.

---

## Jog (top left)

| Control | What it does |
|---|---|
| **0.1 / 1 / 10 / 50 / custom** | Step size in mm. Each arrow click moves this far. The keyboard arrow keys work too. |
| **Arrows** | Move the pen in X/Y. Movement stops automatically at the edge of the work area. |
| **Pen up / Pen down** | Moves Z to the “Pen up (Z)” or “Pen down (Z)” height, e.g. to check that the pen touches down properly. |
| **Set origin** | The current position becomes the corner of your sheet. Placement (X/Y) in the preview is measured from here. |
| **House (center of the arrows)** | Returns to the point set with “Set origin”, with the pen raised. |
| **Machine home** | Moves to the power-on position (corner). The origin you set is kept. |
| **Unlock** | After an alarm (e.g. a limit was hit) the plotter is locked. This clears the lock without losing the origin. |
| **Pen height** | Shows the current Z height in mm (0 = fully up, larger = lower). |
| **▲ 0.5 / ▲ 0.1 / ▼ 0.1 / ▼ 0.5** | Raise (▲) or lower (▼) the pen in small steps to set up the pen height. |
| **Set as up / Set as down** | Stores the current Z height as “Pen up (Z)” or “Pen down (Z)”. |

Keyboard: arrow keys jog, PgUp/PgDn raise and lower the pen, space pauses the plot.
While a plot is running, the jog controls are locked (except during a pen change, see below).

### Setting up the pen height (new pen / different paper)

1. Click **Pen up**.
2. Go down with **▼ 0.5**, finishing with **▼ 0.1**, until the tip just touches the paper.
3. Go another **0.5–1 mm** lower (a little pressure), then click **Set as down**.
4. Go back up with **▲** until the pen is safely clear (about 1–2 mm above the paper), then **Set as up**.
5. Check with **Pen down** / **Pen up**.

---

## Speed & pen

| Setting | Meaning | Notes |
|---|---|---|
| **Drawing** | Speed with the pen down | Slower gives cleaner, richer lines. Too fast can make fineliners skip or fade. |
| **Travel** | Speed with the pen up between lines | Don't run it at the very maximum – e.g. **8000 mm/min** – or the plotter may lose steps (see below). |
| **Jog** | Speed when jogging with the arrows | – |
| **Pen up (Z)** | Z height with the pen raised | Only as high as needed (e.g. 0.5–2 mm). Higher wastes time over thousands of lifts. |
| **Pen down (Z)** | Z height at which the pen draws | Paper contact plus a little pressure (currently 5 mm). |
| **Z speed** | How fast the pen moves up and down | Too fast can slam the pen onto the paper and leave dots or blots at line starts. |
| **Delay after down** | Wait (s) after lowering before moving | Helps if line starts are missing or faint (e.g. 0.05–0.2 s). |
| **Delay after up** | Wait (s) after lifting before moving away | Helps with small hooks or drag marks at line ends. |

**Z values** are in mm from the power-on position. **0 = fully up**, larger values go lower.
The firmware allows **0 to 12 mm**.

**Delays** are normally 0. Each delay is added per line: with 14,000 lines, 0.1 s already adds
about **23 minutes**.

**Maximum values:** on connect, speeds are automatically capped at the firmware maximum
(X/Y 11,000 mm/min, Z 5000 mm/min).

**While plotting:** values are fixed when the plot starts. Changes apply to the next plot.

---

## Machine (work area and limits)

The plotter has no limit switches. It only knows how far it has moved **since it was switched on**.
So the power-on position counts as **machine home**, and all limits are measured from there.

- **Max X / Max Y:** size of the usable area from the power-on corner (dashed in the preview).
  Jogging stops at the limit; plots and frames outside it are not started at all.
- The firmware allows **420 × 297 mm**. A smaller value you enter is kept and never enlarged automatically on connect.
- **Enforce limits** should always be on.
- **Invert X / Invert Y / Swap X/Y:** only needed if the arrows move in the wrong direction.

---

## Optimization

Applied when a file is loaded. After changing anything, press **Recalculate**.
Each field shows its default below it; changed values are highlighted.
**Defaults** resets everything (then “Recalculate” again).

| Setting | Default | Meaning |
|---|---|---|
| **Group layers by** | Automatic | *Color:* one layer per pen color. *Layer/group:* one layer per Illustrator layer. *Everything:* a single layer. *Automatic:* by color if the file has 2–12 colors, otherwise by layer. |
| **Optimize order** | on | Sorts the lines so that travel moves are as short as possible. Saves the most time. |
| **Join connecting lines** | on | Lines whose end is almost at the start of the next one are drawn in one stroke without lifting. |
| **Remove duplicates** | on | Identical lines (e.g. exported twice from Illustrator) are drawn only once. |
| **Join within** | 0.1 mm | Maximum gap for two lines to count as “connecting”. Larger = fewer lifts, but small gaps get bridged. |
| **Simplify** | 0.02 mm | Removes points that deviate less than this from the line. Larger = faster, but curves get more angular. |
| **Drop shorter than** | 0 mm | Lines shorter than this are not plotted (against dots and crumbs). |

---

## Plot

1. Load an SVG (**Open SVG**, or drop the file on the preview). The layers (colors) appear on the right
   under **Layers**; you can toggle and reorder them.
   **Sublayers:** with “Group layers by: Color” (or Automatic), each pen color lists the
   Illustrator layers it is made of. Each one can be unticked individually. Unticked sublayers
   disappear from the preview and are not plotted. If everything in a color is unticked, that color
   is skipped (no pen change).
   Showing or hiding a sublayer is instant; the plot order of the remaining lines stays the same.
   **While plotting**, the colour checkboxes only show or hide the colour in the preview – the
   running plot isn't changed, and everything is shown again when it ends. Sublayers are locked then.
2. Under **Placement**, set position and size (X/Y, Width/Height, Scale, Rotation); **Center**, **Fit**
   and **100 %** help with alignment.
   **Reference point (the 3×3 grid next to X/Y):** sets which corner or center of the design X and Y
   refer to (red square in the preview). Example: choose the center and enter X 210 / Y 148.5 to put
   the design exactly in the middle of an A3 landscape sheet. When you change scale, width, height or
   rotation, the reference point stays put.
3. **Trace frame:** the raised pen traces the outline of the design so you can check its position on the sheet.
4. **Plot.** Between layers the plotter stops for a pen change if “Pause between layers (pen change)” is on.

**Pen change:** the head moves to the origin with the pen raised, where you line up the new pen
(e.g. on a marked dot). During the change you may jog, raise/lower the pen, return to the origin
and set a new origin with **Set origin**. An origin that would push the plot outside the work area
is rejected. Then press **Continue – pen changed**. If you press **Stop** during the change, the
remembered position is the start of the next layer (e.g. layer 2, path 1).

| Function | Description |
|---|---|
| **Pause / Resume** | Stops and continues from the same point. The space bar works too. |
| **Stop** | Aborts. The plotter brakes, lifts the pen and stays where it is – on purpose, so you can see where it stopped and nothing moves while you fix the problem. Press the house to return to the origin. The origin is kept and the position is remembered for resuming. (**STOP** at the top right is the emergency stop.) “Return to origin at the end” only applies when a plot finishes normally. |
| **Plot in reverse** | Layers and lines from end to start, each line in the opposite direction. Handy if e.g. the ink ran out and you want to finish the rest from the back. |
| **Start from** | **Pick in preview**, then click a line. A red marker shows the spot. Lines already done are faded, the ones still to plot are solid. Layer and path can also be entered as numbers (**Layer**, **Path no.**); **Reset** starts from the beginning again. |
| **Resume after an abort** | **Show & resume here** sets the interrupted position (including direction) as the start point. Then start with **Plot**. Works even after restarting Nib. |

---

## Safe operation

- **Always switch on in the corner** (carriage against both stops). Otherwise the limits are wrong.
- **Don't move the carriage by hand** while the plotter is on, or between switching off and on, without pushing it back into the corner afterwards.
- **After a stop in mid-move or after hitting a stop:** switch off, push the carriage into the corner, switch on again.
- **Lost steps:** at very high speed (especially travel at maximum) the heavy Y carriage can lose steps. The position is then wrong and it can hit the end despite the limits. Reduce the travel speed a little.
- **Close the UUNA software first.** Only one program can use the plotter's port at a time.
- Choose **SIMULATOR** as the port to try things out without a plotter.
