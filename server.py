import datetime                             # Date and time manipulator
import pyexpat                              # XML parser backend (only used for version check)
import xml.etree.ElementTree as Xml         # XML parser
from flask import Flask, Response, request  # HTTP server library

app = Flask(__name__)

# timestamp format specified in the CAP v1.2 standard
TIMESTAMP_FORMAT = '%Y-%m-%dT%H:%M:%S%z'

# TODO add to command line parameters
strict = False
ns = { 'CAPv1.2': 'urn:oasis:names:tc:emergency:cap:1.2' }
# TODO take a textfile with a list of accepted senders as input

# Generate a current timestamp
def generate_timestamp():
    timezone = datetime.datetime.now(datetime.timezone.utc).astimezone().tzinfo

    # convert current time to string
    timestamp = datetime.datetime.now(tz=timezone).strftime(TIMESTAMP_FORMAT)

    # add a colon separator to the UTC offset (as required by the CAP v1.2 standard)
    return '{0}:{1}'.format(timestamp[:-2], timestamp[-2:])

# Check if the timestamp that has been received is valid
def check_timestamp(timestamp):
    try:
        return datetime.datetime.strptime(timestamp, TIMESTAMP_FORMAT)
    except ValueError:
        return None

# Generate an acknowledgement
# This applies to all types of requests as they all expect the same format of acknowledgement.
def get_response():
    capns = ns['CAPv1.2']

    root = Xml.Element('alert')
    root.attrib = { 'xmlns': ns['CAPv1.2'] }

    identifier = Xml.SubElement(root, 'identifier')
    identifier.text = 'cfns.identifier.xxx' # FIXME don't hardcode

    sender = Xml.SubElement(root, 'sender')
    sender.text = 'test@test.com' # FIXME don't hardcode

    sent = Xml.SubElement(root, 'sent')
    sent.text = generate_timestamp()

    status = Xml.SubElement(root, 'status')
    status.text = 'Actual'

    msgType = Xml.SubElement(root, 'msgType')
    msgType.text = 'Ack'

    scope = Xml.SubElement(root, 'scope')
    scope.text = 'Public'

    references = Xml.SubElement(root, 'references')
    references.text = 'TODO' # FIXME don't hardcore

    return Xml.tostring(root, encoding='unicode', xml_declaration=True)

def check_info_elements(info):
    # List of _required_ elements in the <info> container
    info_elements = ('category', 'event', 'urgency', 'severity', 'certainty')

    # check for the presence of required elements
    for e in info_elements:
        if info.find(f'CAPv1.2:{e}', ns) is None:
            print(f'FAIL: required element missing from <info> container: {e}')
            return False

    # check <language>, as it should basically always be present
    if info.find(f'CAPv1.2:language', ns) is None:
        print(f'{"FAIL" if strict else "WARN"}: required element missing from <info> container: language')

        # Allow when not running in strict mode
        if strict:
            return False

    # check <category>, it should always have a value of 'Safety'
    # though this may be different in practise, so we just throw a warning
    category = info.find(f'CAPv1.2:category', ns).text
    if category != 'Safety':
        print(f'WARN: invalid category: {category}')

    # these fields should always return 'Unknown' from an NL Subbroker
    # though this may be different in practise, so we just throw a warning
    urgency = info.find(f'CAPv1.2:urgency', ns).text
    if urgency != 'Unknown':
        print(f'WARN: invalid urgency: {urgency}')
    severity = info.find(f'CAPv1.2:severity', ns).text
    if severity != 'Unknown':
        print(f'WARN: invalid severity: {severity}')
    certainty = info.find(f'CAPv1.2:certainty', ns).text
    if certainty != 'Unknown':
        print(f'WARN: invalid certainty: {certainty}')

    # check if the <effective> and <expires> timestamps are formatted correctly
    effective = info.find('CAPv1.2:effective', ns).text
    if check_timestamp(effective) is None:
        print(f'FAIL: invalid <effective> timestamp format: {effective}')
        return False
    expires = info.find('CAPv1.2:expires', ns).text
    if check_timestamp(expires) is None:
        print(f'FAIL: invalid <expires> timestamp format: {expires}')
        return False

    return True

def check_alert_elements(alert):
    # List of _required_ elements in the <alert> container
    alert_elements = ('identifier', 'sender', 'sent', 'status', 'msgType', 'scope')

    # check for the presence of required elements
    for e in alert_elements:
        if alert.find(f'CAPv1.2:{e}', ns) is None:
            print(f'FAIL: required element missing from <alert> container: {e}')
            return False

    # check if the timestamp is formatted correctly
    timestamp = alert.find('CAPv1.2:sent', ns).text
    if check_timestamp(timestamp) is None:
        print(f'FAIL: invalid <sent> timestamp format: {timestamp}')
        return False

    msgType = alert.find('CAPv1.2:msgType', ns).text
    status = alert.find('CAPv1.2:status', ns).text

    if msgType == 'Alert':
        # check if <info> is present when <msgType> has the value 'Alert'
        # This is required by the standard, but poorly implemented in practise.
        # Even the "link test" example in the One2Many document doesn't demonstrate this properly
        #
        # We will ignore this (even in strict mode) when <status> has the value 'Test'
        if status != 'Test':
            info = alert.find(f'CAPv1.2:info', ns)
            if info is None:
                print('FAIL: required element missing from <alert> container: info')
                return False

            # check the <info> container element
            if not check_info_elements(info):
                return False
    elif msgType == 'Cancel':
        # Check <msgType> separately because it influences whether the element <references> is required
        if alert.find('CAPv1.2:references', ns) is None:
            print(f'{"FAIL" if strict else "WARN"}: required element missing from <alert> container: references')
            # We can just give a warning because the documentation isn't 100% clear on whether this
            # should really be enforced
            if strict:
                return False

    # check <scope>, as it should always be 'Public'
    scope = alert.find('CAPv1.2:scope', ns).text
    if scope != 'Public':
        print(f'{"FAIL" if strict else "WARN"}: invalid scope: {scope}')
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
    try:
        root = Xml.fromstring(request.data)
    except Xml.ParseError:
        print('FAIL: invalid XML schema received')
        return Response(status=400)

    # Check the if the namespace matches what is expected of the main broker (CAP v1.2)
    if root.tag != f'{{{ns["CAPv1.2"]}}}alert':
        print(f'{"FAIL" if strict else "WARN"}: invalid namespace: {root.tag}')
        if strict:
            return Response(status=400)

    # Check if all required elements are present
    if not check_alert_elements(root):
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
