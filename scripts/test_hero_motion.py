"""히어로의 순차 점등과 선 이동, 정적 대체 화면을 검증한다."""

import importlib.util
import re
import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("build_assets", Path(__file__).with_name("build-assets.py"))
assets = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = assets
SPEC.loader.exec_module(assets)


class HeroMotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.svg = assets.build_hero()
        cls.root = ET.fromstring(cls.svg)
        cls.css = cls.root.find("{*}style").text

    def test_dots_share_a_pulse_with_increasing_delays(self):
        self.assertRegex(self.css, r"\.dot\s*\{[^}]*animation:\s*playhead 8s linear infinite")
        self.assertRegex(self.css, r"@keyframes playhead\s*\{")
        self.assertIn(f"0%,6.25%,100% {{ fill: {assets.INK_FAINT}; }}", self.css)
        self.assertIn(f"3.125% {{ fill: {assets.INK}; }}", self.css)
        dots = self.root.findall("{*}circle")
        self.assertEqual(len(dots), 14)
        delays = []
        for index, dot in enumerate(dots):
            self.assertEqual(dot.get("class"), "dot")
            self.assertEqual(dot.get("fill"), assets.INK_FAINT)
            self.assertEqual(float(dot.get("cx")), 650 + 14 * index)
            self.assertEqual(dot.get("cy"), "222")
            self.assertEqual(dot.get("r"), "1.25")
            delay = re.fullmatch(r"animation-delay: ([\d.]+)s", dot.get("style", ""))
            self.assertIsNotNone(delay)
            delays.append(float(delay.group(1)))
        self.assertEqual(delays, [index * 0.5 for index in range(14)])
        self.assertGreater(8 - (delays[-1] + 0.5), 0)

    def test_bundle_drifts_and_breathes_with_safe_extremes(self):
        self.assertRegex(self.css, r"\.bundle\s*\{[^}]*animation:[^}]*drift 18s ease-in-out infinite")
        self.assertIn("breathe 14s ease-in-out infinite", self.css)
        self.assertRegex(self.css, r"@keyframes drift\s*\{")
        for frame in ("0%,100% { transform: translateX(0); }",
                      "25% { transform: translateX(-10px); }",
                      "75% { transform: translateX(10px); }"):
            self.assertIn(frame, self.css)
        bundle = self.root.find("{*}g[@class='bundle']")
        lines = bundle.findall("{*}line")
        self.assertEqual([int(line.get("x1")) for line in lines], list(range(646, 807, 8)))
        for line in lines:
            self.assertEqual(line.get("x1"), line.get("x2"))
            self.assertEqual((line.get("y1"), line.get("y2")), ("37", "210"))
        for offset in (-10, 10):
            self.assertGreaterEqual(646 + offset - 0.5, 24)
            self.assertLessEqual(806 + offset + 0.5, assets.HERO_W - 24)

    def test_reduced_motion_disables_every_animated_class(self):
        reduced = re.search(r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{(.*)\}\s*$",
                            self.css, re.S)
        self.assertIsNotNone(reduced)
        rule = re.search(r"([^{}]+)\{\s*animation:\s*none;\s*\}", reduced.group(1))
        self.assertIsNotNone(rule)
        self.assertEqual({selector.strip() for selector in rule.group(1).split(",")},
                         {".bundle", ".dot"})

    def test_no_script_smil_filters_or_gradients(self):
        self.assertNotRegex(self.svg.lower(), r"<script|<animate|filter|gradient")

    def test_centered_variant_has_no_animation(self):
        self.assertNotIn("<style>", assets.build_hero(centered=True))


if __name__ == "__main__":
    unittest.main()
