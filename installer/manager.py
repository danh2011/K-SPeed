#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
K-SPeed manager.

    kspeed                 interactive menu (TUI)
    kspeed install         build the mod against your KSP and install it
    kspeed update          pull the latest from GitHub, rebuild, reinstall
    kspeed uninstall       remove the mod (add --purge to delete settings,
                                    --everything to also remove this tool)
    kspeed status          show what is installed and whether an update exists

Only needs Python 3.8+ (standard library) and the .NET SDK (to compile the plugin).
Works on Windows, macOS and Linux.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

__version__ = "1.0.0"

# Replace with your "owner/repo" (tools/set_repo.py does this for you).
DEFAULT_REPO = "danh2011/k-speed"
PLACEHOLDER_REPO = "OWNER" + "/REPO"  # split so tools/set_repo.py leaves it alone
DEFAULT_REF = "main"

MOD_FOLDER = "kspeed"
DLL_NAME = "kspeed.dll"
CMD_NAME = "kspeed"

IS_WIN = os.name == "nt"
IS_MAC = sys.platform == "darwin"

SOURCE_DIR = Path(__file__).resolve().parent.parent  # the repo checkout this file lives in


def _app_home() -> Path:
    env = os.environ.get("KSPEED_HOME")
    if env:
        return Path(env)
    if IS_WIN:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "K-SPeed"
    return Path.home() / ".kspeed"


HOME = _app_home()
BUILD_DIR = HOME / "build"
STATE_FILE = HOME / "state.json"
BUILD_LOG = HOME / "build.log"

ASSUME_YES = False
VERBOSE = False


# =============================================================================
# Terminal helpers
# =============================================================================
def _enable_vt() -> None:
    """Turn on ANSI escape handling in the Windows console."""
    if not IS_WIN:
        return
    try:
        import ctypes
        k = ctypes.windll.kernel32
        for std in (-11, -12):
            h = k.GetStdHandle(std)
            mode = ctypes.c_uint32()
            if k.GetConsoleMode(h, ctypes.byref(mode)):
                k.SetConsoleMode(h, mode.value | 0x0004)
    except Exception:
        pass


_enable_vt()
try:
    sys.stdout.reconfigure(errors="replace")  # never crash on an odd console encoding
except Exception:
    pass

COLOR = sys.stdout.isatty() and not os.environ.get("NO_COLOR") and os.environ.get("TERM") != "dumb"


def _c(code: str, s: str) -> str:
    return "\x1b[%sm%s\x1b[0m" % (code, s) if COLOR else s


def bold(s): return _c("1", s)
def dim(s): return _c("2", s)
def red(s): return _c("31", s)
def green(s): return _c("32", s)
def yellow(s): return _c("33", s)
def cyan(s): return _c("36", s)


def say(msg: str = "") -> None: print(msg)
def ok(msg: str) -> None: print("  %s %s" % (green("[ok]"), msg))
def info(msg: str) -> None: print("  %s %s" % (cyan("[..]"), msg))
def warn(msg: str) -> None: print("  %s %s" % (yellow("[!!]"), msg))
def fail(msg: str) -> None: print("  %s %s" % (red("[xx]"), msg))


class Abort(Exception):
    pass


def die(msg: str) -> None:
    fail(msg)
    raise Abort(msg)


def term_width() -> int:
    return max(40, shutil.get_terminal_size((80, 24)).columns)


def interactive() -> bool:
    return (not ASSUME_YES) and sys.stdin.isatty() and sys.stdout.isatty()


def read_key() -> str:
    """Blocking single-key read. Returns 'up','down','enter','esc' or the character."""
    if IS_WIN:
        import msvcrt
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            return {"H": "up", "P": "down"}.get(msvcrt.getwch(), "")
        if ch in ("\r", "\n"):
            return "enter"
        if ch == "\x03":
            raise KeyboardInterrupt
        if ch == "\x1b":
            return "esc"
        return ch
    import select
    import termios
    import tty
    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        data = os.read(fd, 1)
        if data == b"\x1b":
            ready, _, _ = select.select([fd], [], [], 0.05)
            if ready:
                data += os.read(fd, 8)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)
    if data in (b"\x1b[A", b"\x1bOA"):
        return "up"
    if data in (b"\x1b[B", b"\x1bOB"):
        return "down"
    if data in (b"\r", b"\n"):
        return "enter"
    if data == b"\x03":
        raise KeyboardInterrupt
    if data == b"\x1b":
        return "esc"
    try:
        return data.decode("utf-8", "ignore")
    except Exception:
        return ""


