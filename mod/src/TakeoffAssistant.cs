using System;
using System.Collections.Generic;
using UnityEngine;

namespace SpaceplaneTakeoffAssistant
{
    enum Phase { Idle, Ready, Roll, Airborne }
    enum Advice { None, Normal, TooShort, Abort, Go, Overrun }

    [KSPAddon(KSPAddon.Startup.Flight, false)]
    public class TakeoffAssistantAddon : MonoBehaviour
    {
        const double RHO0 = 1.225;        // Kerbin sea-level density, kg/m^3 (IAS reference)
        const double MS_TO_KT = 1.943844;
        const double HALF_WIDTH = 45.0;   // m either side of the centreline that counts as "on the runway"
        const double D2R = Math.PI / 180.0;

        // ---- services ----
        Settings cfg;
        RunwayDatabase db;
        Calibration cal;
        AudioSource audioSrc;
        readonly Dictionary<string, AudioClip> clips = new Dictionary<string, AudioClip>();

        // ---- vessel state ----
        Vessel v, lastVessel;
        Phase phase = Phase.Idle;
        Runway rw;
        double along, cross, remaining;
        double gs, prevGs, accel, ias, tasFactor = 1.0;
        double mass, gLocal, thrustKN, wingCoeff;
        double aEst;
        double vsRaw, kScale = 1.0, vs;
        int calSamples;
        double vrIas, v2Ias, v1Ias, vrG;
        double dLof, dStop;
        bool v1Passed;
        Advice advice = Advice.None;
        double lastLiftoffIas;
        float nextStaticUpdate;
        bool autoKscTried;

        // ---- callout bookkeeping ----
        bool saidAlive, saidV1, saidRot, saidV2, saidShort, saidGo;
        float lastAbortSay, lastBrakeSay;
        int abortCount;

        // ---- GUI ----
        bool show = true, uiVisible = true;
        Rect win = new Rect(20, 120, 340, 10);
        GUIStyle bigStyle, smallStyle, boldStyle;
        string runwayNameInput = "My Runway";
        bool hasPendingA;
        double pendingLat, pendingLon;
        string toast = "";
        float toastUntil;

        // =====================================================================
        void Awake()
        {
            cfg = Settings.Load();
            db = RunwayDatabase.Load();
            cal = Calibration.Load();

            audioSrc = gameObject.AddComponent<AudioSource>();
            audioSrc.spatialBlend = 0f;
            audioSrc.playOnAwake = false;

            string[] names = { "eighty", "v1", "rotate", "v2", "abort", "go", "short", "brake" };
            foreach (string n in names)
            {
                AudioClip c = GameDatabase.Instance.GetAudioClip(PluginPaths.SoundUrl + n);
                if (c == null) Debug.LogWarning("[TakeoffAssistant] Missing sound: " + n);
                else clips[n] = c;
            }

            GameEvents.onHideUI.Add(OnHideUI);
            GameEvents.onShowUI.Add(OnShowUI);
            Debug.Log("[TakeoffAssistant] Loaded. Runways: " + db.All.Count + ", sounds: " + clips.Count);
        }

        void OnDestroy()
        {
            GameEvents.onHideUI.Remove(OnHideUI);
            GameEvents.onShowUI.Remove(OnShowUI);
        }

        void OnHideUI() { uiVisible = false; }
        void OnShowUI() { uiVisible = true; }

        void Update()
        {
            if (GameSettings.MODIFIER_KEY.GetKey() && Input.GetKeyDown(cfg.ToggleKey)) show = !show;
        }

        // =====================================================================
        // Physics-rate update
        // =====================================================================
        void FixedUpdate()
        {
            v = FlightGlobals.ActiveVessel;
            if (v == null || v.mainBody == null) return;

            if (v != lastVessel)
            {
                lastVessel = v;
                phase = Phase.Idle;
                ResetCallouts();
                prevGs = v.srfSpeed;
                accel = 0;
                autoKscTried = false;
            }

            UpdateKinematics();
            if (Time.time >= nextStaticUpdate) { UpdateStatics(); nextStaticUpdate = Time.time + 0.25f; }
            UpdateRunwayGeometry();
            UpdatePhase();
            Evaluate();
            Callouts();
        }

