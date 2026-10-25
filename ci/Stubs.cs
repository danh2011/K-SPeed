using System;
using System.Collections.Generic;
using System.Collections;
public class KSPAddon : Attribute { public enum Startup { Flight } public KSPAddon(Startup s, bool once) {} }
public static class KSPUtil { public static string ApplicationRootPath = "/"; }
public class ConfigNode {
  public ConfigNode() {} public ConfigNode(string n) {}
  public static ConfigNode Load(string p) { return null; }
  public string GetValue(string k) { return null; }
  public ConfigNode GetNode(string k) { return null; }
  public ConfigNode[] GetNodes(string k) { return null; }
  public void AddValue(string k, string v) {}
  public ConfigNode AddNode(string k) { return null; }
  public ConfigNode AddNode(ConfigNode n) { return n; }
  public bool Save(string p, string h) { return true; }
}
public class EventVoid { public void Add(Action a) {} public void Remove(Action a) {} }
public static class GameEvents { public static EventVoid onHideUI, onShowUI; }
public class KeyBinding { public bool GetKey() { return false; } }
public static class GameSettings { public static KeyBinding MODIFIER_KEY; }
public static class HighLogic { public static bool LoadedSceneIsFlight; }
public static class GameDatabase_ { }
public class GameDatabase { public static GameDatabase Instance; public UnityEngine.AudioClip GetAudioClip(string u) { return null; } }
public enum VesselType { Plane, Ship }
public class CelestialBody { public double Radius, gravParameter; public string bodyName; public bool atmosphere; }
public class FlightCtrlState { public float mainThrottle; }
public class PartModule { public Part part; }
public class PartModuleList : IEnumerable<PartModule> { public IEnumerator<PartModule> GetEnumerator() { yield break; } IEnumerator IEnumerable.GetEnumerator() { yield break; } }
public class Part { public PartModuleList Modules; public UnityEngine.Transform transform; }
public class ModuleEngines : PartModule { public float maxThrust, thrustPercentage; public bool EngineIgnited; }
public class ModuleLiftingSurface : PartModule { public float deflectionLiftCoeff; }
public class Vessel {
  public enum Situations { PRELAUNCH, LANDED, FLYING }
  public Situations situation; public VesselType vesselType; public string vesselName;
  public double srfSpeed, dynamicPressurekPa, atmDensity, altitude, radarAltitude, latitude, longitude;
  public CelestialBody mainBody; public bool Landed;
  public UnityEngine.Vector3 up, north, east; public UnityEngine.Vector3d srf_velocity;
  public UnityEngine.Transform ReferenceTransform; public FlightCtrlState ctrlState;
  public List<Part> parts;
  public double GetTotalMass() { return 0; }
  public List<T> FindPartModulesImplementing<T>() where T : class { return null; }
}
public static class FlightGlobals { public static Vessel ActiveVessel; }
namespace UnityEngine {
  public class Object { }
  public class GameObject { public T AddComponent<T>() where T : new() { return new T(); } }
  public class Component { public GameObject gameObject; }
  public class MonoBehaviour : Component { }
  public static class Debug { public static void Log(object o) {} public static void LogWarning(object o) {} }
  public struct Vector3d { public double x, y, z; }
  public struct Vector3 { public float x, y, z; public static float Dot(Vector3 a, Vector3 b) { return 0; } public static implicit operator Vector3(Vector3d d) { return new Vector3(); } }
  public class Transform { public Vector3 forward, up; }
  public static class Time { public static float time, fixedDeltaTime, timeSinceLevelLoad; }
  public enum KeyCode { K }
  public static class Input { public static bool GetKeyDown(KeyCode k) { return false; } }
  public class AudioClip { }
  public class AudioSource : Component { public float spatialBlend; public bool playOnAwake; public void PlayOneShot(AudioClip c, float v) {} }
  public struct Rect { public Rect(float a, float b, float c, float d) {} }
  public struct Color { public static Color red, yellow, white, green; public static Color Lerp(Color a, Color b, float t) { return a; } }
  public static class Mathf { public static float Sin(float f) { return 0; } }
  public static class Screen { public static int width; }
  public enum FontStyle { Bold }
  public enum TextAnchor { MiddleCenter }
  public class GUIStyleState { public Color textColor; }
  public class GUIStyle { public GUIStyle() {} public GUIStyle(GUIStyle s) {} public int fontSize; public FontStyle fontStyle; public TextAnchor alignment; public bool wordWrap; public GUIStyleState normal = new GUIStyleState(); }
  public class GUISkin { public GUIStyle label; }
  public delegate void WindowFunction(int id);
  public static class GUI { public static GUISkin skin; public static void Label(Rect r, string t, GUIStyle s) {} public static void DragWindow() {} }
  public static class GUILayout {
    public static Rect Window(int id, Rect r, GUI_WF f, string t) { return r; }
    public static void BeginVertical() {} public static void EndVertical() {} public static void BeginHorizontal() {} public static void EndHorizontal() {}
    public static void Label(string t, GUIStyle s) {} public static void Space(float f) {}
    public static string TextField(string s, int n) { return s; } public static bool Button(string s) { return false; } public static bool Toggle(bool b, string s) { return b; }
  }
  public delegate void GUI_WF(int id);
}
