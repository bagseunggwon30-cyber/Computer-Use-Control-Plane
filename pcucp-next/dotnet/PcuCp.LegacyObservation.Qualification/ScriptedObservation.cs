// Test-only closed inert acquisition seam; this assembly is not packaged for runtime use.
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows;
using PcuCp.LegacyObservation;
namespace PcuCp.LegacyObservation.Qualification {
 public sealed class Scenario {
  public string Name { get; set; }
  public string Operation { get; set; }
  public Dictionary<string,object> Options { get; set; }
  public bool Win32Available { get; set; } = true;
  public bool UiaAvailable { get; set; } = true;
  public long Window { get; set; } = 101;
  public long Root { get; set; } = 100;
  public string Title { get; set; } = "Fixture 한글";
  public string ClassName { get; set; } = "FixtureClass";
  public uint Pid { get; set; } = 42;
  public string ProcessName { get; set; } = "fixture";
  public bool ProcessThrows { get; set; }
  public int[] VirtualBounds { get; set; } = new [] { -200, -200, 1000, 1000 };
  public Dictionary<string,long> PointWindows { get; set; } = new Dictionary<string,long>();
  public Dictionary<string,string> PointElements { get; set; } = new Dictionary<string,string>();
  public List<WindowSpec> Windows { get; set; } = new List<WindowSpec>();
  public string RootElement { get; set; } = "root";
  public string PointElement { get; set; } = "a";
  public List<ElementSpec> Elements { get; set; } = new List<ElementSpec>();
  public List<string> Descendants { get; set; } = new List<string>();
  public string[] Faults { get; set; } = new string[0];
 }
 public sealed class WindowSpec { public long Hwnd {get;set;} public string Title {get;set;} public bool Foreground {get;set;} }
 public sealed class ElementSpec {
  public string Id {get;set;} public string Parent {get;set;}
  public double[] Rect {get;set;} = new double[]{0,0,40,20}; public bool Empty {get;set;}
  public string Name {get;set;} = "Run"; public string AutomationId {get;set;} = "run";
  public string HelpText {get;set;} = ""; public string AccessKey {get;set;} = "";
  public string ClassName {get;set;} = "Button"; public string LocalizedControlType {get;set;} = "button";
  public bool IsEnabled {get;set;} = true; public bool IsOffscreen {get;set;}
  public string[] Patterns {get;set;} = new string[]{"Invoke"}; public bool ValueReadOnly {get;set;}
  public double[] Clickable {get;set;} public string[] Faults {get;set;} = new string[0];
 }
 public static class FixtureState {
  public static Scenario Scenario;
  public static readonly List<string> Trace = new List<string>();
  public static readonly Dictionary<string,FixtureElement> Elements = new Dictionary<string,FixtureElement>();
  public static int Mutations;
  public static void Reset(string json) { Scenario = new JavaScriptSerializer().Deserialize<Scenario>(json); Trace.Clear(); Elements.Clear(); Mutations=0; foreach(var spec in Scenario.Elements) Elements.Add(spec.Id,new FixtureElement(spec)); }
  public static void Record(string text) { Trace.Add(text); if (Scenario.Faults.Contains(text)) throw new InvalidOperationException("fixture:"+text); }
  public static FixtureElement Element(string id) { return id != null && Elements.ContainsKey(id) ? Elements[id] : null; }
  public static string Number(double n) { return n.ToString("R",CultureInfo.InvariantCulture); }
  public static bool EnsureWin32() { Record("ensure-win32"); return Scenario.Win32Available; }
  public static bool EnsureUia() { Record("ensure-uia"); return Scenario.UiaAvailable; }
  public static string ProcessName(uint id) { Record("process-name:"+id); if(Scenario.ProcessThrows) throw new InvalidOperationException("fixture:process"); return Scenario.ProcessName; }
 }
 public sealed class FixtureCurrent {
  public readonly ElementSpec Spec;
  public FixtureCurrent(ElementSpec spec) { Spec=spec; }
  private void Read(string name) { FixtureState.Record("property:"+Spec.Id+":"+name); if(Spec.Faults.Contains(name)) throw new InvalidOperationException("fixture:"+name); }
  public Rect BoundingRectangle { get { Read("Bounds"); return Spec.Empty ? Rect.Empty : new Rect(Spec.Rect[0],Spec.Rect[1],Spec.Rect[2],Spec.Rect[3]); } }
  public string Name {get{Read("Name");return Spec.Name;}}
  public string AutomationId {get{Read("AutomationId");return Spec.AutomationId;}}
  public string HelpText {get{Read("HelpText");return Spec.HelpText;}}
  public string AccessKey {get{Read("AccessKey");return Spec.AccessKey;}}
  public string ClassName {get{Read("ClassName");return Spec.ClassName;}}
  public string LocalizedControlType {get{Read("LocalizedControlType");return Spec.LocalizedControlType;}}
  public bool IsEnabled {get{Read("IsEnabled");return Spec.IsEnabled;}}
  public bool IsOffscreen {get{Read("IsOffscreen");return Spec.IsOffscreen;}}
 }
 public sealed class FixtureElement {
  public readonly ElementSpec Spec; public readonly FixtureCurrent IdentityCurrent;
  public FixtureElement(ElementSpec spec) {Spec=spec;IdentityCurrent=new FixtureCurrent(spec);}
  public FixtureCurrent Current {get{FixtureState.Record("current:"+Spec.Id);if(Spec.Faults.Contains("Current"))throw new InvalidOperationException("fixture:Current");return IdentityCurrent;}}
  public object GetCurrentPattern(object pattern) {string name=(string)pattern;FixtureState.Record("pattern:"+Spec.Id+":"+name);if(Spec.Faults.Contains("Pattern:"+name))throw new InvalidOperationException("fixture:Pattern:"+name);return Spec.Patterns.Contains(name) ? (object)new FixtureValuePattern(this) : null;}
  public bool TryGetClickablePoint(out Point point) {FixtureState.Record("clickable:"+Spec.Id);if(Spec.Faults.Contains("Clickable"))throw new InvalidOperationException("fixture:Clickable");point=Spec.Clickable==null?new Point():new Point(Spec.Clickable[0],Spec.Clickable[1]);return Spec.Clickable!=null;}
  public List<FixtureElement> FindAll(object scope, object condition) {FixtureState.Record("descendants:"+Spec.Id+":"+scope);return FixtureState.Scenario.Descendants.Select(FixtureState.Element).ToList();}
  public static FixtureElement FromPoint(Point point) {string key=FixtureState.Number(point.X)+","+FixtureState.Number(point.Y);FixtureState.Record("from-point:"+key);return FixtureState.Element(FixtureState.Scenario.PointElements.ContainsKey(key)?FixtureState.Scenario.PointElements[key]:FixtureState.Scenario.PointElement);}
  public static FixtureElement FromHandle(IntPtr hwnd) {FixtureState.Record("from-handle:"+hwnd.ToInt64());return FixtureState.Element(FixtureState.Scenario.RootElement);}
 }
 public sealed class FixtureValuePattern {
  private readonly FixtureElement element;
  public FixtureValuePattern(FixtureElement element) {this.element=element;}
  public FixtureValuePattern Current {get {FixtureState.Record("value-current:"+element.Spec.Id);if(element.Spec.Faults.Contains("ValueCurrent"))throw new InvalidOperationException("fixture:ValueCurrent");return this;}}
  public bool IsReadOnly {get{FixtureState.Record("value-readonly:"+element.Spec.Id);if(element.Spec.Faults.Contains("ValueReadOnly"))throw new InvalidOperationException("fixture:ValueReadOnly");return element.Spec.ValueReadOnly;}}
  // Deliberate tripwire: never calls UIA or operating-system input.
  public void Invoke() {FixtureState.Mutations++;FixtureState.Record("mutation-attempt:Invoke");throw new InvalidOperationException("mutation tripwire: Invoke");}
  public void Toggle() {FixtureState.Mutations++;FixtureState.Record("mutation-attempt:Toggle");throw new InvalidOperationException("mutation tripwire: Toggle");}
  public void Select() {FixtureState.Mutations++;FixtureState.Record("mutation-attempt:Select");throw new InvalidOperationException("mutation tripwire: Select");}
 }
 public static class FixtureInvoke {public static object Pattern {get{return "Invoke";}}}
 public static class FixtureToggle {public static object Pattern {get{return "Toggle";}}}
 public static class FixtureSelectionItem {public static object Pattern {get{return "SelectionItem";}}}
 public static class FixtureValue {public static object Pattern {get{return "Value";}}}
 public sealed class FixtureWalker {
  public static FixtureWalker ControlViewWalker {get{FixtureState.Record("walker");return new FixtureWalker();}}
  public FixtureElement GetParent(FixtureElement element) {FixtureState.Record("parent:"+element.Spec.Id);if(element.Spec.Faults.Contains("Parent"))throw new InvalidOperationException("fixture:Parent");return FixtureState.Element(element.Spec.Parent);}
 }
 public static class FixtureNative {
  public struct POINT {public int X,Y;}
  public const uint GA_ROOT=2;public const int SM_XVIRTUALSCREEN=76,SM_YVIRTUALSCREEN=77,SM_CXVIRTUALSCREEN=78,SM_CYVIRTUALSCREEN=79;
  public static int PostClickX,PostClickY;
  public static IntPtr WindowFromPoint(POINT pt) {string key=pt.X+","+pt.Y;FixtureState.Record("window-point:"+key);return new IntPtr(FixtureState.Scenario.PointWindows.ContainsKey(key)?FixtureState.Scenario.PointWindows[key]:FixtureState.Scenario.Window);}
  public static IntPtr GetAncestor(IntPtr hwnd,uint flags) {FixtureState.Record("ancestor:"+hwnd.ToInt64()+":"+flags);return new IntPtr(hwnd.ToInt64()==999?999:FixtureState.Scenario.Root);}
  public static int GetWindowText(IntPtr hwnd,StringBuilder text,int capacity) {FixtureState.Record("window-text:"+hwnd.ToInt64()+":"+capacity);string title=FixtureState.Scenario.Title ?? "";text.Append(title.Substring(0,Math.Min(title.Length,capacity-1)));return text.Length;}
  public static int GetClassName(IntPtr hwnd,StringBuilder text,int capacity) {FixtureState.Record("window-class:"+hwnd.ToInt64()+":"+capacity);string title=FixtureState.Scenario.ClassName ?? "";text.Append(title.Substring(0,Math.Min(title.Length,capacity-1)));return text.Length;}
  public static uint GetWindowThreadProcessId(IntPtr hwnd,out uint pid) {FixtureState.Record("process-id:"+hwnd.ToInt64());pid=(uint)FixtureState.Scenario.Pid;return 1;}
  public static int GetSystemMetrics(int index) {FixtureState.Record("metric:"+index);return FixtureState.Scenario.VirtualBounds[index-76];}
  public static List<ObservationWindow> EnumerateTopLevel() {FixtureState.Record("windows");return FixtureState.Scenario.Windows.Select(w=>new ObservationWindow{Hwnd=w.Hwnd,Title=w.Title,Foreground=w.Foreground}).ToList();}
  public static void SendMouseClick(int x,int y,string button,bool twice) {FixtureState.Record("inert-click:"+x+","+y+":"+button+":"+twice);FixtureState.Mutations++;PostClickX=x;PostClickY=y;}
 }
 public sealed class ScriptedObservationProvider : IObservationProvider {
  public bool EnsureUia(){return FixtureState.EnsureUia();}
  public long WindowFromPoint(int x,int y){return FixtureNative.WindowFromPoint(new FixtureNative.POINT{X=x,Y=y}).ToInt64();}
  public long RootAncestor(long hwnd){return FixtureNative.GetAncestor(new IntPtr(hwnd),2).ToInt64();}
  public string WindowText(long hwnd,int capacity){var b=new StringBuilder(capacity);FixtureNative.GetWindowText(new IntPtr(hwnd),b,capacity);return b.ToString();}
  public string WindowClass(long hwnd,int capacity){var b=new StringBuilder(capacity);FixtureNative.GetClassName(new IntPtr(hwnd),b,capacity);return b.ToString();}
  public uint ProcessId(long hwnd){uint id;FixtureNative.GetWindowThreadProcessId(new IntPtr(hwnd),out id);return id;}
  public string ProcessName(uint id){try {checked { int signed=(int)id; return FixtureState.ProcessName((uint)signed); }}catch(OverflowException){return "";}}
  public int SystemMetric(int index){return FixtureNative.GetSystemMetrics(index);}
  public IEnumerable<ObservationWindow> TopLevelWindows(){return FixtureNative.EnumerateTopLevel();}
  public object FromPoint(int x,int y){return FixtureElement.FromPoint(new Point(x,y));}
  public object FromHandle(long hwnd){return FixtureElement.FromHandle(new IntPtr(hwnd));}
  public IEnumerable<object> Descendants(object element){return ((FixtureElement)element).FindAll("Descendants",null).Cast<object>();}
  public object Current(object element){return ((FixtureElement)element).Current;}
  public ObservationRect Bounds(object current){var r=((FixtureCurrent)current).BoundingRectangle;return new ObservationRect{X=r.X,Y=r.Y,Width=r.Width,Height=r.Height,IsEmpty=r.IsEmpty};}
  public object Property(object current,ObservationProperty property){var c=(FixtureCurrent)current;switch(property){case ObservationProperty.Name:return c.Name;case ObservationProperty.AutomationId:return c.AutomationId;case ObservationProperty.HelpText:return c.HelpText;case ObservationProperty.AccessKey:return c.AccessKey;case ObservationProperty.ClassName:return c.ClassName;case ObservationProperty.LocalizedControlType:return c.LocalizedControlType;case ObservationProperty.IsEnabled:return c.IsEnabled;case ObservationProperty.IsOffscreen:return c.IsOffscreen;default:throw new ArgumentOutOfRangeException(nameof(property));}}
  public object Pattern(object element,ObservationPattern pattern){return ((FixtureElement)element).GetCurrentPattern(pattern.ToString());}
  public bool ValueReadOnly(object pattern){return ((FixtureValuePattern)pattern).Current.IsReadOnly;}
  public bool ClickablePoint(object element,out double x,out double y){Point p;bool result=((FixtureElement)element).TryGetClickablePoint(out p);x=p.X;y=p.Y;return result;}
  public object ControlViewWalker(){return FixtureWalker.ControlViewWalker;}
  public object Parent(object walker,object element){return ((FixtureWalker)walker).GetParent((FixtureElement)element);}
 }
}
