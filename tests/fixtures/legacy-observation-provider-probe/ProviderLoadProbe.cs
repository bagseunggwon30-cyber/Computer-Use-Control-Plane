// Diagnostic only. No reference to UIA or candidate runtime: loading this assembly
// cannot select UIA types, register providers, initialize proxies, or send input.
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Runtime.ExceptionServices;
namespace PcuCp.ObservationProviderProbe {
 public sealed class CallFrameRecord { public string Method, DeclaringType, ReflectedType, Assembly; }
 public sealed class UiaExceptionRecord { public string Type, Message, Stack; public CallFrameRecord[] CallFrames; }
 public static class ProviderLoadProbe {
  private static readonly object gate=new object();
  private static readonly List<UiaExceptionRecord> errors=new List<UiaExceptionRecord>();
  [ThreadStatic] private static bool recording;
  private static bool started;
  public static int Dropped {get;private set;}
  public static void Start(){lock(gate){if(started)return;started=true;AppDomain.CurrentDomain.FirstChanceException+=Capture;}}
  public static UiaExceptionRecord[] Snapshot(){lock(gate)return errors.ToArray();}
  private static void Capture(object sender,FirstChanceExceptionEventArgs args){
   if(recording)return;
   recording=true;
   try{
    string stack=args.Exception.StackTrace ?? "";
    if(stack.IndexOf("System.Windows.Automation",StringComparison.Ordinal)<0 && stack.IndexOf("MS.Internal.Automation",StringComparison.Ordinal)<0 && stack.IndexOf("UIAutomation",StringComparison.Ordinal)<0)return;
    CallFrameRecord[] frames=null;
    if(args.Exception is NullReferenceException && stack.IndexOf("LoadDefaultProxies",StringComparison.Ordinal)>=0){
     var rows=new List<CallFrameRecord>();
     foreach(var frame in new StackTrace().GetFrames()){
      var method=frame.GetMethod();if(method==null)continue;
      rows.Add(new CallFrameRecord{Method=method.Name,DeclaringType=method.DeclaringType==null?null:method.DeclaringType.FullName,ReflectedType=method.ReflectedType==null?null:method.ReflectedType.FullName,Assembly=method.ReflectedType==null?null:method.ReflectedType.Assembly.FullName});
     }
     frames=rows.ToArray();
    }
    lock(gate){if(errors.Count>=256){Dropped++;return;}errors.Add(new UiaExceptionRecord{Type=args.Exception.GetType().FullName,Message=args.Exception.Message,Stack=stack,CallFrames=frames});}
   }catch{}finally{recording=false;}
  }
 }
}
