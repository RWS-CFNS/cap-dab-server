#
#    CFNS - Rijkswaterstaat CIV, Delft © 2021 - 2022 <cfns@rws.nl>
#
#    Copyright 2021 - 2022 Bastiaan Teeuwen <bastiaan@mkcl.nl>
#
#    This file is part of cap-dab-server
#
#    cap-dab-server is free software: you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation, either version 3 of the License, or
#    (at your option) any later version.
#
#    cap-dab-server is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with cap-dab-server. If not, see <https://www.gnu.org/licenses/>.
#

import datetime                         # Date and time manipulator
import logging                          # Logging facilities
import xml.etree.ElementTree as Xml     # XML parser
import utils

logger = logging.getLogger('server.cap')
msg_counter = 0

class CAPParser():
    # Constants
    TYPE_LINK_TEST = 0
    TYPE_ALERT     = 1
    TYPE_CANCEL    = 2

    # CAP version namespaces
    # NOTE: CAP v1.2 is hardcoded right now
    NS = {
            'CAPv1.2': 'urn:oasis:names:tc:emergency:cap:1.2'
    }

    # timestamp format specified in the CAP v1.2 standard
    TIMESTAMP_FORMAT = '%Y-%m-%dT%H:%M:%S%z'

    def __init__(self, app, strict, identifier, sender):
        self.app = app

        # parse stricty, adhering to not only the CAP v1.2 standard but also the NL Subbroker standards
        self.strict = strict

        self.src_identifier = identifier
        self.src_sender = sender

        self.msg_type = None

    # Generate a current timestamp
    def generate_timestamp(self):
        timezone = datetime.datetime.now(datetime.timezone.utc).astimezone().tzinfo

        # convert current time to string
        timestamp = datetime.datetime.now(tz=timezone).strftime(self.TIMESTAMP_FORMAT)

        # add a colon separator to the UTC offset (as required by the CAP v1.2 standard)
        return '{0}:{1}'.format(timestamp[:-2], timestamp[-2:])

    # Generate an acknowledgement
    # This applies to all types of requests as they all expect the same format of acknowledgement.
    def generate_response(self, ref_identifier, ref_sender, ref_sent):
        global msg_counter

        capns = self.NS['CAPv1.2']

        root = Xml.Element('alert')
        root.attrib = { 'xmlns': self.NS['CAPv1.2'] }

        # TODO include msg type too?
        identifier = Xml.SubElement(root, 'identifier')
        identifier.text = f'{self.src_identifier}.{msg_counter}'
        msg_counter += 1

        sender = Xml.SubElement(root, 'sender')
        sender.text = self.src_sender

        sent = Xml.SubElement(root, 'sent')
        sent.text = self.generate_timestamp()

        status = Xml.SubElement(root, 'status')
        status.text = 'Actual'

        msgType = Xml.SubElement(root, 'msgType')
        msgType.text = 'Ack'

        scope = Xml.SubElement(root, 'scope')
        scope.text = 'Public'

        references = Xml.SubElement(root, 'references')
        references.text = f'{ref_sender},{ref_identifier},{ref_sent}'

        return Xml.tostring(root, encoding='unicode', xml_declaration=True)

    # Check if the timestamp that has been received is valid
    @staticmethod
    def get_datetime(timestamp):
        try:
            return datetime.datetime.strptime(timestamp, CAPParser.TIMESTAMP_FORMAT)
        except ValueError:
            return None

    # Check the elements in the <info> container for CAP v1.2 and NL Subbroker conformity
    def __check_info_elements(self, info):
        # List of _required_ elements in the <info> container
        info_elements = ('category', 'event', 'urgency', 'severity', 'certainty')

        # check for the presence of required elements
        for e in info_elements:
            if info.find(f'CAPv1.2:{e}', self.NS) is None:
                logger.error(f'required element missing from <info> container: {e}')
                return False

        # check <language>, as it should basically always be present
        if info.find(f'CAPv1.2:language', self.NS) is None:
            # Allow when not running in strict mode
            if utils.logger_strict(logger, '{required element missing from <info> container: language'):
                return False

        # check <category>, it should always have a value of 'Safety'
        # though this may be different in practise, so we just throw a warning
        category = info.find(f'CAPv1.2:category', self.NS).text
        if category != 'Safety':
            logger.warning(f'invalid category: {category}')

        # these fields should always return 'Unknown' from an NL Subbroker
        # though this may be different in practise, so we just throw a warning
        urgency = info.find(f'CAPv1.2:urgency', self.NS).text
        if urgency != 'Unknown':
            logger.warning(f'invalid urgency: {urgency}')
        severity = info.find(f'CAPv1.2:severity', self.NS).text
        if severity != 'Unknown':
            logger.warning(f'invalid severity: {severity}')
        certainty = info.find(f'CAPv1.2:certainty', self.NS).text
        if certainty != 'Unknown':
            logger.warning(f'invalid certainty: {certainty}')

        # check if the <effective> and <expires> timestamps are formatted correctly
        effective = info.find('CAPv1.2:effective', self.NS).text
        if CAPParser.get_datetime(effective) is None:
            logger.error(f'invalid <effective> timestamp format: {effective}')
            return False
        expires = info.find('CAPv1.2:expires', self.NS).text
        if CAPParser.get_datetime(expires) is None:
            logger.error(f'invalid <expires> timestamp format: {expires}')
            return False

        return True

    # Check the elements in the <alert> container for CAP v1.2 and NL Subbroker conformity
    def __check_elements(self, alert):
        # List of _required_ elements in the <alert> container
        alert_elements = ('identifier', 'sender', 'sent', 'status', 'msgType', 'scope')

        # check for the presence of required elements
        for e in alert_elements:
            if alert.find(f'CAPv1.2:{e}', self.NS) is None:
                logger.error(f'required element missing from <alert> container: {e}')
                return False

        # check if the timestamp is formatted correctly
        timestamp = alert.find('CAPv1.2:sent', self.NS).text
        if CAPParser.get_datetime(timestamp) is None:
            logger.error(f'invalid <sent> timestamp format: {timestamp}')
            return False

        msgType = alert.find('CAPv1.2:msgType', self.NS).text
        status = alert.find('CAPv1.2:status', self.NS).text

        if msgType == 'Alert':
            # check if <info> is present when <msgType> has the value 'Alert'
            # This is required by the standard, but poorly implemented in practise.
            #
            # We will ignore this (even in strict mode) when <status> has the value 'Test'
            if status != 'Test':
                info = alert.find(f'CAPv1.2:info', self.NS)
                if info is None:
                    logger.error('required element missing from <alert> container: info')
                    return False

                # check the <info> container element
                if not self.__check_info_elements(info):
                    return False
        elif msgType == 'Cancel':
            # Check <msgType> separately because it influences whether the element <references> is required
            if alert.find('CAPv1.2:references', self.NS) is None:
                # <references> is required for Cancel
                if logger.error('required element missing from <alert> container: references'):
                    return False

        # check <scope>, as it should always be 'Public'
        scope = alert.find('CAPv1.2:scope', self.NS).text
        if scope != 'Public':
            # In production this should always be 'Public'. In a development/test environment this may
            # not always be this case.
            if utils.logger_strict(logger, f'invalid scope: {scope}'):
                return False

        return True

    # Parse the references tag into a list with a dictionary
    def __parse_references(self, refs):
        msgs = []

        # Parse the references(s) in the format CAPv1.2 describes
        for msg in refs.split(' '):
            ref = msg.split(',')
            msgs.append({
                         'sender': ref[0],
                         'identifier': ref[1],
                         'sent': ref[2]
                        })

        return msgs

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
            logger.error('invalid XML schema received')
            return False

        # Check the if the namespace matches what is expected of the main broker (CAP v1.2)
        if root.tag != f'{{{self.NS["CAPv1.2"]}}}alert':
            if utils.logger_strict(logger, f'invalid namespace: {root.tag}'):
                return False

        # Check if all required elements are present
        if not self.__check_elements(root):
            return False

        # Parse the elements into class-wide variables
        msgType = root.find('CAPv1.2:msgType', self.NS).text

        self.identifier = root.find(f'CAPv1.2:identifier', self.NS).text
        self.sender = root.find(f'CAPv1.2:sender', self.NS).text
        self.sent = root.find(f'CAPv1.2:sent', self.NS).text

        if msgType == 'Alert':
            status = root.find('CAPv1.2:status', self.NS).text
            if status == 'Test':
                self.msg_type = self.TYPE_LINK_TEST
            elif status == 'Actual':
                self.msg_type = self.TYPE_ALERT

                info = root.find(f'CAPv1.2:info', self.NS)
                self.lang = info.find(f'CAPv1.2:language', self.NS).text
                self.effective = CAPParser.get_datetime(info.find(f'CAPv1.2:effective', self.NS).text)
                self.expires = CAPParser.get_datetime(info.find(f'CAPv1.2:expires', self.NS).text)
                self.description = info.find(f'CAPv1.2:description', self.NS).text
        elif msgType == 'Cancel':
            self.msg_type = self.TYPE_CANCEL

            self.references = self.__parse_references(root.find(f'CAPv1.2:references', self.NS).text)
        if self.msg_type is None:
            logger.error(f'Unknown message type: {msgType}')

        return True
