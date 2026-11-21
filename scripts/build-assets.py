#!/usr/bin/env python3
"""README에 들어가는 SVG를 굽는다. 텍스트는 전부 윤곽선 <path>로 변환한다.

GitHub은 README 이미지를 camo 프록시로 감싸기 때문에 SVG 안에서 웹폰트·외부
이미지·외부 CSS를 불러올 수 없다. 그래서 필요한 글자를 harfbuzz로 셰이핑한 뒤
글리프 윤곽선을 직접 path로 써 넣는다. CSS @keyframes는 프록시를 통과하므로
애니메이션만 살려 둔다.

    uv run --with fonttools --with uharfbuzz python scripts/build-assets.py

토큰 정본: seoyulson-site/DESIGN.md
"""

from __future__ import annotations

import io
import argparse
from dataclasses import dataclass
import subprocess
import urllib.request
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.boundsPen import BoundsPen
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.misc.transform import Transform
from fontTools.ttLib import TTFont
from fontTools.varLib import instancer

ROOT = Path(__file__).resolve().parent.parent
FONTDIR = Path(__file__).resolve().parent / "fonts"
OUT = ROOT / "assets"
GF = "https://github.com/google/fonts/raw/main/"

# ---- design tokens (DESIGN.md) ----
BG = "#050505"
INK = "#eeeeec"
INK_DIM = "#a4a4a2"
INK_FAINT = "#6c6c6a"
HAIR = "rgba(238,238,236,0.14)"
PLANE = "#3a3a39"

# (키, google/fonts 경로, 고정할 가변축)
FONTS = {
    "display":   ("ofl/cormorantgaramond/CormorantGaramond%5Bwght%5D.ttf", {"wght": 400}),
    "italic":    ("ofl/cormorantgaramond/CormorantGaramond-Italic%5Bwght%5D.ttf", {"wght": 400}),
    "mono":      ("ofl/spacemono/SpaceMono-Regular.ttf", None),
    "mono-bold": ("ofl/spacemono/SpaceMono-Bold.ttf", None),
    "body":      ("ofl/inter/Inter%5Bopsz,wght%5D.ttf", {"wght": 300, "opsz": 14}),
    "ko":        ("ofl/notoserifkr/NotoSerifKR%5Bwght%5D.ttf", {"wght": 400}),
}

_loaded: dict[str, tuple] = {}


@dataclass
class TextRun:
    asset: str
    text: str
    baseline: float
    bounds: tuple[float, float, float, float]


RUNS: list[TextRun] = []
CANVASES: dict[str, tuple[int, int]] = {}
CURRENT_ASSET = ""


def num(v: float) -> str:
    """좌표를 소수점 2자리로 줄인다."""
    r = round(v, 2)
    if r == int(r):
        return str(int(r))
    return f"{r:.2f}".rstrip("0")


def source_ttf(key: str) -> Path:
    """원본 TTF를 받아 scripts/fonts/에 캐시한다."""
    path, _ = FONTS[key]
    dest = FONTDIR / path.rsplit("/", 1)[-1].replace("%5B", "[").replace("%5D", "]")
    if not dest.exists():
        FONTDIR.mkdir(parents=True, exist_ok=True)
        try:
            with urllib.request.urlopen(GF + path) as r:
                dest.write_bytes(r.read())
        except OSError:
            # 일부 실행 환경은 파이썬 소켓만 막는다. curl로 한 번 더 시도한다.
            subprocess.run(["curl", "-sL", "--fail", "--max-time", "300",
                            "-o", str(dest), GF + path], check=True)
    return dest


def load(key: str):
    """가변 폰트를 원하는 weight로 인스턴스화한 뒤 (TTFont, hb.Font, upem)을 돌려준다."""
    if key in _loaded:
        return _loaded[key]
    _, axes = FONTS[key]
    suffix = "-".join(f"{axis}{value}" for axis, value in (axes or {}).items())
    cache = FONTDIR / f"{key}{'-' + suffix if suffix else ''}.inst.ttf"
    if not cache.exists():
        tt = TTFont(source_ttf(key))
        if axes:
            tt = instancer.instantiateVariableFont(tt, axes, inplace=False)
        tt.save(cache)
    data = cache.read_bytes()
    tt = TTFont(io.BytesIO(data))
    face = hb.Face(data)
    hbf = hb.Font(face)
    hb.ot_font_set_funcs(hbf)
    _loaded[key] = (tt, hbf, face.upem)
    return _loaded[key]


