"""Cosmetic board themes and cached supersampled carrom disc artwork."""
from datetime import date
from pathlib import Path
import math
import random
import sys

THEMES = {
    'classic_maple': ('Классический клён', (133, 86, 47), (128, 69, 43)),
    'ivory_walnut': ('Слоновая кость', (74, 48, 35), (111, 73, 43)),
    'arctic_silver': ('Арктический серебристый', (54, 69, 83), (63, 89, 107)),
    'golden_oak': ('Золотой дуб', (126, 83, 38), (121, 76, 33)),
    'rosewood_pearl': ('Розовое дерево и жемчуг', (104, 45, 39), (136, 66, 48)),
    'lagoon_graphite': ('Лагуна и графит', (43, 67, 73), (47, 97, 103)),
    'halloween': ('Halloween', (55, 33, 68), (117, 64, 35)),
    'new_year': ('Новый год', (36, 53, 90), (60, 91, 124)),
    'christmas': ('Рождество', (38, 69, 48), (114, 51, 43)),
}
HOLIDAYS = frozenset(('halloween', 'new_year', 'christmas'))


def seasonal_themes(today=None):
    today = today or date.today()
    day = (today.month, today.day)
    result = []
    if (10, 1) <= day <= (11, 2):
        result.append('halloween')
    if day >= (12, 20) or day <= (1, 10):
        result.append('new_year')
    if day >= (12, 15) or day <= (1, 7):
        result.append('christmas')
    return result


def choose_theme(previous=None, season='calendar', today=None, rng=None):
    if season not in ('calendar', 'all'):
        raise ValueError('Unknown board season mode')
    choices = list(THEMES) if season == 'all' else [t for t in THEMES if t not in HOLIDAYS] + seasonal_themes(today)
    choices = [t for t in choices if t != previous] or choices
    return (rng or random.SystemRandom()).choice(choices)


def assets_root():
    base = Path(__file__).resolve().parent
    return base / 'assets' if (base / 'assets').is_dir() else Path(getattr(sys, '_MEIPASS', base)) / 'assets'


class Artwork:
    def __init__(self, pygame):
        self.pg = pygame
        self.boards = {}
        self.discs = {}
        self.shadows = {}

    def board(self, theme):
        if theme not in self.boards:
            # Theme IDs come from the fixed catalog, never a user-supplied path.
            if theme not in THEMES:
                raise ValueError('Unknown board theme')
            image = self.pg.image.load(str(assets_root() / 'boards' / (theme + '.png'))).convert()
            self.boards[theme] = self.pg.transform.smoothscale(image, (674, 674))
        return self.boards[theme]

    def disc(self, kind, radius):
        key = (kind, round(radius, 3))
        if key not in self.discs:
            pg = self.pg
            scale = 4
            size = math.ceil(radius * 2 + 4)
            surface = pg.Surface((size * scale, size * scale), pg.SRCALPHA)
            centre = (size * scale // 2, size * scale // 2)
            outer = round(radius * scale)
            palettes = {
                'white': ((150, 126, 92), (252, 245, 218), (227, 205, 158)),
                'black': ((12, 16, 22), (76, 84, 94), (161, 137, 94)),
                'queen': ((97, 19, 42), (235, 78, 103), (255, 162, 160)),
                'striker': ((16, 64, 86), (91, 207, 225), (211, 249, 246)),
            }
            edge, face, ring = palettes[kind]
            pg.draw.circle(surface, edge, centre, outer)
            for r in range(max(1, outer - scale), 0, -1):
                light = .76 + .24 * (1 - r / outer)
                color = tuple(round(c * light) for c in face)
                pg.draw.circle(surface, color, (centre[0] - scale // 2, centre[1] - scale // 2), r)
            pg.draw.circle(surface, ring, centre, max(1, outer - 3 * scale), max(1, scale // 2))
            pg.draw.circle(surface, ring, centre, max(1, outer - 5 * scale), max(1, scale // 3))
            # Restrained glossy highlight; avoids covering the coin colour.
            highlight = pg.Surface(surface.get_size(), pg.SRCALPHA)
            pg.draw.ellipse(highlight, (255, 255, 255, 75),
                (centre[0] - outer * .62, centre[1] - outer * .65, outer * .85, outer * .27))
            surface.blit(highlight, (0, 0))
            self.discs[key] = pg.transform.smoothscale(surface, (size, size))
        return self.discs[key]

    def shadow(self, radius):
        key = round(radius, 3)
        if key not in self.shadows:
            size = math.ceil(radius * 2 + 12)
            surface = self.pg.Surface((size * 2, size * 2), self.pg.SRCALPHA)
            centre = (size, size)
            outer = round((radius + 5) * 2)
            for r in range(outer, 0, -1):
                alpha = round(48 * (1 - r / outer))
                self.pg.draw.circle(surface, (20, 15, 20, alpha), centre, r)
            self.shadows[key] = self.pg.transform.smoothscale(surface, (size, size))
        return self.shadows[key]