        void UpdateKinematics()
        {
            gs = v.srfSpeed;
            double dt = Math.Max(Time.fixedDeltaTime, 1e-3);
            double raw = (gs - prevGs) / dt;
            prevGs = gs;
            if (gs < 1.0) accel = 0; else accel += 0.03 * (raw - accel); // ~0.7 s smoothing at 50 Hz

            ias = Math.Sqrt(Math.Max(0.0, 2.0 * v.dynamicPressurekPa * 1000.0 / RHO0));
            double rho = v.atmDensity;
            tasFactor = rho > 0.05 ? Math.Sqrt(RHO0 / rho) : 1.0; // true airspeed = IAS * tasFactor
        }

        void UpdateStatics()
        {
            mass = v.GetTotalMass(); // tonnes
            double r = v.mainBody.Radius + v.altitude;
            gLocal = v.mainBody.gravParameter / (r * r);

            wingCoeff = ComputeWingCoeff();
            thrustKN = ComputeThrustKN();
            aEst = mass > 0.001
                ? Math.Max(0.1, thrustKN * cfg.ThrustEfficiency / mass - cfg.RollingResistance * gLocal)
                : 0.1;

            vsRaw = 0;
            if (wingCoeff > 0.01 && mass > 0.001 && v.mainBody.atmosphere)
            {
                double weightKN = mass * gLocal;
                vsRaw = Math.Sqrt(2000.0 * weightKN / (RHO0 * cfg.MaxCL * wingCoeff)); // IAS, m/s
            }

            double k;
            if (cal.TryGet(v.vesselName, out k, out calSamples)) kScale = k;
            else { kScale = 1.0; calSamples = 0; }

            vs = vsRaw * kScale;
            vrIas = cfg.VrFactor * vs;
            v2Ias = cfg.V2Factor * vs;
            vrG = vrIas * tasFactor;
        }

        /// <summary>Sum of lifting-surface area coefficients that generate lift "upwards" for the aircraft.</summary>
        double ComputeWingCoeff()
        {
            double total = 0, weighted = 0;
            foreach (Part p in v.parts)
            {
                foreach (PartModule m in p.Modules)
                {
                    ModuleLiftingSurface ls = m as ModuleLiftingSurface; // includes control surfaces
                    if (ls == null) continue;
                    double c = ls.deflectionLiftCoeff;
                    if (c <= 0) continue;
                    total += c;
                    // wings have their lift normal along part.transform.forward; tail fins are rotated 90 degrees
                    weighted += c * Math.Abs(Vector3.Dot(p.transform.forward, v.up));
                }
            }
            return weighted > 0.25 * total ? weighted : total; // fall back if orientation assumption fails
        }

        double ComputeThrustKN()
        {
            double ignited = 0, any = 0;
            List<ModuleEngines> engines = v.FindPartModulesImplementing<ModuleEngines>();
            foreach (ModuleEngines e in engines)
            {
                double t = e.maxThrust * e.thrustPercentage / 100.0;
                any += t;
                if (e.EngineIgnited) ignited += t;
            }
            return ignited > 0 ? ignited : any;
        }

        void UpdateRunwayGeometry()
        {
            rw = null; along = cross = remaining = 0;
            double bestCross = double.MaxValue;
            double radius = v.mainBody.Radius;

            if (!autoKscTried && Time.timeSinceLevelLoad > 1.5f) { autoKscTried = true; TryAutoDefineKsc(); }

            foreach (Runway r in db.All)
            {
                if (r.Body != v.mainBody.bodyName) continue;
                r.Recompute(radius);
                double a, c;
                r.Locate(v.latitude, v.longitude, out a, out c);
                if (Math.Abs(c) <= HALF_WIDTH && a >= -150.0 && a <= r.Length + 150.0 && Math.Abs(c) < bestCross)
                {
                    bestCross = Math.Abs(c);
                    rw = r; along = a; cross = c;
                }
            }
            if (rw == null) return;

            // Which way are we pointing / moving along the runway?
            Vector3 dir = gs > 3.0 ? (Vector3)v.srf_velocity : v.ReferenceTransform.up;
            double de = Vector3.Dot(dir, v.east), dn = Vector3.Dot(dir, v.north);
            bool forward = (de * rw.DirX + dn * rw.DirY) >= 0.0;
            remaining = forward ? rw.Length - along : along;
            if (remaining < 0) remaining = 0;
        }

