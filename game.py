"""Automatic Carrom UI and command-line tournament entry point."""
import argparse
import csv
import json
import math
from pathlib import Path
import time
import uuid
from board import POCKETS, PLAYERS
from runner import Controller, VERSION, run_headless
from settings import Settings, project_root
from graphics import Artwork, THEMES, choose_theme
from tournament import Tournament
from obs_recording import OBSRecorder, OBSError

COLORS = {'white': (245, 229, 197), 'black': (41, 40, 46),
          'queen': (206, 58, 78), 'striker': (63, 161, 199)}


class Carrom:
    def __init__(self, settings=None, directory=None, max_turns=800, matches=1, first_player=0,
                 ruleset='icf', official_match=False, max_boards=200, record_obs=False,
                 obs_scene='Carrom AI Showdown', obs_setup=False, obs_directory=None, record_replay=True,
                 round_stage='pre-quarter', toss_seed=0, aim_seconds=2, board_theme='random', board_season='calendar'):
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
        self.aim_seconds = aim_seconds
        self.theme_choice, self.board_season = board_theme, board_season
        self.board_theme = None
        self.artwork = Artwork(pygame)
        self.matches = matches
        self.first_player = first_player
        self.ruleset = ruleset
        self.round_stage, self.toss_seed = round_stage, toss_seed
        self.tournament = Tournament(first_player, round_stage=round_stage, toss_seed=toss_seed) if official_match else None
        self.max_boards = max_boards
        self.tournament_aborted = False
        self.board_replays = 0
        self.record_obs = record_obs
        self.obs_scene, self.obs_setup, self.obs_directory = obs_scene, obs_setup, obs_directory
        self.record_replay = record_replay
        self.is_replay = False
        self.completed = []
        self.paused = False
        self.finished_at = None
        from audio import AudioPlayer
        self.audio = AudioPlayer(pygame, self.settings)
        self.media_sessions = []
        self.obs_started = None
        self.new_match()

    def new_match(self):
        if hasattr(self, 'controller') and self.controller.media:
            self.audio.stop_speech()
            self.controller.media.close(background=True)
        self.board_theme = (choose_theme(self.board_theme, self.board_season)
                            if self.theme_choice == 'random' else self.theme_choice)
        first = self.tournament.breaker if self.tournament else self.first_player ^ (len(self.completed) % 2)
        scores = self.tournament.points if self.tournament else (0, 0)
        seats = self.tournament.seats if self.tournament else (0, 1)
        self.controller = Controller(self.settings, self.directory, self.max_turns, first,
                                     ruleset=self.ruleset, game_scores=scores, seats=seats, replay=self.record_replay,
                                     aim_seconds=self.aim_seconds, board_theme=self.board_theme, media=True, live_media=True)
        self.controller.media.obs_start = self.obs_started
        self.media_sessions.append(self.controller.media)
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
        mode = ('REPLAY · без запросов API' if self.is_replay else
                'DEMO · локальные стратегии' if self.settings.mode == 'demo' else 'LIVE · OpenAI API vs Anthropic API')
        self.text(mode, (820, 34), (240, 195, 111), self.small)
        board = pg.Surface((760, 760))
        board.fill((20, 24, 35))
        _, frame_color, ink = THEMES[self.board_theme]
        pg.draw.rect(board, frame_color, (20, 20, 720, 720), border_radius=25)
        board.blit(self.artwork.board(self.board_theme), (43, 43))
        geometry = match.board.geometry
        for a, b in geometry.walls:
            pg.draw.line(board, ink, a, b, 3)
        pg.draw.circle(board, ink, (380, 380), round(geometry.outer_radius), 2)
        pg.draw.circle(board, ink, (380, 380), round(geometry.centre_radius), 2)
        for y in geometry.baseline_y:
            for delta in (-geometry.centre_radius, geometry.centre_radius) if match.board.official else (0,):
                pg.draw.line(board, ink, (geometry.baseline_ends[0], y + delta), (geometry.baseline_ends[1], y + delta), 2)
            for x in geometry.baseline_ends:
                pg.draw.circle(board, ink, (round(x), round(y)), round(geometry.centre_radius), 2)
        for pocket in POCKETS:
            pg.draw.circle(board, (39, 33, 30), pocket, round(geometry.pocket_radius))
        for disc in match.board.discs.values():
            pos = disc['body'].position
            point = (round(pos.x), round(pos.y))
            radius = round(disc['radius'])
            shadow = self.artwork.shadow(disc['radius'])
            board.blit(shadow, shadow.get_rect(center=(point[0] + 2, point[1] + 3)))
            sprite = self.artwork.disc(disc['type'], disc['radius'])
            board.blit(sprite, sprite.get_rect(center=point))
        if controller.aiming and controller.last_move and -1 in match.board.discs:
            # Display exactly the selected direction, without changing the AI move.
            position = match.board.discs[-1]['body'].position
            start = (position.x, position.y)
            angle = math.radians(controller.last_move['angle'])
            direction = (math.cos(angle), math.sin(angle))
            edges = [p for wall in geometry.walls for p in wall]
            bounds = (min(p[0] for p in edges), max(p[0] for p in edges),
                      min(p[1] for p in edges), max(p[1] for p in edges))
            distances = []
            for axis, (low, high) in enumerate(((bounds[0], bounds[1]), (bounds[2], bounds[3]))):
                if abs(direction[axis]) > 1e-9:
                    edge = high if direction[axis] > 0 else low
                    distances.append((edge - start[axis]) / direction[axis])
            distance = max(0, min(distances))
            end = (start[0] + direction[0] * distance, start[1] + direction[1] * distance)
            line_color = (255, 222, 112)
            for offset in range(math.ceil(geometry.striker_radius + 5), math.floor(distance), 18):
                finish = min(offset + 10, distance)
                pg.draw.line(board, line_color,
                    (start[0] + direction[0] * offset, start[1] + direction[1] * offset),
                    (start[0] + direction[0] * finish, start[1] + direction[1] * finish), 2)
            pg.draw.circle(board, line_color, (round(end[0]), round(end[1])), 5, 1)
            pg.draw.circle(board, line_color, (round(start[0]), round(start[1])),
                           round(geometry.striker_radius + 4), 2)
        screen.blit(board, (20, 85))
        pg.draw.rect(screen, (29, 34, 49), (820, 105, 430, 645), border_radius=20)
        self.text('МАТЧ ' + str(min(len(self.completed) + 1, self.matches)) + ' / ' + str(self.matches), (845, 130), (172, 181, 201), self.small)
        if self.tournament:
            self.text(f'Игра {self.tournament.game_number} · очки {self.tournament.points[0]}:{self.tournament.points[1]} · игры {self.tournament.games[0]}:{self.tournament.games[1]}', (845, 158), font=self.small)
        for i, (name, color) in enumerate(zip(PLAYERS, ((82, 199, 166), (184, 142, 232)))):
            y = 180 + i * 86
            self.text(name, (845, y), color, self.big)
            self.text(str(match.rules.scores[i]) + ' / 9', (1100, y), font=self.big)
            colour = getattr(match.rules, 'colours', ('white', 'black'))[i]
            seat = getattr(match.rules, 'seats', (0, 1))[i]
            label = ('Белые' if colour == 'white' else 'Чёрные') + (' · нижняя линия' if seat == 0 else ' · верхняя линия')
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
            status = ('ПОБЕДА: ' + PLAYERS[winner] if winner is not None else
                      'НИЧЬЯ · лимит ходов' if controller.summary.get('reason') == 'turn_limit_draw' else
                      'Борд переигрывается' if controller.summary.get('cancelled') else
                      'Матч остановлен · ' + controller.summary.get('reason', 'technical_abort'))
        else:
            status = controller.status
        self.wrapped(status, (820, 785), 430, (240, 195, 111))
        controls = ('SPACE: пауза   ←/→: ±5 сек   ↑/↓: скорость   HOME/END   ESC: выход' if self.is_replay else
                    'SPACE: пауза после удара    R: новый матч    ESC: выход')
        self.text(controls, (35, 857), font=self.small)
        label = 'домашние правила' if not match.board.official else 'ICF · одиночная игра'
        self.text('v' + VERSION + ' · ' + label, (955, 857), (172, 181, 201), self.small)
        self.text('Доска: ' + THEMES[self.board_theme][0], (820, 760), (173, 181, 201), self.small)
        media = getattr(self.controller, 'media', None)
        if media and media.latest and (self.is_replay or media.now() < media.latest_until):
            line = 'АВТОРСКИЙ КОММЕНТАТОР: ' + media.latest
            while self.small.size(line)[0] > 1210:
                line = line[:-4] + '...'
            self.text(line, (35, 878), (144, 217, 191), self.small)
        if not self.is_replay:
            label = self.audio.warning or ('выкл' if not self.audio.enabled or self.audio.muted else f'{self.audio.master:.0%}')
            self.text('Звук: ' + label + ' · M / − / +', (40, 70), (173, 181, 201), self.small)
        if self.paused:
            self.text('ПАУЗА', (835, 740), (240, 195, 111))
        pg.display.flip()

    def start_obs(self):
        if not self.record_obs:
            return None
        self.draw()
        self.pg.event.pump()
        recorder = OBSRecorder(self.settings.obs_url, self.settings.obs_password)
        try:
            if self.obs_setup:
                recorder.setup_window_scene(self.obs_scene, self.pg.display.get_caption()[0], game_audio=self.audio.enabled)
            recorder.start(self.obs_directory, self.obs_scene)
            self.obs_started = recorder.record_started
            for media in self.media_sessions:
                media.obs_start = self.obs_started
        except Exception:
            recorder.close()
            raise
        return recorder

    def finish_obs(self, recorder):
        if recorder is not None:
            try:
                path = recorder.stop()
                manifest = {'recorded_file': path, 'mode': 'replay' if self.is_replay else self.settings.mode,
                            'version': VERSION, 'scene': self.obs_scene}
                for media in self.media_sessions:
                    media.video_file = path
                    manifest['media'] = [str(item.directory) for item in self.media_sessions]
                    saved = media.directory / 'manifest.json'
                    if saved.exists():
                        item = json.loads(saved.read_text(encoding='utf-8'))
                        item['video_file'] = path
                        saved.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding='utf-8')
                self.directory.mkdir(parents=True, exist_ok=True)
                (self.directory / ('obs_' + uuid.uuid4().hex[:8] + '.json')).write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
            finally:
                recorder.close()

    def run(self, quit_on_finish=False, frames=None, screenshot=None):
        pg = self.pg
        running, frame = True, 0
        obs = None
        try:
            obs = self.start_obs()
            while running:
                for event in pg.event.get():
                    if event.type == pg.QUIT or (event.type == pg.KEYDOWN and event.key == pg.K_ESCAPE):
                        running = False
                    elif event.type == pg.KEYDOWN and event.key in (pg.K_m, pg.K_MINUS, pg.K_EQUALS, pg.K_PLUS, pg.K_KP_MINUS, pg.K_KP_PLUS):
                        self.audio.control(event.key)
                    elif event.type == pg.KEYDOWN and event.key == pg.K_SPACE:
                        self.paused = not self.paused
                    elif event.type == pg.KEYDOWN and event.key == pg.K_r and not self.controller.busy:
                        self.controller.abort()
                        self.completed = []
                        if self.tournament:
                            self.tournament = Tournament(self.first_player)
                            self.tournament_aborted = False
                        self.new_match()
                if not running:
                    break
                self.controller.tick(4, advance=not self.paused)
                self.controller.media.tick(self.audio)
                if self.controller.media.status:
                    self.controller.status += ' · ' + self.controller.media.status
                    self.controller.media.status = ''
                self.draw()
                if self.controller.closed and self.finished_at is None:
                    if self.tournament:
                        result = self.controller.summary
                        if result['winner'] is not None:
                            self.tournament.record_board(result['winner'], result['board_points'][result['winner']])
                            self.board_replays = 0
                        elif result['cancelled'] and self.board_replays < 3:
                            self.board_replays += 1
                        else:
                            self.tournament_aborted = True
                        if self.tournament.total_boards >= self.max_boards and not self.tournament.finished:
                            self.tournament_aborted = True
                        if self.tournament.finished or self.tournament_aborted:
                            self.completed.append(self.tournament.snapshot())
                    else:
                        self.completed.append(self.controller.summary)
                    self.finished_at = time.monotonic()
                if self.finished_at is not None:
                    more_boards = self.tournament and not self.tournament.finished and not self.tournament_aborted
                    if (more_boards or len(self.completed) < self.matches) and time.monotonic() - self.finished_at > 3 and not self.paused:
                        if self.tournament and not more_boards:
                            self.tournament = Tournament(self.first_player ^ (len(self.completed) % 2),
                                                         round_stage=self.round_stage, toss_seed=self.toss_seed + len(self.completed))
                            self.tournament_aborted = False
                        self.new_match()
                    elif not more_boards and len(self.completed) >= self.matches and quit_on_finish:
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
            self.audio.close()
            for media in self.media_sessions:
                media.close(background=True)
            try:
                self.finish_obs(obs)
            finally:
                try:
                    for media in self.media_sessions:
                        media.wait_export()
                finally:
                    pg.quit()


