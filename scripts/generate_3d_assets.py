#!/usr/bin/env python3
"""
Generate true 3D isometric & perspective animated SVGs for AnonymusAgent's GitHub Profile README.

Uses real 3D rotation matrices, perspective projection, isometric Z-sorted prism geometry,
and verified GitHub repository & contribution telemetry from data/github_stats.json
(or live `gh api` when `--refresh` is passed).
"""

from __future__ import annotations

import argparse
import html
import json
import math
import subprocess
from pathlib import Path
from typing import Iterable, Sequence

ROOT = Path(__file__).resolve().parent.parent
DATA_PATH = ROOT / "data" / "github_stats.json"
ASSETS_DIR = ROOT / "assets"

FONT_SANS = "'Segoe UI', -apple-system, BlinkMacSystemFont, 'Inter', 'Helvetica Neue', Arial, sans-serif"
FONT_MONO = "'JetBrains Mono', 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace"

COS30 = math.cos(math.radians(30))
SIN30 = math.sin(math.radians(30))


def esc(text: str) -> str:
    return html.escape(str(text), quote=True)


def fmt_pts(pts: Iterable[tuple[float, float]]) -> str:
    return " ".join(f"{x:.2f},{y:.2f}" for x, y in pts)


# ---------------------------------------------------------------------------
# True 3D Math Utilities
# ---------------------------------------------------------------------------

def rot_xyz(p: tuple[float, float, float], rx: float, ry: float, rz: float) -> tuple[float, float, float]:
    x, y, z = p
    cx, sx = math.cos(rx), math.sin(rx)
    y, z = y * cx - z * sx, y * sx + z * cx
    cy, sy = math.cos(ry), math.sin(ry)
    x, z = x * cy + z * sy, -x * sy + z * cy
    cz, sz = math.cos(rz), math.sin(rz)
    x, y = x * cz - y * sz, x * sz + y * cz
    return (x, y, z)


def proj_persp(
    p: tuple[float, float, float],
    cx: float,
    cy: float,
    scale: float = 210.0,
    cam_dist: float = 3.8,
) -> tuple[float, float, float]:
    x, y, z = p
    denom = max(0.35, cam_dist - z)
    factor = scale / denom
    return (cx + x * factor, cy - y * factor, z)


def iso(
    u: float,
    v: float,
    z: float,
    ox: float,
    oy: float,
    scale: float = 1.0,
    sy: float = SIN30,
) -> tuple[float, float]:
    """Axonometric / isometric projection: +u down-right, +v down-left, +z up."""
    return (
        ox + (u - v) * COS30 * scale,
        oy + (u + v) * sy * scale - z * scale,
    )


def iso_prism(
    u0: float,
    v0: float,
    u1: float,
    v1: float,
    z0: float,
    z1: float,
    ox: float,
    oy: float,
    scale: float,
    c_top: str,
    c_left: str,
    c_right: str,
    stroke: str = "rgba(255,255,255,0.14)",
    stroke_w: float = 0.7,
    opacity: float = 1.0,
    sy: float = SIN30,
) -> str:
    """Return SVG polygons for a 3D isometric prism (left, right, top visible faces)."""
    t00 = iso(u0, v0, z1, ox, oy, scale, sy)
    t10 = iso(u1, v0, z1, ox, oy, scale, sy)
    t11 = iso(u1, v1, z1, ox, oy, scale, sy)
    t01 = iso(u0, v1, z1, ox, oy, scale, sy)

    b10 = iso(u1, v0, z0, ox, oy, scale, sy)
    b11 = iso(u1, v1, z0, ox, oy, scale, sy)
    b01 = iso(u0, v1, z0, ox, oy, scale, sy)

    op_attr = f' opacity="{opacity:.2f}"' if opacity < 0.999 else ""
    return "\n".join([
        f'<g{op_attr}>',
        f'<polygon points="{fmt_pts([t01, t11, b11, b01])}" fill="{c_left}" stroke="{stroke}" stroke-width="{stroke_w:.2f}" stroke-linejoin="round"/>',
        f'<polygon points="{fmt_pts([t10, t11, b11, b10])}" fill="{c_right}" stroke="{stroke}" stroke-width="{stroke_w:.2f}" stroke-linejoin="round"/>',
        f'<polygon points="{fmt_pts([t00, t10, t11, t01])}" fill="{c_top}" stroke="{stroke}" stroke-width="{stroke_w:.2f}" stroke-linejoin="round"/>',
        "</g>",
    ])


def icosahedron_mesh() -> tuple[list[tuple[float, float, float]], list[tuple[int, int]]]:
    phi = (1.0 + math.sqrt(5.0)) / 2.0
    raw = [
        (-1, phi, 0), (1, phi, 0), (-1, -phi, 0), (1, -phi, 0),
        (0, -1, phi), (0, 1, phi), (0, -1, -phi), (0, 1, -phi),
        (phi, 0, -1), (phi, 0, 1), (-phi, 0, -1), (-phi, 0, 1),
    ]
    verts = []
    for x, y, z in raw:
        n = math.sqrt(x * x + y * y + z * z)
        verts.append((x / n, y / n, z / n))
    edges: list[tuple[int, int]] = []
    for i in range(len(verts)):
        for j in range(i + 1, len(verts)):
            dx = verts[i][0] - verts[j][0]
            dy = verts[i][1] - verts[j][1]
            dz = verts[i][2] - verts[j][2]
            if dx * dx + dy * dy + dz * dz < 1.3:
                edges.append((i, j))
    return verts, edges


def cube_mesh(r: float = 0.48) -> tuple[list[tuple[float, float, float]], list[tuple[int, int]]]:
    verts = [
        (-r, -r, -r), (r, -r, -r), (r, r, -r), (-r, r, -r),
        (-r, -r, r), (r, -r, r), (r, r, r), (-r, r, r),
    ]
    edges = [
        (0, 1), (1, 2), (2, 3), (3, 0),
        (4, 5), (5, 6), (6, 7), (7, 4),
        (0, 4), (1, 5), (2, 6), (3, 7),
    ]
    return verts, edges


def wireframe_keyframe_paths(
    verts: Sequence[tuple[float, float, float]],
    edges: Sequence[tuple[int, int]],
    cx: float,
    cy: float,
    scale: float,
    frames: int = 36,
    tilt_x: float = 0.42,
    direction: float = 1.0,
) -> list[str]:
    paths: list[str] = []
    for f in range(frames + 1):
        ang = direction * (2.0 * math.pi * f / frames)
        projected = [
            proj_persp(rot_xyz(v, tilt_x + 0.16 * math.sin(ang), ang, ang * 0.35), cx, cy, scale=scale)
            for v in verts
        ]
        segs = []
        for a, b in edges:
            x1, y1, _ = projected[a]
            x2, y2, _ = projected[b]
            segs.append(f"M {x1:.1f} {y1:.1f} L {x2:.1f} {y2:.1f}")
        paths.append(" ".join(segs))
    return paths


def orbit_satellite_keyframes(
    cx: float,
    cy: float,
    rx: float,
    ry: float,
    tilt_deg: float,
    start_deg: float,
    direction: float = 1.0,
    frames: int = 36,
) -> tuple[list[tuple[float, float]], str]:
    """Compute explicit 2D positions along a tilted 3D ellipse so both static & animated SVG look exact."""
    tilt = math.radians(tilt_deg)
    ct, st = math.cos(tilt), math.sin(tilt)
    pts: list[tuple[float, float]] = []
    for f in range(frames + 1):
        theta = math.radians(start_deg) + direction * (2.0 * math.pi * f / frames)
        ex = rx * math.cos(theta)
        ey = ry * math.sin(theta)
        px = cx + ex * ct - ey * st
        py = cy + ex * st + ey * ct
        pts.append((px, py))
    # Build animateTransform translate values relative to frame 0!
    x0, y0 = pts[0]
    vals = ";".join(f"{x - x0:.1f} {y - y0:.1f}" for x, y in pts)
    return pts, vals


