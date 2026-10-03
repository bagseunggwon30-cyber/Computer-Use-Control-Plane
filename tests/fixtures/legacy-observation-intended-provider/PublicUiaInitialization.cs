// Oracle-only intended startup correction. The production provider is unchanged.
// A concrete compiled caller lets .NET Framework load its normal public proxies.
// No registration, private state access, patterns, input, or provider reset.
using System;
using System.Runtime.CompilerServices;
using System.Windows.Automation;
namespace PcuCp.ObservationIntendedProvider {
 public static class PublicUiaInitialization {
  [MethodImpl(MethodImplOptions.NoInlining)]
  public static object FromOwnedHandle(long hwnd) {
   if(hwnd<=0)throw new ArgumentOutOfRangeException(nameof(hwnd));
   return AutomationElement.FromHandle(new IntPtr(hwnd));
  }
 }
}
