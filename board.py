"""One geometry/physics contract used by the renderer, engine and both agents."""
import math
from dataclasses import dataclass

SIZE = 760
POCKETS = ((65, 65), (695, 65), (65, 695), (695, 695))
POCKET_R = 26
COIN_R = 12
STRIKER_R = 16
BASE_X = (265, 495)
BASE_Y = (665, 95)
DT = 1 / 240
MAX_SPEED = 1050
DECELERATION = 100
STOP_SPEED = 3
MAX_STEPS = 240 * 15
WALL_R = 7
WALL_ELASTICITY = 0.83
WALL_FRICTION = 0.27
DISC_ELASTICITY = 0.90
DISC_FRICTION = 0.35
STRIKER_MASS = 1.8
COIN_MASS = 1
WALLS = (((110, 65), (650, 65)), ((110, 695), (650, 695)),
         ((65, 110), (65, 650)), ((695, 110), (695, 650)))
PLAYERS = ('ChatGPT', 'Claude')
COLORS = ('white', 'black')


def initial_coins():
    positions = [(380, 380)]
    for ring in (1, 2):
        for i in range(ring * 6):
            angle = 2 * math.pi * i / (ring * 6)
            positions.append((380 + ring * 25 * math.cos(angle),
                              380 + ring * 25 * math.sin(angle)))
    kinds = ['queen'] + ['white', 'black'] * 9
    return [(i, kind, pos) for i, (kind, pos) in enumerate(zip(kinds, positions))]


def contract():
    return {'size': SIZE, 'pockets': [list(p) for p in POCKETS], 'pocket_radius': POCKET_R,
            'coin_radius': COIN_R, 'striker_radius': STRIKER_R,
            'baseline_x': list(BASE_X), 'baseline_y': list(BASE_Y),
            'walls': [[list(a), list(b)] for a, b in WALLS],
            'wall_radius': WALL_R, 'wall_elasticity': WALL_ELASTICITY,
            'wall_friction': WALL_FRICTION, 'disc_elasticity': DISC_ELASTICITY,
            'disc_friction': DISC_FRICTION, 'striker_mass': STRIKER_MASS,
            'coin_mass': COIN_MASS, 'maximum_speed': MAX_SPEED,
            'deceleration': DECELERATION, 'fixed_dt': DT,
            'coordinates': 'pixels, origin top left; angle 0 right, 90 down, 270 up'}


@dataclass(frozen=True)
class Geometry:
    name: str = 'house-v0.2'
    coin_radius: float = COIN_R
    striker_radius: float = STRIKER_R
    coin_mass: float = COIN_MASS
    striker_mass: float = STRIKER_MASS
    pocket_radius: float = POCKET_R
    baseline_y: tuple = BASE_Y
    legal_intervals: tuple = (BASE_X,)
    outer_radius: float = 75
    centre_radius: float = 12
    walls: tuple = WALLS
    baseline_ends: tuple = (250, 510)

    def snapshot(self, seats=(0, 1)):
        data = contract()
        data.update(geometry=self.name, coin_radius=self.coin_radius, striker_radius=self.striker_radius,
                    coin_mass=self.coin_mass, striker_mass=self.striker_mass, pocket_radius=self.pocket_radius,
                    baseline_y=list(self.baseline_y), baseline_x=[self.legal_intervals[0][0], self.legal_intervals[-1][-1]],
                    baseline_by_player=[self.baseline_y[s] for s in seats],
                    legal_x_intervals=[list(interval) for interval in self.legal_intervals],
                    baseline_ends=list(self.baseline_ends),
                    outer_radius=self.outer_radius, centre_radius=self.centre_radius,
                    walls=[[list(a), list(b)] for a, b in self.walls])
        return data

    @classmethod
    def from_snapshot(cls, data):
        return cls(data['geometry'], data['coin_radius'], data['striker_radius'],
                   data['coin_mass'], data['striker_mass'], data['pocket_radius'],
                   tuple(data['baseline_y']), tuple(tuple(v) for v in data['legal_x_intervals']),
                   data['outer_radius'], data['centre_radius'],
                   tuple(tuple(tuple(p) for p in wall) for wall in data['walls']),
                   tuple(data.get('baseline_ends', (250, 510))))


def official_geometry():
    # 735 mm playing surface scaled to 630 px. All equipment inside standard ranges.
    scale = 630 / 735
    coin_r, striker_r = 15.5 * scale, 20.65 * scale
    circle_r = 15.9 * scale
    left = 65 + (630 - 470 * scale) / 2
    right = 760 - left
    upper_y = 65 + (101.5 + 15.9) * scale
    circle_margin = striker_r - circle_r
    legal = ((left - circle_margin, left + circle_margin),
             (left + circle_r + striker_r, right - circle_r - striker_r),
             (right - circle_margin, right + circle_margin))
    return Geometry('icf-735mm', coin_r, striker_r, 5.4, 15, 22.25 * scale,
                    (760 - upper_y, upper_y), legal, 85 * scale, 15.9 * scale,
                    (((105, 65), (655, 65)), ((105, 695), (655, 695)),
                     ((65, 105), (65, 655)), ((695, 105), (695, 655))), (left, right))


def official_coins(radius):
    # Hexagonal close packing, queen in centre, alternating colours with white Y.
    points = []
    for q in range(-2, 3):
        for r in range(-2, 3):
            ring = max(abs(q), abs(r), abs(q + r))
            if ring <= 2:
                x = 2 * radius * (q + r / 2)
                y = math.sqrt(3) * radius * r
                points.append((ring, math.atan2(y, x) % (2 * math.pi), x, y))
    points.sort()
    coins, counter = [], {1: 0, 2: 0}
    for i, (ring, _, x, y) in enumerate(points):
        if ring == 0:
            kind = 'queen'
        else:
            kind = 'white' if counter[ring] % 2 == 0 else 'black'
            counter[ring] += 1
        coins.append((i, kind, (380 + x, 380 + y)))
    return coins