# ---------------------------------------------------------------------------
# Shared Data Loading
# ---------------------------------------------------------------------------

def load_stats(refresh: bool = False) -> dict:
    if refresh:
        query = '''
query {
  user(login: "AnonymusAgent") {
    name
    login
    bio
    websiteUrl
    contributionsCollection {
      totalCommitContributions
      totalPullRequestContributions
      totalIssueContributions
      totalRepositoryContributions
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            contributionCount
            date
          }
        }
      }
    }
    repositories(first: 100, ownerAffiliations: OWNER, isFork: false) {
      totalCount
      nodes {
        name
        stargazerCount
        forkCount
        pushedAt
        primaryLanguage { name color }
      }
    }
  }
}
'''
        gql = json.loads(
            subprocess.check_output(["gh", "api", "graphql", "-f", f"query={query}"], text=True)
        )["data"]["user"]
        repos = json.loads(
            subprocess.check_output(["gh", "api", "users/AnonymusAgent/repos?per_page=100&sort=updated"], text=True)
        )
        lang_totals: dict[str, int] = {}
        for r in repos:
            langs = json.loads(
                subprocess.check_output(["gh", "api", f"repos/AnonymusAgent/{r['name']}/languages"], text=True)
            )
            for k, v in langs.items():
                lang_totals[k] = lang_totals.get(k, 0) + v
        snapshot = {
            "user": {
                "login": gql["login"],
                "name": gql["name"],
                "bio": gql["bio"],
                "websiteUrl": gql["websiteUrl"],
            },
            "stats": {
                "public_repos": gql["repositories"]["totalCount"],
                "total_stars": sum(r["stargazerCount"] for r in gql["repositories"]["nodes"]),
                "total_contributions": gql["contributionsCollection"]["contributionCalendar"]["totalContributions"],
                "commits": gql["contributionsCollection"]["totalCommitContributions"],
                "pull_requests": gql["contributionsCollection"]["totalPullRequestContributions"],
                "new_repos_year": gql["contributionsCollection"]["totalRepositoryContributions"],
            },
            "languages": dict(sorted(lang_totals.items(), key=lambda x: -x[1])),
            "weeks": gql["contributionsCollection"]["contributionCalendar"]["weeks"],
        }
        DATA_PATH.parent.mkdir(parents=True, exist_ok=True)
        DATA_PATH.write_text(json.dumps(snapshot, indent=2))
        return snapshot
    return json.loads(DATA_PATH.read_text())


# ---------------------------------------------------------------------------
# 1. HERO 3D STAGE (1200 x 440)
# ---------------------------------------------------------------------------

