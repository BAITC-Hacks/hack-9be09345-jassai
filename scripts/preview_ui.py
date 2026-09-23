"""Explicit frontend preview only. Real application: use teammate A/B's launcher."""
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, unquote
import argparse

ROOT = Path(__file__).resolve().parents[1] / 'frontend'

class PreviewHandler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        name = unquote(urlsplit(path).path)
        if name.startswith('/static/'):
            name = name[len('/static/'):]
        else:
            name = name.lstrip('/') or 'index.html'
        resolved = (ROOT / name).resolve()
        if not resolved.is_relative_to(ROOT):
            return str(ROOT / '__not_found__')
        return str(resolved)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Career Quest: synthetic frontend preview')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    print(f'Preview only: http://127.0.0.1:{args.port}/?preview=employee', flush=True)
    ThreadingHTTPServer(('127.0.0.1', args.port), PreviewHandler).serve_forever()