def menu(title: str, items, default: int = 0, keys=None):
    """
    Arrow-key menu. Returns the chosen index, or None if cancelled (q / Esc).
    Non-interactive sessions return `default` without prompting.
    `keys` maps extra hotkeys (e.g. {'y': 0, 'n': 1}) to indices.
    """
    items = list(items)
    if not interactive():
        return default
    keys = keys or {}
    idx = default
    first = True
    width = term_width()
    sys.stdout.write("\x1b[?25l")
    try:
        while True:
            lines = [bold(title)]
            for i, it in enumerate(items):
                label = ("  > " if i == idx else "    ") + ("%d. " % (i + 1) if len(items) < 10 else "") + it
                label = label[: width - 2]
                lines.append(cyan(bold(label)) if i == idx else label)
            lines.append(dim("  up/down move, Enter select, q cancel"))
            if not first:
                sys.stdout.write("\x1b[%dA\x1b[J" % len(lines))
            sys.stdout.write("\n".join(lines) + "\n")
            sys.stdout.flush()
            first = False
            k = read_key()
            if k == "up":
                idx = (idx - 1) % len(items)
            elif k == "down":
                idx = (idx + 1) % len(items)
            elif k == "enter":
                return idx
            elif k in ("q", "esc"):
                return None
            elif k in ("k",):
                idx = (idx - 1) % len(items)
            elif k in ("j",):
                idx = (idx + 1) % len(items)
            elif k in keys:
                return keys[k]
            elif k.isdigit() and 1 <= int(k) <= len(items):
                return int(k) - 1
    finally:
        sys.stdout.write("\x1b[?25h")
        sys.stdout.flush()


def confirm(question: str, default: bool = True) -> bool:
    if ASSUME_YES:
        return True
    if not interactive():
        return default
    r = menu(question, ["Yes", "No"], default=0 if default else 1, keys={"y": 0, "n": 1})
    return r == 0


def prompt_text(prompt: str) -> str:
    try:
        return input("  " + prompt).strip().strip('"').strip("'")
    except EOFError:
        return ""


def pause() -> None:
    if interactive():
        try:
            input(dim("\n  Press Enter to continue..."))
        except EOFError:
            pass


def banner() -> None:
    say()
    say(bold("  K-SPeed") + dim("  manager v" + __version__))
    say(dim("  V1/VR/V2 callouts and runway abort advice for Kerbal Space Program"))
    say()


# =============================================================================
# State
# =============================================================================
def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict) -> None:
    HOME.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


# =============================================================================
# Finding KSP
# =============================================================================
def managed_dir(ksp: Path):
    for sub in ("KSP_x64_Data/Managed", "KSP.app/Contents/Resources/Data/Managed", "KSP_Data/Managed"):
        d = ksp / sub
        if (d / "Assembly-CSharp.dll").exists():
            return d
    return None


def is_ksp(p: Path) -> bool:
    try:
        return p.is_dir() and (p / "GameData").is_dir() and managed_dir(p) is not None
    except OSError:
        return False


def normalize_ksp(p) -> Path:
    p = Path(os.path.expanduser(str(p)))
    if p.suffix.lower() == ".app":      # macOS: user picked KSP.app
        p = p.parent
    if p.name == "GameData":
        p = p.parent
    return p


def ksp_version(ksp: Path) -> str:
    try:
        text = (ksp / "readme.txt").read_text(encoding="utf-8", errors="ignore")[:4000]
        m = re.search(r"\b(1\.\d{1,2}\.\d{1,2})\b", text)
        return m.group(1) if m else ""
    except OSError:
        return ""


def steam_roots() -> list:
    cands = []
    if IS_WIN:
        for var in ("ProgramFiles(x86)", "ProgramFiles"):
            base = os.environ.get(var)
            if base:
                cands.append(Path(base) / "Steam")
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
                cands.append(Path(winreg.QueryValueEx(k, "SteamPath")[0]))
        except Exception:
            pass
    elif IS_MAC:
        cands.append(Path.home() / "Library" / "Application Support" / "Steam")
    else:
        cands += [Path.home() / ".steam" / "steam",
                  Path.home() / ".local" / "share" / "Steam",
                  Path.home() / ".var" / "app" / "com.valvesoftware.Steam" / ".local" / "share" / "Steam",
                  Path.home() / "snap" / "steam" / "common" / ".local" / "share" / "Steam"]
    roots = []
    for r in cands:
        if r.is_dir() and r not in roots:
            roots.append(r)
        vdf = r / "steamapps" / "libraryfolders.vdf"
        try:
            for m in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text(encoding="utf-8", errors="ignore")):
                lib = Path(m.replace("\\\\", "\\"))
                if lib.is_dir() and lib not in roots:
                    roots.append(lib)
        except OSError:
            pass
    return roots


