"""Windows windowed entry point, with safe error reports for unattended runs."""
import os
import sys
from pathlib import Path

os.environ.setdefault('PYGAME_HIDE_SUPPORT_PROMPT', '1')


def launch():
    import game
    if len(sys.argv) == 1:
        sys.argv.append('--official-match')
    try:
        game.main()
    except (Exception, SystemExit) as exc:
        if isinstance(exc, SystemExit) and not exc.code:
            return
        from settings import project_root
        # SDK errors can contain credentials. Only the class is written here.
        kind = type(exc).__name__
        message = f'Carrom could not complete this run ({kind}). Check .env and the supplied options.'
        report = {'ok': False, 'error_type': kind}
        import json
        try:
            (project_root() / 'last-error.json').write_text(json.dumps(report), encoding='utf-8')
            if '--report' in sys.argv:
                path = Path(sys.argv[sys.argv.index('--report') + 1])
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(report), encoding='utf-8')
        except (OSError, IndexError):
            pass
        if '--headless' not in sys.argv and '--self-test' not in sys.argv and '--report' not in sys.argv:
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, 'Carrom AI Showdown', 0x10)
        raise SystemExit(1) from None


if __name__ == '__main__':
    launch()
