# Nib

*Pen plotter control – Every line, by the pen.*

Custom control software for the UUNATeK 3.0 pen plotter (GRBL/FluidNC over USB/CH340).
Light and dark theme (follows Windows, or switch with the button at the top right).

**Every control and setting explained: [USAGE.md](USAGE.md)**

![Nib in light mode, paused at a pen change after two of three layers](docs/screenshot-light.png)

<details>
<summary>Dark mode</summary>

![Nib in dark mode](docs/screenshot-dark.png)

</details>

*Screenshots at 2560 × 1440 (WQHD), using the built-in plotter simulator.*

## Running Nib
Double-click **`Nib.exe`**. Nib opens in its own window – no browser needed.
**Quitting:** close the window. If a plot is running (also paused or waiting for a pen change),
Nib asks first. Answering “Yes” aborts the plot and remembers the position so you can resume later.
Settings (`settings.json`) and the resume point (`job_state.json`) are stored next to the exe.

**Rebuilding the exe** (after changing the code): double-click **`build_exe.bat`**. It takes about
half a minute and puts a new `Nib.exe` into this folder. Requires Python and Windows 11
(or the Edge WebView2 runtime, which Windows 11 includes).

**In a browser instead:** `Start Nib.bat` serves the interface at http://127.0.0.1:8765.
Nib exits by itself when the browser window is closed, except while plotting.
For development, `server.py --keep-running` turns that off.

**Important:** close the UUNA software first. Only one program can use COM3 at a time.

## First test with the real plotter
1. Select **COM3** at the top, then **Connect**. The console should show “Controller started: Grbl …”.
2. Try **Pen up** and **Pen down**. If needed, adjust “Pen up (Z)” / “Pen down (Z)” under *Speed & pen*.
   The defaults come from the UUNA configuration (0.5 mm / 5 mm).
3. Jog with the arrows and check: → moves right, ↓ moves towards you (down the sheet).
   If not, tick **Invert X**, **Invert Y** or **Swap X/Y** under *Machine*.
4. Move the pen to the **top-left corner of the sheet**, then press **Set origin**.
5. Load an SVG (**Open SVG**), then **Trace frame**: the raised pen traces the outline shown in the preview.
6. **Plot**.

## Features
- SVG from Illustrator, DrawingBotV3 etc. at the correct size in mm,
  keeping the position on the artboard.
- Layers by color or by Illustrator layer – toggle them, reorder them, automatic pause for pen changes.
- Path optimization: sort order, join connecting lines, remove duplicates, simplify (defaults are shown).
- Show or hide individual Illustrator layers within one pen color.
- Preview with travel moves, time estimate per layer, live progress and pen position.
- Pause/resume (also with the space bar), stop without losing the origin,
  **resume after an abort** (even after restarting the program) or start from any path.
- **Plot in reverse** (end to start) and pick the start point by clicking in the preview.
- Work-area limits measured from the power-on corner; speeds capped at the firmware maximum.
- Manual jogging, adjustable speeds, console for G-code and `$` commands.
- “SIMULATOR” port for trying things out without a plotter.

## Files
| File | Contents |
|---|---|
| `server.py` | Web server and job control |
| `grbl.py` | Connection, streaming, plot job |
| `svgload.py` | SVG import |
| `optimize.py` | Path optimization |
| `gcode.py` | Placement and G-code |
| `mockgrbl.py` | Simulated plotter |
| `app.py` | Program window (Nib.exe) |
| `web/` | User interface (fonts: IBM Plex, SIL Open Font License, see `web/fonts/`) |
| `settings.json`, `job_state.json` | Saved settings and resume point (created automatically) |
