from flask import Flask, Response, request  # HTTP server library
import logging                              # Logging facilities
import pyexpat                              # CAP XML parser backend (only used for version check)
from cap.parser import CAPParser            # CAP XML parser (internal)
from cap.parser import logging_strict       # More logging facilities
import os                                   # For redirecting Flask's logging output to a file using an env. variable

app = Flask(__name__)   # HTTP server
cp = None               # CAP XML parser

# Main HTTP POST request handler
@app.post('/')
def index():
    content_type = request.content_type

    # Check if Content-Type header is set to an XML MIME type
    if not content_type.startswith('application/xml') and not content_type.startswith('text/xml'):
        if logging_strict(f'{"FAIL" if strict else "WARN"}: invalid Content-Type: {content_type}'):
            return Response(status=415)

    # Initialize the CAP parser
    try:
        cp = CAPParser(strict)
    except Exception as e:
        logging.error(f'FAIL: {e}')
        exit(1)

    # parse the Xml into memory and check if all required elements present
    if not cp.parse(request.data):
        return Response(status=400)

    # Generate an appropriate response
    xml = cp.generate_response()
    return Response(response=xml, status=200, content_type='application/xml; charset=utf-8')

def cap_server(host, port, debug, strict_parsing):
    global strict

    # Check if the version of PyExpat is vulnerable to XML DDoS attacks (version 2.4.1+).
    # See https://docs.python.org/3/library/xml.html#xml-vulnerabilitiesk
    ver = pyexpat.version_info
    if ver[0] < 2 or ver[1] < 4 or ver[2] < 1:
        raise ModuleNotFoundError('PyExpat 2.4.1+ is required but not found on this system')

    strict = strict_parsing

    os.environ['WERKZEUG_RUN_MAIN'] = 'true'

    # start Flask (HTTP server)
    app.run(host=host, port=port, debug=debug, use_reloader=False)