def build_hero_3d(stats: dict) -> str:
    W, H = 1200, 440
    s = stats["stats"]
    langs = stats["languages"]
    total_bytes = sum(langs.values()) or 1
    ts_pct = 100.0 * langs.get("TypeScript", 0) / total_bytes

    # 3D perspective floor grid
    vx, vy = 875.0, 178.0
    floor_top = 248.0
    floor_bot = 428.0
    grid_lines = []
    for u in range(-10, 15):
        bx = 50.0 + u * 92.0
        t = (floor_top - vy) / (floor_bot - vy)
        tx = vx + (bx - vx) * t
        grid_lines.append(
            f'<line x1="{tx:.1f}" y1="{floor_top:.1f}" x2="{bx:.1f}" y2="{floor_bot:.1f}" '
            f'stroke="url(#heroGridFade)" stroke-width="1" opacity="0.48"/>'
        )
    for i in range(1, 10):
        k = (i / 9.0) ** 1.75
        y = floor_top + k * (floor_bot - floor_top)
        op = 0.14 + 0.34 * k
        grid_lines.append(
            f'<line x1="22" y1="{y:.1f}" x2="{W - 22}" y2="{y:.1f}" '
            f'stroke="#38bdf8" stroke-width="0.9" opacity="{op:.2f}"/>'
        )

    cx, cy = 935.0, 200.0
    ico_v, ico_e = icosahedron_mesh()
    ico_paths = wireframe_keyframe_paths(ico_v, ico_e, cx, cy, scale=325.0, frames=36, tilt_x=0.38, direction=1.0)

    cube_v, cube_e = cube_mesh(0.48)
    cube_paths = wireframe_keyframe_paths(cube_v, cube_e, cx, cy, scale=325.0, frames=36, tilt_x=-0.52, direction=-1.0)

    # Orbiting satellites positioned accurately at frame 0 AND animated along tilted 3D orbits
    sat_specs = [
        ("TS", "#38bdf8", 176, 52, -22, 16, 1.0, "7s"),
        ("NX", "#a855f7", 172, 50, 24, 162, -1.0, "8.5s"),
        ("PG", "#34d399", 154, 38, 2, 36, 1.0, "6s"),
    ]
    sat_svgs = []
    for label, col, rx_o, ry_o, tilt_deg, start_deg, dir_, dur in sat_specs:
        pts, trans_vals = orbit_satellite_keyframes(cx, cy, rx_o, ry_o, tilt_deg, start_deg, dir_, frames=36)
        sx0, sy0 = pts[0]
        sat_svgs.append(f'''<g>
  <ellipse cx="{cx}" cy="{cy}" rx="{rx_o}" ry="{ry_o}" fill="none" stroke="{col}" stroke-width="1.2"
    stroke-dasharray="5 5" opacity="0.48" transform="rotate({tilt_deg} {cx} {cy})"/>
  <g>
    <animateTransform attributeName="transform" type="translate" values="{trans_vals}" dur="{dur}" repeatCount="indefinite"/>
    <circle cx="{sx0:.1f}" cy="{sy0:.1f}" r="14" fill="#0b1326" stroke="{col}" stroke-width="1.6"/>
    <text x="{sx0:.1f}" y="{sy0 + 4:.1f}" text-anchor="middle" font-family="{FONT_MONO}" font-size="9.8" font-weight="800" fill="{col}">{label}</text>
  </g>
</g>''')

    # Extruded 3D Title "ALI MUKHTAR"
    title_layers = []
    depth_colors = ["#0e1a3a", "#122654", "#173370", "#1e4590", "#265ab2", "#38bdf8"]
    for i, col in enumerate(depth_colors):
        off = (len(depth_colors) - i) * 1.85
        title_layers.append(
            f'<text x="{66 + off:.1f}" y="{148 + off:.1f}" font-family="{FONT_SANS}" '
            f'font-size="60" font-weight="900" letter-spacing="3.5" fill="{col}">ALI MUKHTAR</text>'
        )
    title_layers.append(
        f'<text x="66" y="148" font-family="{FONT_SANS}" font-size="60" font-weight="900" '
        f'letter-spacing="3.5" fill="url(#titleChrome)" stroke="#e0f2fe" stroke-width="0.6">ALI MUKHTAR</text>'
    )

    chips_data = [
        (f"{s['public_repos']}", "PUBLIC REPOS", "#38bdf8", "#0284c7", "#075985", 0.0),
        (f"{s['total_contributions']}", "CONTRIBUTIONS", "#34d399", "#059669", "#065f46", 0.7),
        (f"{ts_pct:.1f}%", "TYPESCRIPT", "#818cf8", "#4f46e5", "#3730a3", 1.4),
        ("7+", "LIVE VERCEL APPS", "#f472b6", "#db2777", "#9d174d", 2.1),
    ]
    chip_svgs = []
    for idx, (val, label, c_accent, c_left, c_right, phase) in enumerate(chips_data):
        x0 = 66 + idx * 155
        y0 = 308
        w, h, d = 138, 66, 9
        chip_svgs.append(
            f'<polygon points="{x0 + 10},{y0 + h + 18} {x0 + w + 16},{y0 + h + 18} '
            f'{x0 + w + 6},{y0 + h + 28} {x0 + 2},{y0 + h + 28}" fill="#020617" opacity="0.72"/>'
        )
        chip_svgs.append(f'''<g>
  <animateTransform attributeName="transform" type="translate"
    values="0 0; 0 -5; 0 0" begin="{phase:.1f}s" dur="4.2s" repeatCount="indefinite"/>
  <polygon points="{x0},{y0 + h} {x0 + w},{y0 + h} {x0 + w + d},{y0 + h + d} {x0 + d},{y0 + h + d}"
    fill="{c_right}" opacity="0.88"/>
  <polygon points="{x0 + w},{y0} {x0 + w + d},{y0 + d} {x0 + w + d},{y0 + h + d} {x0 + w},{y0 + h}"
    fill="{c_left}" opacity="0.92"/>
  <rect x="{x0}" y="{y0}" width="{w}" height="{h}" rx="8" fill="#0d172b" fill-opacity="0.94"
    stroke="{c_accent}" stroke-width="1.2" stroke-opacity="0.75"/>
  <rect x="{x0 + 1}" y="{y0 + 1}" width="{w - 2}" height="3" rx="1.5" fill="{c_accent}" opacity="0.85"/>
  <text x="{x0 + 14}" y="{y0 + 34}" font-family="{FONT_SANS}" font-size="24" font-weight="800" fill="#f8fafc">{esc(val)}</text>
  <text x="{x0 + 14}" y="{y0 + 53}" font-family="{FONT_MONO}" font-size="9.5" font-weight="600" letter-spacing="1" fill="#94a3b8">{esc(label)}</text>
</g>''')

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Ali Mukhtar — AnonymusAgent 3D Hero Stage">
  <defs>
    <linearGradient id="heroBg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#050814"/>
      <stop offset="55%" stop-color="#0a1226"/>
      <stop offset="100%" stop-color="#060b18"/>
    </linearGradient>
    <radialGradient id="nebulaCyan" cx="78%" cy="44%" r="42%">
      <stop offset="0%" stop-color="#0ea5e9" stop-opacity="0.34"/>
      <stop offset="48%" stop-color="#6366f1" stop-opacity="0.16"/>
      <stop offset="100%" stop-color="#050814" stop-opacity="0"/>
    </radialGradient>
    <radialGradient id="nebulaLeft" cx="18%" cy="28%" r="45%">
      <stop offset="0%" stop-color="#6366f1" stop-opacity="0.18"/>
      <stop offset="100%" stop-color="#050814" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="heroGridFade" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.06"/>
      <stop offset="100%" stop-color="#38bdf8" stop-opacity="0.62"/>
    </linearGradient>
    <linearGradient id="titleChrome" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0%" stop-color="#ffffff"/>
      <stop offset="55%" stop-color="#e2e8f0"/>
      <stop offset="100%" stop-color="#7dd3fc"/>
    </linearGradient>
    <linearGradient id="wireCyan" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#38bdf8"/>
      <stop offset="50%" stop-color="#818cf8"/>
      <stop offset="100%" stop-color="#34d399"/>
    </linearGradient>
    <linearGradient id="borderGlow" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.72"/>
      <stop offset="50%" stop-color="#818cf8" stop-opacity="0.45"/>
      <stop offset="100%" stop-color="#34d399" stop-opacity="0.65"/>
    </linearGradient>
    <filter id="neonGlow" x="-25%" y="-25%" width="150%" height="150%">
      <feGaussianBlur stdDeviation="3.5" result="blur"/>
      <feMerge>
        <feMergeNode in="blur"/>
        <feMergeNode in="SourceGraphic"/>
      </feMerge>
    </filter>
    <clipPath id="heroClip">
      <rect x="6" y="6" width="{W - 12}" height="{H - 12}" rx="20"/>
    </clipPath>
  </defs>

  <rect x="10" y="10" width="{W - 12}" height="{H - 12}" rx="22" fill="#02040a" opacity="0.85"/>
  <g clip-path="url(#heroClip)">
    <rect x="6" y="6" width="{W - 12}" height="{H - 12}" rx="20" fill="url(#heroBg)"/>
    <rect x="6" y="6" width="{W - 12}" height="{H - 12}" rx="20" fill="url(#nebulaCyan)"/>
    <rect x="6" y="6" width="{W - 12}" height="{H - 12}" rx="20" fill="url(#nebulaLeft)"/>

    <line x1="20" y1="248" x2="{W - 20}" y2="248" stroke="#38bdf8" stroke-width="1.2" opacity="0.35"/>
    {''.join(grid_lines)}

    <ellipse cx="{cx}" cy="368" rx="115" ry="20" fill="#020617" opacity="0.82">
      <animate attributeName="rx" values="115;96;115" dur="4.5s" repeatCount="indefinite"/>
      <animate attributeName="opacity" values="0.82;0.55;0.82" dur="4.5s" repeatCount="indefinite"/>
    </ellipse>
    <ellipse cx="{cx}" cy="368" rx="74" ry="11" fill="#0ea5e9" opacity="0.24" filter="url(#neonGlow)"/>

    <g>
      <rect x="66" y="42" width="405" height="32" rx="16" fill="#0f172a" fill-opacity="0.88"
        stroke="#38bdf8" stroke-width="1" stroke-opacity="0.55"/>
      <circle cx="86" cy="58" r="4.5" fill="#34d399">
        <animate attributeName="opacity" values="1;0.35;1" dur="1.8s" repeatCount="indefinite"/>
      </circle>
      <text x="100" y="62" font-family="{FONT_MONO}" font-size="11.5" font-weight="700"
        letter-spacing="1.4" fill="#cbd5e1">ANONYMUSAGENT  //  WEB LOOM STUDIO</text>
    </g>

    <g>{''.join(title_layers)}</g>

    <text x="68" y="192" font-family="{FONT_MONO}" font-size="15.5" font-weight="700"
      letter-spacing="2.2" fill="#38bdf8">FULL-STACK PRODUCT ARCHITECT  ·  CODE · CREATE · INNOVATE</text>

    <g>
      <rect x="68" y="216" width="596" height="42" rx="10" fill="#0b1325" fill-opacity="0.9"
        stroke="#334155" stroke-width="1.1"/>
      <circle cx="88" cy="237" r="4.2" fill="#f43f5e"/>
      <circle cx="104" cy="237" r="4.2" fill="#f59e0b"/>
      <circle cx="120" cy="237" r="4.2" fill="#10b981"/>
      <text x="142" y="241" font-family="{FONT_MONO}" font-size="12.5" fill="#94a3b8">
        <tspan fill="#34d399">$</tspan> stack: <tspan fill="#f8fafc">Next.js 16 · TypeScript · React Native / Expo · PostgreSQL</tspan>
      </text>
      <rect x="636" y="229" width="7" height="16" rx="1" fill="#38bdf8">
        <animate attributeName="opacity" values="1;0;1" dur="1s" repeatCount="indefinite"/>
      </rect>
    </g>

    {''.join(chip_svgs)}

    <g>
      <animateTransform attributeName="transform" type="translate"
        values="0 0; 0 -8; 0 0" dur="4.5s" repeatCount="indefinite"/>

      {''.join(sat_svgs)}

      <circle cx="{cx}" cy="{cy}" r="52" fill="#0ea5e9" opacity="0.14" filter="url(#neonGlow)"/>

      <path d="{ico_paths[0]}" fill="none" stroke="url(#wireCyan)" stroke-width="2.1"
        stroke-linecap="round" stroke-linejoin="round" filter="url(#neonGlow)">
        <animate attributeName="d" values="{';'.join(ico_paths)}" dur="14s" repeatCount="indefinite"/>
      </path>

      <path d="{cube_paths[0]}" fill="none" stroke="#34d399" stroke-width="1.6" opacity="0.88"
        stroke-linecap="round" stroke-linejoin="round">
        <animate attributeName="d" values="{';'.join(cube_paths)}" dur="10s" repeatCount="indefinite"/>
      </path>

      <circle cx="{cx}" cy="{cy}" r="7" fill="#f8fafc" filter="url(#neonGlow)">
        <animate attributeName="r" values="6;9;6" dur="2.6s" repeatCount="indefinite"/>
      </circle>
    </g>

    <text x="{W - 36}" y="{H - 24}" text-anchor="end" font-family="{FONT_MONO}" font-size="10.5"
      fill="#64748b" letter-spacing="1.2">3D SPATIAL PROFILE  ·  WEBLOOM-NU.VERCEL.APP</text>
  </g>

  <rect x="6" y="6" width="{W - 12}" height="{H - 12}" rx="20" fill="none" stroke="url(#borderGlow)" stroke-width="1.6"/>
