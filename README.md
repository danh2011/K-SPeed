# Spaceplane Takeoff Assistant

A Kerbal Space Program (1.12.x) plugin that calls out **V1 / VR / V2** for your spaceplane,
knows the runway length, and tells you to **ABORT** when you can't get airborne in time.

- Voice callouts: "Airspeed alive", "V one", "Rotate", "V two", "Abort, abort", "Go, committed", "Brake"
- Live abort logic: compares runway left vs. distance needed to stop and to lift off
- Learns each craft's real liftoff speed (speeds are an *estimate* until your first takeoff)
- Mark any runway in-game; the KSC runway is measured automatically from the SPH spawn point

## Install (one command)

**macOS / Linux**

```sh
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/OWNER/REPO/main/install.sh)"
```

**Windows (PowerShell)**

```powershell
irm https://raw.githubusercontent.com/OWNER/REPO/main/install.ps1 | iex
```

That downloads the repo, then opens a small keyboard-driven installer (arrow keys + Enter) that:

1. checks for the .NET SDK and offers to install it (winget / brew / apt / dnf / pacman),
2. finds your KSP install (Steam libraries, GOG, common folders) or lets you type a path,
3. compiles the plugin against *your* KSP and copies it into `GameData/SpaceplaneTakeoffAssistant`,
4. installs a `takeoff-assistant` command.

Requirements: **Python 3.8+** (only to run the installer) and the **.NET SDK 6+** (to compile).
The plugin has to be compiled locally because it links against KSP's own DLLs, which can't be redistributed.

Non-interactive: add `--yes --ksp "/path/to/Kerbal Space Program"`, e.g.
`curl -fsSL .../install.sh | bash -s -- --yes --ksp "$HOME/KSP"`.

## Commands

```text
takeoff-assistant              interactive menu
takeoff-assistant install      build + install (also re-installs)
takeoff-assistant update       pull latest from GitHub, rebuild, reinstall
takeoff-assistant status       what's installed, and is an update available?
takeoff-assistant uninstall    remove the mod, keep settings/calibration/runways
takeoff-assistant uninstall --purge       ...and delete settings/calibration/runways
takeoff-assistant uninstall --everything  ...and remove this tool too
```

Useful flags (put them *after* the command): `--ksp PATH`, `--yes`, `--verbose`, `--force`, `--ref BRANCH`.

Your settings, per-craft calibration and custom runways live in
`GameData/SpaceplaneTakeoffAssistant/PluginData/` and are never overwritten by an update.

## In the game

- Launch a plane from the SPH. **Alt+K** shows/hides the window.
- Take off once per craft so it learns the real liftoff speed.
- Other runways: park at one end, *Mark start (A)*, taxi to the far end, *Mark end (B)*.
- Tuning: `PluginData/settings.cfg` (`brakeDecel` matters most for abort timing).

## Where things go

| What | Where |
| --- | --- |
| Installer checkout + state | `~/.takeoff-assistant` (Windows: `%LOCALAPPDATA%\TakeoffAssistant`) |
| `takeoff-assistant` command | `~/.local/bin` (Windows: `...\TakeoffAssistant\bin`, added to your user PATH) |
| Plugin + sounds | `<KSP>/GameData/SpaceplaneTakeoffAssistant` |
| Build log (if a build fails) | `~/.takeoff-assistant/build.log` |

Override with `TAKEOFF_ASSISTANT_HOME` / `TAKEOFF_ASSISTANT_BIN`.

## Publishing this repo (for the maintainer)

```sh
python tools/set_repo.py YOUR_USER/YOUR_REPO   # swaps the OWNER/REPO placeholder in the scripts and this README
git init -b main && git add -A && git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USER/YOUR_REPO.git && git push -u origin main
```

Every `takeoff-assistant update` tracks the `main` branch, so pushing to `main` ships to everyone.
Forks/mirrors: set `TAKEOFF_ASSISTANT_REPO=you/fork` and/or `TAKEOFF_ASSISTANT_REF=branch`.

## Repo layout

```text
install.sh / install.ps1        one-line bootstrap (fetch repo, launch the manager)
installer/manager.py            TUI + install/update/uninstall/status (Python stdlib only)
mod/                            the KSP plugin (C#), sounds, csproj
ci/                             compiles the plugin against API stubs (no KSP needed)
tests/                          installer tests (run on Windows, macOS, Linux in CI)
tools/set_repo.py               sets your GitHub owner/repo
```

## Development

```sh
python -m unittest discover -s tests -v      # installer tests
dotnet build ci/check.csproj                 # syntax/type check of the plugin without KSP
python installer/manager.py install --ksp "/path/to/KSP" --verbose
```

Compiling against stubs proves the C# is well-formed, not that every KSP API member matches your game version.
If a real build fails with `CS0246`/`CS1061`, open an issue with the end of `build.log` and your KSP version.

## License

MIT
