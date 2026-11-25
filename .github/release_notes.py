"""Release text for a tag, built from CHANGELOG.md (used by .github/workflows/release.yml).

    python .github/release_notes.py v1.2.0           # prints the release text
    python .github/release_notes.py v1.2.0 --check   # only checks tag, VERSION and changelog
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


tag = sys.argv[1]
version = tag.removeprefix("v")
code_version = re.search(r'^VERSION = "([^"]+)"', read("server.py"), re.M).group(1)
if code_version != version:
    sys.exit(f"Tag {tag} doesn't match VERSION = \"{code_version}\" in server.py")

m = re.search(rf"^## {re.escape(version)}\b.*?\n(.*?)(?=^## |\Z)", read("CHANGELOG.md"), re.M | re.S)
if not m or not m.group(1).strip():
    sys.exit(f"CHANGELOG.md has no section '## {version} – <date>'")
if "--check" in sys.argv:
    print(f"OK: {tag}")
    sys.exit(0)

print(f"""## Download & start
- **Windows 10/11:** download `Nib-{tag}-windows.zip`, unzip it, put `Nib.exe` in a folder of its own \
and double-click it. Windows may show a SmartScreen warning because the exe isn't signed: click \
"More info", then "Run anyway".
- **macOS 11 or later, Apple Silicon (M1 or newer):** download `Nib-{tag}-macos.zip`, unzip it and \
move `Nib.app` to Applications. The app isn't signed by Apple, so macOS blocks it the first time: \
double-click it and close the warning with **Done**, then open **System Settings → Privacy & Security**, \
scroll all the way down, click **Open Anyway** and start Nib again. If macOS says the app "is damaged" or \
there's no Open Anyway button, run `xattr -dr com.apple.quarantine /Applications/Nib.app` in Terminal. \
Intel Macs can run Nib from source (see the README).

**Updating:** replace `Nib.exe` or `Nib.app` with the new version. Your settings are kept.

## What's new
{m.group(1).strip()}

Full list: [CHANGELOG.md](https://github.com/pedda90/Nib/blob/main/CHANGELOG.md) · \
Documentation: [USAGE.md](https://github.com/pedda90/Nib/blob/main/USAGE.md)""")
