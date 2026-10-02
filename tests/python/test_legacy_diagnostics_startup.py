"""Only the seven qualified diagnostic production routes are checked here."""
import unittest
from legacy_production_startup import ProductionStartupChecks


class DiagnosticProductionStartupTests(ProductionStartupChecks, unittest.TestCase):
    family = 'diagnostics'
