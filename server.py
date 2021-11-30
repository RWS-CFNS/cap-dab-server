import datetime                             # Date and time manipulator
import pyexpat                              # XML parser backend (only used for version check)
import xml.etree.ElementTree as Xml         # XML parser
from flask import Flask, Response, request  # HTTP server library

app = Flask(__name__)

# TODO add to command line parameters
strict = False
ns = { 'CAPv1.2': 'urn:oasis:names:tc:emergency:cap:1.2' }
# TODO take a textfile with a list of accepted senders as input

def get_timestamp():
    timezone = datetime.datetime.now(datetime.timezone.utc).astimezone().tzinfo

    # convert current time to string
    timestamp = datetime.datetime.now(tz=timezone).strftime('%Y-%m-%dT%H:%M:%S%z')

    # add a colon separator to the UTC offset (as required by the CAP v1.2 standard)
    return '{0}:{1}'.format(timestamp[:-2], timestamp[-2:])

def get_response():
    capns = ns['CAPv1.2']

    root = Xml.Element('alert')
    root.attrib = { 'xmlns': ns['CAPv1.2'] }

    identifier = Xml.SubElement(root, 'identifier')
    identifier.text = 'cfns.identifier.xxx' # FIXME don't hardcode

    sender = Xml.SubElement(root, 'sender')
    sender.text = 'test@test.com' # FIXME don't hardcode

    sent = Xml.SubElement(root, 'sent')
    sent.text = get_timestamp()

    status = Xml.SubElement(root, 'status')
    status.text = 'Actual'

    msgType = Xml.SubElement(root, 'msgType')
    msgType.text = 'Ack'

    scope = Xml.SubElement(root, 'scope')
    scope.text = 'Public'

    references = Xml.SubElement(root, 'references')
    references.text = 'TODO' # FIXME don't hardcore

    return Xml.tostring(root, encoding='unicode', xml_declaration=True)


def check_elements(root):
    # List of _required_ elements in the <alert> container
    alert_elements = ('identifier', 'sender', 'sent', 'status', 'msgType', 'scope')

    for e in alert_elements:
        if root.find(f'CAPv1.2:{e}', ns) is None:
            print(f'FAIL: required element missing from Alert container: {e}')
            return False

    # Check <msgType> separately because it influences whether the element <references> is required
    if root.find('CAPv1.2:msgType', ns).text == 'Cancel':
        if root.find('CAPv1.2:references', ns) is None:
            print(f'{"FAIL" if strict else "WARN"}: required element missing from Alert container: {e}')
            # We can just give a warning because the documentation isn't 100% clear on whether this
            # should really be enforced
            if strict:
                return False

    # check <scope>, as it should always be 'Public'
    if root.find('CAPv1.2:scope', ns).text != 'Public':
        print(f'{"FAIL" if strict else "WARN"}: invalid scope: {e}')
        # In production this should always be 'Public'. In a development/test environment this may
        # not always be this case.
        if strict:
            return False

    return True

# Main request handler
@app.post('/')
def index():
    content_type = request.content_type

    # Check if Content-Type header is set to an XML MIME type
    if not content_type.startswith('application/xml') and not content_type.startswith('text/xml'):
        print(f'{"FAIL" if strict else "WARN"}: invalid Content-Type: {content_type}')
        if strict:
            return Response(status=415)

    # Parse the received XML
    # TODO handle errors!
    root = Xml.fromstring(request.data)

    # Check the if the namespace matches what is expected of the main broker (CAP v1.2)
    if root.tag != f'{{{ns["CAPv1.2"]}}}alert':
        print(f'{"FAIL" if strict else "WARN"}: invalid namespace: {root.tag}')
        if strict:
            return Response(status=400)

    # Check if all required elements are present
    if not check_elements(root):
        return Response(status=400)

    xml = get_response()
    return Response(response=xml, status=200, content_type='application/xml; charset=utf-8')

# Check if the version of PyExpat is vulnerable to XML DDoS attacks (version 2.4.1+).
# See https://docs.python.org/3/library/xml.html#xml-vulnerabilitiesk
def version_check():
    ver = pyexpat.version_info
    assert ver[0] >= 2 and ver[1] >= 4 and ver[2] >= 1

def main():
    version_check()

if __name__ == '__main__':
    main()
