"""Tests for installer/manager.py. Run: python -m unittest discover -s tests -v

These exercise detection, deploy, uninstall and state handling on a fake KSP tree.
They do not need the .NET SDK or a real KSP install (the build step is skipped).
"""
import os
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "installer"))

import manager as m  # noqa: E402


def make_fake_ksp(base: Path) -> Path:
    ksp = base / "Kerbal Space Program"
    managed = {
        "nt": "KSP_x64_Data/Managed",
        "darwin": "KSP.app/Contents/Resources/Data/Managed",
    }.get("darwin" if sys.platform == "darwin" else os.name, "KSP_Data/Managed")
    (ksp / managed).mkdir(parents=True)
    (ksp / managed / "Assembly-CSharp.dll").write_bytes(b"fake")
    (ksp / "GameData").mkdir()
    return ksp


class ManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="kspeed-test-"))
        self.ksp = make_fake_ksp(self.tmp)
        # Redirect all manager state into the temp dir.
        m.HOME = self.tmp / "home"
        m.BUILD_DIR = m.HOME / "build"
        m.STATE_FILE = m.HOME / "state.json"
        m.BUILD_LOG = m.HOME / "build.log"
        m.ASSUME_YES = True
        m.BUILD_DIR.mkdir(parents=True)
        self.dll = m.BUILD_DIR / m.DLL_NAME
        self.dll.write_bytes(b"MZ-fake-dll")

    def test_is_ksp_and_normalize(self):
        self.assertTrue(m.is_ksp(self.ksp))
        self.assertFalse(m.is_ksp(self.tmp))
        self.assertEqual(m.normalize_ksp(self.ksp / "GameData"), self.ksp)

    def test_find_ksp_includes_applications_path_on_mac_and_linux(self):
        expected = Path("/Applications/KSP/Kerbal Space Program")
        with mock.patch.object(m, "steam_roots", return_value=[]), \
                mock.patch.object(m, "is_ksp", side_effect=lambda path: path == expected):
            for is_mac in (False, True):
                with self.subTest(is_mac=is_mac), \
                        mock.patch.object(m, "IS_MAC", is_mac), \
                        mock.patch.object(m, "IS_WIN", False):
                    self.assertEqual(m.find_ksp_installs(), [expected])

    def test_deploy_copies_sounds_dll_and_never_touches_plugindata(self):
        pd = self.ksp / "GameData" / m.MOD_FOLDER / "PluginData"
        pd.mkdir(parents=True)
        (pd / "calibration.cfg").write_text("keep me")
        manifest = m.deploy(self.ksp, self.dll, [])
        gd = self.ksp / "GameData" / m.MOD_FOLDER
        self.assertTrue((gd / "Plugins" / m.DLL_NAME).read_bytes() == b"MZ-fake-dll")
        self.assertTrue((gd / "Sounds" / "v1.wav").exists())
        self.assertEqual((pd / "calibration.cfg").read_text(), "keep me")
        self.assertIn("GameData/%s/Plugins/%s" % (m.MOD_FOLDER, m.DLL_NAME), manifest)
        self.assertFalse(any("PluginData" in x for x in manifest))

    def test_redeploy_removes_stale_files(self):
        manifest = m.deploy(self.ksp, self.dll, [])
        stale = self.ksp / "GameData" / m.MOD_FOLDER / "Sounds" / "old.wav"
        stale.write_bytes(b"x")
        manifest.append("GameData/%s/Sounds/old.wav" % m.MOD_FOLDER)
        m.deploy(self.ksp, self.dll, manifest)
        self.assertFalse(stale.exists())

    def test_uninstall_keeps_settings_unless_purged(self):
        state = {"ksp": str(self.ksp), "manifest": []}
        state["manifest"] = m.deploy(self.ksp, self.dll, [])
        pd = self.ksp / "GameData" / m.MOD_FOLDER / "PluginData"
        (pd / "settings.cfg").write_text("mine")
        m.save_state(state)

        args = m.build_parser().parse_args(["uninstall", "--yes"])
        self.assertEqual(m.cmd_uninstall(args), 0)
        mod = self.ksp / "GameData" / m.MOD_FOLDER
        self.assertFalse((mod / "Plugins" / m.DLL_NAME).exists())
        self.assertFalse((mod / "Sounds").exists())
        self.assertEqual((pd / "settings.cfg").read_text(), "mine")

        m.deploy(self.ksp, self.dll, [])
        args = m.build_parser().parse_args(["uninstall", "--yes", "--purge"])
        m.cmd_uninstall(args)
        self.assertFalse(mod.exists())

    def test_install_with_skip_build_records_state(self):
        if os.name == "nt":
            self.skipTest("launcher install edits the real user PATH on Windows")
        os.environ["KSPEED_BIN"] = str(self.tmp / "bin")
        args = m.build_parser().parse_args(
            ["install", "--yes", "--skip-build", "--ksp", str(self.ksp), "--repo", "me/kspeed"])
        self.assertEqual(m.cmd_install(args), 0)
        st = m.load_state()
        self.assertEqual(st["ksp"], str(self.ksp))
        self.assertEqual(st["repo"], "me/kspeed")
        self.assertTrue(st["manifest"])
        self.assertTrue((self.tmp / "bin" / m.CMD_NAME).exists())

    def test_placeholder_repo_is_detected(self):
        self.assertEqual(m.remote_sha(m.PLACEHOLDER_REPO, "main"), "")

    def test_steam_vdf_library_parsing(self):
        steam = self.tmp / "Steam"
        (steam / "steamapps").mkdir(parents=True)
        lib = self.tmp / "SteamLib"
        lib.mkdir()
        (steam / "steamapps" / "libraryfolders.vdf").write_text('"libraryfolders" { "1" { "path"  "%s" } }' % str(lib).replace("\\", "\\\\"))
        orig = Path.home
        try:
            if sys.platform == "darwin":
                (self.tmp / "Library" / "Application Support").mkdir(parents=True)
                os.replace(str(steam), str(self.tmp / "Library" / "Application Support" / "Steam"))
            elif os.name != "nt":
                (self.tmp / ".steam").mkdir()
                os.replace(str(steam), str(self.tmp / ".steam" / "steam"))
            else:
                self.skipTest("Windows locations come from the registry / Program Files")
            Path.home = classmethod(lambda cls: self.tmp)
            self.assertIn(lib, m.steam_roots())
        finally:
            Path.home = orig


if __name__ == "__main__":
    unittest.main()
