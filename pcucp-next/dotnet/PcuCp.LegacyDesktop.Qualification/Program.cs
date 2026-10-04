using System;
using System.Drawing;
using System.IO;
using System.Linq;
using System.Text;
using System.Web.Script.Serialization;
using System.Windows.Forms;

// An owned acceptance surface, never a user application or production fallback.
internal static class Program
{
    private sealed class OwnedForm : Form { protected override bool ShowWithoutActivation => true; }
    [STAThread]
    private static int Main(string[] args)
    {
        if (args.Length != 2 || args[0] != "--state-directory" || !Path.IsPathRooted(args[1]) || !Directory.Exists(args[1])) return 2;
        var root = Path.GetFullPath(args[1]); var state = Path.Combine(root, "state.json"); var shutdown = Path.Combine(root, "shutdown");
        string title = "CUCP Owned Qualification " + Guid.NewGuid().ToString("N");
        Application.EnableVisualStyles();
        using (var form = new OwnedForm { Text = title, Name = "CUCPQualification", Width = 520, Height = 220, StartPosition = FormStartPosition.Manual,
            Location = new Point(40, 40), ShowInTaskbar = false })
        using (var text = new TextBox { Text = "initial", Name = "fixtureText", AccessibleName = "Fixture Text", Bounds = new Rectangle(20, 20, 440, 32) })
        using (var button = new Button { Text = "Save Message", Name = "fixtureSave", AccessibleName = "Save Message", Bounds = new Rectangle(20, 65, 170, 40) })
        using (var check = new CheckBox { Text = "Fixture Enabled", Name = "fixtureEnabled", AccessibleName = "Fixture Enabled", Bounds = new Rectangle(230, 70, 180, 30) })
        using (var timer = new Timer { Interval = 40 })
        {
            int clicks = 0; button.Click += (sender, eventArgs) => clicks++;
            form.Controls.AddRange(new Control[] { text, button, check });
            var json = new JavaScriptSerializer();
            bool safeClipboard = false; string priorText = null; bool clipboardWasEmpty = false;
            try
            {
                var previous = Clipboard.GetDataObject();
                var formats = previous?.GetFormats(false) ?? new string[0];
                clipboardWasEmpty = previous == null || formats.Length == 0;
                var allowed = new[] { "UnicodeText", "Text", "System.String", "OEMText", "Locale" };
                safeClipboard = formats.All(format => allowed.Contains(format)) && (clipboardWasEmpty || Clipboard.ContainsText());
                if (safeClipboard && Clipboard.ContainsText()) priorText = Clipboard.GetText();
                if (safeClipboard) Clipboard.SetDataObject("CUCP owned clipboard sentinel", true, 5, 100);
            }
            catch { safeClipboard = false; }
            void Publish()
            {
                bool clipboardRestored = false;
                if (safeClipboard) { try { clipboardRestored = Clipboard.GetText() == "CUCP owned clipboard sentinel"; } catch { } }
                var buttonPoint = button.PointToScreen(new Point(button.Width / 2, button.Height / 2));
                var current = new { title, hwnd = form.Handle.ToInt64(), pid = System.Diagnostics.Process.GetCurrentProcess().Id,
                    text = text.Text, toggled = check.Checked, clicks, clipboard_safe = safeClipboard, clipboard_restored = clipboardRestored,
                    button = new { x = buttonPoint.X, y = buttonPoint.Y } };
                string temporary = state + ".new"; File.WriteAllText(temporary, json.Serialize(current), new UTF8Encoding(false));
                if (File.Exists(state)) File.Replace(temporary, state, null); else File.Move(temporary, state);
            }
            form.Shown += (sender, eventArgs) => Publish();
            timer.Tick += (sender, eventArgs) => { if (File.Exists(shutdown)) form.Close(); else Publish(); };
            timer.Start();
            try { Application.Run(form); }
            finally
            {
                if (safeClipboard)
                {
                    try { if (priorText != null) Clipboard.SetDataObject(priorText, true, 5, 100); else if (clipboardWasEmpty) Clipboard.Clear(); }
                    catch { }
                }
            }
        }
        return 0;
    }
}
