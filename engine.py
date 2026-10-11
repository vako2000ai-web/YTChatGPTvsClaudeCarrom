"""Pymunk simulation without any display or network dependency."""
import math
import pymunk
from board import (BASE_X, BASE_Y, COIN_R, STRIKER_R, DT, MAX_SPEED,
                   DECELERATION, STOP_SPEED, MAX_STEPS, WALLS, POCKETS,
                   POCKET_R, PLAYERS, contract, initial_coins, WALL_R,
                   WALL_ELASTICITY, WALL_FRICTION, DISC_ELASTICITY, DISC_FRICTION,
                   STRIKER_MASS, COIN_MASS, Geometry, official_geometry, official_coins)
from rules import Rules
from official_rules import OfficialRules


class Board:
    def __init__(self, official=False):
        self.geometry = official_geometry() if official else Geometry()
        self.official = official
        self.space = pymunk.Space()
        self.space.gravity = (0, 0)
        self.space.iterations = 20
        self.discs = {}
        rack = official_coins(self.geometry.coin_radius) if official else initial_coins()
        self.kinds = {i: kind for i, kind, _ in rack}
        for a, b in self.geometry.walls:
            wall = pymunk.Segment(self.space.static_body, a, b, WALL_R)
            wall.elasticity = WALL_ELASTICITY
            wall.friction = WALL_FRICTION
            self.space.add(wall)
        for coin_id, kind, pos in rack:
            self.add_disc(coin_id, kind, pos)
        self.sound_events = []
        self.last_sound_step = {}
        self.space.on_collision(1, 2, begin=self._contact, post_solve=self._impact)
        self.space.on_collision(1, 1, post_solve=self._impact)
        self.space.on_collision(1, 0, post_solve=self._wall_impact)
        self.space.on_collision(2, 0, post_solve=self._wall_impact)
        self.touched = False
        self.overboard = []
        self.pending_returns = []
        self.active = False
        self.steps = 0
        self.still_steps = 0
        self.pocketed = []
        self.timed_out = False

    def _contact(self, arbiter, space, data):
        self.touched = True

    def _sound_impact(self, arbiter, name):
        # Observe impulse only: callbacks never alter velocities or collision responses.
        impulse = arbiter.total_impulse.length
        if impulse < 80 or self.steps - self.last_sound_step.get(name, -100) < 6:
            return
        self.last_sound_step[name] = self.steps
        self.sound_events.append((name, min(1, impulse / 4500)))

    def _impact(self, arbiter, space, data):
        self._sound_impact(arbiter, 'impact')

    def _wall_impact(self, arbiter, space, data):
        self._sound_impact(arbiter, 'wall')

    def drain_sounds(self):
        events, self.sound_events = self.sound_events, []
        return events

    @staticmethod
    def velocity(body, gravity, damping, dt):
        pymunk.Body.update_velocity(body, gravity, damping, dt)
        speed = body.velocity.length
        if speed:
            body.velocity *= max(0, speed - DECELERATION * dt) / speed
        body.angular_velocity *= max(0, 1 - 3 * dt)

    def add_disc(self, coin_id, kind, pos):
        radius = self.geometry.striker_radius if kind == 'striker' else self.geometry.coin_radius
        mass = self.geometry.striker_mass if kind == 'striker' else self.geometry.coin_mass
        body = pymunk.Body(mass, pymunk.moment_for_circle(mass, 0, radius))
        body.position = pos
        body.velocity_func = self.velocity
        shape = pymunk.Circle(body, radius)
        shape.collision_type = 2 if kind == 'striker' else 1
        shape.elasticity = DISC_ELASTICITY
        shape.friction = DISC_FRICTION
        self.space.add(body, shape)
        self.discs[coin_id] = {'body': body, 'shape': shape, 'type': kind, 'radius': radius}
        return body

    def remove(self, coin_id):
        disc = self.discs.pop(coin_id)
        self.space.remove(disc['shape'], disc['body'])

    def placement_allowed(self, x, player):
        return any(a <= x <= b for a, b in self.geometry.legal_intervals) and all(
            (d['body'].position - pymunk.Vec2d(x, self.geometry.baseline_y[player])).length >=
            d['radius'] + self.geometry.striker_radius + 0.5
            for i, d in self.discs.items() if i != -1)

    def has_legal_placement(self, player):
        # Test continuous interval endpoints, not a sampled pixel grid (Law 142).
        candidates = [x for interval in self.geometry.legal_intervals for x in interval]
        y = self.geometry.baseline_y[player]
        for i, disc in self.discs.items():
            if i == -1:
                continue
            position = disc['body'].position
            radius = disc['radius'] + self.geometry.striker_radius + 0.5
            if abs(position.y - y) < radius:
                width = math.sqrt(radius * radius - (position.y - y) ** 2)
                candidates.extend((position.x - width - 1e-7, position.x + width + 1e-7))
        return any(self.placement_allowed(x, player) for x in candidates)

    def prepare_shot(self, move, player):
        """Place a stationary striker; physics starts only when shoot is called."""
        if self.active:
            raise RuntimeError('Shot still active')
        if not self.placement_allowed(move['x'], player):
            raise ValueError('Striker overlaps a coin or is outside baseline')
        if -1 not in self.discs:
            self.add_disc(-1, 'striker', (move['x'], self.geometry.baseline_y[player]))
        body = self.discs[-1]['body']
        body.position = (move['x'], self.geometry.baseline_y[player])
        body.velocity = (0, 0)
        body.angular_velocity = 0
        return body

    def shoot(self, move, player):
        if self.active:
            raise RuntimeError('Shot still active')
        if not self.placement_allowed(move['x'], player):
            raise ValueError('Striker overlaps a coin or is outside baseline')
        self.pocketed = []
        self.overboard = []
        self.sound_events = [('shot', .35 + .65 * move['power'])]
        self.last_sound_step = {}
        self.touched = False
        self.steps = self.still_steps = 0
        self.timed_out = False
        body = self.prepare_shot(move, player)
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
            captured = any((pos - pymunk.Vec2d(*p)).length < self.geometry.pocket_radius for p in POCKETS)
            # The only openings are in the four corners. Catch escaped corner discs.
            escaped = not (0 <= pos.x <= 760 and 0 <= pos.y <= 760)
            if captured or escaped:
                if escaped and not captured and self.official:
                    self.overboard.append((coin_id, disc['type']))
                else:
                    self.pocketed.append((coin_id, disc['type']))
                    self.sound_events.append(('pocket', 1))
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

    def return_coin(self, coin_id, kind='centre', shooter_seat=0):
        if self.official:
            # Dues fully inside outer circle, never cover the centre circle.
            g = self.geometry
            low = math.ceil(g.centre_radius + g.coin_radius + 0.1) if kind == 'due' else 0
            high = math.floor(g.outer_radius - g.coin_radius) if kind == 'due' else 150
            direction = -math.pi / 2 if shooter_seat == 0 else math.pi / 2
            for radius in range(low, high + 1, 2):
                count = max(1, math.ceil(2 * math.pi * radius / 2))
                for index in range(count):
                    angle = direction + index * 2 * math.pi / count
                    pos = pymunk.Vec2d(380 + radius * math.cos(angle), 380 + radius * math.sin(angle))
                    if all((d['body'].position - pos).length >= d['radius'] + g.coin_radius + 0.01 for d in self.discs.values()):
                        self.add_disc(coin_id, self.kinds[coin_id], pos)
                        return True
            self.pending_returns.append((coin_id, kind, shooter_seat))
            return False  # Law 79: wait for space; never place outside permitted circle.
        # Deterministic central spiral. Never place a returned piece onto another.
        for radius in range(0, 281, 28):
            count = max(1, math.ceil(2 * math.pi * radius / 28))
            for index in range(count):
                angle = index * 2 * math.pi / count
                pos = pymunk.Vec2d(380 + radius * math.cos(angle), 380 + radius * math.sin(angle))
                if all((d['body'].position - pos).length >= d['radius'] + COIN_R + 1
                       for d in self.discs.values()):
                    self.add_disc(coin_id, self.kinds[coin_id], pos)
                    return True
        raise RuntimeError('No safe return position')

    def coins(self):
        return [{'id': i, 'type': d['type'], 'x': round(d['body'].position.x, 4),
                 'y': round(d['body'].position.y, 4)}
                for i, d in sorted(self.discs.items()) if i != -1]