</svg>'''


# ---------------------------------------------------------------------------
# 2. 3D ARCHITECTURE & CODEBASE TELEMETRY (1200 x 410)
# ---------------------------------------------------------------------------

def build_stack_3d(stats: dict) -> str:
    W, H = 1200, 410
    langs = stats["languages"]
    total = sum(langs.values()) or 1

    layers = [
        ("01 // MEDIA, OCR & CLOUD", "Mux Video · PDF.js · Tesseract OCR · AWS S3 · Vercel",
         "rgba(244,114,182,0.22)", "#be185d", "#831843", "#f472b6", 0.0),
        ("02 // DATA & PERSISTENCE", "PostgreSQL · Neon Serverless · Supabase · Drizzle ORM",
         "rgba(52,211,153,0.22)", "#059669", "#065f46", "#34d399", 0.6),
        ("03 // APPLICATION & AUTH", "TypeScript · App Router · Node.js · Express · Better Auth",
         "rgba(129,140,248,0.24)", "#4f46e5", "#312e81", "#818cf8", 1.2),
        ("04 // EXPERIENCE LAYER", "Next.js 16 · React 19 · React Native / Expo · Tailwind 4",
         "rgba(56,189,248,0.28)", "#0284c7", "#075985", "#38bdf8", 1.8),
    ]

    ox, oy_base = 178.0, 232.0
    slab_w = 122.0
    layer_svgs = []
    c_center = iso(slab_w * 0.5, slab_w * 0.5, -10, ox, oy_base, 1.0)
    layer_svgs.append(
        f'<line x1="{c_center[0]:.1f}" y1="{c_center[1] + 8:.1f}" x2="{c_center[0]:.1f}" y2="{c_center[1] - 185:.1f}" '
        f'stroke="#38bdf8" stroke-width="1.6" stroke-dasharray="4 4" opacity="0.5"/>'
    )

    for idx, (title, sub, c_top, c_left, c_right, c_rim, phase) in enumerate(layers):
        z0 = idx * 42.0
        z1 = z0 + 10.0
        prism = iso_prism(
            0, 0, slab_w, slab_w, z0, z1, ox, oy_base, 1.0,
            c_top=c_top, c_left=c_left, c_right=c_right, stroke=c_rim, stroke_w=1.3, opacity=0.95
        )
        anchor = iso(slab_w, slab_w * 0.5, (z0 + z1) * 0.5, ox, oy_base, 1.0)
        label_x = 344
        label_y = 335 - idx * 72
        layer_svgs.append(f'''<g>
  <animateTransform attributeName="transform" type="translate"
    values="0 0; 0 -3.5; 0 0" begin="{phase:.1f}s" dur="4s" repeatCount="indefinite"/>
  {prism}
  <polyline points="{anchor[0]:.1f},{anchor[1]:.1f} {anchor[0] + 24:.1f},{label_y:.1f} {label_x - 8:.1f},{label_y:.1f}"
    fill="none" stroke="{c_rim}" stroke-width="1.2" opacity="0.8"/>
  <circle cx="{anchor[0]:.1f}" cy="{anchor[1]:.1f}" r="3.2" fill="{c_rim}"/>
  <rect x="{label_x}" y="{label_y - 23}" width="334" height="46" rx="9" fill="#0d172c" fill-opacity="0.94"
    stroke="{c_rim}" stroke-width="1" stroke-opacity="0.6"/>
  <text x="{label_x + 14}" y="{label_y - 4}" font-family="{FONT_MONO}" font-size="10.8" font-weight="800" fill="{c_rim}">{esc(title)}</text>
  <text x="{label_x + 14}" y="{label_y + 13}" font-family="{FONT_SANS}" font-size="10.6" fill="#cbd5e1">{esc(sub)}</text>
</g>''')

    # Right half: 3D Isometric Language Crystal Towers (clean separation from legend below)
    lang_specs = [
        ("TypeScript", langs.get("TypeScript", 0), "#38bdf8", "#0284c7", "#075985"),
        ("JavaScript", langs.get("JavaScript", 0), "#fbbf24", "#d97706", "#92400e"),
        ("HTML", langs.get("HTML", 0), "#fb7185", "#e11d48", "#9f1239"),
        ("CSS", langs.get("CSS", 0), "#a78bfa", "#7c3aed", "#5b21b6"),
        ("PLpgSQL", langs.get("PLpgSQL", 0), "#34d399", "#059669", "#065f46"),
    ]

    pox, poy = 916.0, 198.0
    pedestal = iso_prism(
        -8, -4, 198, 32, -9, 0, pox, poy, 1.0,
        c_top="#0f1c38", c_left="#0a1328", c_right="#070e1d",
        stroke="#38bdf8", stroke_w=1.0, opacity=0.95
    )

    towers = [pedestal]
    max_b = max(v for _, v, *_ in lang_specs) or 1
    for i, (lname, bcount, ct, cl, cr) in enumerate(lang_specs):
        u0 = 6 + i * 38
        u1 = u0 + 22
        v0, v1 = 4, 24
        pct = 100.0 * bcount / total
        ratio = bcount / max_b
        h_px = 14.0 + (ratio ** 0.36) * 102.0
        prism = iso_prism(
            u0, v0, u1, v1, 0, h_px, pox, poy, 1.0,
            c_top=ct, c_left=cl, c_right=cr, stroke="#e2e8f0", stroke_w=0.65, opacity=0.96
        )
        top_pt = iso((u0 + u1) * 0.5, (v0 + v1) * 0.5, h_px, pox, poy, 1.0)
        towers.append(prism)
        towers.append(
            f'<text x="{top_pt[0]:.1f}" y="{top_pt[1] - 14:.1f}" text-anchor="middle" '
            f'font-family="{FONT_MONO}" font-size="10.2" font-weight="800" fill="{ct}">{pct:.1f}%</text>'
        )

    # Clean legend box cleanly placed BELOW pedestal (no overlap!)
    legend_items = [
        f'<rect x="726" y="328" width="438" height="66" rx="10" fill="#091122" fill-opacity="0.98" stroke="#1e293b" stroke-width="1"/>'
    ]
    for i, (lname, bcount, ct, _, _) in enumerate(lang_specs):
        pct = 100.0 * bcount / total
        size_str = f"{bcount / 1_000_000:.2f} MB" if bcount >= 1_000_000 else f"{bcount / 1_000:.0f} KB"
        lx = 744 + (i % 2) * 218
        ly = 348 + (i // 2) * 18.5
        legend_items.append(
            f'<circle cx="{lx}" cy="{ly - 4}" r="4.2" fill="{ct}"/>'
            f'<text x="{lx + 11}" y="{ly}" font-family="{FONT_MONO}" font-size="10.5" fill="#e2e8f0">'
            f'{esc(lname)} <tspan fill="#94a3b8">({pct:.1f}% · {size_str})</tspan></text>'
        )

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="3D Isometric Architecture and Language Distribution">
  <defs>
    <linearGradient id="stackBg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#060a16"/>
      <stop offset="100%" stop-color="#0b1326"/>
    </linearGradient>
    <linearGradient id="stackBorder" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.6"/>
      <stop offset="50%" stop-color="#818cf8" stop-opacity="0.5"/>
      <stop offset="100%" stop-color="#34d399" stop-opacity="0.6"/>
    </linearGradient>
  </defs>

  <rect x="8" y="8" width="{W - 12}" height="{H - 12}" rx="18" fill="#02040a" opacity="0.8"/>
  <rect x="4" y="4" width="{W - 12}" height="{H - 12}" rx="18" fill="url(#stackBg)" stroke="url(#stackBorder)" stroke-width="1.4"/>

  <text x="36" y="42" font-family="{FONT_MONO}" font-size="13" font-weight="800" letter-spacing="2" fill="#38bdf8">
    01 // 3D FULL-STACK ARCHITECTURE
  </text>
  <text x="726" y="42" font-family="{FONT_MONO}" font-size="13" font-weight="800" letter-spacing="2" fill="#34d399">
    02 // 24-REPO CODEBASE ({total / 1_000_000:.2f} MB)
  </text>
  <line x1="700" y1="28" x2="700" y2="{H - 28}" stroke="#1e293b" stroke-width="1.2" stroke-dasharray="5 5"/>

  {''.join(layer_svgs)}
  {''.join(towers)}
  {''.join(legend_items)}
</svg>'''


