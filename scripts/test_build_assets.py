"""레이아웃 검사기의 경계 조건과 실패 종료 코드를 검증한다."""

import contextlib
import io
import sys
import unittest
from unittest.mock import patch

import importlib.util
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("build_assets", Path(__file__).with_name("build-assets.py"))
assets = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = assets
SPEC.loader.exec_module(assets)


class LayoutCheckTests(unittest.TestCase):
    def setUp(self):
        assets.RUNS.clear()
        assets.CANVASES.clear()
        assets.CANVASES["test.svg"] = (880, 300)

    def check(self, runs):
        assets.RUNS[:] = runs
        with contextlib.redirect_stdout(io.StringIO()):
            return assets.check_layout()

    def run_at(self, bounds, baseline=40, asset="test.svg"):
        return assets.TextRun(asset, "검사용 글자", baseline, bounds)

    def test_exact_margin_is_allowed(self):
        self.assertTrue(self.check([self.run_at((24, 0, 856, 300))]))

    def test_each_canvas_edge_is_enforced(self):
        for bounds in [(23.99, 10, 100, 30), (24, 10, 856.01, 30),
                       (24, -0.01, 100, 30), (24, 10, 100, 300.01)]:
            with self.subTest(bounds=bounds):
                self.assertFalse(self.check([self.run_at(bounds)]))

    def test_same_baseline_overlap_fails(self):
        self.assertFalse(self.check([self.run_at((24, 10, 101, 40)),
                                     self.run_at((100, 10, 200, 40))]))

    def test_touching_runs_are_allowed(self):
        self.assertTrue(self.check([self.run_at((24, 10, 100, 40)),
                                    self.run_at((100, 10, 200, 40))]))

    def test_different_canvases_do_not_overlap(self):
        assets.CANVASES["other.svg"] = (880, 300)
        self.assertTrue(self.check([self.run_at((24, 10, 100, 40)),
                                    self.run_at((24, 10, 100, 40), asset="other.svg")]))

    def test_check_mode_returns_nonzero_for_real_glyph_overflow(self):
        original = assets.build_hero

        def overflow(centered=False):
            svg = original(centered)
            assets.t("mono", "OVERFLOW", 12, -50, 290, assets.INK)
            return svg

        with patch.object(sys, "argv", ["build-assets.py", "--check"]), \
                patch.object(assets, "build_hero", side_effect=overflow), \
                contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaises(SystemExit) as result:
                assets.main()
        self.assertEqual(result.exception.code, 1)


if __name__ == "__main__":
    unittest.main()