def find_ksp_installs() -> list:
    found = []

    def add(p):
        p = normalize_ksp(p)
        if p not in found and is_ksp(p):
            found.append(p)

    for env in ("KSP_PATH", "KSP_ROOT"):
        if os.environ.get(env):
            add(os.environ[env])
    for lib in steam_roots():
        add(lib / "steamapps" / "common" / "Kerbal Space Program")
    extras = []
    if IS_WIN:
        extras = ["C:/GOG Games/Kerbal Space Program", "C:/Program Files (x86)/GOG Galaxy/Games/Kerbal Space Program",
                  "C:/Kerbal Space Program"]
    elif IS_MAC:
        extras = ["/Applications/Kerbal Space Program", str(Path.home() / "Applications" / "Kerbal Space Program")]
    else:
        extras = [str(Path.home() / "GOG Games" / "Kerbal Space Program" / "game"),
                  str(Path.home() / "KSP"), str(Path.home() / "Games" / "Kerbal Space Program")]
    for e in extras:
        add(e)
    return found


def ksp_running() -> bool:
    try:
        if IS_WIN:
            out = subprocess.run(["tasklist"], capture_output=True, text=True, timeout=10).stdout.lower()
            return "ksp_x64.exe" in out or "ksp.exe" in out
        out = subprocess.run(["ps", "-A", "-o", "comm="], capture_output=True, text=True, timeout=10).stdout
        return "KSP.x86_64" in out or "KSP.app/Contents/MacOS" in out
    except Exception:
        return False


def choose_ksp(state: dict, explicit):
    """Resolve which KSP folder to use, prompting in the TUI when needed."""
    if explicit:
        p = normalize_ksp(explicit)
        if not is_ksp(p):
            die("That does not look like a KSP install (needs GameData and a Managed folder): %s" % p)
        return p

    remembered = Path(state["ksp"]) if state.get("ksp") else None
    detected = find_ksp_installs()
    if remembered and is_ksp(remembered) and remembered not in detected:
        detected.insert(0, remembered)

    if not interactive():
        if remembered and is_ksp(remembered):
            return remembered
        if detected:
            return detected[0]
        die("Could not find Kerbal Space Program. Re-run with --ksp \"/path/to/Kerbal Space Program\".")

    while True:
        items = []
        for p in detected:
            v = ksp_version(p)
            items.append("%s%s" % (p, ("   (KSP %s)" % v) if v else ""))
        items.append("Enter a path manually...")
        title = "Which Kerbal Space Program install?" if detected else "No KSP install found automatically."
        r = menu(title, items, default=0)
        if r is None:
            raise Abort("cancelled")
        if r < len(detected):
            return detected[r]
        typed = prompt_text("Path to your KSP folder (the one containing GameData): ")
        if not typed:
            continue
        p = normalize_ksp(typed)
        if is_ksp(p):
            return p
        warn("Not a KSP install: %s" % p)


# =============================================================================
# .NET SDK
# =============================================================================
def find_dotnet():
    exe = shutil.which("dotnet")
    if exe:
        return exe
    guesses = []
    if IS_WIN:
        guesses = [os.path.join(os.environ.get("ProgramFiles", "C:\\Program Files"), "dotnet", "dotnet.exe")]
    elif IS_MAC:
        guesses = ["/usr/local/share/dotnet/dotnet", "/opt/homebrew/bin/dotnet", "/usr/local/bin/dotnet"]
    else:
        guesses = ["/usr/share/dotnet/dotnet", "/usr/lib/dotnet/dotnet", "/usr/local/bin/dotnet",
                   str(Path.home() / ".dotnet" / "dotnet")]
    for g in guesses:
        if os.path.exists(g):
            return g
    return None


def dotnet_major(exe: str) -> int:
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30).stdout.strip()
        return int(out.split(".")[0])
    except Exception:
        return 0


def dotnet_install_command():
    """(human description, argv) for installing the .NET 8 SDK, or (hint, None) if we cannot automate it."""
    if IS_WIN and shutil.which("winget"):
        return ("winget install Microsoft.DotNet.SDK.8",
                ["winget", "install", "--id", "Microsoft.DotNet.SDK.8", "-e",
                 "--accept-package-agreements", "--accept-source-agreements"])
    if IS_MAC and shutil.which("brew"):
        return ("brew install --cask dotnet-sdk", ["brew", "install", "--cask", "dotnet-sdk"])
    if not IS_WIN and not IS_MAC:
        if shutil.which("apt-get"):
            return ("sudo apt-get install -y dotnet-sdk-8.0", ["sudo", "apt-get", "install", "-y", "dotnet-sdk-8.0"])
        if shutil.which("dnf"):
            return ("sudo dnf install -y dotnet-sdk-8.0", ["sudo", "dnf", "install", "-y", "dotnet-sdk-8.0"])
        if shutil.which("pacman"):
            return ("sudo pacman -S --noconfirm dotnet-sdk", ["sudo", "pacman", "-S", "--noconfirm", "dotnet-sdk"])
    return ("Download the .NET SDK 8 from https://dotnet.microsoft.com/download", None)