# ---------------------------------------------------------------------------
# 3. 3D ISOMETRIC PROJECT CARDS (560 x 215 each)
# ---------------------------------------------------------------------------

def render_mini_3d_icon(kind: str, cx: float, cy: float, c_top: str, c_left: str, c_right: str) -> str:
    if kind == "layers":
        return "\n".join([
            iso_prism(0, 0, 44, 44, 0, 8, cx, cy + 16, 1.0, c_top, c_left, c_right, "#f8fafc", 0.8),
            iso_prism(4, 4, 40, 40, 18, 26, cx, cy + 16, 1.0, "#a78bfa", "#6d28d9", "#4c1d95", "#f8fafc", 0.8),
            iso_prism(8, 8, 36, 36, 36, 44, cx, cy + 16, 1.0, "#f8fafc", c_top, c_left, "#ffffff", 0.9),
        ])
    if kind == "bars":
        # Staircase 3D bars side-by-side along +u so all 3 pillars are distinctly visible!
        return "\n".join([
            iso_prism(-2, 4, 52, 34, -6, 0, cx, cy + 18, 1.0, "#1e293b", "#0f172a", "#020617", c_top, 0.9),
            iso_prism(4, 12, 16, 26, 0, 20, cx, cy + 18, 1.0, "#38bdf8", "#0284c7", "#075985", "#e0f2fe", 0.7),
            iso_prism(20, 12, 32, 26, 0, 35, cx, cy + 18, 1.0, c_top, c_left, c_right, "#d1fae5", 0.7),
            iso_prism(36, 12, 48, 26, 0, 50, cx, cy + 18, 1.0, "#f8fafc", c_top, c_left, "#ffffff", 0.85),
        ])
    if kind == "cinema":
        cube = iso_prism(0, 0, 46, 46, 0, 46, cx, cy + 24, 1.0, c_top, c_left, c_right, "#fda4af", 1.0)
        p1 = iso(14, 46, 34, cx, cy + 24, 1.0)
        p2 = iso(14, 46, 12, cx, cy + 24, 1.0)
        p3 = iso(36, 46, 23, cx, cy + 24, 1.0)
        return cube + f'\n<polygon points="{fmt_pts([p1, p2, p3])}" fill="#ffffff"/>'
    if kind == "docs":
        s1 = iso_prism(0, 0, 38, 48, 0, 6, cx, cy + 18, 1.0, "#475569", "#334155", "#1e293b")
        s2 = iso_prism(4, 3, 42, 51, 14, 20, cx, cy + 18, 1.0, c_top, c_left, c_right)
        s3 = iso_prism(8, 6, 46, 54, 28, 34, cx, cy + 18, 1.0, "#f8fafc", "#bae6fd", c_top)
        return "\n".join([s1, s2, s3])
    if kind == "keycap":
        base = iso_prism(0, 0, 50, 50, 0, 16, cx, cy + 20, 1.0, "#1e293b", "#0f172a", "#020617", c_top, 1.0)
        cap = iso_prism(7, 7, 43, 43, 16, 34, cx, cy + 20, 1.0, c_top, c_left, c_right, "#fef08a", 1.0)
        pt = iso(25, 25, 34, cx, cy + 20, 1.0)
        return base + "\n" + cap + f'\n<text x="{pt[0]:.1f}" y="{pt[1] + 4:.1f}" text-anchor="middle" font-family="{FONT_MONO}" font-size="13" font-weight="900" fill="#090d16">A</text>'
    if kind == "shield":
        outer = iso_prism(0, 0, 46, 46, 0, 34, cx, cy + 22, 1.0, c_top, c_left, c_right, "#bbf7d0", 0.9)
        top_core = iso_prism(13, 13, 33, 33, 34, 46, cx, cy + 22, 1.0, "#f8fafc", "#34d399", "#059669", "#ffffff", 0.9)
        return outer + "\n" + top_core
    if kind == "compass":
        base = iso_prism(4, 4, 44, 44, 0, 10, cx, cy + 24, 1.0, c_top, c_left, c_right, "#fde68a", 0.9)
        orb_c = iso(24, 24, 34, cx, cy + 24, 1.0)
        return (
            base
            + f'\n<circle cx="{orb_c[0]:.1f}" cy="{orb_c[1]:.1f}" r="18" fill="#0f172a" stroke="{c_top}" stroke-width="2"/>'
            + f'\n<path d="M {orb_c[0]+4:.1f},{orb_c[1]-11:.1f} A 11,11 0 1,0 {orb_c[0]+4:.1f},{orb_c[1]+11:.1f} A 8.5,10 0 1,1 {orb_c[0]+4:.1f},{orb_c[1]-11:.1f} Z" fill="#fef08a"/>'
        )
    outer = iso_prism(0, 0, 46, 46, 0, 40, cx, cy + 22, 1.0, "rgba(168,85,247,0.38)", "rgba(126,34,206,0.6)", "rgba(88,28,135,0.7)", "#e9d5ff", 1.1)
    inner = iso_prism(13, 13, 33, 33, 12, 28, cx, cy + 22, 1.0, "#38bdf8", "#0284c7", "#0369a1", "#ffffff", 0.9)
    return outer + "\n" + inner


