"""Writes the Windows version resource for Nib.exe (Properties -> Details).

The version comes from VERSION in server.py. build_exe.bat runs this before PyInstaller:
    python version_info.py build\\version_info.txt
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

with open(os.path.join(HERE, "server.py"), encoding="utf-8") as f:
    version = re.search(r'^VERSION = "([^"]+)"', f.read(), re.M).group(1)

nums = [int(n) for n in re.findall(r"\d+", version)[:4]]
nums += [0] * (4 - len(nums))
tup = ", ".join(map(str, nums))

text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers=({tup}), prodvers=({tup}), mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([StringTable('040904B0', [
      StringStruct('CompanyName', 'Peter Dietrich'),
      StringStruct('FileDescription', 'Nib - pen plotter control'),
      StringStruct('FileVersion', '{version}'),
      StringStruct('InternalName', 'Nib'),
      StringStruct('LegalCopyright', '(c) 2026 Peter Dietrich - PolyForm Noncommercial 1.0.0'),
      StringStruct('OriginalFilename', 'Nib.exe'),
      StringStruct('ProductName', 'Nib'),
      StringStruct('ProductVersion', '{version}')])]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""

out = sys.argv[1]
os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    f.write(text)
print(f"Version {version}")
