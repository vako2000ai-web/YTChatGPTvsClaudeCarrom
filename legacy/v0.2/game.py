"""Automatic Carrom UI and command-line tournament entry point."""
import argparse
import csv
import json
from pathlib import Path
import time
import uuid
from board import POCKETS, POCKET_R, BASE_Y, PLAYERS, WALLS
from runner import Controller, VERSION, run_headless
from settings import Settings, project_root

COLORS = {'white': (245, 229, 197), 'black': (41, 40, 46),
          'queen': (206, 58, 78), 'striker': (63, 161, 199)}


class Carrom:
    def __init__(self, settings=None, directory=None, max_turns=80, matches=1, first_player=0):
        import pygame
        self.pg = pygame
        pygame.init()
        pygame.display.set_caption('Carrom AI Showdown v' + VERSION)
        self.screen = pygame.display.set_mode((1280, 900))
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont('segoeui,arial', 22)
        self.small = pygame.font.SysFont('segoeui,arial', 17)
        self.big = pygame.font.SysFont('segoeui,arial', 38, bold=True)
        self.settings = settings or Settings.load()
        self.directory = Path(directory or project_root() / 'matches')
        self.max_turns = max_turns
        self.matches = matches
        self.first_player = first_player
        self.completed = []
        self.paused = False
        self.finished_at = None
        self.new_match()

    def new_match(self):
        self.controller = Controller(self.settings, self.directory, self.max_turns,
                                     self.first_player ^ (len(self.completed) % 2))
        self.finished_at = None

    def text(self, content, pos, color=(229, 232, 241), font=None):
        self.screen.blit((font or self.font).render(str(content), True, color), pos)

    def wrapped(self, content, pos, width, color=(200, 207, 220)):
        x, y = pos
        line = ''
        for word in str(content).split():
            if self.small.size(line + word)[0] > width and line:
                self.text(line, (x, y), color, self.small)
                y += 25
                line = ''
            line += word + ' '
        self.text(line, (x, y), color, self.small)

    def draw(self):
        pg, screen = self.pg, self.screen
        controller, match = self.controller, self.controller.match
        screen.fill((20, 24, 35))
        self.text('CARROM / AI SHOWDOWN', (30, 22), font=self.big)
        mode = 'DEMO · локальные стратегии' if self.settings.mode == 'demo' else 'LIVE · OpenAI API vs Anthropic API'
        self.text(mode, (820, 34), (240, 195, 111), self.small)
        board = pg.Surface((760, 760))
        board.fill((20, 24, 35))
        pg.draw.rect(board, (136, 91, 51), (20, 20, 720, 720), border_radius=25)
        pg.draw.rect(board, (229, 193, 137), (43, 43, 674, 674), border_radius=10)
        for a, b in WALLS:
            pg.draw.line(board, (132, 74, 46), a, b, 3)
        pg.draw.circle(board, (143, 81, 56), (380, 380), 75, 2)
        pg.draw.circle(board, (143, 81, 56), (380, 380), 25, 2)
        for y in BASE_Y:
            pg.draw.line(board, (128, 67, 44), (250, y), (510, y), 3)
            for x in (250, 510):
                pg.draw.circle(board, (128, 67, 44), (x, y), 13, 3)
        for pocket in POCKETS:
            pg.draw.circle(board, (39, 33, 30), pocket, POCKET_R)
        for disc in match.board.discs.values():
            pos = disc['body'].position
            point = (round(pos.x), round(pos.y))
            radius = disc['radius']
            pg.draw.circle(board, (90, 62, 40), (point[0] + 2, point[1] + 3), radius + 1)
            pg.draw.circle(board, COLORS[disc['type']], point, radius)
            pg.draw.circle(board, (214, 189, 151), point, radius - 5, 1)
        screen.blit(board, (20, 85))
        pg.draw.rect(screen, (29, 34, 49), (820, 105, 430, 645), border_radius=20)
        self.text('МАТЧ ' + str(min(len(self.completed) + 1, self.matches)) + ' / ' + str(self.matches), (845, 130), (172, 181, 201), self.small)
        for i, (name, color) in enumerate(zip(PLAYERS, ((82, 199, 166), (184, 142, 232)))):
            y = 180 + i * 86
            self.text(name, (845, y), color, self.big)
            self.text(str(match.rules.scores[i]) + ' / 9', (1100, y), font=self.big)
            label = 'Белые · нижняя линия' if i == 0 else 'Чёрные · верхняя линия'
            self.text(label, (848, y + 46), (173, 181, 201), self.small)
        pg.draw.line(screen, (58, 64, 81), (845, 365), (1225, 365), 1)
        current = PLAYERS[match.rules.player]
        turn = min(match.rules.turn + 1, match.rules.max_turns)
        self.text(f'Ход {turn} / {match.rules.max_turns} · {current}', (845, 390))
        if match.rules.queen_owner is not None:
            queen = 'Королева покрыта: ' + PLAYERS[match.rules.queen_owner]
        elif match.rules.queen_pending is not None:
            queen = 'Королева ждёт покрытия'
        else:
            queen = 'Королева на доске'
        self.text(queen, (845, 430), (233, 174, 129), self.small)
        self.text(f'Штрафной долг: {match.rules.debt[0]} / {match.rules.debt[1]}', (845, 463), font=self.small)
        self.text('РЕШЕНИЕ ИГРОКА', (845, 510), (172, 181, 201), self.small)
        self.wrapped(controller.comment or 'Ожидание первого удара...', (845, 545), 365)
        if controller.last_move:
            move = controller.last_move
            self.text(f"X {move['x']:.0f}   угол {move['angle']:.1f}°   сила {move['power']:.0%}", (845, 645), font=self.small)
            pg.draw.rect(screen, (53, 62, 78), (845, 685, 365, 8), border_radius=4)
            pg.draw.rect(screen, (82, 199, 166), (845, 685, round(365 * move['power']), 8), border_radius=4)
        if controller.closed and controller.summary:
            winner = controller.summary['winner']
            status = 'НИЧЬЯ · лимит ходов' if winner is None else 'ПОБЕДА: ' + PLAYERS[winner]
        else:
            status = controller.status
        self.wrapped(status, (820, 785), 430, (240, 195, 111))
        self.text('SPACE: пауза после удара    R: новый матч    ESC: выход', (35, 857), font=self.small)
        self.text('v0.2 · домашние правила', (970, 857), (172, 181, 201), self.small)
        if self.paused:
            self.text('ПАУЗА', (835, 740), (240, 195, 111))
        pg.display.flip()

    def run(self, quit_on_finish=False, frames=None, screenshot=None):
        pg = self.pg
        running, frame = True, 0
        try:
            while running:
                for event in pg.event.get():
                    if event.type == pg.QUIT or (event.type == pg.KEYDOWN and event.key == pg.K_ESCAPE):
                        running = False
                    elif event.type == pg.KEYDOWN and event.key == pg.K_SPACE:
                        self.paused = not self.paused
                    elif event.type == pg.KEYDOWN and event.key == pg.K_r and not self.controller.busy:
                        self.controller.abort()
                        self.completed = []
                        self.new_match()
                if not running:
                    break
                self.controller.tick(4, advance=not self.paused)
                self.draw()
                if self.controller.closed and self.finished_at is None:
                    self.completed.append(self.controller.summary)
                    self.finished_at = time.monotonic()
                if self.finished_at is not None:
                    if len(self.completed) < self.matches and time.monotonic() - self.finished_at > 3 and not self.paused:
                        self.new_match()
                    elif len(self.completed) >= self.matches and quit_on_finish:
                        running = False
                frame += 1
                if frames and frame >= frames:
                    running = False
                self.clock.tick(60)
            if screenshot:
                Path(screenshot).parent.mkdir(parents=True, exist_ok=True)
                pg.image.save(self.screen, str(screenshot))
        finally:
            self.controller.abort()
            pg.quit()