def measure(key: str, text: str, size: float, tracking: float = 0.0) -> float:
    """마지막 글자 뒤 자간을 뺀 실제 폭."""
    _, hbf, upem = load(key)
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(hbf, buf, {"kern": True, "liga": True})
    s = size / upem
    w = sum(p.x_advance for p in buf.glyph_positions) * s
    return w + tracking * max(len(buf.glyph_infos) - 1, 0)


def text_path(key: str, text: str, size: float, x: float, y: float,
              tracking: float = 0.0, anchor: str = "start") -> str:
    """셰이핑된 글리프 윤곽선을 하나의 path d 문자열로 합친다."""
    tt, hbf, upem = load(key)
    glyph_set = tt.getGlyphSet()
    order = tt.getGlyphOrder()
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(hbf, buf, {"kern": True, "liga": True})
    s = size / upem

    if anchor != "start":
        w = measure(key, text, size, tracking)
        x = x - w if anchor == "end" else x - w / 2

    parts: list[str] = []
    bounds = BoundsPen(glyph_set)
    pen_x = x
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        if info.codepoint == 0:
            raise ValueError(f"누락 글리프: {text!r} (문자 위치 {info.cluster}, 폰트 {key})")
        name = order[info.codepoint]
        gx = pen_x + pos.x_offset * s
        gy = y - pos.y_offset * s
        pen = SVGPathPen(glyph_set, ntos=num)
        transform = Transform(s, 0, 0, -s, gx, gy)
        glyph_set[name].draw(TransformPen(pen, transform))
        glyph_set[name].draw(TransformPen(bounds, transform))
        d = pen.getCommands()
        if d:
            parts.append(d)
        pen_x += pos.x_advance * s + tracking
    if bounds.bounds is not None:
        RUNS.append(TextRun(CURRENT_ASSET, text, y, bounds.bounds))
    return "".join(parts)


def t(key: str, text: str, size: float, x: float, y: float, fill: str,
      tracking: float = 0.0, anchor: str = "start", opacity: str | None = None) -> str:
    d = text_path(key, text, size, x, y, tracking, anchor)
    op = f' opacity="{opacity}"' if opacity else ""
    return f'  <path d="{d}" fill="{fill}"{op}/>\n'


# ---------------------------------------------------------------- assets

HERO_W, HERO_H = 880, 254


def build_hero(centered: bool = False) -> str:
    """사이트의 평면·선 다발·점 열 또는 격자를 옮긴다."""
    role = "COMPOSER · SOUND ARTIST · WEB DEVELOPER"
    s = [
        f'<svg viewBox="0 0 {HERO_W} {HERO_H}" width="{HERO_W}" height="{HERO_H}"'
        ' xmlns="http://www.w3.org/2000/svg" role="img"'
        ' aria-label="Seoyul Son · composer, sound artist, web developer">\n',
        '  <title>Seoyul Son</title>\n',
        f'  <rect width="{HERO_W}" height="{HERO_H}" fill="{BG}"/>\n',
    ]
    if centered:
        s.append(f'  <g stroke="{HAIR}" stroke-width="0.5">\n')
        for x in range(40, HERO_W, 40):
            s.append(f'    <line x1="{x}" y1="19" x2="{x}" y2="230"/>\n')
        for y in range(30, 231, 40):
            s.append(f'    <line x1="24" y1="{y}" x2="856" y2="{y}"/>\n')
        s.append('  </g>\n')
    else:
        s.extend([
            '  <style>\n'
            '    .bundle { animation: breathe 14s ease-in-out infinite, drift 18s ease-in-out infinite; }\n'
            '    .dot { animation: playhead 8s linear infinite; }\n'
            '    @keyframes breathe { 0%,100% { opacity: 0.55; } 50% { opacity: 1; } }\n'
            '    @keyframes drift { 0%,100% { transform: translateX(0); } '
            '25% { transform: translateX(-10px); } 75% { transform: translateX(10px); } }\n'
            f'    @keyframes playhead {{ 0%,6.25%,100% {{ fill: {INK_FAINT}; }} '
            f'3.125% {{ fill: {INK}; }} }}\n'
            '    @media (prefers-reduced-motion: reduce) { .bundle, .dot { animation: none; } }\n'
            '  </style>\n',
            f'  <rect x="686" y="54" width="146" height="132" fill="{PLANE}"/>\n',
            f'  <g class="bundle" stroke="{HAIR}" stroke-width="1">\n',
        ])
        for x in range(646, 807, 8):
            s.append(f'    <line x1="{x}" y1="37" x2="{x}" y2="210"/>\n')
        s.append('  </g>\n')
        for index, x in enumerate(range(650, 833, 14)):
            s.append(f'  <circle class="dot" cx="{x}" cy="222" r="1.25" fill="{INK_FAINT}" '
                     f'style="animation-delay: {num(index * 0.5)}s"/>\n')

    if centered:
        s.append(t("display", "Seoyul Son", 112, 440, 127, INK, anchor="middle"))
        s.append(t("mono", role, 11, 440, 208, INK_DIM, anchor="middle"))
    else:
        s.append(t("display", "Seoyul Son", 92, 32, 136, INK))
        s.append(t("mono", role, 12, 34, 181, INK_DIM))
    s.append("</svg>\n")
    return "".join(s)