        /// <summary>
        /// The stock KSC runway: when a plane spawns from the SPH it sits at the west end facing east.
        /// Use that position as the exact western threshold and extend 2526 m east.
        /// </summary>
        void TryAutoDefineKsc()
        {
            if (v.situation != Vessel.Situations.PRELAUNCH) return;
            if (v.vesselType != VesselType.Plane) return;
            if (v.mainBody.bodyName != "Kerbin") return;
            if (Math.Abs(v.latitude - (-0.0972)) > 0.3 || Math.Abs(v.longitude - (-74.5577)) > 0.5) return;

            double dLon = RunwayDatabase.KscLength / (v.mainBody.Radius * D2R * Math.Cos(v.latitude * D2R));
            db.Upsert(new Runway
            {
                Name = RunwayDatabase.KscName, Body = "Kerbin",
                LatA = v.latitude, LonA = v.longitude,
                LatB = v.latitude, LonB = v.longitude + dLon
            });
            db.Save();
            Debug.Log("[TakeoffAssistant] KSC runway set from SPH spawn point.");
        }

        // =====================================================================
        // State machine
        // =====================================================================
        void UpdatePhase()
        {
            bool grounded = v.Landed || v.situation == Vessel.Situations.PRELAUNCH;
            switch (phase)
            {
                case Phase.Idle:
                    if (grounded && rw != null && gs < 1.5) { phase = Phase.Ready; ResetCallouts(); }
                    break;

                case Phase.Ready:
                    if (!grounded || rw == null) phase = Phase.Idle;
                    else if (gs >= 1.5) phase = Phase.Roll;
                    break;

                case Phase.Roll:
                    if (!grounded)
                    {
                        if (v.situation == Vessel.Situations.FLYING && gs > 0.5 * vrG) { OnLiftoff(); phase = Phase.Airborne; }
                        else phase = Phase.Idle;
                    }
                    else if (gs < 0.8)
                    {
                        phase = Phase.Ready; // stopped again (rejected takeoff)
                        ResetCallouts();
                    }
                    break;

                case Phase.Airborne:
                    if (grounded || v.radarAltitude > 200.0) phase = Phase.Idle;
                    break;
            }
        }

        void OnLiftoff()
        {
            lastLiftoffIas = ias;
            if (vsRaw > 1.0 && ias > 10.0)
            {
                double observedK = ias / (cfg.LiftoffFactor * vsRaw);
                cal.AddSample(v.vesselName, observedK);
                Toast("Liftoff at " + Spd(ias) + " - calibration saved for this craft");
            }
        }

        void ResetCallouts()
        {
            saidAlive = saidV1 = saidRot = saidV2 = saidShort = saidGo = false;
            abortCount = 0; lastAbortSay = lastBrakeSay = -100f;
        }

        // =====================================================================
        // Takeoff / abort decision logic
        // =====================================================================
        void Evaluate()
        {
            advice = Advice.None;
            v1Passed = false;
            if (rw == null || vrG <= 1.0) return;
            if (phase != Phase.Ready && phase != Phase.Roll) return;

            double R = remaining * (1.0 - cfg.RunwayMargin);       // usable runway ahead
            double a = gs < 20.0 ? aEst : Math.Max(accel, 0.1);     // trust the model early, measurement later
            a = Math.Max(a, 0.1);
            double b = Math.Max(cfg.BrakeDecel, 0.5);

            double dToRot = gs < vrG ? (vrG * vrG - gs * gs) / (2.0 * a) : 0.0;
            dLof = dToRot + cfg.RotationTime * Math.Max(vrG, gs);
            dStop = gs * gs / (2.0 * b) + gs * cfg.ReactionTime;

            // V1: the speed at which (distance still needed to reach it) + (distance to stop from it) = runway left
            double A = 1.0 / (2.0 * a) + 1.0 / (2.0 * b);
            double C = R + gs * gs / (2.0 * a);
            double t = cfg.ReactionTime;
            double v1G = (-t + Math.Sqrt(t * t + 4.0 * A * C)) / (2.0 * A);
            v1Passed = v1G <= gs + 0.01;
            v1Ias = Math.Min(v1G, vrG) / tasFactor;

            bool canGo = dLof <= R;
            bool canStop = dStop <= R;

            if (phase == Phase.Ready)
            {
                advice = canGo ? Advice.Normal : Advice.TooShort;
                return;
            }

            if (canStop && canGo) advice = Advice.Normal;
            else if (canStop) advice = Advice.Abort;      // can still stop, can't get airborne in time
            else if (canGo) advice = Advice.Go;           // can't stop any more, but takeoff works
            else advice = Advice.Overrun;                 // neither works
        }

