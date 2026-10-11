"""Automatic lifecycle; workers make API decisions, main thread owns physics."""
from dataclasses import asdict, replace
import json
from pathlib import Path
import queue
import threading
import uuid
import time
from datetime import datetime, timezone
from agents import decide
from engine import Match
from replay import Recorder
from board import DT

VERSION = '0.3.2'


class MatchLog:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '_' + uuid.uuid4().hex[:8] + '.jsonl')
        self.file = self.path.open('x', encoding='utf-8')

    def write(self, event, **data):
        self.file.write(json.dumps({'event': event, **data}, ensure_ascii=False, allow_nan=False) + '\n')
        self.file.flush()

    def close(self):
        self.file.close()


class Controller:
    def __init__(self, settings, directory='matches', max_turns=80, first_player=0, chooser=decide,
                 ruleset='house', game_scores=(0, 0), seats=(0, 1), replay=True, aim_seconds=0, board_theme=None, media=False, live_media=False):
        self.match = Match(max_turns, first_player, ruleset, game_scores, seats)
        if aim_seconds != 0 and not 1 <= aim_seconds <= 3:
            raise ValueError('Aiming duration must be 1..3 seconds (0 for headless)')
        self.aim_seconds = aim_seconds
        self.aiming_move = None
        self.aim_started = None
        self.aim_frames = 0
        limit = getattr(self.match.rules, 'stroke_seconds', settings.timeout + aim_seconds)
        # Reserve presentation time inside the official stroke deadline.
        self.settings = replace(settings, timeout=min(settings.timeout, limit - aim_seconds))
        self.chooser = chooser
        self.log = MatchLog(directory)
        self.recorder = Recorder(self.log.path.with_suffix('.replay.jsonl.gz'), self.match.state(), VERSION, settings.mode, board_theme=board_theme) if replay else None
        self.media = None
        if media:
            from media import MediaSession
            self.media = MediaSession(self.log.path, settings, live=live_media)
        self.shot_player = first_player
        self.physics_time = 0
        self.replay_time = 0
        self.log.write('match_start', version=VERSION, mode=settings.mode, board_theme=board_theme,
                       models={'ChatGPT': settings.openai_model if settings.mode == 'api' else 'local-geometric-v0.3',
                               'Claude': settings.anthropic_model if settings.mode == 'api' else 'local-geometric-v0.3'},
                       initial_state=self.match.state(), replay_file=str(self.recorder.path) if self.recorder else None)
        self.results = queue.Queue()
        self.busy = False
        self.closed = False
        self.summary = None
        self.status = 'Готов к автоматическому матчу'
        self.comment = ''
        self.last_move = None
        self.decision_count = 0
        self.failures = 0
        self.tokens = [0, 0]
        self.request_serial = 0
        self.request_started = None
        self.consecutive_failures = 0
        self._frame()

    @property
    def aiming(self):
        return self.aiming_move is not None

    def _frame(self):
        if self.media:
            self.media.update(self.replay_time)
        if self.recorder:
            self.recorder.frame(self.match, self.replay_time, self.comment, self.status,
                                self.last_move, aiming=self.aiming)

    def _advance_aim(self):
        elapsed = max(0, time.monotonic() - self.aim_started)
        target_frames = int(min(elapsed, self.aim_seconds) * 60 + 1e-7)
        while self.aim_frames < target_frames:
            self.aim_frames += 1
            self.replay_time += 1 / 60
            self._frame()
        if elapsed < self.aim_seconds:
            return
        move = self.aiming_move
        self.aiming_move = None
        self.match.shoot(move)
        self.status = self.match.state()['player'] + ': удар'
        self.log.write('shot_start', move=move, aim_seconds=self.aim_seconds)
        self._frame()

    def request(self, background=True):
        if self.busy or self.aiming or self.match.board.active or self.match.rules.finished or self.closed:
            return
        if self.match.board.official:
            seat = self.match.rules.seats[self.match.rules.player]
            if not self.match.board.has_legal_placement(seat):
                result = self.match.rules.referee('blocked_baseline')
                self.log.write('referee', resolution=asdict(result), state=self.match.state())
                self._frame()
                return
        state = self.match.state()
        self.busy = True
        self.request_serial += 1
        serial = self.request_serial
        self.request_started = time.monotonic()
        self.status = state['player'] + ' выбирает удар...'
        self.log.write('decision_start', state=state)
        def work():
            try:
                self.results.put((serial, self.chooser(state, self.settings), None))
            except Exception as exc:
                # Never write SDK exception messages, HTTP headers or API secrets.
                self.results.put((serial, None, type(exc).__name__))
        if background:
            threading.Thread(target=work, daemon=True).start()
        else:
            work()

    def tick(self, physics_steps=4, background=True, advance=True):
        if self.closed:
            return
        if self.busy:
            try:
                serial, decision, error = self.results.get_nowait()
                if serial != self.request_serial:
                    return  # Discard late result from a timed-out turn.
            except queue.Empty:
                if time.monotonic() - self.request_started < self.settings.timeout:
                    return
                decision, error = None, 'StrokeTimeout'
            if self.match.board.official and time.monotonic() - self.request_started > self.settings.timeout:
                decision, error = None, 'StrokeTimeout'
            self.busy = False
            self.decision_count += 1
            player = self.match.rules.player
            if decision is not None:
                self.tokens[player] += sum(decision.usage.get(k, 0) for k in ('input_tokens', 'output_tokens'))
                self.log.write('decision', player=player, **asdict(decision))
                try:
                    if self.aim_seconds:
                        seat = getattr(self.match.rules, 'seats', (0, 1))[player]
                        self.match.board.prepare_shot(decision.move, seat)
                    else:
                        self.match.shoot(decision.move)
                except ValueError:
                    error = 'InvalidPlacement'
                else:
                    self.last_move = decision.move
                    self.comment = decision.move['comment']
                    self.shot_player = player
                    if self.media:
                        self.media.player_comment(player, self.comment)
                    self.status = f"{self.match.state()['player']} [{decision.source}]: удар"
                    self.consecutive_failures = 0
                    if self.aim_seconds:
                        self.aiming_move = dict(decision.move)
                        self.aim_started = time.monotonic()
                        self.aim_frames = 0
                        self.status = f'{self.match.state()["player"]}: прицеливание ({self.aim_seconds:g} сек)'
                        self.log.write('aim_start', move=decision.move, aim_seconds=self.aim_seconds)
                    self._frame()
            if error:
                self.failures += 1
                self.consecutive_failures += 1
                resolution = self.match.forfeit_turn()
                self.log.write('decision_failed', player=player, error_type=error,
                               resolution=asdict(resolution), state=self.match.state())
                self.status = 'Ошибка решения: ' + error + '. Ход пропущен.'
                if self.media:
                    self.media.interruption(player, error)
                if self.match.board.official and self.consecutive_failures >= 6:
                    self.match.rules.finished = True
                    self.match.rules.winner = None
                    self.match.rules.finish_reason = 'technical_failure_aborted'
                self._frame()
        if self.aiming:
            self._advance_aim()
            if self.aiming:
                return
        self._sounds()
        if self.match.board.active:
            for _ in range(physics_steps):
                self.match.board.step()
                self.physics_time += DT
                self.replay_time += DT
                self._sounds()
                if self.match.board.steps % 4 == 0:
                    self._frame()
                if not self.match.board.active:
                    resolution = self.match.finish_shot()
                    if self.match.board.official and self.match.board.timed_out:
                        self.match.rules.finished = True
                        self.match.rules.winner = None
                        self.match.rules.points = [0, 0]
                        self.match.rules.cancelled = False
                        self.match.rules.finish_reason = 'physics_timeout_aborted'
                        resolution.events.append('physics_timeout_aborted')
                    self.log.write('shot_end', pocketed=self.match.board.pocketed,
                                   overboard=self.match.board.overboard,
                                   physics_steps=self.match.board.steps,
                                   physics_timeout=self.match.board.timed_out,
                                   resolution=asdict(resolution), state=self.match.state())
                    self.status = ', '.join(resolution.events) or 'Удар завершён'
                    if self.media:
                        self.media.completed(self.shot_player, self.match.board.pocketed, resolution, self.match.rules)
                    self._frame()
                    break
        if self.match.rules.finished:
            self.summary = {'winner': self.match.rules.winner,
                            'reason': self.match.rules.finish_reason,
                            'scores': self.match.rules.scores, 'turns': self.match.rules.turn,
                            'decisions': self.decision_count, 'failures': self.failures,
                            'tokens': self.tokens, 'board_points': getattr(self.match.rules, 'points', [0, 0]),
                            'cancelled': getattr(self.match.rules, 'cancelled', False),
                            'replay': str(self.recorder.path) if self.recorder else None}
            self.log.write('match_end', summary=self.summary, state=self.match.state())
            self.log.close()
            if self.recorder:
                self.recorder.close(self.summary)
            self.closed = True
        elif advance and not self.busy and not self.aiming and not self.match.board.active:
            self.request(background)

    def _sounds(self):
        events = self.match.board.drain_sounds()
        if self.media:
            self.media.update(self.replay_time)
            for name, strength in events:
                self.media.sound(name, strength)

    def abort(self):
        if not self.closed:
            if self.aiming:
                self.aiming_move = None
                if -1 in self.match.board.discs:
                    self.match.board.remove(-1)
            self.log.write('match_aborted', state=self.match.state(), decision_pending=self.busy)
            self.log.close()
            if self.recorder:
                self._frame()
                self.recorder.close({'reason': 'match_aborted'})
            self.closed = True


def run_headless(settings, directory='matches', max_turns=80, first_player=0,
                 ruleset='house', game_scores=(0, 0), seats=(0, 1), replay=True):
    controller = Controller(settings, directory, max_turns, first_player, ruleset=ruleset,
                            game_scores=game_scores, seats=seats, replay=replay, media=True)
    try:
        while not controller.closed:
            controller.tick(physics_steps=240, background=False)
        return {**controller.summary, 'log': str(controller.log.path)}
    finally:
        controller.abort()
        if controller.media:
            controller.media.close()