class Match:
    def __init__(self, max_turns=80, first_player=0, ruleset='house', game_scores=(0, 0), seats=(0, 1)):
        self.board = Board(official=ruleset != 'house')
        self.rules = (Rules(max_turns, first_player) if ruleset == 'house' else
                      OfficialRules(max_turns, first_player, game_scores, ruleset, seats))
        self.last_resolution = None

    def state(self):
        seats = getattr(self.rules, 'seats', (0, 1))
        return {'schema_version': 2, 'board': self.board.geometry.snapshot(seats), 'rules': self.rules.snapshot(),
                'player': PLAYERS[self.rules.player], 'coins': self.board.coins(),
                'pending_returns': list(self.board.pending_returns)}

    def _apply(self, resolution, shooter=None):
        shooter = getattr(self.rules, 'seats', (0, 1))[self.rules.player] if shooter is None else shooter
        for coin_id in resolution.returned:
            self.board.return_coin(coin_id, resolution.return_kinds.get(coin_id, 'centre'), shooter)
        waiting, self.board.pending_returns = self.board.pending_returns, []
        for coin_id, kind, seat in waiting:
            self.board.return_coin(coin_id, kind, seat)
        self.last_resolution = resolution
        return resolution

    def finish_shot(self):
        if self.board.active:
            raise RuntimeError('Wait until physics settles')
        shooter = getattr(self.rules, 'seats', (0, 1))[self.rules.player]
        if isinstance(self.rules, OfficialRules):
            resolution = self.rules.resolve(self.board.pocketed, touched=self.board.touched, overboard=self.board.overboard)
        else:
            resolution = self.rules.resolve(self.board.pocketed)
        return self._apply(resolution, shooter)

    def shoot(self, move):
        seat = getattr(self.rules, 'seats', (0, 1))[self.rules.player]
        self.board.shoot(move, seat)

    def forfeit_turn(self):
        shooter = getattr(self.rules, 'seats', (0, 1))[self.rules.player]
        result = (self.rules.resolve([], invalid=True, touched=False) if isinstance(self.rules, OfficialRules)
                  else self.rules.resolve([], invalid=True))
        return self._apply(result, shooter)
