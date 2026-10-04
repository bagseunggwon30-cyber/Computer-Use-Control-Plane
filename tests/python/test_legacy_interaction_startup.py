"""Production interaction routing must load its real support module once."""
import unittest
from legacy_production_startup import ProductionStartupChecks


class InteractionProductionStartupTests(ProductionStartupChecks, unittest.TestCase):
    family = 'interaction'
