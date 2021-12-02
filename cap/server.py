import threading                            # Threading support (for running Flask in the background)
import logging                              # Logging facilities
import logging.handlers                     # Logging handlers
import re                                   # For removing color from werkzeug's log messages
import pyexpat                              # CAP XML parser backend (only used for version check)
import os                                   # For redirecting Flask's logging output to a file using an env. variable
from flask import Flask, Response, request  # Flask HTTP server library
from werkzeug.serving import make_server    # Flask backend
from cap.parser import CAPParser            # CAP XML parser (internal)
from cap.parser import logger_strict        # More logging facilities

cp = None               # CAP XML parser
app = Flask(__name__)   # Flask app

# Werkzeug adds colors to the log file by default.
# Unfortunately, dialog can't display this, so this has to be filtered out.
class StripEsc(logging.Filter):
    def __init__(self):
        # Don't bother with just colors, removing all escape sequences is more straightforward
        self.esc = re.compile(r'(?:\x1B[@-_]|[\x80-\x9F])[0-?]*[ -/]*[@-~]')

    def strip(self, s):
        try:
            return self.esc.sub('', s)
        except:
            return s

    def filter(self, record):
        if record:
            if record.msg:
                record.msg = self.strip(record.msg)
            if type(record.args) is tuple:
                record.args = tuple(map(self.strip, record.args))

        return True
strip_esc = StripEsc()

# Main HTTP POST request handler
@app.post('/')
def index():
    content_type = request.content_type

    # Check if Content-Type header is set to an XML MIME type
    if not content_type.startswith('application/xml') and not content_type.startswith('text/xml'):
        if logger_strict(app, f'{"FAIL" if strict else "WARN"}: invalid Content-Type: {content_type}'):
            return Response(status=415)

    # Initialize the CAP parser
    try:
        cp = CAPParser(app, strict)
    except Exception as e:
        app.logger.error(f'FAIL: {e}')
        exit(1)

    # Parse the Xml into memory and check if all required elements present
    if not cp.parse(request.data):
        return Response(status=400)

    # Generate an appropriate response
    xml = cp.generate_response()
    return Response(response=xml, status=200, content_type='application/xml; charset=utf-8')

# Actual Werkzeug/Flask server thread
class CAPServer(threading.Thread):
    def __init__(self, app, host, port):
        threading.Thread.__init__(self)

        self.server = make_server(host, port, app)
        self.ctx = app.app_context()
        self.ctx.push()

    def run(self):
        self.server.serve_forever()

    def join(self):
        print('Waiting for CAP HTTP server to terminate... ', end='', flush=True)
        self.server.shutdown()
        print('OK')

def cap_server(logdir, host, port, strict_parsing):
    global strict
    strict = strict_parsing

    # Check if the version of PyExpat is vulnerable to XML DDoS attacks (version 2.4.1+).
    # See https://docs.python.org/3/library/xml.html#xml-vulnerabilitiesk
    ver = pyexpat.version_info
    if ver[0] < 2 or ver[1] < 4 or ver[2] < 1:
        raise ModuleNotFoundError('PyExpat 2.4.1+ is required but not found on this system')

    print('Starting up CAP HTTP server...')

    # Remove Flask and werkzeug's default logging handler(s).
    for h in app.logger.handlers:
        app.logger.removeHandler(h)
    for h in logging.getLogger('werkzeug').handlers:
        app.logger.removeHandler(h)

    # Setup log target
    handler = logging.FileHandler('log/capsrv.log') # FIXME don't hardcode
    handler.setFormatter(logging.Formatter(fmt='%(asctime)s [%(levelname)s] %(message)s'))
    handler.setLevel(logging.INFO)
    handler.addFilter(strip_esc)

    # Setup the logging file for werkzeug and Flask
    app.logger.addHandler(handler)
    logging.getLogger('werkzeug').addHandler(handler)

    # Start the werkzeug/Flask thread
    server = CAPServer(app, host, port)
    server.start()

    return server
