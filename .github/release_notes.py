"""Release text for a tag, built from CHANGELOG.md (used by .github/workflows/release.yml).

    python .github/release_notes.py v1.3.0           # prints the release text
    python .github/release_notes.py v1.3.0 --check   # only checks tag, VERSION and changelog
    python .github/release_notes.py v1.1.0 --old     # text for an older release (no VERSION check)

Every release has the same layout: an intro sentence, "Download & start", "What's new" and the
links. The intro is the first paragraph of the version's CHANGELOG section (lines before the
first "- " item); the items follow. Wrapped items are joined into one line each.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = "https://github.com/pedda90/Nib/blob/main"


def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


def section(version):
    """(intro, [items]) of a version in CHANGELOG.md."""
    m = re.search(rf"^## {re.escape(version)}\b.*?\n(.*?)(?=^## |\Z)", read("CHANGELOG.md"), re.M | re.S)
    if not m or not m.group(1).strip():
        sys.exit(f"CHANGELOG.md has no section '## {version} – <date>'")
    intro, items = [], []
    for line in m.group(1).strip().splitlines():
        if line.startswith("- "):
            items.append(line[2:].strip())
        elif line.startswith((" ", "\t")) and items:
            items[-1] += " " + line.strip()              # continuation of a wrapped item
        elif line.strip() and not items:
            intro.append(line.strip())
    return " ".join(intro), items


def download(tag, windows_only=False):
    win = (f"- **Windows 10/11:** download `Nib-{tag}{'' if windows_only else '-windows'}.zip`, unzip it, "
           "put `Nib.exe` in a folder of its own and double-click it. Windows may show a SmartScreen "
           'warning because the exe isn\'t signed: click "More info", then "Run anyway".')
    if windows_only:
        mac = ("- **macOS:** no app in this version yet – Nib can run in the browser from source "
               "(see the README).")
    else:
        mac = (f"- **macOS 11 or later, Apple Silicon (M1 or newer):** download `Nib-{tag}-macos.zip`, unzip "
               "it and move `Nib.app` to Applications. The app isn't signed by Apple, so macOS blocks it the "
               "first time: double-click it and close the warning with **Done**, then open **System Settings → "
               "Privacy & Security**, scroll all the way down, click **Open Anyway** and start Nib again. If "
               'macOS says the app "is damaged" or there\'s no Open Anyway button, run '
               "`xattr -dr com.apple.quarantine /Applications/Nib.app` in Terminal. Intel Macs can run Nib "
               "from source (see the README).")
    apps = "`Nib.exe`" if windows_only else "`Nib.exe` or `Nib.app`"
    return f"## Download & start\n{win}\n{mac}\n\n**Updating:** replace {apps} with the new version. " \
           f"Your settings are kept."


def notes(tag, windows_only=False):
    intro, items = section(tag.removeprefix("v"))
    parts = [intro] if intro else []
    parts += [download(tag, windows_only), "## What's new\n" + "\n".join(f"- {i}" for i in items),
              f"Full list: [CHANGELOG.md]({REPO}/CHANGELOG.md) · Documentation: [USAGE.md]({REPO}/USAGE.md)"]
    return "\n\n".join(parts)


if __name__ == "__main__":
    tag = sys.argv[1]
    version = tag.removeprefix("v")
    if "--old" not in sys.argv:
        code_version = re.search(r'^VERSION = "([^"]+)"', read("server.py"), re.M).group(1)
        if code_version != version:
            sys.exit(f"Tag {tag} doesn't match VERSION = \"{code_version}\" in server.py")
    section(version)
    if "--check" in sys.argv:
        print(f"OK: {tag}")
        sys.exit(0)
    print(notes(tag, windows_only=version == "1.0.0"))       # 1.0.0 had a Windows build only