def ensure_dotnet(allow_auto: bool):
    exe = find_dotnet()
    if exe and dotnet_major(exe) >= 6:
        ok(".NET SDK %s" % subprocess.run([exe, "--version"], capture_output=True, text=True).stdout.strip())
        return exe
    desc, argv = dotnet_install_command()
    warn("The .NET SDK (6 or newer) is needed to compile the plugin and was not found.")
    if argv and allow_auto and confirm("Install it now with: %s ?" % desc):
        info("Running: %s" % desc)
        if subprocess.call(argv) == 0:
            exe = find_dotnet()
            if exe and dotnet_major(exe) >= 6:
                ok("Installed .NET SDK")
                return exe
            warn("Installed, but this terminal can't see it yet. Open a NEW terminal and run: %s install" % CMD_NAME)
            raise Abort("restart terminal")
        die("The .NET installation failed. Install it manually and re-run.")
    say("      Install it with:  %s" % desc)
    say("      then run:         %s install" % CMD_NAME)
    raise Abort("dotnet missing")


# =============================================================================
# Building
# =============================================================================
def run_logged(cmd, log_path: Path, cwd=None) -> int:
    """Run a command, logging all output; show the latest line (or everything with --verbose)."""
    HOME.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, DOTNET_CLI_TELEMETRY_OPTOUT="1", DOTNET_NOLOGO="1")
    with open(str(log_path), "w", encoding="utf-8") as log:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=cwd, env=env,
                             encoding="utf-8", errors="replace", bufsize=1)
        width = term_width() - 8
        for line in p.stdout:
            log.write(line)
            if VERBOSE:
                sys.stdout.write(line)
            elif sys.stdout.isatty():
                sys.stdout.write("\r\x1b[K    " + dim(line.strip()[:width]))
                sys.stdout.flush()
        code = p.wait()
        if sys.stdout.isatty() and not VERBOSE:
            sys.stdout.write("\r\x1b[K")
    return code


def build_plugin(dotnet: str, ksp: Path) -> Path:
    csproj = SOURCE_DIR / "mod" / "kspeed.csproj"
    if not csproj.exists():
        die("Cannot find %s" % csproj)
    if BUILD_DIR.exists():
        shutil.rmtree(str(BUILD_DIR), ignore_errors=True)
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    info("Compiling plugin against your KSP (first run downloads reference assemblies)...")
    cmd = [dotnet, "build", str(csproj), "-c", "Release", "-nologo", "-o", str(BUILD_DIR),
           "-p:KSPRoot=%s" % ksp.as_posix(), "-p:SkipDeploy=true"]
    code = run_logged(cmd, BUILD_LOG)
    dll = BUILD_DIR / DLL_NAME
    if code != 0 or not dll.exists():
        fail("Build failed. Full log: %s" % BUILD_LOG)
        try:
            tail = BUILD_LOG.read_text(encoding="utf-8", errors="replace").splitlines()
            errs = [l for l in tail if " error " in l][:8] or tail[-12:]
            for l in errs:
                say("      " + l.strip()[: term_width() - 8])
            blob = "\n".join(tail)
            if "NU1301" in blob or "NU1101" in blob:
                warn("NuGet could not download packages. Check your internet connection / proxy.")
            if "CS0246" in blob or "CS1061" in blob or "CS0117" in blob:
                warn("Looks like a KSP API mismatch. This mod targets KSP 1.12.x - which version do you have?")
        except OSError:
            pass
        raise Abort("build failed")
    ok("Built %s" % DLL_NAME)
    return dll


# =============================================================================
# Deploy / remove
# =============================================================================
def _inside(root: Path, p: Path) -> bool:
    try:
        r = str(root.resolve())
        q = str(p.resolve())
    except OSError:
        return False
    return q == r or q.startswith(r + os.sep)


def remove_manifest_files(ksp: Path, manifest) -> int:
    n = 0
    for rel in manifest:
        target = ksp / rel
        if _inside(ksp, target) and target.is_file():
            try:
                target.unlink()
                n += 1
            except OSError:
                pass
    return n


def prune_empty_dirs(base: Path) -> None:
    if not base.is_dir():
        return
    for d in sorted([p for p in base.rglob("*") if p.is_dir()], key=lambda p: len(p.parts), reverse=True):
        try:
            d.rmdir()
        except OSError:
            pass
    try:
        base.rmdir()
    except OSError:
        pass


