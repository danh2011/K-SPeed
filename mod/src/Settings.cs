using System;
using System.Collections.Generic;
using System.Globalization;
using UnityEngine;

namespace kspeed
{
    public static class PluginPaths
    {
        public static string Root { get { return KSPUtil.ApplicationRootPath + "GameData/kspeed/"; } }
        public static string Data { get { return Root + "PluginData/"; } }
        public const string SoundUrl = "kspeed/Sounds/";
    }

    /// <summary>Culture-safe ConfigNode helpers (a German/UK locale must not break "4.0").</summary>
    public static class Cfg
    {
        public static double D(ConfigNode n, string key, double def)
        {
            string s = n.GetValue(key);
            double v;
            if (s != null && double.TryParse(s, NumberStyles.Float, CultureInfo.InvariantCulture, out v)) return v;
            return def;
        }

        public static bool B(ConfigNode n, string key, bool def)
        {
            string s = n.GetValue(key);
            bool v;
            if (s != null && bool.TryParse(s, out v)) return v;
            return def;
        }

        public static string S(double v) { return v.ToString("R", CultureInfo.InvariantCulture); }
    }

    public class Settings
    {
        // --- Ground handling ---
        public double BrakeDecel = 4.0;         // m/s^2 you can rely on when braking hard
        public double ReactionTime = 1.0;       // s between "abort" decision and full braking
        public double RotationTime = 3.0;       // s spent rotating/accelerating between VR and liftoff
        public double RunwayMargin = 0.05;      // fraction of runway kept as safety buffer
        public double ThrustEfficiency = 0.85;  // fudge on static thrust estimate
        public double RollingResistance = 0.03; // fraction of g

        // --- Speed model ---
        public double MaxCL = 1.0;              // assumed CL for the stall-speed estimate
        public double VrFactor = 1.10;          // VR  = VrFactor * Vs
        public double LiftoffFactor = 1.15;     // nominal liftoff speed = LiftoffFactor * Vs (used for calibration)
        public double V2Factor = 1.25;          // V2  = V2Factor * Vs

        // --- UI / audio ---
        public bool Voice = true;
        public double Volume = 0.8;
        public KeyCode ToggleKey = KeyCode.K;   // pressed together with the KSP modifier key (Alt)

        static string FilePath { get { return PluginPaths.Data + "settings.cfg"; } }

        public static Settings Load()
        {
            var s = new Settings();
            try
            {
                if (System.IO.File.Exists(FilePath))
                {
                    ConfigNode root = ConfigNode.Load(FilePath);
                    ConfigNode n = root != null ? root.GetNode("SETTINGS") : null;
                    if (n != null)
                    {
                        s.BrakeDecel = Cfg.D(n, "brakeDecel", s.BrakeDecel);
                        s.ReactionTime = Cfg.D(n, "reactionTime", s.ReactionTime);
                        s.RotationTime = Cfg.D(n, "rotationTime", s.RotationTime);
                        s.RunwayMargin = Cfg.D(n, "runwayMargin", s.RunwayMargin);
                        s.ThrustEfficiency = Cfg.D(n, "thrustEfficiency", s.ThrustEfficiency);
                        s.RollingResistance = Cfg.D(n, "rollingResistance", s.RollingResistance);
                        s.MaxCL = Cfg.D(n, "maxCL", s.MaxCL);
                        s.VrFactor = Cfg.D(n, "vrFactor", s.VrFactor);
                        s.LiftoffFactor = Cfg.D(n, "liftoffFactor", s.LiftoffFactor);
                        s.V2Factor = Cfg.D(n, "v2Factor", s.V2Factor);
                        s.Voice = Cfg.B(n, "voice", s.Voice);
                        s.Volume = Cfg.D(n, "volume", s.Volume);
                        string key = n.GetValue("toggleKey");
                        if (!string.IsNullOrEmpty(key))
                        {
                            try { s.ToggleKey = (KeyCode)Enum.Parse(typeof(KeyCode), key, true); }
                            catch (Exception) { /* keep default */ }
                        }
                        return s;
                    }
                }
                s.Save(); // first run: write defaults so the user can edit them
            }
            catch (Exception e)
            {
                Debug.LogWarning("[kspeed] Could not read settings: " + e.Message);
            }
            return s;
        }

