import pyexpat                              # XML parser backend (only used for version check)
import xml.etree.ElementTree as Xml         # XML parser
from flask import Flask, Response, request  # HTTP server library
from io import StringIO

app = Flask(__name__)

# add to command line parameters
strict = False
ns = { 'cap': 'urn:oasis:names:tc:emergency:cap:1.2' }

def check_elements(root):
    # list of _required_ elements in the Alert container
    alert_elements = ('identifier', 'sender', 'sent', 'status', 'msgType', 'scope')

    for e in alert_elements:
        if root.find(f'cap:{e}', ns) is None:
            print(f'FAIL: required element missing from Alert container: {e}')
            return False

    # check "msgType" separately because it influences whether the element "references" is required
    if root.find('cap:msgType', ns).text == 'Cancel':
        if root.find('cap:references', ns) is None:
            print(f'{"FAIL" if strict else "WARN"}: required element missing from Alert container: {e}')
            # we can just give a warning because the documentation isn't 100% clear on whether this
            # should really be enforced
            if strict:
                return False

    return True

# Main request handler
@app.post('/')
def index():
    content_type = request.content_type

    # check if Content-Type header is set to an XML MIME type
    if not content_type.startswith('application/xml') and not content_type.startswith('text/xml'):
        print(f'{"FAIL" if strict else "WARN"}: invalid Content-Type: {content_type}')
        if strict:
            return Response(status=415)

    # parse the received XML
    # TODO handle errors!
    root = Xml.fromstring(request.data)

    # check the if the namespace matches what is expected of the main broker (CAP v1.2)
    if root.tag != f'{{{ns["cap"]}}}alert':
        print(f'{"FAIL" if strict else "WARN"}: invalid namespace: {root.tag}')
        if strict:
            return Response(status=400)

    # remove the namespace for easier handling of tags
    #it = Xml.iterparse(StringIO(str(request.data)))
    #for _, e in it:
    #    _, _, e.tag = e.tag.rpartition('}')
    #root = it.root

    # check if all required elements are present
    if not check_elements(root):
        return Response(status=400)

    print(root.tag)
    #print(root)
    #for child in root:
    #    print(child.tag, child.attrib)
    print(root.find('cap:identifier', ns))
    xml = 'hi'
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
