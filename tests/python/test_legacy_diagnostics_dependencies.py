"""The one inert diagnostic type-display literal never grants engine access."""
import unittest
from test_legacy_diagnostics_parity import (
    DIAGNOSTIC_DISPLAY_DECLARATION, ROOT, diagnostic_dependency_source,
)


class DiagnosticDependencyGuards(unittest.TestCase):
    def check(self, source, name='LegacyDiagnosticJson.cs'):
        inspected = diagnostic_dependency_source(name, source)
        # These are the same unchanged forbidden dependencies as the corpus gate.
        for token in ('Process.Start(', 'ProcessStartInfo', 'File.Read', 'File.Write',
                      'DllImport', 'SendKeys', 'Management.Automation'):
            self.assertNotIn(token, inspected)

    def test_exact_named_declaration_is_allowed_only_as_inert_display_data(self):
        self.check(DIAGNOSTIC_DISPLAY_DECLARATION + '\nstring Display() => CustomObjectDisplayType;')
        for name in ('Other.cs', 'legacydiagnosticjson.cs', '../LegacyDiagnosticJson.cs'):
            with self.subTest(name=name), self.assertRaises(AssertionError):
                self.check(DIAGNOSTIC_DISPLAY_DECLARATION, name)
        with self.assertRaises(AssertionError):
            self.check('string Display() => "inert";')

    def test_using_qualified_reference_duplicate_and_reflective_uses_remain_forbidden(self):
        # Every payload uses the constant too: a test cannot pass solely because
        # the declared display constant happens to be unused by its example.
        payloads = [
            'using System.Management.Automation;',
            'object x = new System.Management.Automation.PSObject();',
            'var reference = typeof(System.Management.Automation.PSObject);',
            'string second = "System.Management.Automation.PSCustomObject";',
            DIAGNOSTIC_DISPLAY_DECLARATION,
            'Type.GetType(CustomObjectDisplayType);',
            'Assembly.Load(CustomObjectDisplayType);',
            'System.Reflection.Assembly.LoadFrom(CustomObjectDisplayType);',
            'Activator.CreateInstance(Type.GetType(CustomObjectDisplayType));',
            'assembly.GetType(CustomObjectDisplayType);',
            'assembly.GetManifestResourceStream(CustomObjectDisplayType);',
            'CustomObjectDisplayType.GetTypeInfo();',
        ]
        for payload in payloads:
            with self.subTest(payload=payload), self.assertRaises(AssertionError):
                self.check(DIAGNOSTIC_DISPLAY_DECLARATION + '\nstring Display() => CustomObjectDisplayType;\n' + payload)


    def test_nls_boundary_remains_fixed_readonly_and_local_to_diagnostic_errors(self):
        source = (ROOT / 'pcucp-next/dotnet/PcuCp.NativeHost/LegacyDiagnosticCulture.cs').read_text()
        self.assertEqual(source.count('[DllImport('), 1)
        self.assertIn('[DllImport("kernel32.dll",', source)
        self.assertIn('private static extern int GetLocaleInfoEx(', source)
        self.assertIn('private const uint ShortDate = 0x1f, LongTime = 0x1003, Am = 0x28, Pm = 0x29;', source)
        self.assertIn('count is < 1 or > 1024', source)
        self.assertIn('culture.Calendar is GregorianCalendar', source)
        self.assertIn('CultureInfo.InvariantCulture.DateTimeFormat.Clone()', source)
        for forbidden in ('Process.Start', 'File.', 'Registry', 'Environment.Set', 'CurrentCulture =',
                          'CurrentUICulture =', 'GetDateFormatEx(', 'GetTimeFormatEx(', 'Assembly.Load', 'Type.GetType'):
            self.assertNotIn(forbidden, source)


if __name__ == '__main__':
    unittest.main()