def positive(value):
    value = int(value)
    if value < 1:
        raise argparse.ArgumentTypeError('Must be positive')
    return value


def main():
    parser = argparse.ArgumentParser(description='Carrom AI Showdown v' + VERSION)
    parser.add_argument('--mode', choices=('demo', 'api'))
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--matches', type=positive, default=1)
    parser.add_argument('--max-turns', type=positive, default=80)
    parser.add_argument('--first-player', type=int, choices=(0, 1), default=0)
    parser.add_argument('--log-dir', type=Path, default=project_root() / 'matches')
    parser.add_argument('--quit-on-finish', action='store_true')
    parser.add_argument('--frames', type=positive, help='Limit UI frames for smoke tests')
    parser.add_argument('--screenshot', type=Path)
    args = parser.parse_args()
    try:
        settings = Settings.load(mode=args.mode)
    except ValueError as exc:
        parser.error(str(exc))
    if args.headless:
        results = [run_headless(settings, args.log_dir, args.max_turns, args.first_player ^ (i % 2))
                   for i in range(args.matches)]
        prefix = args.log_dir / ('series_' + uuid.uuid4().hex[:8])
        summary = {'version': VERSION, 'mode': settings.mode, 'matches': results,
                   'wins': [sum(r['winner'] == i for r in results) for i in (0, 1)],
                   'draws': sum(r['winner'] is None for r in results)}
        prefix.with_suffix('.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        with prefix.with_suffix('.csv').open('w', newline='', encoding='utf-8-sig') as file:
            writer = csv.DictWriter(file, fieldnames=('match', 'winner', 'reason', 'white', 'black', 'turns', 'failures'))
            writer.writeheader()
            for i, result in enumerate(results, 1):
                writer.writerow({'match': i, 'winner': result['winner'], 'reason': result['reason'],
                                 'white': result['scores'][0], 'black': result['scores'][1],
                                 'turns': result['turns'], 'failures': result['failures']})
        print(json.dumps(summary, ensure_ascii=False))
    else:
        Carrom(settings, args.log_dir, args.max_turns, args.matches, args.first_player).run(
            args.quit_on_finish, args.frames, args.screenshot)


if __name__ == '__main__':
    main()