def deploy(ksp: Path, dll: Path, old_manifest) -> list:
    gd = ksp / "GameData"
    remove_manifest_files(ksp, old_manifest)  # drop files from a previous version that no longer exist
    manifest = []
    src_gd = SOURCE_DIR / "mod" / "GameData"
    try:
        for f in sorted(src_gd.rglob("*")):
            if not f.is_file() or f.name == ".gitkeep":
                continue
            rel = f.relative_to(src_gd)
            if "PluginData" in rel.parts:     # never touch user settings
                continue
            dest = gd / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(f), str(dest))
            manifest.append("GameData/" + rel.as_posix())
        dest = gd / MOD_FOLDER / "Plugins" / DLL_NAME
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(dll), str(dest))
        manifest.append("GameData/%s/Plugins/%s" % (MOD_FOLDER, DLL_NAME))
        (gd / MOD_FOLDER / "PluginData").mkdir(parents=True, exist_ok=True)
    except PermissionError as e:
        fail("Permission denied writing to %s" % gd)
        if IS_WIN:
            say("      KSP is probably under 'Program Files'. Run this terminal as Administrator, or move KSP.")
        elif ksp_running():
            say("      KSP seems to be running; close it and retry.")
        raise Abort(str(e))
    return manifest


# =============================================================================
# Launcher on PATH
# =============================================================================
def bin_dir() -> Path:
    if IS_WIN:
        return HOME / "bin"
    return Path(os.environ.get("KSPEED_BIN") or (Path.home() / ".local" / "bin"))


def launcher_path() -> Path:
    return bin_dir() / (CMD_NAME + (".cmd" if IS_WIN else ""))


def win_path_update(add=None, remove=None) -> None:
    try:
        import ctypes
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0,
                            winreg.KEY_READ | winreg.KEY_WRITE) as k:
            try:
                cur, typ = winreg.QueryValueEx(k, "Path")
            except FileNotFoundError:
                cur, typ = "", winreg.REG_EXPAND_SZ
            parts = [p for p in cur.split(";") if p]
            if remove:
                parts = [p for p in parts if p.lower() != remove.lower()]
            if add and add.lower() not in [p.lower() for p in parts]:
                parts.append(add)
            winreg.SetValueEx(k, "Path", 0, typ, ";".join(parts))
        ctypes.windll.user32.SendMessageTimeoutW(0xFFFF, 0x1A, 0, "Environment", 2, 5000, None)
    except Exception as e:
        warn("Could not update PATH automatically: %s" % e)


def install_launcher() -> Path:
    p = launcher_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    manager = Path(__file__).resolve()
    if IS_WIN:
        p.write_text('@echo off\r\n"%s" "%s" %%*\r\n' % (sys.executable, manager), encoding="utf-8")
        win_path_update(add=str(bin_dir()))
    else:
        p.write_text('#!/bin/sh\nexec "%s" "%s" "$@"\n' % (sys.executable, manager), encoding="utf-8")
        p.chmod(0o755)
        if str(bin_dir()) not in os.environ.get("PATH", "").split(os.pathsep):
            warn("%s is not on your PATH. Add this to your shell profile:" % bin_dir())
            say('      export PATH="%s:$PATH"' % bin_dir())
    return p


# =============================================================================
# GitHub: version checks and pulling
# =============================================================================
def have_git() -> bool:
    return shutil.which("git") is not None


def git(*args, cwd=None):
    return subprocess.run(["git"] + list(args), cwd=str(cwd or SOURCE_DIR), capture_output=True,
                          text=True, timeout=120)


def is_git_checkout() -> bool:
    return (SOURCE_DIR / ".git").exists() and have_git()


def resolve_repo(state: dict, explicit=None) -> str:
    slug = explicit or state.get("repo") or os.environ.get("KSPEED_REPO")
    if not slug and is_git_checkout():
        r = git("config", "--get", "remote.origin.url")
        m = re.search(r"github\.com[:/](.+?)(?:\.git)?\s*$", r.stdout.strip())
        if m:
            slug = m.group(1)
    return slug or DEFAULT_REPO


def local_sha(state: dict) -> str:
    if is_git_checkout():
        r = git("rev-parse", "HEAD")
        if r.returncode == 0:
            return r.stdout.strip()
    return state.get("sha", "")