        // =====================================================================
        // Voice + callouts
        // =====================================================================
        void Callouts()
        {
            if (v == null) return;
            float now = Time.time;

            if (phase == Phase.Ready && advice == Advice.TooShort && !saidShort && v.ctrlState.mainThrottle > 0.3f)
            {
                saidShort = true;
                Say("short");
            }

            if (phase == Phase.Roll)
            {
                if (!saidAlive && ias >= 0.5 * vrIas && vrIas > 0) { saidAlive = true; Say("eighty"); }

                if (advice == Advice.Abort && abortCount < 4 && now - lastAbortSay > 3.5f)
                {
                    lastAbortSay = now; abortCount++; Say("abort");
                }
                else if (advice == Advice.Overrun && now - lastBrakeSay > 3.0f)
                {
                    lastBrakeSay = now; Say("brake");
                }

                bool v1AtRotate = v1Ias >= 0.98 * vrIas; // runway long enough that V1 == VR
                if (!saidV1 && (v1Passed || v1AtRotate && ias >= vrIas) && advice != Advice.Abort)
                {
                    saidV1 = true;
                    if (!v1AtRotate) Say("v1");
                }
                if (!saidGo && advice == Advice.Go && saidV1) { saidGo = true; Say("go"); }
                if (!saidRot && vrIas > 0 && ias >= vrIas && advice != Advice.Abort)
                {
                    saidRot = true; Say("rotate");
                }
            }

            if (phase == Phase.Airborne && !saidV2 && v2Ias > 0 && ias >= v2Ias)
            {
                saidV2 = true; Say("v2");
            }
        }

        void Say(string clip)
        {
            if (!cfg.Voice) return;
            AudioClip c;
            if (clips.TryGetValue(clip, out c) && c != null) audioSrc.PlayOneShot(c, (float)cfg.Volume);
        }

        // =====================================================================
        // GUI
        // =====================================================================
        static string Spd(double ms)
        {
            return (ms * MS_TO_KT).ToString("F0") + " kt / " + ms.ToString("F0") + " m/s";
        }

        void Toast(string msg) { toast = msg; toastUntil = Time.time + 6f; }

        void BuildStyles()
        {
            if (bigStyle != null) return;
            bigStyle = new GUIStyle(GUI.skin.label) { fontSize = 26, fontStyle = FontStyle.Bold, alignment = TextAnchor.MiddleCenter };
            smallStyle = new GUIStyle(GUI.skin.label) { fontSize = 12, wordWrap = true };
            boldStyle = new GUIStyle(GUI.skin.label) { fontSize = 13, fontStyle = FontStyle.Bold };
        }

        void OnGUI()
        {
            if (!uiVisible || v == null || !HighLogic.LoadedSceneIsFlight) return;
            BuildStyles();

            DrawAdviceBanner();
            if (show) win = GUILayout.Window(0x7A5B, win, DrawWindow, "Takeoff Assistant  (Alt+" + cfg.ToggleKey + ")");
        }

        void DrawAdviceBanner()
        {
            string text = null; Color col = Color.white;
            switch (advice)
            {
                case Advice.Abort:
                    text = "ABORT TAKEOFF"; col = Color.Lerp(Color.red, Color.yellow, 0.5f + 0.5f * Mathf.Sin(Time.time * 10f)); break;
                case Advice.Overrun:
                    text = gs >= vrG * 0.97 ? "ROTATE - NO RUNWAY TO STOP" : "BRAKE - OVERRUN LIKELY";
                    col = Color.Lerp(Color.red, Color.white, 0.5f + 0.5f * Mathf.Sin(Time.time * 12f)); break;
                case Advice.Go:
                    text = "GO - COMMITTED"; col = Color.green; break;
                case Advice.TooShort:
                    text = "RUNWAY TOO SHORT FOR THIS TAKEOFF"; col = Color.red; break;
            }
            if (text == null) return;
            bigStyle.normal.textColor = col;
            GUI.Label(new Rect(Screen.width / 2f - 400f, 90f, 800f, 50f), text, bigStyle);
        }

