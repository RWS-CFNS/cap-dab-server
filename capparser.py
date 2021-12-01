import datetime                     # Date and time manipulator
import pyexpat                      # XML parser backend (only used for version check)
import xml.etree.ElementTree as Xml # XML parser

class CAPParser:
    # CAP version namespaces
    # NOTE: CAP v1.2 is hardcoded right now
    ns = {
            'CAPv1.2': 'urn:oasis:names:tc:emergency:cap:1.2'
    }

    # timestamp format specified in the CAP v1.2 standard
    TIMESTAMP_FORMAT = '%Y-%m-%dT%H:%M:%S%z'

    def __init__(self):
        # Check if the version of PyExpat is vulnerable to XML DDoS attacks (version 2.4.1+).
        # See https://docs.python.org/3/library/xml.html#xml-vulnerabilitiesk
        ver = pyexpat.version_info
        if ver[0] < 2 or ver[1] < 4 or ver[2] < 1:
            raise ModuleNotFoundError('PyExpat 2.4.1+ is required but not found on this system')

    # Generate a current timestamp
    def generate_timestamp(self):
        timezone = datetime.datetime.now(datetime.timezone.utc).astimezone().tzinfo

        # convert current time to string
        timestamp = datetime.datetime.now(tz=timezone).strftime(self.TIMESTAMP_FORMAT)

        # add a colon separator to the UTC offset (as required by the CAP v1.2 standard)
        return '{0}:{1}'.format(timestamp[:-2], timestamp[-2:])

    # Generate an acknowledgement
    # This applies to all types of requests as they all expect the same format of acknowledgement.
    def generate_response(self):
        capns = self.ns['CAPv1.2']

        root = Xml.Element('alert')
        root.attrib = { 'xmlns': self.ns['CAPv1.2'] }

        identifier = Xml.SubElement(root, 'identifier')
        identifier.text = 'cfns.identifier.xxx' # FIXME don't hardcode

        sender = Xml.SubElement(root, 'sender')
        sender.text = 'test@test.com' # FIXME don't hardcode

        sent = Xml.SubElement(root, 'sent')
        sent.text = self.generate_timestamp()

        status = Xml.SubElement(root, 'status')
        status.text = 'Actual'

        msgType = Xml.SubElement(root, 'msgType')
        msgType.text = 'Ack'

        scope = Xml.SubElement(root, 'scope')
        scope.text = 'Public'

        references = Xml.SubElement(root, 'references')
        references.text = 'TODO' # FIXME don't hardcore, derive from request

        return Xml.tostring(root, encoding='unicode', xml_declaration=True)

    # Check if the timestamp that has been received is valid
    def check_timestamp(self, timestamp):
        try:
            return datetime.datetime.strptime(timestamp, self.TIMESTAMP_FORMAT)
        except ValueError:
            return None

    # Check the elements in the <info> container for CAP v1.2 and NL Subbroker conformity
    def __check_info_elements(self, info):
        # List of _required_ elements in the <info> container
        info_elements = ('category', 'event', 'urgency', 'severity', 'certainty')

        # check for the presence of required elements
        for e in info_elements:
            if info.find(f'CAPv1.2:{e}', self.ns) is None:
                print(f'FAIL: required element missing from <info> container: {e}')
                return False

        # check <language>, as it should basically always be present
        if info.find(f'CAPv1.2:language', self.ns) is None:
            print(f'{"FAIL" if strict else "WARN"}: required element missing from <info> container: language')

            # Allow when not running in strict mode
            if strict:
                return False

        # check <category>, it should always have a value of 'Safety'
        # though this may be different in practise, so we just throw a warning
        category = info.find(f'CAPv1.2:category', self.ns).text
        if category != 'Safety':
            print(f'WARN: invalid category: {category}')

        # these fields should always return 'Unknown' from an NL Subbroker
        # though this may be different in practise, so we just throw a warning
        urgency = info.find(f'CAPv1.2:urgency', self.ns).text
        if urgency != 'Unknown':
            print(f'WARN: invalid urgency: {urgency}')
        severity = info.find(f'CAPv1.2:severity', self.ns).text
        if severity != 'Unknown':
            print(f'WARN: invalid severity: {severity}')
        certainty = info.find(f'CAPv1.2:certainty', self.ns).text
        if certainty != 'Unknown':
            print(f'WARN: invalid certainty: {certainty}')

        # check if the <effective> and <expires> timestamps are formatted correctly
        effective = info.find('CAPv1.2:effective', self.ns).text
        if self.check_timestamp(effective) is None:
            print(f'FAIL: invalid <effective> timestamp format: {effective}')
            return False
        expires = info.find('CAPv1.2:expires', self.ns).text
        if self.check_timestamp(expires) is None:
            print(f'FAIL: invalid <expires> timestamp format: {expires}')
            return False

        return True

    # Check the elements in the <alert> container for CAP v1.2 and NL Subbroker conformity
    def __check_elements(self, alert):
        # List of _required_ elements in the <alert> container
        alert_elements = ('identifier', 'sender', 'sent', 'status', 'msgType', 'scope')

        # check for the presence of required elements
        for e in alert_elements:
            if alert.find(f'CAPv1.2:{e}', self.ns) is None:
                print(f'FAIL: required element missing from <alert> container: {e}')
                return False

        # check if the timestamp is formatted correctly
        timestamp = alert.find('CAPv1.2:sent', self.ns).text
        if self.check_timestamp(timestamp) is None:
            print(f'FAIL: invalid <sent> timestamp format: {timestamp}')
            return False

        msgType = alert.find('CAPv1.2:msgType', self.ns).text
        status = alert.find('CAPv1.2:status', self.ns).text

        if msgType == 'Alert':
            # check if <info> is present when <msgType> has the value 'Alert'
            # This is required by the standard, but poorly implemented in practise.
            # Even the "link test" example in the One2Many document doesn't demonstrate this properly
            #
            # We will ignore this (even in strict mode) when <status> has the value 'Test'
            if status != 'Test':
                info = alert.find(f'CAPv1.2:info', self.ns)
                if info is None:
                    print('FAIL: required element missing from <alert> container: info')
                    return False

                # check the <info> container element
                if not self.__check_info_elements(info):
                    return False
        elif msgType == 'Cancel':
            # Check <msgType> separately because it influences whether the element <references> is required
            if alert.find('CAPv1.2:references', self.ns) is None:
                print(f'{"FAIL" if strict else "WARN"}: required element missing from <alert> container: references')
                # We can just give a warning because the documentation isn't 100% clear on whether this
                # should really be enforced
                if strict:
                    return False

        # check <scope>, as it should always be 'Public'
        scope = alert.find('CAPv1.2:scope', self.ns).text
        if scope != 'Public':
            print(f'{"FAIL" if strict else "WARN"}: invalid scope: {scope}')
            # In production this should always be 'Public'. In a development/test environment this may
            # not always be this case.
            if strict:
                return False

        return True

    # Attempt to parse the raw XML (from a webpage for instance) into memory and check
    # if required elements are present
    # Return bool:
    # - True on success
    # - False on failure
    def parse(self, raw):
        # Parse the received XML
        try:
            root = Xml.fromstring(raw)
        except Xml.ParseError:
            print('FAIL: invalid XML schema received')
            return False

        # Check the if the namespace matches what is expected of the main broker (CAP v1.2)
        if root.tag != f'{{{self.ns["CAPv1.2"]}}}alert':
            print(f'{"FAIL" if strict else "WARN"}: invalid namespace: {root.tag}')
            if strict:
                return False

        # Check if all required elements are present
        if not self.__check_elements(root):
            return False

        return True
