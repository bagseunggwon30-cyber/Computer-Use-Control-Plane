using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows.Forms;
internal static class Program {
 private static int inputEvents,invokeEvents,valueEvents;
 private static string evidence;
 private static void Save(string name,object value) { string path=Path.Combine(evidence,name);string tmp=path+".tmp";File.WriteAllText(tmp,new JavaScriptSerializer().Serialize(value),new UTF8Encoding(false));if(File.Exists(path))File.Delete(path);File.Move(tmp,path); }
 private static void Observe(Control control) {
  control.MouseDown+=(s,e)=>inputEvents++;control.KeyDown+=(s,e)=>inputEvents++;control.KeyPress+=(s,e)=>inputEvents++;
  if(control is ButtonBase)control.Click+=(s,e)=>invokeEvents++;
  if(control is TextBox)control.TextChanged+=(s,e)=>valueEvents++;
  foreach(Control child in control.Controls)Observe(child);
 }
 private static object Rect(Control control){var r=control.RectangleToScreen(control.ClientRectangle);return new {x=r.X,y=r.Y,width=r.Width,height=r.Height,center_x=r.X+r.Width/2,center_y=r.Y+r.Height/2};}
 [STAThread] private static int Main(string[] args) {
  if(args.Length!=2)return 2;evidence=Path.GetFullPath(args[0]);Directory.CreateDirectory(evidence);
  try {
   Application.EnableVisualStyles();Application.SetCompatibleTextRenderingDefault(false);
   using(var form=new Form {Text=args[1],Name="ObservationFixture",StartPosition=FormStartPosition.Manual,Location=new Point(120,120),Size=new Size(620,430),AutoScaleMode=AutoScaleMode.None}) {
    var group=new GroupBox {Name="NestedGroup",Text="Fixture group",Location=new Point(20,20),Size=new Size(550,300)};
    var run=new Button{Name="RunButton",Text="Run 한글",Location=new Point(20,30),Size=new Size(130,40),AccessibleName="Run 한글"};
    var duplicate1=new Button{Name="DuplicateOne",Text="Duplicate",Location=new Point(180,30),Size=new Size(130,40)};
    var duplicate2=new Button{Name="DuplicateTwo",Text="Duplicate",Location=new Point(330,30),Size=new Size(130,40)};
    var disabled=new Button{Name="DisabledButton",Text="Disabled",Enabled=false,Location=new Point(20,100),Size=new Size(130,40)};
    var edit=new TextBox{Name="FixtureEdit",Text="Read only fixture",ReadOnly=true,Location=new Point(180,110),Size=new Size(270,30),AccessibleName="Fixture value"};
    var offscreen=new Button{Name="OffscreenButton",Text="Offscreen",Location=new Point(20,900),Size=new Size(130,40)};
    group.Controls.AddRange(new Control[]{run,duplicate1,duplicate2,disabled,edit,offscreen});form.Controls.Add(group);Observe(form);
    using(var timer=new Timer{Interval=100}) {
     timer.Tick+=(s,e)=>{if(File.Exists(Path.Combine(evidence,"close.request")))form.Close();};
     form.Shown+=(s,e)=> {Save("ready.json",new {schema="cucp.owned-observation-window/v1",pid=Process.GetCurrentProcess().Id,hwnd=form.Handle.ToInt64(),title=form.Text,desktop_interactive=Environment.UserInteractive,form=Rect(form),run=Rect(run),duplicate=Rect(duplicate1),disabled=Rect(disabled),offscreen=Rect(offscreen),input_events=inputEvents,invoke_events=invokeEvents,value_events=valueEvents});timer.Start();};
     Application.Run(form);
    }
   }
   Save("closed.json",new {input_events=inputEvents,invoke_events=invokeEvents,value_events=valueEvents});return 0;
  }catch(Exception error){Save("failed.json",new {error=error.ToString()});return 1;}
 }
}
