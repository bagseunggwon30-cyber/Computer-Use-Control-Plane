"""Real startup checks for eight diagnostic delegates, including staged audit."""
import unittest
from legacy_production_startup import ProductionStartupChecks


class DiagnosticProductionStartupTests(ProductionStartupChecks, unittest.TestCase):
    family = 'diagnostics'
