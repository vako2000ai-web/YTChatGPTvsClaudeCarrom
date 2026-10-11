"""Playback controls. Frame data only; never starts a live Controller."""
from types import SimpleNamespace as NS
from board import Geometry
from replay import Replay
from game import Carrom
from settings import Settings
from graphics import THEMES


class ReplayController:
    def __init__(self, replay):
        self.replay = replay
        self.closed = False
        self.summary = replay.summary
        self.match = None
        self.apply(0)

    def apply(self, index):
        from pygame.math import Vector2
        self.index = index
        frame = self.replay.frames[index]
        state = frame['state']
        saved = state['rules']
        official = state['board'].get('geometry') == 'icf-735mm'
        geometry = Geometry.from_snapshot(state['board'])
        board = NS(geometry=geometry, official=official, discs={})
        for disc in frame['discs']:
            board.discs[disc['id']] = {'type': disc['type'], 'radius': disc['radius'],
                'body': NS(position=Vector2(disc['x'], disc['y']))}
        rules = NS(player=saved['player_index'], turn=saved['turn'], max_turns=saved['max_turns'],
                   scores=saved['scores'], queen_owner=saved['queen_owner'], queen_pending=saved['queen_pending'],
                   debt=saved['penalty_debt'], colours=saved.get('colour_by_player', ('white', 'black')),
                   seats=saved.get('seat_by_player', (0, 1)))
        self.match = NS(board=board, rules=rules)
        self.comment, self.last_move = frame['comment'], frame['move']
        self.aiming = frame.get('aiming', False)
        self.status = f"REPLAY · {frame['time']:.1f} / {self.replay.duration:.1f} сек · кадр {index + 1}/{len(self.replay.frames)}"

    def abort(self):
        self.closed = True


class ReplayApp(Carrom):
    def __init__(self, path, settings=None, directory=None, record_obs=False,
                 obs_scene='Carrom AI Showdown', obs_setup=False, obs_directory=None):
        self.replay_data = Replay(path)
        # No Settings.validate for API and no live Controller created for replay.
        from dataclasses import replace
        replay_settings = replace(settings or Settings(), eleven_enabled=False, audio_music=0)
        super().__init__(replay_settings, directory, record_obs=record_obs,
                         obs_scene=obs_scene, obs_setup=obs_setup, obs_directory=obs_directory)
        self.is_replay = True
        from runner import VERSION
        self.pg.display.set_caption('Carrom AI Showdown v' + VERSION + ' / REPLAY')
        from media import ReplayMedia
        self.controller.media = ReplayMedia(path)
        self.cursor = 0.0
        self.speed_index = 2
        self.speeds = (0.25, 0.5, 1, 2, 4)

    def new_match(self):
        saved_theme = self.replay_data.header.get('board_theme')
        self.board_theme = saved_theme if saved_theme in THEMES else 'classic_maple'
        self.controller = ReplayController(self.replay_data)
        self.finished_at = None

    def run(self, quit_on_finish=False, frames=None, screenshot=None):
        from pathlib import Path
        pg, running, frame, obs = self.pg, True, 0, None
        try:
            obs = self.start_obs()
            while running:
                elapsed = self.clock.tick(60) / 1000
                seeked = False
                for event in pg.event.get():
                    if event.type == pg.QUIT or (event.type == pg.KEYDOWN and event.key == pg.K_ESCAPE):
                        running = False
                    elif event.type == pg.KEYDOWN:
                        if event.key == pg.K_SPACE:
                            self.paused = not self.paused
                            self.audio.close()
                        elif event.key in (pg.K_m, pg.K_MINUS, pg.K_EQUALS, pg.K_PLUS, pg.K_KP_MINUS, pg.K_KP_PLUS):
                            self.audio.control(event.key)
                        elif event.key in (pg.K_LEFT, pg.K_RIGHT):
                            seeked = True
                            self.cursor = min(self.replay_data.duration, max(0, self.cursor + (5 if event.key == pg.K_RIGHT else -5)))
                        elif event.key in (pg.K_UP, pg.K_DOWN):
                            self.speed_index = min(4, max(0, self.speed_index + (1 if event.key == pg.K_UP else -1)))
                        elif event.key == pg.K_HOME:
                            seeked = True
                            self.cursor = 0
                        elif event.key == pg.K_END:
                            seeked = True
                            self.cursor = self.replay_data.duration
                if not self.paused:
                    self.cursor = min(self.replay_data.duration, self.cursor + elapsed * self.speeds[self.speed_index])
                if seeked:
                    self.controller.media.seek(self.cursor, self.audio)
                elif not self.paused:
                    self.controller.media.advance(self.cursor, self.audio)
                self.controller.apply(self.replay_data.seek(self.cursor))
                self.controller.status += f' · {self.speeds[self.speed_index]}x'
                self.draw()
                frame += 1
                if (frames and frame >= frames) or (quit_on_finish and self.cursor >= self.replay_data.duration):
                    running = False
            if screenshot:
                Path(screenshot).parent.mkdir(parents=True, exist_ok=True)
                pg.image.save(self.screen, str(screenshot))
        finally:
            self.controller.abort()
            try:
                self.finish_obs(obs)
            finally:
                self.audio.close()
                pg.quit()
