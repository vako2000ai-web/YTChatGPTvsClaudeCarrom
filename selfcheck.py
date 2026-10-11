"""Packaging smoke check. HTTP is explicitly replaced with local MockTransport."""
import json
import platform
import sys
from pathlib import Path


def run(directory):
    import httpx2 as httpx
    import openai
    import anthropic
    import pygame
    import pymunk
    import websocket
    from agents import decide
    from engine import Match
    from runner import run_headless, VERSION
    from replay import Replay
    from settings import Settings
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    move = {'x': 380, 'angle': 270, 'power': .65, 'comment': 'Packaging check'}
    requests = []
    def transport(request):
        requests.append(request.url.path)
        if request.url.path.endswith('/responses'):
            data = {'id': 'resp_check', 'object': 'response', 'created_at': 0,
                    'status': 'completed', 'model': 'offline-check',
                    'output': [{'type': 'message', 'id': 'msg_check', 'role': 'assistant', 'status': 'completed',
                                'content': [{'type': 'output_text', 'text': json.dumps(move), 'annotations': []}]}],
                    'usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2}}
        else:
            data = {'id': 'msg_check', 'type': 'message', 'role': 'assistant', 'model': 'offline-check',
                    'stop_reason': 'end_turn', 'stop_sequence': None,
                    'content': [{'type': 'text', 'text': json.dumps(move)}],
                    'usage': {'input_tokens': 1, 'output_tokens': 1}}
        return httpx.Response(200, json=data)
    settings = Settings(mode='api', openai_key='offline-placeholder', anthropic_key='offline-placeholder',
                        openai_model='offline-check', anthropic_model='offline-check')
    for player, provider in ((0, openai.OpenAI), (1, anthropic.Anthropic)):
        with httpx.Client(transport=httpx.MockTransport(transport)) as http:
            with provider(api_key='offline-placeholder', http_client=http, max_retries=0) as client:
                assert decide(Match(first_player=player, ruleset='icf').state(), settings, client).move == move
    result = run_headless(Settings(), directory, max_turns=2, ruleset='icf')
    replay = Replay(result['replay'])
    assert replay.summary['reason'] == result['reason']
    return {'version': VERSION, 'frozen': bool(getattr(sys, 'frozen', False)),
            'platform': platform.platform(), 'sdk_http': 'local MockTransport only',
            'requests': requests, 'pygame': pygame.version.ver, 'pymunk': pymunk.version,
            'openai': openai.__version__, 'anthropic': anthropic.__version__,
            'websocket': websocket.__version__, 'replay_frames': len(replay.frames), 'board': result}
