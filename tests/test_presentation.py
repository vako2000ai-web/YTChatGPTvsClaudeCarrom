"""Presentation must never change an AI move or trigger an extra API request."""
from datetime import date
import json
import random
import pytest
from agents import Decision
from graphics import THEMES, choose_theme, seasonal_themes, assets_root, Artwork
from runner import Controller
from settings import Settings
from replay import Replay

MOVE = {'x': 380, 'angle': 270, 'power': .7, 'comment': 'Проверка прицела'}


def controller_with_clock(tmp_path, monkeypatch, seconds=2):
    clock = [10.0]
    requests = []
    monkeypatch.setattr('runner.time.monotonic', lambda: clock[0])
    def choose(state, settings):
        requests.append(state)
        return Decision(dict(MOVE), 'test', 'fixture', 0, {})
    controller = Controller(Settings(), tmp_path, max_turns=1, chooser=choose,
                            ruleset='icf', aim_seconds=seconds, board_theme='halloween')
    controller.tick(background=False)
    controller.tick(background=False, advance=False)
    return controller, clock, requests


@pytest.mark.parametrize('seconds', (1, 2, 3))
def test_striker_waits_then_fires_exactly_once(tmp_path, monkeypatch, seconds):
    controller, clock, requests = controller_with_clock(tmp_path, monkeypatch, seconds)
    try:
        assert controller.aiming and not controller.match.board.active
        striker = controller.match.board.discs[-1]['body']
        assert striker.velocity.length == 0
        bodies_before = len(controller.match.board.space.bodies)
        controller.request(background=False)
        clock[0] += seconds - .001
        controller.tick(physics_steps=0, advance=False)
        assert controller.aiming and striker.velocity.length == 0
        clock[0] += .001
        controller.tick(physics_steps=0, advance=False)
        assert not controller.aiming and controller.match.board.active
        assert controller.match.board.discs[-1]['body'] is striker
        assert len(controller.match.board.space.bodies) == bodies_before
        assert striker.velocity.x == pytest.approx(0, abs=1e-6)
        assert striker.velocity.y == pytest.approx(-735)
        assert len(requests) == controller.decision_count == 1
        assert controller.last_move == MOVE
    finally:
        controller.abort()


def test_aim_replay_has_duration_and_stationary_striker(tmp_path, monkeypatch):
    controller, clock, requests = controller_with_clock(tmp_path, monkeypatch)
    clock[0] += 2
    controller.tick(physics_steps=0, advance=False)
    while not controller.closed:
        controller.tick(physics_steps=240, advance=False)
    replay = Replay(controller.recorder.path)
    aim_frames = [f for f in replay.frames if f.get('aiming')]
    assert len(aim_frames) == 121
    assert aim_frames[-1]['time'] - aim_frames[0]['time'] == pytest.approx(2)
    for frame in aim_frames:
        striker = next(d for d in frame['discs'] if d['id'] == -1)
        assert striker['vx'] == striker['vy'] == 0
        assert frame['move'] == MOVE
    assert replay.duration == pytest.approx(controller.physics_time + 2)
    assert replay.header['board_theme'] == 'halloween'
    events = [json.loads(line)['event'] for line in controller.log.path.read_text(encoding='utf-8').splitlines()]
    assert events.count('aim_start') == events.count('shot_start') == 1
    assert events.index('decision') < events.index('aim_start') < events.index('shot_start') < events.index('shot_end')
    assert len(requests) == 1


def test_cancel_aim_cleans_up_striker_without_shooting(tmp_path, monkeypatch):
    controller, clock, requests = controller_with_clock(tmp_path, monkeypatch)
    controller.abort()
    clock[0] += 20
    controller.tick()
    assert controller.closed and not controller.aiming
    assert -1 not in controller.match.board.discs and not controller.match.board.active
    assert len(requests) == 1


