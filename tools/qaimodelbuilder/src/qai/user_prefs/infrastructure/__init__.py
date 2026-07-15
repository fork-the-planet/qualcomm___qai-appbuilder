"""Infrastructure layer for ``qai.user_prefs`` — currently empty.

The ``user_prefs`` BC's persistence is fully covered by adapters
under :mod:`qai.user_prefs.adapters` (KV-backed) so no
framework-level helpers are needed here.  The empty layer is kept
in the package layout so the layered-``user_prefs`` import-linter
contract finds the directory it expects.
"""
