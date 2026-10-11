import json
from types import SimpleNamespace as NS
import pytest
from agents import parse_move, decide, MOVE_SCHEMA, INSTRUCTIONS
from engine import Match
from settings import Settings

GOOD = {'x': 380, 'angle': 270, 'power': 0.7, 'comment': 'test'}


@pytest.mark.parametrize('bad', [[], {}, {**GOOD, 'x': 999}, {**GOOD, 'angle': -90},
    {**GOOD, 'power': 7}, {**GOOD, 'x': True}, {**GOOD, 'x': '380'}, {**GOOD, 'power': float('nan')},
    {**GOOD, 'comment': None}, {**GOOD, 'comment': 'a' * 151}, {**GOOD, 'extra': 1}])
def test_reject_invalid_model_moves(bad):
    with pytest.raises(ValueError):
        parse_move(json.dumps(bad))


@pytest.mark.parametrize('text', ['not JSON', 'prefix ' + json.dumps(GOOD), '{"x":1,"x":2}', 'null'])
def test_reject_invalid_json(text):
    with pytest.raises(ValueError):
        parse_move(text)


def test_plain_and_fenced_moves():
    assert parse_move(json.dumps(GOOD)) == GOOD
    assert parse_move('```json\n' + json.dumps(GOOD) + '\n```') == GOOD


class FakeCreate:
    def __init__(self, response):
        self.response, self.kwargs = response, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def api_settings():
    return Settings(mode='api', openai_key='fake-openai', anthropic_key='fake-claude',
                    openai_model='configured-openai', anthropic_model='configured-claude')


def test_provider_contracts_share_schema_and_instructions():
    state = Match().state()
    openai = FakeCreate(NS(status='completed', output_text=json.dumps(GOOD), usage=NS(input_tokens=12, output_tokens=8)))
    claude = FakeCreate(NS(stop_reason='end_turn', content=[NS(type='text', text=json.dumps(GOOD))],
                           usage=NS(input_tokens=14, output_tokens=9)))
    first = decide(state, api_settings(), NS(responses=openai))
    state['player'] = 'Claude'
    state['rules']['player_index'] = 1
    second = decide(state, api_settings(), NS(messages=claude))
    assert first.move == second.move == GOOD
    assert openai.kwargs['text']['format']['schema'] == claude.kwargs['output_config']['format']['schema'] == MOVE_SCHEMA
    assert openai.kwargs['instructions'] == claude.kwargs['system'] == INSTRUCTIONS
    assert json.loads(claude.kwargs['messages'][0]['content']) == state
    assert openai.kwargs['store'] is False
    assert first.usage == {'input_tokens': 12, 'output_tokens': 8}


@pytest.mark.parametrize('status', ['incomplete', 'failed'])
def test_openai_incomplete_is_not_a_move(status):
    fake = FakeCreate(NS(status=status, output_text=json.dumps(GOOD)))
    with pytest.raises(ValueError):
        decide(Match().state(), api_settings(), NS(responses=fake))


@pytest.mark.parametrize('reason', ['max_tokens', 'refusal'])
def test_claude_incomplete_is_not_a_move(reason):
    state = Match(first_player=1).state()
    fake = FakeCreate(NS(stop_reason=reason, content=[]))
    with pytest.raises(ValueError):
        decide(state, api_settings(), NS(messages=fake))


def test_demo_never_uses_client():
    decision = decide(Match().state(), Settings(), NS())
    assert decision.source == 'demo' and decision.usage == {}


def test_api_missing_config_rejected_without_network(tmp_path):
    path = tmp_path / '.env'
    path.write_text('MODE=api\n', encoding='utf-8')
    with pytest.raises(ValueError, match='OPENAI_API_KEY'):
        Settings.load(path)


def test_keys_not_in_repr_or_state(tmp_path):
    settings = api_settings()
    assert 'fake-openai' not in repr(settings) and 'fake-claude' not in repr(settings)
    assert 'API_KEY' not in json.dumps(Match().state())


def test_env_loaded_independent_of_cwd(tmp_path, monkeypatch):
    path = tmp_path / '.env'
    path.write_text('MODE=demo\nAPI_TIMEOUT=10\n', encoding='utf-8')
    monkeypatch.chdir(tmp_path.parent)
    assert Settings.load(path).timeout == 10
