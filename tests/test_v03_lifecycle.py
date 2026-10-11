import json
import pytest
from agents import Decision
from engine import Board, Match
from runner import Controller
from settings import Settings
from official_rules import OfficialRules
from tournament import Tournament


def test_blocked_baseline_is_replayed_without_requesting_agent(tmp_path):
    def forbidden(*args):
        raise AssertionError('Agent queried on blocked baseline')
    controller = Controller(Settings(), tmp_path, chooser=forbidden, ruleset='icf')
    board = controller.match.board
    y = board.geometry.baseline_y[0]
    for i, disc in board.discs.items():
        disc['body'].position = (174 + i * 23, y)
    assert not board.has_legal_placement(0)
    controller.tick(background=False)
    controller.tick(background=False)
    assert controller.summary['cancelled'] and controller.summary['reason'] == 'law_142_replay'
    assert controller.decision_count == 0


def test_first_invalid_request_does_not_complete_break(tmp_path):
    def invalid(*args):
        raise ValueError('not a shot')
    controller = Controller(Settings(), tmp_path, chooser=invalid, ruleset='icf')
    controller.tick(background=False)
    controller.tick(background=False, advance=False)
    assert not controller.match.rules.break_made
    assert controller.match.rules.debt == [0, 0]
    controller.abort()


def test_timed_out_worker_cannot_shoot_in_later_turn(tmp_path, monkeypatch):
    controller = Controller(Settings(timeout=1), tmp_path, ruleset='icf')
    controller.busy, controller.request_serial, controller.request_started = True, 1, 1
    monkeypatch.setattr('runner.time.monotonic', lambda: 3)
    controller.tick(advance=False)
    assert controller.failures == 1 and controller.match.rules.turn == 1
    controller.busy, controller.request_serial, controller.request_started = True, 2, 3
    stale = Decision({'x': 380, 'angle': 270, 'power': .7, 'comment': ''}, 'demo', 'local', 0, {})
    controller.results.put((1, stale, None))
    controller.tick(advance=False)
    assert not controller.match.board.active and controller.decision_count == 1
    controller.abort()


def test_queen_and_own_overboard_return_first_in_order():
    rules = OfficialRules()
    rules.break_made = True
    result = rules.resolve([], overboard=[(2, 'black'), (1, 'white'), (0, 'queen')])
    assert result.returned == [0, 1, 2]
    assert set(result.return_kinds.values()) == {'centre'}


def test_extra_board_toss_is_recorded_and_reproducible():
    games = [Tournament(toss_seed=17), Tournament(toss_seed=17)]
    for game in games:
        for i in range(8):
            game.record_board(i % 2, 1)
        assert game.breaker == game.history[-1]['extra_board_toss']
    assert games[0].breaker == games[1].breaker


@pytest.mark.parametrize('event', ['disqualification', 'concede_match'])
def test_administrative_match_loss(event):
    game = Tournament()
    game.referee(event, 0)
    assert game.finished and game.winner == 1


def test_two_game_concessions_finish_match():
    game = Tournament()
    game.referee('concede_game', 1)
    assert game.game_number == 2 and game.games == [1, 0]
    game.referee('concede_game', 1)
    assert game.finished and game.winner == 0


def test_quarter_final_sides_change_only_at_thirteen():
    game = Tournament(game_number=3, round_stage='quarter')
    for i in range(4):
        game.record_board(i % 2, 1)
    assert not game.midgame_swapped
    game.record_board(0, 11)
    assert game.midgame_swapped


def test_source_packaging_check_uses_real_sdks_without_network(tmp_path):
    from selfcheck import run
    result = run(tmp_path)
    assert result['requests'] == ['/v1/responses', '/v1/messages']
    assert result['replay_frames'] > 20


def test_physics_timeout_does_not_award_official_board(tmp_path, monkeypatch):
    controller = Controller(Settings(), tmp_path, ruleset='icf')
    controller.match.shoot({'x': 380, 'angle': 270, 'power': .7})
    def fail_to_settle():
        board = controller.match.board
        if -1 in board.discs:
            board.remove(-1)
        board.active, board.timed_out = False, True
    monkeypatch.setattr(controller.match.board, 'step', fail_to_settle)
    controller.tick()
    assert controller.summary['reason'] == 'physics_timeout_aborted'
    assert controller.summary['winner'] is None and controller.summary['board_points'] == [0, 0]


def test_csv_identifies_models_after_changing_breaker(tmp_path, monkeypatch):
    import csv
    import game
    monkeypatch.setattr('sys.argv', ['game.py', '--mode', 'demo', '--headless', '--first-player', '1',
                                   '--max-turns', '1', '--log-dir', str(tmp_path), '--no-replay'])
    game.main()
    with next(tmp_path.glob('series_*.csv')).open(encoding='utf-8-sig') as file:
        row = next(csv.DictReader(file))
    assert 'chatgpt_coins' in row and 'claude_coins' in row and 'white' not in row
