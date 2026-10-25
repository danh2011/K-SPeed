#!/usr/bin/env python3
"""Point the installer at your GitHub repo:  python tools/set_repo.py YOUR_USER/YOUR_REPO"""
import re
import sys
from pathlib import Path

if len(sys.argv) != 2 or not re.fullmatch(r"[\w.-]+/[\w.-]+", sys.argv[1]) or sys.argv[1] == "OWNER/REPO":
    sys.exit("usage: python tools/set_repo.py OWNER/REPO   (your GitHub user and repository name)")

slug = sys.argv[1]
root = Path(__file__).resolve().parent.parent
changed = 0
for rel in ("install.sh", "install.ps1", "installer/manager.py", "README.md"):
    p = root / rel
    text = p.read_bytes().decode("utf-8")
    new = text.replace("OWNER/REPO", slug)
    if new != text:
        p.write_bytes(new.encode("utf-8"))  # bytes: keep line endings untouched
        print("updated", rel)
        changed += 1
print("Done (%d files)." % changed)
print("Commit and push; then the one-line installers in the README work for everyone.")