def build_project_card(spec: dict) -> str:
    W, H = 560, 215
    c1, c2, c3 = spec["colors"]
    d = 10
    card_w, card_h = W - 26, H - 24
    x0, y0 = 8, 8

    pills = []
    px = x0 + 26
    py = y0 + card_h - 42
    for tech in spec["stack"]:
        pw = max(62, len(tech) * 7.6 + 22)
        pills.append(
            f'<rect x="{px:.1f}" y="{py}" width="{pw:.1f}" height="24" rx="6" fill="#0b1326" '
            f'stroke="{c1}" stroke-width="0.9" stroke-opacity="0.5"/>'
            f'<text x="{px + pw / 2:.1f}" y="{py + 15.5}" text-anchor="middle" font-family="{FONT_MONO}" '
            f'font-size="10.2" font-weight="700" fill="#e2e8f0">{esc(tech)}</text>'
        )
        px += pw + 8

    emblem = render_mini_3d_icon(spec["icon"], x0 + card_w - 72, y0 + 84, c1, c2, c3)
    tag_w = len(spec["tag"]) * 7.8 + 28

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="{esc(spec['title'])} 3D Project Card">
  <defs>
    <linearGradient id="bg_{spec['id']}" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#080e1e"/>
      <stop offset="100%" stop-color="#0e172e"/>
    </linearGradient>
    <radialGradient id="glow_{spec['id']}" cx="86%" cy="38%" r="48%">
      <stop offset="0%" stop-color="{c1}" stop-opacity="0.22"/>
      <stop offset="100%" stop-color="{c1}" stop-opacity="0"/>
    </radialGradient>
  </defs>

  <rect x="{x0 + 12}" y="{y0 + 14}" width="{card_w}" height="{card_h}" rx="15" fill="#010308" opacity="0.82"/>
  <polygon points="{x0 + 10},{y0 + card_h} {x0 + card_w - 6},{y0 + card_h} {x0 + card_w + d - 6},{y0 + card_h + d} {x0 + d + 10},{y0 + card_h + d}"
    fill="{c3}" opacity="0.9"/>
  <polygon points="{x0 + card_w},{y0 + 10} {x0 + card_w + d},{y0 + d + 10} {x0 + card_w + d},{y0 + card_h + d - 6} {x0 + card_w},{y0 + card_h - 6}"
    fill="{c2}" opacity="0.92"/>

  <rect x="{x0}" y="{y0}" width="{card_w}" height="{card_h}" rx="14" fill="url(#bg_{spec['id']})"
    stroke="{c1}" stroke-width="1.3" stroke-opacity="0.72"/>
  <rect x="{x0}" y="{y0}" width="{card_w}" height="{card_h}" rx="14" fill="url(#glow_{spec['id']})"/>

  <rect x="{x0 + 24}" y="{y0 + 1}" width="110" height="3" rx="1.5" fill="{c1}"/>

  <rect x="{x0 + 26}" y="{y0 + 20}" width="{tag_w:.1f}" height="21" rx="10.5"
    fill="{c1}" fill-opacity="0.14" stroke="{c1}" stroke-width="0.8" stroke-opacity="0.6"/>
  <text x="{x0 + 26 + tag_w / 2:.1f}" y="{y0 + 34}" text-anchor="middle" font-family="{FONT_MONO}" font-size="9.6" font-weight="800"
    letter-spacing="1.0" fill="{c1}">{esc(spec['tag'])}</text>

  <text x="{x0 + 26}" y="{y0 + 68}" font-family="{FONT_SANS}" font-size="24" font-weight="800" fill="#f8fafc">{esc(spec['title'])}</text>
  <text x="{x0 + 26}" y="{y0 + 94}" font-family="{FONT_SANS}" font-size="12.6" fill="#cbd5e1">{esc(spec['line1'])}</text>
  <text x="{x0 + 26}" y="{y0 + 113}" font-family="{FONT_SANS}" font-size="12.6" fill="#94a3b8">{esc(spec['line2'])}</text>

  {''.join(pills)}

  <g>
    <animateTransform attributeName="transform" type="translate"
      values="0 0; 0 -4; 0 0" begin="{spec['phase']:.1f}s" dur="4s" repeatCount="indefinite"/>
    {emblem}
  </g>
</svg>'''


# ---------------------------------------------------------------------------
# 4. 3D ISOMETRIC CONTRIBUTION SKYLINE (1200 x 430)
# ---------------------------------------------------------------------------

def build_skyline_3d(stats: dict) -> str:
    W, H = 1200, 430
    weeks = stats["weeks"]
    s = stats["stats"]
    days_flat = [d for w in weeks for d in w["contributionDays"]]
    max_day = max(days_flat, key=lambda d: d["contributionCount"])
    max_cnt = max(1, max_day["contributionCount"])

    longest_streak = 0
    cur = 0
    for d in days_flat:
        if d["contributionCount"] > 0:
            cur += 1
            longest_streak = max(longest_streak, cur)
        else:
            cur = 0

    # Flatter dimetric-isometric angle (sy = 0.25) so all 53 weeks span cleanly inside 1200x430!
    cell = 16.0
    sy = 0.25
    ox, oy = 215.0, 140.0

    # Thin sleek deck base (-0.9 units = ~14px)
    deck = iso_prism(
        -0.6, -0.6, len(weeks) + 0.1, 7.5, -0.9, 0.0, ox, oy, cell,
        c_top="#0b1324", c_left="#091020", c_right="#050a15",
        stroke="#1e293b", stroke_w=1.1, opacity=0.98, sy=sy
    )

    cells = []
    for w_idx, w in enumerate(weeks):
        for d_idx, day in enumerate(w["contributionDays"]):
            cells.append((w_idx + d_idx, w_idx, d_idx, day["contributionCount"], day["date"]))
    cells.sort(key=lambda item: (item[0], item[1]))

    pillars = [deck]
    peak_beacon = ""
    for _, w_idx, d_idx, cnt, date_str in cells:
        u0, v0 = w_idx + 0.14, d_idx + 0.14
        u1, v1 = w_idx + 0.86, d_idx + 0.86

        if cnt == 0:
            t00 = iso(u0, v0, 0.08, ox, oy, cell, sy)
            t10 = iso(u1, v0, 0.08, ox, oy, cell, sy)
            t11 = iso(u1, v1, 0.08, ox, oy, cell, sy)
            t01 = iso(u0, v1, 0.08, ox, oy, cell, sy)
            pillars.append(
                f'<polygon points="{fmt_pts([t00, t10, t11, t01])}" fill="#111c33" stroke="#1e293b" stroke-width="0.45"/>'
            )
            continue

        h_units = 0.65 + ((cnt / max_cnt) ** 0.56) * 8.2

        if cnt >= 30:
            ct, cl, cr, st = "#6ee7b7", "#10b981", "#047857", "#ecfdf5"
        elif cnt >= 12:
            ct, cl, cr, st = "#a78bfa", "#7c3aed", "#4c1d95", "#ddd6fe"
        elif cnt >= 4:
            ct, cl, cr, st = "#38bdf8", "#0284c7", "#075985", "#bae6fd"
        else:
            ct, cl, cr, st = "#22d3ee", "#0e7490", "#164e63", "#67e8f9"

        pillars.append(
            iso_prism(u0, v0, u1, v1, 0.0, h_units, ox, oy, cell, ct, cl, cr, stroke=st, stroke_w=0.6, sy=sy)
        )

        if date_str == max_day["date"]:
            top_c = iso((u0 + u1) * 0.5, (v0 + v1) * 0.5, h_units, ox, oy, cell, sy)
            peak_beacon = f'''<g>
  <line x1="{top_c[0]:.1f}" y1="{top_c[1]:.1f}" x2="{top_c[0]:.1f}" y2="{top_c[1] - 54:.1f}"
    stroke="#6ee7b7" stroke-width="1.8" stroke-dasharray="3 3"/>
  <circle cx="{top_c[0]:.1f}" cy="{top_c[1]:.1f}" r="4.5" fill="#6ee7b7">
    <animate attributeName="r" values="4;7.5;4" dur="2s" repeatCount="indefinite"/>
    <animate attributeName="opacity" values="1;0.35;1" dur="2s" repeatCount="indefinite"/>
  </circle>
  <rect x="{top_c[0] - 88:.1f}" y="{top_c[1] - 78:.1f}" width="176" height="26" rx="7"
    fill="#064e3b" stroke="#6ee7b7" stroke-width="1.1"/>
  <text x="{top_c[0]:.1f}" y="{top_c[1] - 61:.1f}" text-anchor="middle" font-family="{FONT_MONO}"
    font-size="10.5" font-weight="800" fill="#ecfdf5">PEAK: {cnt} ON {date_str}</text>