def remote_sha(slug: str, ref: str) -> str:
    if slug == PLACEHOLDER_REPO:
        return ""
    if have_git():
        try:
            url = os.environ.get("KSPEED_GIT_URL") or "https://github.com/%s.git" % slug
            r = subprocess.run(["git", "ls-remote", url, "refs/heads/%s" % ref],
                               capture_output=True, text=True, timeout=20)
            if r.returncode == 0 and r.stdout.strip():
                return r.stdout.split()[0]
        except Exception:
            pass
    try:
        req = urllib.request.Request("https://api.github.com/repos/%s/commits/%s" % (slug, ref),
                                     headers={"Accept": "application/vnd.github.sha",
                                              "User-Agent": "kspeed"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.read().decode("ascii", "ignore").strip()
    except Exception:
        return ""


def pull_latest(slug: str, ref: str) -> str:
    """Fetch the newest source into SOURCE_DIR. Returns a short changelog (may be empty)."""
    if is_git_checkout():
        old = git("rev-parse", "HEAD").stdout.strip()
        r = git("fetch", "origin", ref)
        if r.returncode != 0:
            die("git fetch failed: %s" % r.stderr.strip()[:300])
        log = git("log", "--oneline", "--no-decorate", "-n", "15", "%s..FETCH_HEAD" % old).stdout.strip()
        r = git("reset", "--hard", "FETCH_HEAD")
        if r.returncode != 0:
            die("git reset failed: %s" % r.stderr.strip()[:300])
        return log

    url = "https://codeload.github.com/%s/zip/refs/heads/%s" % (slug, ref)
    info("Downloading %s" % url)
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "kspeed"}),
                                    timeout=60) as resp:
            data = resp.read()
    except (urllib.error.URLError, OSError) as e:
        die("Download failed: %s" % e)
    tmp = Path(tempfile.mkdtemp(prefix="takeoff-"))
    try:
        zpath = tmp / "src.zip"
        zpath.write_bytes(data)
        with zipfile.ZipFile(str(zpath)) as z:
            z.extractall(str(tmp / "x"))
        tops = list((tmp / "x").iterdir())
        if len(tops) != 1:
            die("Unexpected archive layout")
        for child in list(SOURCE_DIR.iterdir()):
            if child.name == ".git":
                continue
            shutil.rmtree(str(child)) if child.is_dir() else child.unlink()
        for child in tops[0].iterdir():
            shutil.move(str(child), str(SOURCE_DIR / child.name))
    finally:
        shutil.rmtree(str(tmp), ignore_errors=True)
    return ""


# =============================================================================
# Commands
# =============================================================================
def cmd_install(args) -> int:
    state = load_state()
    banner()
    dotnet = None
    if not args.skip_build:
        dotnet = ensure_dotnet(allow_auto=interactive() or args.install_deps)
    ksp = choose_ksp(state, args.ksp)
    ok("KSP: %s%s" % (ksp, ("  (version %s)" % ksp_version(ksp)) if ksp_version(ksp) else ""))
    v = ksp_version(ksp)
    if v and not v.startswith("1.12"):
        warn("This mod targets KSP 1.12.x; you have %s. It may fail to compile or load." % v)
    if ksp_running():
        warn("KSP appears to be running. Close it first, or the plugin DLL may be locked.")
        if interactive() and not confirm("Continue anyway?", default=False):
            raise Abort("KSP running")
    if interactive() and not confirm("Install into %s ?" % ksp):
        raise Abort("cancelled")

    if args.skip_build:
        dll = BUILD_DIR / DLL_NAME
        if not dll.exists():
            die("--skip-build given but %s does not exist" % dll)
        warn("Skipping build; using %s" % dll)
    else:
        dll = build_plugin(dotnet, ksp)

    manifest = deploy(ksp, dll, state.get("manifest", []))
    ok("Installed %d files into %s" % (len(manifest), ksp / "GameData" / MOD_FOLDER))
    launcher = install_launcher()
    ok("Command installed: %s" % launcher)

    slug = resolve_repo(state, args.repo)
    state.update({
        "repo": slug, "ref": args.ref or state.get("ref") or DEFAULT_REF, "sha": local_sha(state),
        "ksp": str(ksp), "manifest": manifest, "installed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "manager_version": __version__,
    })
    save_state(state)

    say()
    say(bold("  All set."))
    say("   - Start KSP and launch a plane from the SPH. Press Alt+K for the K-SPeed window.")
    say("   - Take off once so the mod learns your craft's real liftoff speed.")
    say("   - Update later with:  %s update" % CMD_NAME)
    say("   - Remove with:        %s uninstall" % CMD_NAME)
    say("   - Settings live in:   %s" % (ksp / "GameData" / MOD_FOLDER / "PluginData"))
    say()
    return 0


