"""Test de fumée : le module principal s'importe sans effet de bord."""
import importlib
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_import_recap_geopolitique():
    module = importlib.import_module("recap_geopolitique")
    assert callable(module.main)
