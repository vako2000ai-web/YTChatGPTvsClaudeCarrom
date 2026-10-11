"""One geometry/physics contract used by the renderer, engine and both agents."""
import math

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
