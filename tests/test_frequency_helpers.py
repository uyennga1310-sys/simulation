"""Offline numerical checks; these do not validate the AEDT COM API."""
import ast
import math
from pathlib import Path
import re
import unittest

source = Path(__file__).resolve().parents[1] / 'ECT_Maxwell_2021R1.py'
tree = ast.parse(source.read_text(encoding='utf-8'))
selected = [node for node in tree.body if isinstance(node, ast.FunctionDef)
            and node.name in ('frequency_points', 'skin_depth_mm', 'detect_material',
                              'insert_frequency_setups')]
scope = dict(math=math, re=re, MAX_ADAPTIVE_PASSES=10, ADAPTIVE_PERCENT_ERROR=1.0)
exec(compile(ast.Module(body=selected, type_ignores=[]), str(source), 'exec'), scope)


class FrequencyTests(unittest.TestCase):
    def test_log_grid_includes_endpoints(self):
        values = scope['frequency_points'](1e4, 1e6, 9)
        self.assertEqual(len(values), 9)
        self.assertAlmostEqual(values[0], 1e4)
        self.assertAlmostEqual(values[-1], 1e6)
        for a, b in zip(values, values[1:]):
            self.assertAlmostEqual(b/a, 100 ** (1/8))

    def test_invalid_grid(self):
        for args in [(0, 100, 9), (100, 10, 9), (10, 100, 1),
                     (10, 100, 2.5), (10, float('nan'), 9)]:
            with self.assertRaises(ValueError):
                scope['frequency_points'](*args)
        self.assertEqual(scope['frequency_points'](100, 100, 1), [100])

    def test_copper_skin_depth_and_scaling(self):
        delta = scope['skin_depth_mm'](1e6, 1, 5.8e7)
        self.assertAlmostEqual(delta, 0.0661, places=4)
        self.assertAlmostEqual(scope['skin_depth_mm'](4e6, 1, 5.8e7), delta/2)
        with self.assertRaises(ValueError):
            scope['skin_depth_mm'](0, 1, 5.8e7)

    def test_no_steel_guess_for_generic_specimen(self):
        detect = scope['detect_material']
        self.assertIsNone(detect('specimen', 'vacuum'))
        self.assertEqual(detect('Specimen', 'aluminum'), 'aluminum')
        self.assertEqual(detect('TX_Copper', ''), 'copper')
        self.assertIsNone(detect('TX_Substrate', ''))

    def test_every_frequency_has_a_separate_setup(self):
        class Recorder:
            def __init__(self):
                self.calls = []
            def InsertSetup(self, kind, args):
                self.calls.append((kind, args))
        recorder = Recorder()
        names = scope['insert_frequency_setups'](recorder, [1e4, 1e5, 1e6])
        self.assertEqual(names, ['Freq_001', 'Freq_002', 'Freq_003'])
        for (kind, args), frequency in zip(recorder.calls, [1e4, 1e5, 1e6]):
            self.assertEqual(kind, 'EddyCurrent')
            self.assertEqual(float(args[args.index('Frequency:=')+1][:-2]), frequency)


if __name__ == '__main__':
    unittest.main()