        void DrawWindow(int id)
        {
            GUILayout.BeginVertical();

            // Runway
            if (rw != null)
                GUILayout.Label(rw.Name + " - " + rw.Length.ToString("F0") + " m, " + remaining.ToString("F0") + " m ahead", boldStyle);
            else
                GUILayout.Label("No known runway here. Park on one end and use the Mark buttons below.", smallStyle);

            // Speeds
            GUILayout.Space(4);
            if (vsRaw <= 0)
            {
                GUILayout.Label(!v.mainBody.atmosphere ? "No atmosphere here." : "No lifting surfaces found.", smallStyle);
            }
            else
            {
                GUILayout.Label("V1   " + (v1Ias > 0 ? Spd(v1Ias) : "-") + (v1Passed ? "  (passed)" : "") + (v1Ias >= 0.98 * vrIas ? "  (= VR)" : ""), boldStyle);
                GUILayout.Label("VR   " + Spd(vrIas), boldStyle);
                GUILayout.Label("V2   " + Spd(v2Ias), boldStyle);
                GUILayout.Label(calSamples > 0
                    ? "Calibrated from " + calSamples + " takeoff(s) of this craft"
                    : "ESTIMATE ONLY - take off once and the speeds are learned for this craft", smallStyle);
            }

            // Live data
            GUILayout.Space(4);
            GUILayout.Label("IAS " + Spd(ias) + "   accel " + accel.ToString("F1") + " m/s2", smallStyle);
            if (phase == Phase.Ready || phase == Phase.Roll)
                GUILayout.Label("Needs ~" + dLof.ToString("F0") + " m to lift off, ~" + dStop.ToString("F0") + " m to stop from here", smallStyle);
            if (lastLiftoffIas > 0)
                GUILayout.Label("Last liftoff: " + Spd(lastLiftoffIas), smallStyle);

            // Runway marking
            GUILayout.Space(6);
            GUILayout.Label("Add a runway", boldStyle);
            runwayNameInput = GUILayout.TextField(runwayNameInput, 40);
            GUILayout.BeginHorizontal();
            if (GUILayout.Button(hasPendingA ? "A set (re-mark)" : "Mark start (A)"))
            {
                hasPendingA = true; pendingLat = v.latitude; pendingLon = v.longitude;
                Toast("Start marked. Drive to the other end and press Mark end (B).");
            }
            if (GUILayout.Button("Mark end (B)") && hasPendingA) AddRunwayFromMarks();
            GUILayout.EndHorizontal();

            // Options
            GUILayout.Space(6);
            GUILayout.BeginHorizontal();
            bool voice = GUILayout.Toggle(cfg.Voice, "Voice");
            if (voice != cfg.Voice) { cfg.Voice = voice; cfg.Save(); }
            if (GUILayout.Button("Reset calibration")) { cal.Reset(v.vesselName); Toast("Calibration cleared for " + v.vesselName); }
            GUILayout.EndHorizontal();

            if (Time.time < toastUntil) GUILayout.Label(toast, smallStyle);

            GUILayout.EndVertical();
            GUI.DragWindow();
        }

        void AddRunwayFromMarks()
        {
            double R = v.mainBody.Radius;
            double dx = (v.longitude - pendingLon) * D2R * R * Math.Cos(pendingLat * D2R);
            double dy = (v.latitude - pendingLat) * D2R * R;
            double len = Math.Sqrt(dx * dx + dy * dy);
            if (len < 200.0) { Toast("Points are only " + len.ToString("F0") + " m apart - move to the far end first."); return; }

            string name = string.IsNullOrEmpty(runwayNameInput) ? "Custom Runway" : runwayNameInput.Trim();
            db.Upsert(new Runway
            {
                Name = name, Body = v.mainBody.bodyName,
                LatA = pendingLat, LonA = pendingLon, LatB = v.latitude, LonB = v.longitude
            });
            db.Save();
            hasPendingA = false;
            Toast("Saved '" + name + "' (" + len.ToString("F0") + " m).");
        }
    }
}