</g>'''

    month_marks = []
    seen_months = set()
    for w_idx, w in enumerate(weeks):
        if not w["contributionDays"]:
            continue
        dt = w["contributionDays"][0]["date"]
        ym = dt[:7]
        if ym not in seen_months and w_idx % 4 == 0:
            seen_months.add(ym)
            pt = iso(w_idx + 0.5, 8.8, -0.5, ox, oy, cell, sy)
            month_name = {
                "01": "JAN", "02": "FEB", "03": "MAR", "04": "APR", "05": "MAY", "06": "JUN",
                "07": "JUL", "08": "AUG", "09": "SEP", "10": "OCT", "11": "NOV", "12": "DEC"
            }.get(dt[5:7], dt[5:7])
            month_marks.append(
                f'<text x="{pt[0]:.1f}" y="{pt[1]:.1f}" font-family="{FONT_MONO}" font-size="9.5" '
                f'font-weight="700" fill="#64748b">{month_name}</text>'
            )

    hud = [
        (f"{s['total_contributions']}", "12-MO CONTRIBUTIONS", "#38bdf8"),
        (f"{s['commits']}", "COMMITS", "#818cf8"),
        (f"{s['pull_requests']}", "PULL REQUESTS", "#a855f7"),
        (f"{max_day['contributionCount']}", "PEAK DAY", "#34d399"),
        (f"{longest_streak} DAYS", "BEST STREAK", "#fbbf24"),
    ]
    hud_svgs = []
    for i, (val, lbl, col) in enumerate(hud):
        hx = 36 + i * 165
        hy = 58
        hud_svgs.append(f'''<g>
  <rect x="{hx}" y="{hy}" width="152" height="54" rx="10" fill="#0b1326" fill-opacity="0.92"
    stroke="{col}" stroke-width="1" stroke-opacity="0.55"/>
  <text x="{hx + 14}" y="{hy + 26}" font-family="{FONT_SANS}" font-size="20" font-weight="800" fill="#f8fafc">{esc(val)}</text>
  <text x="{hx + 14}" y="{hy + 43}" font-family="{FONT_MONO}" font-size="9" font-weight="700" letter-spacing="0.9" fill="{col}">{esc(lbl)}</text>
</g>''')

    tiers = [
        ("0", "#111c33"),
        ("1–3", "#22d3ee"),
        ("4–11", "#38bdf8"),
        ("12–29", "#a78bfa"),
        ("30+", "#6ee7b7"),
    ]
    legend = []
    lx = 36
    ly = H - 26
    legend.append(f'<text x="{lx}" y="{ly}" font-family="{FONT_MONO}" font-size="10" font-weight="700" fill="#64748b">INTENSITY:</text>')
    lx += 78
    for label, col in tiers:
        legend.append(f'<rect x="{lx}" y="{ly - 10}" width="12" height="12" rx="2.5" fill="{col}" stroke="#334155" stroke-width="0.6"/>')
        legend.append(f'<text x="{lx + 17}" y="{ly}" font-family="{FONT_MONO}" font-size="10" fill="#94a3b8">{label}</text>')
        lx += 62

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="3D Isometric GitHub Contribution Skyline">
  <defs>
    <linearGradient id="skyBg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#050914"/>
      <stop offset="100%" stop-color="#0a1328"/>
    </linearGradient>
    <linearGradient id="skyBorder" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#38bdf8" stop-opacity="0.65"/>
      <stop offset="50%" stop-color="#a855f7" stop-opacity="0.5"/>
      <stop offset="100%" stop-color="#34d399" stop-opacity="0.7"/>
    </linearGradient>
  </defs>

  <rect x="8" y="8" width="{W - 12}" height="{H - 12}" rx="18" fill="#02040a" opacity="0.82"/>
  <rect x="4" y="4" width="{W - 12}" height="{H - 12}" rx="18" fill="url(#skyBg)" stroke="url(#skyBorder)" stroke-width="1.4"/>

  <text x="36" y="40" font-family="{FONT_MONO}" font-size="13" font-weight="800" letter-spacing="2" fill="#38bdf8">
    03 // 3D ISOMETRIC CONTRIBUTION SKYLINE (53 WEEKS × 7 DAYS)
  </text>

  {''.join(hud_svgs)}
  {''.join(pillars)}
  {peak_beacon}
  {''.join(month_marks)}
  {''.join(legend)}

  <text x="{W - 36}" y="{H - 26}" text-anchor="end" font-family="{FONT_MONO}" font-size="10" fill="#64748b">
    LIVE GRAPHQL TELEMETRY  ·  @ANONYMUSAGENT
  </text>
</svg>'''


# ---------------------------------------------------------------------------
# 5. 3D ENGINEERING PIPELINE & HORIZON FOOTER (1200 x 235)
# ---------------------------------------------------------------------------