SEC_W, SEC_H = 880, 40


def build_section(title: str, right: list[tuple[str, str]], label: str) -> str:
    """투명 배경의 섹션 머리글을 양쪽 테마에서 읽히는 회색으로 쓴다."""
    base = 26.0
    s = [
        f'<svg viewBox="0 0 {SEC_W} {SEC_H}" width="{SEC_W}" height="{SEC_H}"'
        f' xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{label}">\n',
        f"  <title>{label}</title>\n",
        t("mono", title, 13.5, 32, base, INK_FAINT),
    ]
    left_end = 32 + measure("mono", title, 13.5)
    right_w = sum(measure(k, txt, 11) for k, txt in right) + 6 * max(len(right) - 1, 0)
    rx = SEC_W - 32 - right_w
    for k, txt in right:
        s.append(t(k, txt, 11, rx, base, INK_FAINT))
        rx += measure(k, txt, 11) + 6
    rule_end = SEC_W - 32 - right_w - (18 if right else 0)
    s.append(f'  <line x1="{num(left_end + 18)}" y1="21.5" x2="{num(rule_end)}" y2="21.5"'
             f' stroke="{INK_FAINT}" stroke-width="1" opacity="0.34"/>\n')
    s.append("</svg>\n")
    return "".join(s)


def check_layout() -> bool:
    """실제 윤곽선의 네 변과 같은 기준선의 글자 겹침을 검사한다."""
    errors = []
    for run in RUNS:
        left, top, right, bottom = run.bounds
        width, height = CANVASES[run.asset]
        print(f"{run.asset}: {run.text!r} left={left:.2f} right={right:.2f}")
        if left < 24 or right > width - 24 or top < 0 or bottom > height:
            errors.append(f"{run.asset}: 캔버스 여백 이탈 {run.text!r}")
    for i, run in enumerate(RUNS):
        for other in RUNS[i + 1:]:
            if run.asset == other.asset and abs(run.baseline - other.baseline) < 0.01:
                if min(run.bounds[2], other.bounds[2]) > max(run.bounds[0], other.bounds[0]):
                    errors.append(f"{run.asset}: 같은 기준선 겹침 {run.text!r}, {other.text!r}")
    for error in errors:
        print(f"FAIL: {error}")
    print(f"{'FAIL' if errors else 'PASS'}: {len(RUNS)} text runs, {len(CANVASES)} canvases, {len(errors)} errors")
    return not errors


def main() -> None:
    global CURRENT_ASSET
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="파일을 쓰지 않고 글자 경계를 검사한다")
    args = parser.parse_args()
    RUNS.clear()
    CANVASES.clear()
    builders = {
        "hero.svg": (lambda: build_hero(), HERO_W, HERO_H),
        "web.svg": (lambda: build_section("WEB", [], "Web"), SEC_W, SEC_H),
        "design.svg": (lambda: build_section("DESIGN", [], "Design"), SEC_W, SEC_H),
    }
    files = {}
    for name, (builder, width, height) in builders.items():
        CURRENT_ASSET = name
        CANVASES[name] = (width, height)
        files[name] = builder()
    if args.check:
        raise SystemExit(0 if check_layout() else 1)
    OUT.mkdir(parents=True, exist_ok=True)
    for name, body in files.items():
        (OUT / name).write_text(body, encoding="utf-8")
        print(f"{name:16} {len(body.encode()) / 1024:7.1f} KB")


if __name__ == "__main__":
    main()
