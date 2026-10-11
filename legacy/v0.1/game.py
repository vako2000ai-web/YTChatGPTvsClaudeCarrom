"""Carrom AI Showdown: executable physics prototype (simplified rules)."""
import math
import random
import threading
import pygame
import pymunk
from agents import choose_move
from dotenv import load_dotenv

load_dotenv()
SIZE = 760
WIDTH, HEIGHT = 760, 850
FPS = 60
POCKETS = [(45,45), (715,45), (45,715), (715,715)]
POCKET_R = 26
COLORS = {'white': (243, 227, 195), 'black': (47, 42, 50), 'queen': (199, 63, 78)}
PLAYERS = ['ChatGPT', 'Claude']


class Carrom:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption('Carrom AI Showdown — ChatGPT vs Claude')
        self.screen = pygame.display.set_mode((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont('arial', 21)
        self.small = pygame.font.SysFont('arial', 16)
        self.reset()

    def reset(self):
        self.space = pymunk.Space()
        self.space.gravity = (0, 0)
        self.space.damping = 0.987
        self.coins = []
        self.striker = None
        self.scores = [0, 0]
        self.player_idx = 0
        self.turn = 0
        self.status = 'Нажми ПРОБЕЛ, чтобы начать матч'
        self.last_comment = ''
        self.busy = False
        self.result = None
        self.request_serial = getattr(self, 'request_serial', 0) + 1
        self.shot_active = False
        self.shot_ticks = 0
        self.pocketed_this_shot = []
        self.finished = False
        walls = [((70,65),(690,65)), ((70,695),(690,695)),
                 ((65,70),(65,690)), ((695,70),(695,690))]
        for a,b in walls:
            shape = pymunk.Segment(self.space.static_body, a,b,7)
            shape.elasticity = 0.83
            shape.friction = 0.27
            self.space.add(shape)
        # Close-packed 19 coins: 9 white + 9 black + queen.
        arrangements = [(0, 0)]
        for ring in (1, 2):
            for i in range(ring * 6):
                t = 2 * math.pi * i / (ring * 6)
                arrangements.append((round(ring * 25 * math.cos(t), 5),
                                     round(ring * 25 * math.sin(t), 5)))
        types = ['queen'] + ['white', 'black'] * 9
        for (dx,dy), typ in zip(arrangements, types):
            self.add_disc(380 + dx, 380 + dy, 12, 1, typ)

    def add_disc(self, x, y, radius, mass, typ):
        moment = pymunk.moment_for_circle(mass, 0, radius)
        body = pymunk.Body(mass, moment)
        body.position = (x, y)
        shape = pymunk.Circle(body, radius)
        shape.elasticity = 0.90
        shape.friction = 0.35
        self.space.add(body, shape)
        obj = {'body': body, 'shape': shape, 'type': typ, 'radius': radius}
        if typ == 'striker':
            self.striker = obj
        else:
            self.coins.append(obj)
        return obj

    def is_moving(self):
        objs = self.coins + ([self.striker] if self.striker else [])
        return any(o['body'].velocity.length > 8 for o in objs)

    def state(self):
        return {'player': PLAYERS[self.player_idx], 'turn': self.turn + 1,
                'score': dict(zip(PLAYERS, self.scores)),
                'coins': [{'type': c['type'], 'x': round(c['body'].position.x,1),
                           'y': round(c['body'].position.y,1)} for c in self.coins]}

    def get_move_async(self):
        if self.busy or self.shot_active or self.finished:
            return
        self.busy = True
        self.result = None
        request_id = self.request_serial
        state = self.state()
        self.status = f"{state['player']} выбирает удар..."

        def work():
            try:
                move, source = choose_move(state)
                result = ('ok', move, source)
            except Exception as exc:
                result = ('error', str(exc), '')
            # Worker never touches pygame/pymunk; main thread consumes the result.
            if request_id == self.request_serial:
                self.result = result
        threading.Thread(target=work, daemon=True).start()

    def start_shot(self, move, source):
        base_y = 665 if self.player_idx == 0 else 95
        x = move['x']
        # Avoid placing striker on an existing coin.
        if any(math.hypot(c['body'].position.x-x, c['body'].position.y-base_y) < 30 for c in self.coins):
            self.status = 'Неверная позиция битка — пропуск хода'
            self.advance_turn()
            return
        self.add_disc(x, base_y, 16, 1.8, 'striker')
        angle = math.radians(move['angle'])
        speed = 1050 * move['power']
        self.striker['body'].velocity = (math.cos(angle) * speed, math.sin(angle) * speed)
        self.pocketed_this_shot = []
        self.shot_ticks = 0
        self.shot_active = True
        self.last_comment = move['comment']
        self.status = f"{PLAYERS[self.player_idx]} [{source}]: {self.last_comment}"
        self.turn += 1

    def pocket_check(self):
        for obj in self.coins[:] + ([self.striker] if self.striker else []):
            if any((obj['body'].position - pymunk.Vec2d(*p)).length < POCKET_R for p in POCKETS):
                self.space.remove(obj['shape'], obj['body'])
                if obj is self.striker:
                    self.striker = None
                    self.pocketed_this_shot.append('striker')
                else:
                    self.coins.remove(obj)
                    self.pocketed_this_shot.append(obj['type'])

    def advance_turn(self):
        scored = False
        my_color = 'white' if self.player_idx == 0 else 'black'
        # Prototype scoring: one point per own coin, queen = 2; no queen covering rule yet.
        for typ in self.pocketed_this_shot:
            if typ == my_color:
                self.scores[self.player_idx] += 1
                scored = True
            elif typ == 'queen':
                self.scores[self.player_idx] += 2
                scored = True
            elif typ != 'striker':
                self.scores[1-self.player_idx] += 1
        foul = 'striker' in self.pocketed_this_shot
        if foul:
            self.scores[self.player_idx] = max(0, self.scores[self.player_idx] - 1)
        self.pocketed_this_shot = []
        if self.striker:
            self.space.remove(self.striker['shape'], self.striker['body'])
            self.striker = None
        if not self.coins or self.turn >= 80:
            self.finished = True
            if self.scores[0] == self.scores[1]:
                self.status = 'Ничья! R — новый матч'
            else:
                winner = PLAYERS[0 if self.scores[0] > self.scores[1] else 1]
                self.status = f'Победил {winner}! R — новый матч'
            return
        # Keep turn only when successfully pocketing an own coin without foul.
        if not scored or foul:
            self.player_idx = 1 - self.player_idx
        self.status = ('Удачное попадание! ' if scored else 'Следующий ход. ') + 'ПРОБЕЛ — продолжить'

    def update(self):
        if self.result is not None:
            kind, payload, source = self.result
            self.result = None
            self.busy = False
            if kind == 'ok':
                self.start_shot(payload, source)
            else:
                self.status = f'Ошибка API: {payload[:100]} (проверь .env)'
        if not self.shot_active:
            return
        for _ in range(3):
            self.space.step(1 / (FPS * 3))
            self.pocket_check()
        self.shot_ticks += 1
        if self.shot_ticks > 25 and (not self.is_moving() or self.shot_ticks >= FPS * 15):
            # Stop residual drift; otherwise matches can never advance.
            for obj in self.coins:
                obj['body'].velocity = (0, 0)
                obj['body'].angular_velocity = 0
            self.shot_active = False
            self.advance_turn()

    def draw(self):
        s = self.screen
        s.fill((29, 31, 42))
        pygame.draw.rect(s, (138, 91, 46), (20, 20, 720, 720), border_radius=26)
        pygame.draw.rect(s, (225, 186, 122), (43, 43, 674, 674), border_radius=12)
        pygame.draw.rect(s, (130, 72, 43), (62, 62, 636, 636), width=4, border_radius=8)
        pygame.draw.circle(s, (135, 73, 51), (380,380), 75, 2)
        pygame.draw.circle(s, (135, 73, 51), (380,380), 25, 2)
        for y in (95, 665):
            pygame.draw.line(s, (128, 67, 44), (250, y), (510,y), 3)
            for x in (250,510):
                pygame.draw.circle(s, (128,67,44), (x,y), 13, 3)
        for x,y in POCKETS:
            pygame.draw.circle(s, (39,33,30), (x,y), POCKET_R)
        for obj in self.coins + ([self.striker] if self.striker else []):
            p = obj['body'].position
            pos = (int(p.x), int(p.y))
            if obj['type'] == 'striker':
                color = (78, 166, 206)
            else:
                color = COLORS[obj['type']]
            pygame.draw.circle(s, (61,43,37), pos, obj['radius']+2)
            pygame.draw.circle(s, color, pos, obj['radius'])
            pygame.draw.circle(s, (235, 213, 167), pos, obj['radius']-5, 1)
        title = self.font.render(f'ChatGPT {self.scores[0]} : {self.scores[1]} Claude', True, (239,239,247))
        s.blit(title, (25, 757))
        current = PLAYERS[self.player_idx]
        self.screen.blit(self.small.render(f'Ход: {current}  |  SPACE: удар  R: новая игра  ESC: выход', True, (187,195,208)), (25,787))
        msg = self.small.render(self.status[:91], True, (242,206,128))
        s.blit(msg, (25,816))
        pygame.display.flip()

    def run(self):
        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT or (event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE):
                    running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                    self.reset()
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                    self.get_move_async()
            self.update()
            self.draw()
            self.clock.tick(FPS)
        pygame.quit()


if __name__ == '__main__':
    Carrom().run()