        public void Save()
        {
            try
            {
                System.IO.Directory.CreateDirectory(PluginPaths.Data);
                var root = new ConfigNode();
                ConfigNode n = root.AddNode("SETTINGS");
                n.AddValue("brakeDecel", Cfg.S(BrakeDecel));
                n.AddValue("reactionTime", Cfg.S(ReactionTime));
                n.AddValue("rotationTime", Cfg.S(RotationTime));
                n.AddValue("runwayMargin", Cfg.S(RunwayMargin));
                n.AddValue("thrustEfficiency", Cfg.S(ThrustEfficiency));
                n.AddValue("rollingResistance", Cfg.S(RollingResistance));
                n.AddValue("maxCL", Cfg.S(MaxCL));
                n.AddValue("vrFactor", Cfg.S(VrFactor));
                n.AddValue("liftoffFactor", Cfg.S(LiftoffFactor));
                n.AddValue("v2Factor", Cfg.S(V2Factor));
                n.AddValue("voice", Voice.ToString());
                n.AddValue("volume", Cfg.S(Volume));
                n.AddValue("toggleKey", ToggleKey.ToString());
                root.Save(FilePath, "K-SPeed settings");
            }
            catch (Exception e)
            {
                Debug.LogWarning("[kspeed] Could not save settings: " + e.Message);
            }
        }
    }

    /// <summary>
    /// Per-craft speed scale learned from real liftoffs. k multiplies the physics-estimated stall speed.
    /// </summary>
    public class Calibration
    {
        public class Entry { public double K = 1.0; public int Samples = 0; }

        readonly Dictionary<string, Entry> map = new Dictionary<string, Entry>();
        static string FilePath { get { return PluginPaths.Data + "calibration.cfg"; } }

        public static Calibration Load()
        {
            var c = new Calibration();
            try
            {
                if (System.IO.File.Exists(FilePath))
                {
                    ConfigNode root = ConfigNode.Load(FilePath);
                    if (root != null)
                    {
                        foreach (ConfigNode n in root.GetNodes("CRAFT"))
                        {
                            string name = n.GetValue("name");
                            if (string.IsNullOrEmpty(name)) continue;
                            c.map[name] = new Entry { K = Cfg.D(n, "k", 1.0), Samples = (int)Cfg.D(n, "samples", 1) };
                        }
                    }
                }
            }
            catch (Exception e)
            {
                Debug.LogWarning("[kspeed] Could not read calibration: " + e.Message);
            }
            return c;
        }

        void Save()
        {
            try
            {
                System.IO.Directory.CreateDirectory(PluginPaths.Data);
                var root = new ConfigNode();
                foreach (KeyValuePair<string, Entry> kv in map)
                {
                    ConfigNode n = root.AddNode("CRAFT");
                    n.AddValue("name", kv.Key);
                    n.AddValue("k", Cfg.S(kv.Value.K));
                    n.AddValue("samples", kv.Value.Samples.ToString(CultureInfo.InvariantCulture));
                }
                root.Save(FilePath, "Per-craft takeoff calibration");
            }
            catch (Exception e)
            {
                Debug.LogWarning("[kspeed] Could not save calibration: " + e.Message);
            }
        }

        public bool TryGet(string craft, out double k, out int samples)
        {
            Entry e;
            if (craft != null && map.TryGetValue(craft, out e)) { k = e.K; samples = e.Samples; return true; }
            k = 1.0; samples = 0; return false;
        }

        public void AddSample(string craft, double observedK)
        {
            if (string.IsNullOrEmpty(craft)) return;
            observedK = Math.Max(0.5, Math.Min(2.0, observedK));
            Entry e;
            if (map.TryGetValue(craft, out e)) { e.K = 0.5 * e.K + 0.5 * observedK; e.Samples++; }
            else map[craft] = new Entry { K = observedK, Samples = 1 };
            Save();
        }

        public void Reset(string craft)
        {
            if (craft != null && map.Remove(craft)) Save();
        }
    }
}
