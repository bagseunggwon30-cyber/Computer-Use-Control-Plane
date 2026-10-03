using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Linq;
using System.Reflection;
using System.Runtime.CompilerServices;
using System.Text;
using System.Windows;
using System.Windows.Automation;

namespace PcuCp.LegacyObservation
{
    // Only acquisition occurs here. Pattern instances are returned for inspection,
    // never invoked, and element/current instances pass through unchanged.
    public sealed class WindowsObservationProvider : IObservationProvider
    {
        private bool uiaLoaded;

        public bool EnsureUia()
        {
            if (uiaLoaded) return true;
            try
            {
                // Avoid typeof(UIA types) here: a JIT load failure must be caught,
                // and constructing this provider must not load UIA for SkipUia.
                const string frameworkIdentity = ", Version=4.0.0.0, Culture=neutral, PublicKeyToken=31bf3856ad364e35";
                Assembly.Load("UIAutomationClient" + frameworkIdentity);
                Assembly.Load("UIAutomationTypes" + frameworkIdentity);
                Assembly.Load("WindowsBase" + frameworkIdentity);
                uiaLoaded = true;
                return true;
            }
            catch { return false; }
        }

        public long WindowFromPoint(int x, int y)
        {
            return CucpNative.WindowFromPoint(new CucpNative.POINT { X = x, Y = y }).ToInt64();
        }

        public long RootAncestor(long hwnd)
        {
            return CucpNative.GetAncestor(new IntPtr(hwnd), CucpNative.GA_ROOT).ToInt64();
        }

        public string WindowText(long hwnd, int capacity)
        {
            var text = new StringBuilder(capacity);
            CucpNative.GetWindowText(new IntPtr(hwnd), text, capacity);
            return text.ToString();
        }

        public string WindowClass(long hwnd, int capacity)
        {
            var text = new StringBuilder(capacity);
            CucpNative.GetClassName(new IntPtr(hwnd), text, capacity);
            return text.ToString();
        }

        public uint ProcessId(long hwnd)
        {
            uint processId;
            CucpNative.GetWindowThreadProcessId(new IntPtr(hwnd), out processId);
            return processId;
        }

        public string ProcessName(uint processId)
        {
            // Get-Process -ErrorAction SilentlyContinue emits no object for an
            // absent id, so that case is null; a property-read failure retains "".
            Process process;
            try { process = Process.GetProcessById(checked((int)processId)); }
            catch (ArgumentException) { return null; }
            catch { return ""; }
            try { return process.ProcessName; }
            catch { return ""; }
        }

        public int SystemMetric(int index) { return CucpNative.GetSystemMetrics(index); }

        public IEnumerable<ObservationWindow> TopLevelWindows()
        {
            // Reuse the exact legacy enumerator, including its filtering and catches.
            return CucpNative.EnumerateTopLevel().Select(window => new ObservationWindow {
                Hwnd = window.Hwnd.ToInt64(), Title = window.Title, Foreground = window.Foreground
            });
        }

        // No UIA type occurs in these method signatures or in instance fields.
        // The no-inline boundary keeps assembly binding inside actual UIA reads.
        [MethodImpl(MethodImplOptions.NoInlining)]
        public object FromPoint(int x, int y) { return AutomationElement.FromPoint(new Point(x, y)); }

        [MethodImpl(MethodImplOptions.NoInlining)]
        public object FromHandle(long hwnd) { return AutomationElement.FromHandle(new IntPtr(hwnd)); }

        [MethodImpl(MethodImplOptions.NoInlining)]
        public IEnumerable<object> Descendants(object element)
        {
            return ((AutomationElement)element).FindAll(TreeScope.Descendants, Condition.TrueCondition).Cast<object>();
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        public object Current(object element) { return ((AutomationElement)element).Current; }

        [MethodImpl(MethodImplOptions.NoInlining)]
        public ObservationRect Bounds(object current)
        {
            return RectFromNative(((AutomationElement.AutomationElementInformation)current).BoundingRectangle);
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        public static ObservationRect RectFromNative(object rect)
        {
            if (rect == null) return null;
            var native = (Rect)rect;
            return new ObservationRect { X = native.X, Y = native.Y, Width = native.Width,
                Height = native.Height, IsEmpty = native.IsEmpty };
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        public object Property(object current, ObservationProperty property)
        {
            var information = (AutomationElement.AutomationElementInformation)current;
            switch (property)
            {
                case ObservationProperty.Name: return information.Name;
                case ObservationProperty.AutomationId: return information.AutomationId;
                case ObservationProperty.HelpText: return information.HelpText;
                case ObservationProperty.AccessKey: return information.AccessKey;
                case ObservationProperty.ClassName: return information.ClassName;
                case ObservationProperty.LocalizedControlType: return information.LocalizedControlType;
                case ObservationProperty.IsEnabled: return information.IsEnabled;
                case ObservationProperty.IsOffscreen: return information.IsOffscreen;
                default: throw new ArgumentOutOfRangeException(nameof(property));
            }
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        public object Pattern(object element, ObservationPattern pattern)
        {
            AutomationPattern identifier;
            switch (pattern)
            {
                case ObservationPattern.Invoke: identifier = InvokePattern.Pattern; break;
                case ObservationPattern.Toggle: identifier = TogglePattern.Pattern; break;
                case ObservationPattern.SelectionItem: identifier = SelectionItemPattern.Pattern; break;
                case ObservationPattern.Value: identifier = ValuePattern.Pattern; break;
                default: throw new ArgumentOutOfRangeException(nameof(pattern));
            }
            return ((AutomationElement)element).GetCurrentPattern(identifier);
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        public bool ValueReadOnly(object pattern) { return ((ValuePattern)pattern).Current.IsReadOnly; }

        [MethodImpl(MethodImplOptions.NoInlining)]
        public bool ClickablePoint(object element, out double x, out double y)
        {
            Point point;
            var result = ((AutomationElement)element).TryGetClickablePoint(out point);
            x = point.X; y = point.Y;
            return result;
        }

        [MethodImpl(MethodImplOptions.NoInlining)]
        public object ControlViewWalker() { return TreeWalker.ControlViewWalker; }

        [MethodImpl(MethodImplOptions.NoInlining)]
        public object Parent(object walker, object element) { return ((TreeWalker)walker).GetParent((AutomationElement)element); }
    }
}
