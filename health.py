"""
Мини HTTP-сервер для Back4App / Render и подобных платформ.
Они ждут, что контейнер слушает TCP-порт — иначе деплой падает.
Наш бот работает через polling и порт ему не нужен, поэтому поднимаем
заглушку на отдельном потоке. Она отвечает 200 OK на любой запрос.
"""
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is running")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, format, *args):
        pass  # не спамим в логи


def start_health_server():
    port = int(os.getenv("PORT", "8080"))
    server = HTTPServer(("0.0.0.0", port), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"[health] HTTP-заглушка слушает порт {port}")