"""
Desktop Launch Agent
Run this in an interactive user session (startup or scheduled task "Run only when user is logged on").
Listens on localhost and accepts signed launch requests from services.
"""

import os
import json
import logging
import subprocess
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

logger = logging.getLogger('desktop_agent')
logging.basicConfig(level=logging.INFO)

PORT = int(os.environ.get('LAUNCH_AGENT_PORT', '5001'))
SECRET = os.environ.get('LAUNCH_AGENT_SECRET', '')


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != '/launch':
            self.send_response(404)
            self.end_headers()
            return

        auth = self.headers.get('Authorization', '')
        if not auth.startswith('Bearer ') or auth.split(' ', 1)[1] != SECRET:
            self.send_response(403)
            self.end_headers()
            return

        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length)
        try:
            payload = json.loads(body)
            app = payload.get('app')
            args = payload.get('args') or []
            if not app:
                self.send_response(400)
                self.end_headers()
                return

            # Launch using the native method for the platform
            try:
                if os.name == 'nt':
                    try:
                        os.startfile(app)
                        logger.info('Launched via os.startfile: %s', app)
                    except Exception:
                        subprocess.Popen([app] + args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                        logger.info('Launched via subprocess: %s %s', app, args)
                else:
                    subprocess.Popen([app] + args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                    logger.info('Launched: %s %s', app, args)

                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')
            except Exception as e:
                logger.exception('Failed to launch')
                self.send_response(500)
                self.end_headers()
                self.wfile.write(b'{"status":"error"}')

        except Exception:
            logger.exception('Invalid request')
            self.send_response(400)
            self.end_headers()


def run():
    server = ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    logger.info('Desktop agent listening on 127.0.0.1:%d', PORT)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()


if __name__ == '__main__':
    run()