def test_invalid_move_does_not_display_a_striker(tmp_path):
    def invalid(*args):
        return Decision({**MOVE, 'x': 999}, 'test', 'fixture', 0, {})
    controller = Controller(Settings(), tmp_path, max_turns=1, chooser=invalid, aim_seconds=2)
    while not controller.closed:
        controller.tick(background=False)
    assert controller.failures == 1 and -1 not in controller.match.board.discs


def test_presentation_reserves_official_stroke_time(tmp_path):
    controller = Controller(Settings(timeout=25), tmp_path, ruleset='icf', aim_seconds=3)
    try:
        assert controller.settings.timeout == 12
    finally:
        controller.abort()


@pytest.mark.parametrize('today,expected', (
    (date(2026, 10, 31), ['halloween']),
    (date(2026, 11, 3), []),
    (date(2026, 12, 25), ['new_year', 'christmas']),
    (date(2027, 1, 7), ['new_year', 'christmas']),
    (date(2027, 1, 11), []),
))
def test_calendar_seasons(today, expected):
    assert seasonal_themes(today) == expected


def test_new_board_is_random_and_different_from_previous():
    rng = random.Random(12)
    previous, seen = None, set()
    for _ in range(100):
        selected = choose_theme(previous, season='all', rng=rng)
        assert selected in THEMES and selected != previous
        seen.add(selected)
        previous = selected
    assert seen == set(THEMES)


@pytest.fixture
def pygame_display(monkeypatch):
    monkeypatch.setenv('SDL_VIDEODRIVER', 'dummy')
    monkeypatch.setenv('SDL_AUDIODRIVER', 'dummy')
    import pygame
    pygame.init()
    pygame.display.set_mode((1280, 900))
    yield pygame
    pygame.quit()


@pytest.mark.parametrize('theme', tuple(THEMES))
def test_generated_board_assets_load(theme, pygame_display):
    assert (assets_root() / 'boards' / (theme + '.png')).is_file()
    image = Artwork(pygame_display).board(theme)
    assert image.get_size() == (674, 674)


def test_supersampled_disc_edges_are_transparent_and_antialiased(pygame_display):
    artwork = Artwork(pygame_display)
    sprites = [artwork.disc(kind, 13.2857) for kind in ('white', 'black', 'queen', 'striker')]
    for sprite in sprites:
        assert sprite.get_at((0, 0)).a == 0
        assert any(0 < sprite.get_at((x, y)).a < 255 for x in range(sprite.get_width()) for y in range(sprite.get_height()))
    assert len({tuple(s.get_at(s.get_rect().center)) for s in sprites}) == 4


def test_ui_draws_selected_aim_line_and_theme_without_mutating_board(tmp_path, pygame_display):
    from game import Carrom
    app = Carrom(Settings(), tmp_path, board_theme='halloween')
    try:
        state = app.controller.match.state()
        board = app.controller.match.board
        board.prepare_shot(MOVE, 0)
        app.controller.aiming_move = dict(MOVE)
        app.controller.last_move = dict(MOVE)
        app.draw()
        target = (255, 222, 112)
        assert sum(tuple(app.screen.get_at((400, y)))[:3] == target for y in range(150, 800)) > 100
        assert app.controller.match.state() == state
        app.controller.abort()
        app.new_match()
        assert app.board_theme == 'halloween'
    finally:
        app.controller.abort()


def test_replay_restores_theme_and_aim_without_agent(tmp_path, monkeypatch, pygame_display):
    controller, clock, requests = controller_with_clock(tmp_path, monkeypatch)
    controller.abort()
    from replay_ui import ReplayApp
    app = ReplayApp(controller.recorder.path, directory=tmp_path / 'playback')
    try:
        index = next(i for i, frame in enumerate(app.replay_data.frames) if frame.get('aiming'))
        app.controller.apply(index)
        assert app.board_theme == 'halloween' and app.controller.aiming
        app.draw()
        assert len(requests) == 1
    finally:
        app.controller.abort()
