#!/usr/bin/env python3
"""
Простой сервер синхронизации выбора Даша/Илья.
GET /picks.json — получить текущий выбор
POST /picks.json — обновить выбор
"""

import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path

PICKS_FILE = Path('/root/личное/поездка в Самару/picks.json')

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/picks.json':
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            data = PICKS_FILE.read_text() if PICKS_FILE.exists() else '{}'
            self.wfile.write(data.encode())
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self):
        if self.path == '/picks.json':
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length).decode()
            try:
                data = json.loads(body)
                PICKS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2))
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(b'{"ok":true}')
            except json.JSONDecodeError:
                self.send_response(400)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def log_message(self, format, *args):
        pass  # тихий режим

if __name__ == '__main__':
    server = HTTPServer(('127.0.0.1', 8091), Handler)
    print('Sync server running on :8091')
    server.serve_forever()
