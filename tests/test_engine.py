import math
import json
import os
import pytest
from board import DT, COIN_R, POCKETS, initial_coins
from engine import Board, Match
from runner import Controller, run_headless
from settings import Settings
from agents import Decision, local_move


def test_initial_rack_has_19_nonoverlapping_discs():
    coins = initial_coins()
    assert len(coins) == 19
    assert [kind for _, kind, _ in coins].count('white') == 9
    assert [kind for _, kind, _ in coins].count('black') == 9
    for i, (_, _, pos) in enumerate(coins):
        for _, _, other in coins[i + 1:]:
            assert math.dist(pos, other) >= COIN_R * 2


def test_overlap_rejected():
    board = Board()
    board.add_disc(100, 'white', (380, 665))
    with pytest.raises(ValueError):
        board.shoot({'x': 380, 'angle': 270, 'power': 0.7}, 0)
    assert not board.active and -1 not in board.discs


def test_fixed_step_shot_settles_without_timeout():
    board = Board()
    board.shoot({'x': 380, 'angle': 270, 'power': 0.75}, 0)
    while board.active:
        board.step()
    assert board.steps * DT < 15 and not board.timed_out
    assert -1 not in board.discs
    assert all(d['body'].velocity.length == 0 for d in board.discs.values())


def test_pocket_removes_disc_and_queen_return_is_safe():
    board = Board()
    board.discs[0]['body'].position = POCKETS[0]
    board.active = True
    board.step()
    assert (0, 'queen') in board.pocketed and 0 not in board.discs
    board.active = False
    board.return_coin(0)
    queen_pos = board.discs[0]['body'].position
    assert all((d['body'].position - queen_pos).length >= 25 for i, d in board.discs.items() if i != 0)


@pytest.mark.parametrize('player,pos,coin_id,kind', [
    (0, (500, 500), 1, 'white'), (0, (260, 500), 1, 'white'),
    (1, (500, 260), 2, 'black'), (1, (260, 260), 2, 'black')])
def test_actual_shot_can_enter_each_corner_pocket(player, pos, coin_id, kind):
    board = Board()
    for original_id in list(board.discs):
        board.remove(original_id)
    board.add_disc(coin_id, kind, pos)
    state = {'player': ('ChatGPT', 'Claude')[player], 'coins': board.coins()}
    move = local_move(state)
    board.shoot(move, player)
    while board.active:
        board.step()
    assert (coin_id, kind) in board.pocketed


def test_completed_match_conserves_all_coin_ids(tmp_path):
    controller = Controller(Settings(), tmp_path, max_turns=30)
    while not controller.closed:
        controller.tick(240, background=False)
        match = controller.match
        present = {i for i in match.board.discs if i != -1}
        banked = set(match.rules.banked[0] + match.rules.banked[1])
        pending_pockets = {i for i, kind in match.board.pocketed if kind != 'striker'} if match.board.active else set()
        queen = {0} if match.rules.queen_pending is not None or match.rules.queen_owner is not None else set()
        assert present | banked | pending_pockets | queen == set(range(19))
        assert len(present) + len(banked) + len(pending_pockets) + len(queen) == 19
    assert controller.summary['turns'] <= 30 and controller.summary['failures'] == 0
    entries = [json.loads(line) for line in controller.log.path.read_text(encoding='utf-8').splitlines()]
    assert entries[0]['event'] == 'match_start' and entries[-1]['event'] == 'match_end'


def test_failed_api_turns_finish_and_do_not_leak_exception(tmp_path):
    def failed(state, settings):
        raise RuntimeError('secret-key-should-never-be-logged')
    controller = Controller(Settings(), tmp_path, max_turns=3, chooser=failed)
    while not controller.closed:
        controller.tick(240, background=False)
    assert controller.summary['failures'] == 3 and controller.summary['turns'] == 3
    assert 'secret-key' not in controller.log.path.read_text(encoding='utf-8')


def test_pause_prevents_next_request(tmp_path):
    controller = Controller(Settings(), tmp_path, max_turns=3)
    controller.tick(advance=False)
    assert not controller.busy and controller.decision_count == 0
    controller.abort()


def test_invalid_placement_counts_as_turn(tmp_path):
    def invalid(state, settings):
        return Decision({'x': 999, 'angle': 270, 'power': 0.7, 'comment': 'invalid'}, 'test', 'test', 0, {})
    controller = Controller(Settings(), tmp_path, max_turns=2, chooser=invalid)
    while not controller.closed:
        controller.tick(background=False)
    assert controller.summary['turns'] == 2 and controller.summary['failures'] == 2


def test_repeatable_headless_matches(tmp_path):
    first = run_headless(Settings(), tmp_path / 'a', max_turns=20)
    second = run_headless(Settings(), tmp_path / 'b', max_turns=20)
    assert {k: v for k, v in first.items() if k not in ('log', 'replay')} == {k: v for k, v in second.items() if k not in ('log', 'replay')}


def test_ui_smoke(tmp_path, monkeypatch):
    monkeypatch.setenv('SDL_VIDEODRIVER', 'dummy')
    monkeypatch.setenv('SDL_AUDIODRIVER', 'dummy')
    monkeypatch.setenv('PYGAME_HIDE_SUPPORT_PROMPT', '1')
    from game import Carrom
    app = Carrom(Settings(), tmp_path, max_turns=1)
    screenshot = tmp_path / 'smoke.png'
    app.run(frames=3, screenshot=screenshot)
    assert screenshot.stat().st_size > 1000
