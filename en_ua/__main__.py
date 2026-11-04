"""Tray application entry point and offline diagnostics."""

import argparse
import json
import os
import sys

from .core import Dictionaries, Detector, convert
from . import __version__


def doctor():
    from .config import Config
    import importlib.util
    checks = {}
    checks['version'] = __version__
    checks['session'] = os.environ.get('XDG_SESSION_TYPE', 'unknown')
    checks['background_supported'] = checks['session'] == 'x11'
    checks['x11_library'] = bool(importlib.util.find_spec('Xlib'))
    checks['enabled'] = Config().data['enabled']
    checks['autostart'] = Config().data['autostart']
    try:
        Dictionaries()
        checks['dictionaries'] = 'English and Ukrainian available'
    except RuntimeError as error:
        checks['dictionaries'] = str(error)
    try:
        import gi
        gi.require_version('AyatanaAppIndicator3', '0.1')
        checks['tray_library'] = True
    except (ImportError, ValueError) as error:
        checks['tray_library'] = str(error)
    return checks



def main(argv=None):
    parser = argparse.ArgumentParser(description='Offline English/Ukrainian layout correction')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--doctor', action='store_true', help='print desktop and dictionary status')
    group.add_argument('--status', action='store_true', help='print live background monitor status')
    group.add_argument('--quit', action='store_true', help='stop the running tray utility')
    group.add_argument('--background', action='store_true', help='start quietly at sign-in')
    group.add_argument('--run', action='store_true', help='start the tray utility')
    group.add_argument('--setup', action='store_true', help='open tray settings (default)')
    group.add_argument('--convert', metavar='TEXT', help='convert physical key positions, no dictionary needed')
    group.add_argument('--detect', metavar='RAW_US_TEXT', help='correct one token using installed dictionaries')
    parser.add_argument('--to', choices=('en', 'uk'), default='uk', help='conversion direction')
    parser.add_argument('--language', choices=('en', 'uk'), default='en', help='current mode for --detect')
    args = parser.parse_args(argv)
    try:
        if args.convert is not None:
            print(convert(args.convert, args.to))
        elif args.detect is not None:
            result = Detector(Dictionaries()).decide(args.detect, args.language)
            print(json.dumps(result.__dict__, ensure_ascii=False))
        elif args.doctor:
            print(json.dumps(doctor(), ensure_ascii=False, indent=2))
        else:
            from .tray import run
            return run(['--status'] if args.status else ['--quit'] if args.quit else
                       ['--background'] if args.background else ['--run'] if args.run else ['--setup'])
    except (RuntimeError, ImportError, ValueError) as error:
        print(f'en-ua-switcher: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