def cmd_status(args) -> int:
    state = load_state()
    banner()
    slug = resolve_repo(state, args.repo)
    ref = state.get("ref") or DEFAULT_REF
    ksp = Path(state["ksp"]) if state.get("ksp") else None
    dll = ksp / "GameData" / MOD_FOLDER / "Plugins" / DLL_NAME if ksp else None

    say("  Repository   : %s (%s)" % (slug, ref))
    say("  KSP folder   : %s" % (ksp if ksp else dim("not set")))
    installed = bool(dll and dll.exists())
    say("  Mod installed: %s" % (green("yes") if installed else yellow("no")))
    ls = local_sha(state)
    say("  Local version: %s" % (ls[:8] if ls else dim("unknown")))
    rs = remote_sha(slug, ref)
    if rs:
        if ls and rs == ls:
            say("  Latest       : %s  %s" % (rs[:8], green("up to date")))
        else:
            say("  Latest       : %s  %s" % (rs[:8], yellow("update available - run: %s update" % CMD_NAME)))
    else:
        say("  Latest       : %s" % dim("could not check (offline, or repo not configured)"))
    exe = find_dotnet()
    say("  .NET SDK     : %s" % (subprocess.run([exe, "--version"], capture_output=True, text=True).stdout.strip()
                                  if exe else yellow("not found")))
    say("  Python       : %s" % sys.version.split()[0])
    say()
    return 0


def cmd_update(args) -> int:
    state = load_state()
    banner()
    slug = resolve_repo(state, args.repo)
    ref = args.ref or state.get("ref") or DEFAULT_REF
    if slug == PLACEHOLDER_REPO:
        die("No GitHub repo configured. Run: python tools/set_repo.py YOUR_USER/YOUR_REPO (or set KSPEED_REPO).")
    ksp = choose_ksp(state, args.ksp)

    info("Checking %s (%s) ..." % (slug, ref))
    ls = local_sha(state)
    rs = remote_sha(slug, ref)
    if not rs:
        warn("Could not reach GitHub to compare versions; continuing with a fresh download.")
    elif ls and rs == ls and not args.force:
        ok("Already up to date (%s)." % ls[:8])
        return 0
    else:
        info("Update available: %s -> %s" % (ls[:8] or "unknown", rs[:8]))
    if interactive() and not confirm("Pull the latest and reinstall?"):
        raise Abort("cancelled")

    changes = pull_latest(slug, ref)
    ok("Source updated")
    if changes:
        say(dim("  What's new:"))
        for l in changes.splitlines():
            say("    " + l[: term_width() - 6])

    # Re-run install from the NEW code on disk (this process still holds the old manager in memory).
    state["ref"] = ref
    state["repo"] = slug
    save_state(state)
    cmd = [sys.executable, str(Path(__file__).resolve()), "install", "--yes", "--ksp", str(ksp), "--ref", ref,
           "--repo", slug]
    if VERBOSE:
        cmd.append("--verbose")
    if args.skip_build:
        cmd.append("--skip-build")
    return subprocess.call(cmd)


def cmd_uninstall(args) -> int:
    state = load_state()
    banner()
    ksp = Path(state["ksp"]) if state.get("ksp") else None
    if args.ksp:
        ksp = normalize_ksp(args.ksp)
    if ksp is None:
        det = find_ksp_installs()
        ksp = det[0] if det else None
    if ksp is None or not (ksp / "GameData").is_dir():
        warn("No KSP install on record; nothing to remove from GameData.")
    else:
        if interactive() and not args.purge and not args.everything and not args.no_prompt:
            r = menu("Uninstall options", [
                "Remove the mod only (keep my settings, calibration and runways)",
                "Remove the mod AND delete settings, calibration and runways",
                "Remove everything, including this manager tool",
                "Cancel"], default=0)
            if r is None or r == 3:
                raise Abort("cancelled")
            args.purge = r in (1, 2)
            args.everything = r == 2
        if ksp_running():
            warn("KSP appears to be running; close it first so files can be deleted.")
        mod_dir = ksp / "GameData" / MOD_FOLDER
        removed = remove_manifest_files(ksp, state.get("manifest", []))
        dll = mod_dir / "Plugins" / DLL_NAME
        if dll.exists():
            try:
                dll.unlink()
                removed += 1
            except OSError as e:
                die("Could not delete %s (%s). Is KSP running?" % (dll, e))
        if args.purge:
            if mod_dir.name == MOD_FOLDER and _inside(ksp / "GameData", mod_dir) and mod_dir.is_dir():
                shutil.rmtree(str(mod_dir), ignore_errors=True)
            ok("Removed %s (including settings)" % mod_dir)
        else:
            for sub in ("Plugins", "Sounds"):
                prune_empty_dirs(mod_dir / sub)
            ok("Removed %d mod files" % removed)
            if (mod_dir / "PluginData").exists():
                info("Kept your settings/calibration in %s" % (mod_dir / "PluginData"))
                info("Delete them too with: %s uninstall --purge" % CMD_NAME)
        state["manifest"] = []
        save_state(state)

    if args.everything:
        remove_self(state)
    say()
    return 0