def positive(value):
    value = int(value)
    if value < 1:
        raise argparse.ArgumentTypeError('Must be positive')
    return value


def main():
    parser = argparse.ArgumentParser(description='Carrom AI Showdown v' + VERSION)
    parser.add_argument('--mode', choices=('demo', 'api'))
    parser.add_argument('--config', type=Path, help='Path to an alternative .env file')
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--no-audio', action='store_true', help='Disable mixer and live TTS; text/export remains')
    parser.add_argument('--matches', type=positive, default=1)
    parser.add_argument('--max-turns', type=positive, default=800)
    parser.add_argument('--rules', choices=('icf', 'aicf-senior', 'house'), default='icf')
    parser.add_argument('--official-match', action='store_true', help='25 points, eight boards, best of three games')
    parser.add_argument('--round-stage', choices=('pre-quarter', 'quarter'), default='pre-quarter')
    parser.add_argument('--toss-seed', type=int, default=0)
    parser.add_argument('--max-boards', type=positive, default=200, help='Technical safety cap, not a sporting tiebreak')
    parser.add_argument('--aim-seconds', type=int, choices=(1, 2, 3), default=2,
                        help='Visible pre-shot aiming duration; headless has no presentation delay')
    parser.add_argument('--board-theme', choices=('random', *THEMES), default='random')
    parser.add_argument('--board-season', choices=('calendar', 'all'), default='calendar',
                        help='Calendar limits holiday boards to their season; all includes every design')
    parser.add_argument('--no-replay', action='store_true')
    parser.add_argument('--replay', type=Path)
    parser.add_argument('--replay-info', type=Path)
    parser.add_argument('--obs-record', action='store_true')
    parser.add_argument('--obs-setup-scene', action='store_true')
    parser.add_argument('--obs-scene', default='Carrom AI Showdown')
    parser.add_argument('--obs-output-dir', type=Path)
    parser.add_argument('--report', type=Path, help='Also save CLI result to JSON (useful for Windows EXE)')
    parser.add_argument('--self-test', action='store_true', help='Offline packaging check, no paid API calls')
    parser.add_argument('--first-player', type=int, choices=(0, 1), default=0)
    parser.add_argument('--log-dir', type=Path, default=project_root() / 'matches')
    parser.add_argument('--quit-on-finish', action='store_true')
    parser.add_argument('--frames', type=positive, help='Limit UI frames for smoke tests')
    parser.add_argument('--screenshot', type=Path)
    args = parser.parse_args()
    def output(data):
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        import sys
        if sys.stdout is not None:
            print(json.dumps(data, ensure_ascii=False))
    if args.self_test:
        from selfcheck import run
        output(run(args.log_dir))
        return
    if args.replay_info:
        from replay import inspect_replay
        try:
            output(inspect_replay(args.replay_info))
        except ValueError as exc:
            parser.error(str(exc))
        return
    try:
        settings = Settings.load(args.config, mode='demo' if args.replay else args.mode,
                                 disable_audio=args.no_audio, disable_voice=bool(args.replay or args.headless))
    except ValueError as exc:
        parser.error(str(exc))
    if args.no_audio:
        from dataclasses import replace
        settings = replace(settings, audio_enabled=False, eleven_enabled=False)
    if args.headless:
        if args.obs_record or args.replay:
            parser.error('OBS/replay playback requires a GUI window')
        if args.official_match and args.rules == 'house':
            parser.error('Official match requires an official ruleset')
        if args.official_match:
            results = [run_official_match(settings, args.log_dir, args.max_turns,
                                          args.first_player ^ (i % 2), args.rules, args.max_boards, not args.no_replay,
                                          args.round_stage, args.toss_seed + i)
                       for i in range(args.matches)]
        else:
            results = [run_headless(settings, args.log_dir, args.max_turns, args.first_player ^ (i % 2),
                                    ruleset=args.rules, replay=not args.no_replay) for i in range(args.matches)]
        prefix = args.log_dir / ('series_' + uuid.uuid4().hex[:8])
        summary = {'version': VERSION, 'mode': settings.mode, 'matches': results,
                   'wins': [sum(r['winner'] == i for r in results) for i in (0, 1)],
                   'draws': sum(r['reason'] == 'turn_limit_draw' for r in results),
                   'aborted': sum(r['winner'] is None and r['reason'] != 'turn_limit_draw' for r in results)}
        prefix.with_suffix('.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
        with prefix.with_suffix('.csv').open('w', newline='', encoding='utf-8-sig') as file:
            writer = csv.DictWriter(file, fieldnames=('match', 'winner', 'reason', 'chatgpt_coins', 'claude_coins',
                                                     'chatgpt_games', 'claude_games', 'turns', 'failures'))
            writer.writeheader()
            for i, result in enumerate(results, 1):
                writer.writerow({'match': i, 'winner': result['winner'], 'reason': result['reason'],
                                 'chatgpt_coins': result.get('scores', [None, None])[0],
                                 'claude_coins': result.get('scores', [None, None])[1],
                                 'chatgpt_games': result.get('tournament', {}).get('games', [None, None])[0],
                                 'claude_games': result.get('tournament', {}).get('games', [None, None])[1],
                                 'turns': result.get('turns'), 'failures': result.get('failures')})
        output(summary)
    else:
        if args.replay:
            from replay_ui import ReplayApp
            try:
                app = ReplayApp(args.replay, settings, args.log_dir, args.obs_record,
                                args.obs_scene, args.obs_setup_scene, args.obs_output_dir)
            except ValueError as exc:
                parser.error(str(exc))
        else:
            if args.official_match and args.rules == 'house':
                parser.error('Official match requires an official ruleset')
            app = Carrom(settings, args.log_dir, args.max_turns, args.matches, args.first_player,
                         args.rules, args.official_match, args.max_boards, args.obs_record,
                         args.obs_scene, args.obs_setup_scene, args.obs_output_dir, not args.no_replay,
                         args.round_stage, args.toss_seed, args.aim_seconds, args.board_theme, args.board_season)
        try:
            app.run(args.quit_on_finish, args.frames, args.screenshot)
        except OBSError as exc:
            parser.error(str(exc))


def run_official_match(settings, directory, max_turns=800, first_player=0, ruleset='icf', max_boards=200, replay=True,
                       round_stage='pre-quarter', toss_seed=0):
    tournament = Tournament(first_player, round_stage=round_stage, toss_seed=toss_seed)
    boards, attempts, failures = [], 0, 0
    reason = 'best_of_three'
    while not tournament.finished:
        attempts += 1
        result = run_headless(settings, directory, max_turns, tournament.breaker,
                              ruleset, tournament.points, tournament.seats, replay)
        boards.append(result)
        failures += result['failures']
        if result['winner'] is not None:
            tournament.record_board(result['winner'], result['board_points'][result['winner']])
        elif not result['cancelled']:
            reason = result['reason']
            break
        if attempts >= max_boards and not tournament.finished:
            reason = 'board_safety_limit_aborted'
            break
    return {'winner': tournament.winner, 'reason': reason, 'tournament': tournament.snapshot(),
            'boards': boards, 'failures': failures, 'turns': sum(b['turns'] for b in boards),
            'history': tournament.history}


if __name__ == '__main__':
    main()
