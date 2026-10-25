using System;
using System.Collections.Generic;
using UnityEngine;

namespace kspeed
{
    /// <summary>
    /// A runway is a straight line between two threshold points given as latitude/longitude.
    /// Positions are projected to a local flat plane (metres) around point A, which is accurate
    /// to well under a metre over a few kilometres.
    /// </summary>
    public class Runway
    {
        const double D2R = Math.PI / 180.0;

        public string Name = "Runway";
        public string Body = "Kerbin";
        public double LatA, LonA, LatB, LonB;

        // Derived (call Recompute with the body radius before using)
        public double Length;
        public double DirX; // unit vector A->B, east component
        public double DirY; // unit vector A->B, north component
        double radius = 600000.0;
        double cosLatA = 1.0;

        public void Recompute(double bodyRadius)
        {
            radius = bodyRadius;
            cosLatA = Math.Cos(LatA * D2R);
            double x, y;
            ToXY(LatB, LonB, out x, out y);
            Length = Math.Sqrt(x * x + y * y);
            if (Length < 1e-6) { DirX = 1; DirY = 0; Length = 1; return; }
            DirX = x / Length;
            DirY = y / Length;
        }

        void ToXY(double lat, double lon, out double x, out double y)
        {
            x = (lon - LonA) * D2R * radius * cosLatA; // east
            y = (lat - LatA) * D2R * radius;           // north
        }

        /// <summary>along = metres from A towards B; cross = metres off the centreline.</summary>
        public void Locate(double lat, double lon, out double along, out double cross)
        {
            double x, y;
            ToXY(lat, lon, out x, out y);
            along = x * DirX + y * DirY;
            cross = x * DirY - y * DirX;
        }

        public ConfigNode ToNode()
        {
            var n = new ConfigNode("RUNWAY");
            n.AddValue("name", Name);
            n.AddValue("body", Body);
            n.AddValue("latA", Cfg.S(LatA));
            n.AddValue("lonA", Cfg.S(LonA));
            n.AddValue("latB", Cfg.S(LatB));
            n.AddValue("lonB", Cfg.S(LonB));
            return n;
        }

        public static Runway FromNode(ConfigNode n)
        {
            string name = n.GetValue("name");
            if (string.IsNullOrEmpty(name)) return null;
            return new Runway
            {
                Name = name,
                Body = n.GetValue("body") ?? "Kerbin",
                LatA = Cfg.D(n, "latA", 0), LonA = Cfg.D(n, "lonA", 0),
                LatB = Cfg.D(n, "latB", 0), LonB = Cfg.D(n, "lonB", 0)
            };
        }
    }

    public class RunwayDatabase
    {
        public const string KscName = "KSC Runway";
        public const double KscLength = 2526.0; // m, per the KSP wiki (runway 09/27)

        public readonly List<Runway> All = new List<Runway>();
        static string FilePath { get { return PluginPaths.Data + "runways.cfg"; } }

        public static RunwayDatabase Load()
        {
            var db = new RunwayDatabase();
            try
            {
                if (System.IO.File.Exists(FilePath))
                {
                    ConfigNode root = ConfigNode.Load(FilePath);
                    if (root != null)
                    {
                        foreach (ConfigNode n in root.GetNodes("RUNWAY"))
                        {
                            Runway r = Runway.FromNode(n);
                            if (r != null) db.All.Add(r);
                        }
                    }
                }
            }
            catch (Exception e)
            {
                Debug.LogWarning("[kspeed] Could not read runways: " + e.Message);
            }

            if (db.All.Count == 0)
            {
                db.SeedDefaults();
                db.Save();
            }
            return db;
        }

        /// <summary>
        /// Rough KSC seed: centre taken from the KSP wiki (about 0°02'26"S, 74°41'28"W), running due
        /// east-west for 2526 m. This is only a starting guess; the mod replaces it with an exact value the
        /// first time you launch a plane from the SPH (see KSpeedAddon.TryAutoDefineKsc).
        /// </summary>
        void SeedDefaults()
        {
            const double bodyR = 600000.0;
            double lat = -(2.0 + 26.0 / 60.0) / 60.0;      // -0.04056
            double lonC = -(74.0 + 41.0 / 60.0 + 28.0 / 3600.0); // -74.6911
            double halfDeg = (KscLength / 2.0) / (bodyR * Math.PI / 180.0 * Math.Cos(lat * Math.PI / 180.0));
            All.Add(new Runway
            {
                Name = KscName, Body = "Kerbin",
                LatA = lat, LonA = lonC - halfDeg,
                LatB = lat, LonB = lonC + halfDeg
            });
        }

        public void Upsert(Runway r)
        {
            for (int i = 0; i < All.Count; i++)
            {
                if (All[i].Name == r.Name) { All[i] = r; return; }
            }
            All.Add(r);
        }

        public void Save()
        {
            try
            {
                System.IO.Directory.CreateDirectory(PluginPaths.Data);
                var root = new ConfigNode();
                foreach (Runway r in All) root.AddNode(r.ToNode());
                root.Save(FilePath, "Known runways. Add your own in-game with the Mark buttons.");
            }
            catch (Exception e)
            {
                Debug.LogWarning("[kspeed] Could not save runways: " + e.Message);
            }
        }
    }
}