def remove_self(state: dict) -> None:
    lp = launcher_path()
    try:
        if lp.exists():
            lp.unlink()
            ok("Removed command %s" % lp)
    except OSError:
        pass
    if IS_WIN:
        win_path_update(remove=str(bin_dir()))
    inside_home = _inside(HOME, SOURCE_DIR)
    if IS_WIN:
        # The running interpreter can't delete its own folder; let a detached cmd do it after we exit.
        flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(["cmd", "/c", 'ping -n 3 127.0.0.1 >nul & rmdir /s /q "%s"' % HOME],
                         creationflags=flags, close_fds=True)
        ok("Manager data will be removed in a moment: %s" % HOME)
    else:
        if inside_home:
            shutil.rmtree(str(HOME), ignore_errors=True)
            ok("Removed %s" % HOME)
        else:
            for p in (STATE_FILE, BUILD_LOG):
                try:
                    p.unlink()
                except OSError:
                    pass
            shutil.rmtree(str(BUILD_DIR), ignore_errors=True)
            info("Left the source checkout at %s (not inside %s)" % (SOURCE_DIR, HOME))


# =============================================================================
# TUI
# =============================================================================
def cmd_tui(args) -> int:
    if not interactive():
        return cmd_status(args)
    while True:
        state = load_state()
        banner()
        ksp = state.get("ksp")
        installed = bool(ksp and (Path(ksp) / "GameData" / MOD_FOLDER / "Plugins" / DLL_NAME).exists())
        say("  KSP    : %s" % (ksp or dim("not chosen yet")))
        say("  Status : %s" % (green("installed") if installed else yellow("not installed")))
        say()
        r = menu("What would you like to do?", [
            "Update to the latest version" if installed else "Install",
            "Reinstall (rebuild from the current source)" if installed else "Choose a KSP folder first",
            "Uninstall",
            "Status / check for updates",
            "Quit"], default=0)
        say()
        try:
            if r is None or r == 4:
                return 0
            if r == 0:
                (cmd_update if installed else cmd_install)(args)
            elif r == 1:
                if installed:
                    cmd_install(args)
                else:
                    state["ksp"] = str(choose_ksp({}, None))
                    save_state(state)
            elif r == 2:
                cmd_uninstall(args)
            elif r == 3:
                cmd_status(args)
        except Abort as e:
            say(dim("  (%s)" % e))
        except KeyboardInterrupt:
            say()
            return 130
        pause()


# =============================================================================
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=CMD_NAME, description="Install, update and remove the K-SPeed KSP mod.")
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="cmd")

    def common(sp):
        sp.add_argument("--ksp", help="path to your Kerbal Space Program folder (the one containing GameData)")
        sp.add_argument("--repo", help="GitHub owner/repo to update from")
        sp.add_argument("--ref", help="branch to track (default: main)")
        sp.add_argument("-y", "--yes", action="store_true", help="never prompt; accept defaults")
        sp.add_argument("-v", "--verbose", action="store_true", help="show full build output")
        sp.add_argument("--skip-build", action="store_true", help="reuse the last built DLL (development)")
        sp.add_argument("--install-deps", action="store_true", help="with --yes: also install the .NET SDK if missing")
        sp.add_argument("--force", action="store_true", help="update even if already up to date")

    common(p)
    for name, helptext in (("install", "build the plugin and install it into KSP"),
                           ("update", "pull the latest from GitHub, rebuild and reinstall"),
                           ("status", "show install and update status")):
        common(sub.add_parser(name, help=helptext))
    u = sub.add_parser("uninstall", help="remove the mod from KSP")
    common(u)
    u.add_argument("--purge", action="store_true", help="also delete settings, calibration and custom runways")
    u.add_argument("--everything", action="store_true", help="also remove this manager (implies --purge)")
    u.add_argument("--no-prompt", action="store_true", help=argparse.SUPPRESS)
    return p


def main(argv=None) -> int:
    global ASSUME_YES, VERBOSE
    args = build_parser().parse_args(argv)
    for name, default in (("purge", False), ("everything", False), ("no_prompt", False)):
        if not hasattr(args, name):
            setattr(args, name, default)
    if getattr(args, "everything", False):
        args.purge = True
    ASSUME_YES = bool(args.yes) or os.environ.get("KSPEED_YES") == "1"
    VERBOSE = bool(args.verbose)
    handlers = {"install": cmd_install, "update": cmd_update, "uninstall": cmd_uninstall,
                "status": cmd_status, None: cmd_tui}
    try:
        return handlers[args.cmd](args) or 0
    except Abort:
        return 1
    except KeyboardInterrupt:
        say()
        return 130


if __name__ == "__main__":
    sys.exit(main())
