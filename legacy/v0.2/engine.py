"""Pymunk simulation without any display or network dependency."""
import math
import pymunk
from board import (BASE_X, BASE_Y, COIN_R, STRIKER_R, DT, MAX_SPEED,
                   DECELERATION, STOP_SPEED, MAX_STEPS, WALLS, POCKETS,
                   POCKET_R, PLAYERS, contract, initial_coins, WALL_R,
                   WALL_ELASTICITY, WALL_FRICTION, DISC_ELASTICITY, DISC_FRICTION,
                   STRIKER_MASS, COIN_MASS)
from rules import Rules


class Board:
    def __init__(self):
        self.space = pymunk.Space()
        self.space.gravity = (0, 0)
        self.space.iterations = 20
        self.discs = {}
        self.kinds = {i: kind for i, kind, _ in initial_coins()}
        for a, b in WALLS:
            wall = pymunk.Segment(self.space.static_body, a, b, WALL_R)
            wall.elasticity = WALL_ELASTICITY
            wall.friction = WALL_FRICTION
            self.space.add(wall)
        for coin_id, kind, pos in initial_coins():
            self.add_disc(coin_id, kind, pos)
        self.active = False
        self.steps = 0
        self.still_steps = 0
        self.pocketed = []
        self.timed_out = False

    @staticmethod
    def velocity(body, gravity, damping, dt):
        pymunk.Body.update_velocity(body, gravity, damping, dt)
        speed = body.velocity.length
        if speed:
            body.velocity *= max(0, speed - DECELERATION * dt) / speed
        body.angular_velocity *= max(0, 1 - 3 * dt)

    def add_disc(self, coin_id, kind, pos):
        radius = STRIKER_R if kind == 'striker' else COIN_R
        mass = STRIKER_MASS if kind == 'striker' else COIN_MASS
        body = pymunk.Body(mass, pymunk.moment_for_circle(mass, 0, radius))
        body.position = pos
        body.velocity_func = self.velocity
        shape = pymunk.Circle(body, radius)
        shape.elasticity = DISC_ELASTICITY
        shape.friction = DISC_FRICTION
        self.space.add(body, shape)
        self.discs[coin_id] = {'body': body, 'shape': shape, 'type': kind, 'radius': radius}
        return body

    def remove(self, coin_id):
        disc = self.discs.pop(coin_id)
        self.space.remove(disc['shape'], disc['body'])

    def placement_allowed(self, x, player):
        return BASE_X[0] <= x <= BASE_X[1] and all(
            (d['body'].position - pymunk.Vec2d(x, BASE_Y[player])).length >=
            d['radius'] + STRIKER_R + 0.5
            for i, d in self.discs.items() if i != -1)

    def shoot(self, move, player):
        if self.active:
            raise RuntimeError('Shot still active')
        if not self.placement_allowed(move['x'], player):
            raise ValueError('Striker overlaps a coin or is outside baseline')
        self.pocketed = []
        self.steps = self.still_steps = 0
        self.timed_out = False
        body = self.add_disc(-1, 'striker', (move['x'], BASE_Y[player]))
        angle = math.radians(move['angle'])
        body.velocity = (math.cos(angle) * MAX_SPEED * move['power'],
                         math.sin(angle) * MAX_SPEED * move['power'])
        self.active = True

    def step(self):
        if not self.active:
            return
        self.space.step(DT)
        self.steps += 1
        for coin_id, disc in list(self.discs.items()):
            pos = disc['body'].position
            captured = any((pos - pymunk.Vec2d(*p)).length < POCKET_R for p in POCKETS)
            # The only openings are in the four corners. Catch escaped corner discs.
            escaped = not (0 <= pos.x <= 760 and 0 <= pos.y <= 760)
            if captured or escaped:
                self.pocketed.append((coin_id, disc['type']))
                self.remove(coin_id)
        moving = any(d['body'].velocity.length > STOP_SPEED for d in self.discs.values())
        self.still_steps = 0 if moving else self.still_steps + 1
        if self.still_steps >= 24 or self.steps >= MAX_STEPS:
            self.timed_out = self.steps >= MAX_STEPS
            for disc in self.discs.values():
                disc['body'].velocity = (0, 0)
                disc['body'].angular_velocity = 0
            if -1 in self.discs:
                self.remove(-1)
            self.active = False

    def return_coin(self, coin_id):
        # Deterministic central spiral. Never place a returned piece onto another.
        for radius in range(0, 281, 28):
            count = max(1, math.ceil(2 * math.pi * radius / 28))
            for index in range(count):
                angle = index * 2 * math.pi / count
                pos = pymunk.Vec2d(380 + radius * math.cos(angle), 380 + radius * math.sin(angle))
                if all((d['body'].position - pos).length >= d['radius'] + COIN_R + 1
                       for d in self.discs.values()):
                    self.add_disc(coin_id, self.kinds[coin_id], pos)
                    return
        raise RuntimeError('No safe return position')

    def coins(self):
        return [{'id': i, 'type': d['type'], 'x': round(d['body'].position.x, 4),
                 'y': round(d['body'].position.y, 4)}
                for i, d in sorted(self.discs.items()) if i != -1]


class Match:
    def __init__(self, max_turns=80, first_player=0):
        self.board = Board()
        self.rules = Rules(max_turns, first_player)
        self.last_resolution = None

    def state(self):
        return {'schema_version': 1, 'board': contract(), 'rules': self.rules.snapshot(),
                'player': PLAYERS[self.rules.player], 'coins': self.board.coins()}

    def _apply(self, resolution):
        for coin_id in resolution.returned:
            self.board.return_coin(coin_id)
        self.last_resolution = resolution
        return resolution

    def finish_shot(self):
        if self.board.active:
            raise RuntimeError('Wait until physics settles')
        return self._apply(self.rules.resolve(self.board.pocketed))

    def forfeit_turn(self):
        return self._apply(self.rules.resolve([], invalid=True))