def build_workflow_3d() -> str:
    W, H = 1200, 235
    steps = [
        ("01 // ARCHITECT", "System Design & Schema", "PostgreSQL · Drizzle · APIs", "#38bdf8", "#0284c7", "#075985", 0.0),
        ("02 // ENGINEER", "Full-Stack TypeScript", "Next.js 16 · Expo · Tailwind", "#818cf8", "#4f46e5", "#312e81", 0.5),
        ("03 // VERIFY", "Automated Quality Gates", "Vitest · Playwright · Biome", "#a855f7", "#7e22ce", "#581c87", 1.0),
        ("04 // SHIP", "Production Launch", "Vercel · Neon · Mobile Builds", "#34d399", "#059669", "#065f46", 1.5),
    ]

    nodes = [
        '<line x1="170" y1="108" x2="1030" y2="108" stroke="#1e293b" stroke-width="4" stroke-linecap="round"/>',
        '''<line x1="170" y1="108" x2="1030" y2="108" stroke="url(#flowGrad)" stroke-width="2.2"
  stroke-dasharray="14 10" stroke-linecap="round">
  <animate attributeName="stroke-dashoffset" from="48" to="0" dur="1.6s" repeatCount="indefinite"/>
</line>''',
    ]

    for i, (title, sub1, sub2, c1, c2, c3, phase) in enumerate(steps):
        x0 = 38 + i * 286
        y0 = 58
        cw, ch, d = 262, 102, 8
        nodes.append(
            f'<rect x="{x0 + 9}" y="{y0 + 10}" width="{cw}" height="{ch}" rx="12" fill="#010308" opacity="0.8"/>'
        )
        nodes.append(f'''<g>
  <animateTransform attributeName="transform" type="translate"
    values="0 0; 0 -4; 0 0" begin="{phase:.1f}s" dur="3.8s" repeatCount="indefinite"/>
  <polygon points="{x0 + 8},{y0 + ch} {x0 + cw - 4},{y0 + ch} {x0 + cw + d - 4},{y0 + ch + d} {x0 + d + 8},{y0 + ch + d}" fill="{c3}" opacity="0.9"/>
  <polygon points="{x0 + cw},{y0 + 8} {x0 + cw + d},{y0 + d + 8} {x0 + cw + d},{y0 + ch + d - 4} {x0 + cw},{y0 + ch - 4}" fill="{c2}" opacity="0.92"/>
  <rect x="{x0}" y="{y0}" width="{cw}" height="{ch}" rx="12" fill="#0b1325" stroke="{c1}" stroke-width="1.2" stroke-opacity="0.72"/>
  <rect x="{x0 + 18}" y="{y0 + 1}" width="84" height="3" rx="1.5" fill="{c1}"/>
  <text x="{x0 + 18}" y="{y0 + 30}" font-family="{FONT_MONO}" font-size="11.2" font-weight="800" letter-spacing="1.2" fill="{c1}">{esc(title)}</text>
  <text x="{x0 + 18}" y="{y0 + 57}" font-family="{FONT_SANS}" font-size="15" font-weight="800" fill="#f8fafc">{esc(sub1)}</text>
  <text x="{x0 + 18}" y="{y0 + 80}" font-family="{FONT_MONO}" font-size="10.2" fill="#94a3b8">{esc(sub2)}</text>
</g>''')

    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="3D Engineering Delivery Pipeline">
  <defs>
    <linearGradient id="wfBg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#050814"/>
      <stop offset="100%" stop-color="#0b1326"/>
    </linearGradient>
    <linearGradient id="flowGrad" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0%" stop-color="#38bdf8"/>
      <stop offset="35%" stop-color="#818cf8"/>
      <stop offset="70%" stop-color="#a855f7"/>
      <stop offset="100%" stop-color="#34d399"/>
    </linearGradient>
  </defs>

  <rect x="8" y="8" width="{W - 12}" height="{H - 12}" rx="18" fill="#02040a" opacity="0.82"/>
  <rect x="4" y="4" width="{W - 12}" height="{H - 12}" rx="18" fill="url(#wfBg)" stroke="url(#flowGrad)" stroke-width="1.3" stroke-opacity="0.7"/>

  <text x="38" y="38" font-family="{FONT_MONO}" font-size="13" font-weight="800" letter-spacing="2" fill="#818cf8">
    04 // SPATIAL ENGINEERING PIPELINE
  </text>

  {''.join(nodes)}

  <text x="{W / 2}" y="{H - 22}" text-anchor="middle" font-family="{FONT_MONO}" font-size="11" letter-spacing="1.6" fill="#64748b">
    DESIGNED &amp; ENGINEERED BY ALI MUKHTAR (@ANONYMUSAGENT)  ·  WEB LOOM STUDIO
  </text>
</svg>'''


# ---------------------------------------------------------------------------
# Flagship Project Definitions (100% verified from AnonymusAgent repos)
# ---------------------------------------------------------------------------

PROJECT_CARDS = [
    {
        "id": "webloom",
        "filename": "card-webloom.svg",
        "title": "Webloom Studio",
        "tag": "LIVE STUDIO PLATFORM",
        "line1": "Full-stack digital product studio with interactive",
        "line2": "estimator, blog, analytics & protected admin CMS.",
        "stack": ["Next.js", "TypeScript", "Drizzle", "PostgreSQL"],
        "colors": ("#38bdf8", "#0284c7", "#075985"),
        "icon": "layers",
        "phase": 0.0,
    },
    {
        "id": "bloomar",
        "filename": "card-bloomar.svg",
        "title": "Bloom-AR Manager",
        "tag": "ENTERPRISE HEALTHCARE",
        "line1": "Medical billing AR system · 27 UI pages, 57 APIs,",
        "line2": "40 DB tables & 272 CARC/RARC ICD-10 denial codes.",
        "stack": ["Next.js", "PostgreSQL", "ICD-10", "Drizzle"],
        "colors": ("#34d399", "#059669", "#065f46"),
        "icon": "bars",
        "phase": 0.4,
    },
    {
        "id": "veltrio",
        "filename": "card-veltrio.svg",
        "title": "VELTRIO Video Hub",
        "tag": "STREAMING & STUDIO",
        "line1": "Cinematic video platform with HTTP range streaming,",
        "line2": "direct uploads, viewer accounts & admin studio.",
        "stack": ["Next.js", "Mux Video", "Vercel Blob", "Neon Auth"],
        "colors": ("#fb7185", "#e11d48", "#881337"),
        "icon": "cinema",
        "phase": 0.8,
    },
    {
        "id": "pdfpro",
        "filename": "card-pdfpro.svg",
        "title": "PDF Pro Suite",
        "tag": "DOCUMENTS & OCR",
        "line1": "Browser PDF editor, Office converter, Tesseract OCR",
        "line2": "& Manifest V3 extension with S3 + PostgreSQL.",
        "stack": ["Next.js", "PDF.js", "Tesseract", "AWS S3"],
        "colors": ("#60a5fa", "#2563eb", "#1e3a8a"),
        "icon": "docs",
        "phase": 1.2,
    },
    {
        "id": "typearena",
        "filename": "card-typearena.svg",
        "title": "Type Arena",
        "tag": "COMPETITIVE GAMING",
        "line1": "Multiplayer typing-game arena featuring racing,",
        "line2": "XP progression, 3D-styled scenes & leaderboards.",
        "stack": ["Next.js 16", "Tailwind 4", "Drizzle", "Playwright"],
        "colors": ("#fbbf24", "#d97706", "#78350f"),
        "icon": "keycap",
        "phase": 1.6,
    },
    {
        "id": "bloomrcm",
        "filename": "card-bloomrcm.svg",
        "title": "Bloom RCM",
        "tag": "REVENUE CYCLE CONSOLE",
        "line1": "Healthcare medical billing portal & admin console",
        "line2": "with lead pipeline, accessibility tools & CMS.",
        "stack": ["Next.js 16", "React 19", "Neon DB", "Zod"],
        "colors": ("#2dd4bf", "#0d9488", "#115e59"),
        "icon": "shield",
        "phase": 2.0,
    },
    {
        "id": "noor",
        "filename": "card-noor.svg",
        "title": "Noor (IslamicGuide)",
        "tag": "CROSS-PLATFORM MOBILE",
        "line1": "iOS, Android & Web companion with all 114 surahs,",
        "line2": "Qibla magnetometer compass, audio & GPS prayers.",
        "stack": ["Expo", "React Native", "TypeScript", "Router"],
        "colors": ("#f59e0b", "#b45309", "#78350f"),
        "icon": "compass",
        "phase": 2.4,
    },
    {
        "id": "bloomai",
        "filename": "card-bloomai.svg",
        "title": "BloomAI Workspace",
        "tag": "IDEA & BRIEF STUDIO",
        "line1": "Collaborative workspace for drafting, attaching",
        "line2": "references & exporting structured website briefs.",
        "stack": ["React 18", "Vite", "Supabase", "Tailwind"],
        "colors": ("#c084fc", "#9333ea", "#581c87"),
        "icon": "ai",
        "phase": 2.8,
    },
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="Refresh data/github_stats.json from GitHub API")
    args = parser.parse_args()

    stats = load_stats(refresh=args.refresh)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    outputs = {
        "hero-3d.svg": build_hero_3d(stats),
        "stack-3d.svg": build_stack_3d(stats),
        "skyline-3d.svg": build_skyline_3d(stats),
        "workflow-3d.svg": build_workflow_3d(),
    }
    for card in PROJECT_CARDS:
        outputs[card["filename"]] = build_project_card(card)

    for fname, svg in outputs.items():
        path = ASSETS_DIR / fname
        path.write_text(svg, encoding="utf-8")
        print(f"Generated {path.relative_to(ROOT)} ({len(svg):,} bytes)")


if __name__ == "__main__":
    main()
