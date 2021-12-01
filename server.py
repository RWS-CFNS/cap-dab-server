#!/usr/bin/env python3

from flask import Flask, Response, request  # HTTP server library

from capparser import CAPParser

app = Flask(__name__)   # HTTP server
cp = None               # CAP XML parser

# TODO add to command line parameters
strict = False
host = '127.0.0.1'
port = 5000
debug = True
# TODO take a textfile with a list of accepted senders as input

# Main HTTP POST request handler
@app.post('/')
def index():
    content_type = request.content_type

    # Check if Content-Type header is set to an XML MIME type
    if not content_type.startswith('application/xml') and not content_type.startswith('text/xml'):
        print(f'{"FAIL" if strict else "WARN"}: invalid Content-Type: {content_type}')
        if strict:
            return Response(status=415)

    # parse the Xml into memory and check if all required elements present
    if not cp.parse(request.data):
        return Response(status=400)

    # Generate an appropriate response
    xml = cp.generate_response()
    return Response(response=xml, status=200, content_type='application/xml; charset=utf-8')

if __name__ == '__main__':
    # Initialize the CAP parser
    try:
        cp = CAPParser()
    except Exception as e:
        print(f'FAIL: {e}')
        exit(1)

    # start Flask (HTTP server)
    app.run(host=host, port=port, debug=debug)
