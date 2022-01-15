#!/usr/bin/env python3

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

# Support loading modules from subdirectories
import sys
import os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.dirname(SCRIPT_DIR))

# Check Python version, need 3.7+ for ordered dictionaries
assert sys.version_info >= (3, 7)

import configparser                 # Python INI file parser
import getpass                      # For getting the current user
import logging                      # Logging facilities
import logging.handlers             # Logging handlers
import queue                        # Queue for passing data to the DAB processing thread
import socket                       # To get the system's hostname
import string                       # String utilities (for checking if string is hexadecimal)
import threading                    # Threading support (for running Flask and DAB Mux/Mod in the background)
import time                         # For sleep support
from dialog import Dialog           # Beautiful dialogs using the external program dialog
from cap.server import CAPServer    # CAP server
from dab.server import DABServer    # DAB server
from dab.streams import DABStreams  # DAB streams
import dab.types                    # DAB types
import utils

# Max path length from limits.h
MAX_PATH = os.pathconf('/', 'PC_PATH_MAX')

# Config file path home
try:
    CONFIG_HOME = f'{os.environ["XDG_CONFIG_HOME"]}'
except KeyError:
    CONFIG_HOME = f'{os.path.expanduser("~")}/.config'

# Cache file home
try:
    CACHE_HOME = f'{os.environ["XDG_CACHE_HOME"]}'
except KeyError:
    CACHE_HOME = f'{os.path.expanduser("~")}/.cache'

# Setup the main server config file
server_config = f'{CONFIG_HOME}/cap-dab-server/server.ini'
os.makedirs(os.path.dirname(server_config), exist_ok=True)
config = configparser.ConfigParser()
if os.path.isfile(server_config):
    config.read(server_config)
else:
    config['general'] = {
                         'logdir': f'{CACHE_HOME}/cap-dab-server',
                         'max_log_size': '8192',
                         'queuelimit': '10'
                        }
    config['dab'] =     {
                         'stream_config': f'{CONFIG_HOME}/cap-dab-server/streams.ini',
                         'odrbin_path': f'/usr/local/bin',
                         'mux_config': f'{CONFIG_HOME}/cap-dab-server/dabmux.mux',
                         'mod_config': f'{CONFIG_HOME}/cap-dab-server/dabmod.ini'
                        }
    config['cap'] =     {
                         'host': '127.0.0.1',
                         'port': '39800',
                         'identifier': f'cap-dab-server.{socket.gethostname()}',
                         'sender': f'{getpass.getuser()}@{socket.gethostname()}',
                         'strict_parsing': 'no'
                        }
    config['warning'] = {
                         'alarm': 'yes',
                         'replace': 'yes',
                         'data': 'yes',
                         'announcement': 'alarm',
                         'label': 'Alert',
                         'shortlabel': 'Alert',
                         'pty': '3'
                        }

    with open(server_config, 'w') as config_file:
        config.write(config_file)

# Create directories if they didn't exist yet
os.makedirs(config['general']['logdir'], exist_ok=True)
os.makedirs(config['dab']['odrbin_path'], exist_ok=True)
os.makedirs(os.path.dirname(config['dab']['mux_config']), exist_ok=True)
os.makedirs(os.path.dirname(config['dab']['mod_config']), exist_ok=True)

# Setup a general server logger
logger = logging.getLogger('server')
logger.setLevel(logging.DEBUG)
handler = logging.handlers.RotatingFileHandler(f'{config["general"]["logdir"]}/server.log', mode='a', maxBytes=int(config['general']['max_log_size'])*1024, backupCount=5)
handler.setFormatter(logging.Formatter(fmt='%(asctime)s %(name)-12s %(levelname)-8s %(message)s', datefmt='%y-%m-%d %H:%M:%s'))
handler.setLevel(logging.DEBUG)
logger.addHandler(handler)

d = Dialog(dialog='dialog', autowidgetsize=True)

def _error(msg=''):
    d.msgbox(f'''
Invalid entry!
{msg}
''',         title='Error', colors=True, width=60, height=8)

def cap_restart(start=0, target=100):
    GAUGE_HEIGHT = 6
    GAUGE_WIDTH = 64

    d.gauge_update(start, 'Saving changes to CAP config, one moment please...', update_text=True)
    if capsrv.restart():
        d.gauge_update(target, 'Successfully saved!', update_text=True)
    else:
        d.gauge_stop()
        d.msgbox('Failed to start CAP server, please refer to the server logs', title='Error',
                 width=GAUGE_WIDTH, height=GAUGE_HEIGHT)
        d.gauge_start('', height=GAUGE_HEIGHT, width=GAUGE_WIDTH, percent=target)
        time.sleep(4)
    time.sleep(0.5)

def dab_restart(start=0, target=100):
    GAUGE_HEIGHT = 6
    GAUGE_WIDTH = 64

    # Restart DAB Streams
    d.gauge_update(start, 'Saving changes to DAB stream config, one moment please...', update_text=True)

    if not dabstreams.restart():
        d.gauge_stop()
        d.msgbox('Failed to start one or more DAB streams, please check configuration', title='Error',
                 width=GAUGE_WIDTH, height=GAUGE_HEIGHT)
        d.gauge_start('', height=GAUGE_HEIGHT, width=GAUGE_WIDTH, percent=target)

    # Restart DAB server
    d.gauge_update(int((start + target) / 2), 'Saving changes to DAB server config, one moment please...', update_text=True)
    if dabsrv.restart():
        d.gauge_update(target, 'Successfully saved!', update_text=True)
        time.sleep(0.5)
    else:
        d.gauge_stop()
        d.msgbox('Failed to start DAB server, please refer to the server logs', title='Error',
                 width=GAUGE_WIDTH, height=GAUGE_HEIGHT)
        d.gauge_start('', height=GAUGE_HEIGHT, width=GAUGE_WIDTH, percent=target)

def status():
    def state(b):
        if b is None:
            return '\Zb\Z1MISCFG\Zn'
        elif b == True:
            return '\Zb\Z2OK\Zn'
        elif b == False:
            return '\Zb\Z1STOPPED\Zn'

    while True:
        cap_server = capsrv.status()
        dab_server, dab_watcher, dab_mux, dab_mod = dabsrv.status()

        # Query the state of the various subcomponents
        states = [
            ['CAP HTTP Server', state(cap_server)],
            ['DAB Server',      state(dab_server)],
            ['DAB Multiplexer', state(dab_mux)],
            ['DAB Modulator',   state(dab_mod)]
        ]

        # Insert the state of DAB Streams in separate rows (after 'DAB Streams')
        streamstates = dabstreams.status()
        states.insert(2, ['DAB Streams', str(len(streamstates))])
        for s in streamstates:
            states.insert(3, [f'  - {s[0]}', state(s[1])])

        # Format the states list into columns
        sstr = ''
        for s in states:
            sstr += '{: <20}{: <6}\n'.format(*s)

        code = d.msgbox(sstr, colors=True, title='Server Status', no_collapse=True,
                        ok_label='Refresh', extra_button=True, extra_label='Exit')

        if code in (Dialog.EXTRA, Dialog.ESC):
            break

def dab_config():
    TITLE = 'DAB Configuration'

    # Country ID and ECC modification menu, used for DAB ensemble and service configuration
    def _country_config(title, ecc, cid, allow_empty=False):
        if ecc != '':
            ecc = int(ecc, 16)
        if cid != '':
            if len(cid) == 3:
                cid = int(cid, 16)
            else:
                cid = int(cid[:-3], 16)

        menu = [(k, f'ECC: {hex(v[0]).upper()}, Country ID: {hex(v[1]).upper()}', bool(v[0] == ecc and v[1] == cid)) for k, v in dab.types.COUNTRY_IDS.items()]

        if allow_empty:
            menu.insert(0, ('Empty', 'Don\'t overwrite country ID from the ensemble\'s default', bool(ecc == '')))

        # TODO allow to configure unlisted/custom Country ID and ECC
        #\ZbCountry ID\Zn and \ZbECC\Zn are found in section 5.4 Country Id of ETSI TS 101 756.
        #These values both represent a hexidecimal value.

        code, tag = d.radiolist('', title=f'Country - {title}', choices=menu)

        if code == Dialog.OK and tag != 'Empty':
            return dab.types.COUNTRY_IDS[tag]

        return (None, None)

    # Label and short label renaming menu, used for both ensemble and DAB services configuration
    def _label_config(title, label, shortlabel):
        if not isinstance(label, str):
            label = ''
        if not isinstance(shortlabel, str):
            shortlabel = ''

        while True:
            code, elems = d.form('''
\ZbLabel\Zn cannot be longer than 16 characters (REQ).
\ZbShort Label\Zn cannot be longer than 8 characters and must contain characters from \ZbLabel\Zn (OPT).
''',                             colors=True, title=f'Label - {title}', elements=[
                                ('Label',       1, 1, label, 1, 20, 17, 16),
                                ('Short Label', 2, 1, shortlabel, 2, 20, 9, 8)
                                ])

            if code == Dialog.OK:
                # check if the shortlabel has characters from label
                if elems[1] == '':
                    return (elems[0], None)
                elif all(c in elems[0] for c in elems[1]):
                    return (elems[0], elems[1])
                else:
                    _error('\ZbShort Label\Zn must contain characters from \ZbLabel\Zn.')
                    continue

            return (None, None)

    # Programme Type changing menu
    def _pty_config(title, curpty):
        menu = [(v[0], v[1], bool(k == curpty)) for k, v in dab.types.PROGRAMME_TYPES.items()]

        code, tag = d.radiolist('', title=title, choices=menu)

        if code == Dialog.OK:
            return next((k for k, v in dab.types.PROGRAMME_TYPES.items() if v[0] == tag), None)

        return None

    def ensemble():
        localtitle = f'Ensemble - {TITLE}'

        def announcements():
            # TODO implement
            _error('Not Yet Implemented')
            #code, tags = d.checklist('Please configure the announcements you would like the ensemble to support.',
            #                        title=f'Warning method - {TITLE}', choices=[
            #        ('Alarm',    'nt', config['warning'].getboolean('alarm')),
            #        ('Replace',  '', config['warning'].getboolean('replace'))
            #        ])

        while True:
            code, tag = d.menu('', title=localtitle, cancel_label='Back', choices=[
                              ('Country',           'Change the DAB Country ID and ECC'),
                              ('Label',             'Change the ensemble label'),
                              ('Announcements',     'Add/Remove/Modify ensemble announcements (FIG 0/19)')
                              ])

            if code in (Dialog.CANCEL, Dialog.ESC):
                break
            elif tag == 'Country':
                ecc, cid = _country_config(localtitle,
                                           str(dabsrv.config.cfg.ensemble['ecc']),
                                           str(dabsrv.config.cfg.ensemble['id']))

                if cid is not None and ecc is not None:
                    dabsrv.config.cfg.ensemble['id'] = str(hex(cid)) + 'fff'
                    dabsrv.config.cfg.ensemble['ecc'] = str(hex(ecc))
            elif tag == 'Label':
                label, shortlabel = _label_config(localtitle,
                                                  str(dabsrv.config.cfg.ensemble['label']),
                                                  str(dabsrv.config.cfg.ensemble['shortlabel']))

                if label is not None:
                    dabsrv.config.cfg.ensemble['label'] = label

                    if shortlabel is not None:
                        dabsrv.config.cfg.ensemble['shortlabel'] = shortlabel
                    else:
                        del dabsrv.config.cfg.ensemble['shortlabel']
            elif tag == 'Announcements':
                announcements()

    def streams():
        def modify(stream):
            localtitle = f'{stream} - Streams - {TITLE}'

            def stream_input():
                input_type = dabstreams.config.cfg[stream]['input_type']
                inputuri = dabstreams.config.cfg[stream]['input']
                output_type = dabstreams.config.cfg[stream]['output_type']

                # Configure the output type
                menu_output = {
                    'dab':      ['DAB',     'MP2 audio stream', False],
                    'dabplus':  ['DAB+',    'AAC+ audio stream', False],
                    'data':     ['Data',    'Arbitrary data stream', False]
                }
                menu_output[output_type][2] = True

                code, tag = d.radiolist('', title=f'Stream Output - {localtitle}', choices=list(menu_output.values()))
                if code in (Dialog.CANCEL, Dialog.ESC):
                    return
                output_type = next(k for k, v in menu_output.items() if v[0] == tag)
                print(output_type)

                # Configure the input type
                menu_input = {
                    'file': ['File',        'Specify a file path as input', False],
                    'fifo': ['FIFO',        'Specify a named Unix PIPE (FIFO) as input', False]
                }

                # Data output can't use gstreamer as input, because odr-audioenc is not used
                if output_type != 'data':
                    menu_input['gst'] = ['GStreamer',   'Specify a GStreamer URI as input stream', False]
                elif input_type == 'gst':
                    input_type = 'fifo'

                menu_input[input_type][2] = True

                code, tag = d.radiolist('', title=f'Stream Input - {localtitle}', choices=list(menu_input.values()))
                if code in (Dialog.CANCEL, Dialog.ESC):
                    return
                input_type = next(k for k, v in menu_input.items() if v[0] == tag)

                # Configure the input URI/Path
                code, string = d.inputbox('Please enter the input URI/Path',
                                            title=f'Stream Input Path - {localtitle}', init=inputuri)
                if code in (Dialog.CANCEL, Dialog.ESC):
                    return
                inputuri = string

                dabstreams.config.cfg[stream]['input_type'] = input_type
                dabstreams.config.cfg[stream]['output_type'] = output_type
                dabstreams.config.cfg[stream]['input'] = inputuri

            def bitrate():
                bitrates = [
                            ['8',    '8 kbps',   False],
                            ['16',   '16 kbps',  False],
                            ['24',   '24 kbps',  False],
                            ['32',   '32 kbps',  False],
                            ['40',   '40 kbps',  False],
                            ['48',   '48 kbps',  False],
                            ['56',   '56 kbps',  False],
                            ['64',   '64 kbps',  False],
                            ['72',   '72 kbps',  False],
                            ['80',   '80 kbps',  False],
                            ['88',   '88 kbps',  False],
                            ['96',   '96 kbps',  False],
                            ['104',  '104 kbps', False],
                            ['112',  '112 kbps', False],
                            ['120',  '120 kbps', False],
                            ['128',  '128 kbps', False],
                            ['136',  '136 kbps', False],
                            ['144',  '144 kbps', False],
                            ['152',  '152 kbps', False],
                            ['160',  '160 kbps', False],
                            ['168',  '168 kbps', False],
                            ['176',  '176 kbps', False],
                            ['184',  '184 kbps', False],
                            ['192',  '192 kbps', False]
                           ]

                # This is probably super inefficient but whatever
                cur = dabstreams.config.cfg[stream]['bitrate']
                bitrates[next(bitrates.index(b) for b in bitrates if b[0] == cur)][2] = True

                code, tag = d.radiolist('', title=f'Bitrate - {localtitle}', no_tags=True, choices=bitrates)
                if code in (Dialog.CANCEL, Dialog.ESC):
                    return
                dabstreams.config.cfg[stream]['bitrate'] = tag

            def protection():
                _error('Not Yet Implemented. Default is: EEP_A 3. Configure in streams.ini')

            def pad_components():
                _error('Not Yet Implemented. Default is: DLS enabled, MOT slideshow disabled. Configure in streams.ini')

            while True:
                code, tag = d.menu('', title=localtitle, extra_button=True, extra_label='Delete', cancel_label='Back', choices=[
                                  ('Stream Input',    'Configure the stream input'),
                                  ('Bitrate',         'Configure the bitrate to broadcast this stream at'),
                                  ('Protection',      'Configure the DAB protection level for the subchannel'),
                                  ('PAD Components',  'Configure PAD components for this subchannel')
                                  #('DLS',               ''),
                                  #('Slideshow',         ''),
                                  #('Slideshow Timeout', ''),
                                  #('Pad length',        '')
                                  ])

                if code in (Dialog.CANCEL, Dialog.ESC):
                    break
                elif code in Dialog.EXTRA:
                    yncode = d.yesno(f'Are you sure you want to delete the stream {stream}?', width=60, height=6)
                    if yncode == Dialog.OK:
                        dabstreams.config.cfg.remove_section(stream)

                        break
                elif tag == 'Stream Input':
                    stream_input()
                elif tag == 'Bitrate':
                    bitrate()
                elif tag == 'Protection':
                    protection()
                elif tag == 'PAD Components':
                    pad_components()

        def add():
            while True:
                code, name = d.inputbox('Please enter a new identifier for this stream/subchannel (no spaces)',
                                        title=f'Add - Stream - {TITLE}')

                if code in (Dialog.CANCEL, Dialog.ESC):
                    break
                elif name == '':
                    _error('Identifier cannot be empty.')
                elif ' ' in name:
                    _error('Identifier cannot contain spaces.')
                else:
                    # TODO prompt to setup input right away

                    # Set some sane defaults
                    dabstreams.config.cfg[name] = {}
                    dabstreams.config.cfg[name]['input_type'] = 'gst'
                    dabstreams.config.cfg[name]['input'] = 'http://127.0.0.1:1234'
                    dabstreams.config.cfg[name]['output_type'] = 'dabplus'
                    dabstreams.config.cfg[name]['bitrate'] = '88'
                    dabstreams.config.cfg[name]['protection_profile'] = 'EEP_A'
                    dabstreams.config.cfg[name]['protection'] = '3'
                    dabstreams.config.cfg[name]['dls_enable'] = 'yes'
                    dabstreams.config.cfg[name]['mot_enable'] = 'no'
                    dabstreams.config.cfg[name]['pad_length'] = '58'

                    modify(name)
                    break

        while True:
            menu = [('Add', 'Add a new stream')]

            # Load streams into the menu list
            i = 0
            for stream in dabstreams.config.cfg.sections():
                menu.insert(i, (stream, dabstreams.config.cfg[stream]['output_type'].title() + ' stream'))
                i += 1

            code, tag = d.menu('Please select a stream/subchannel', title=f'Streams - {TITLE}', cancel_label='Back', choices=menu)

            if code in (Dialog.CANCEL, Dialog.ESC):
                break
            elif tag == 'Add':
                add()
            elif code == Dialog.OK:
                modify(tag)

    def services():
        def modify(service=''):
            localtitle = f'{service} - Services - {TITLE}'

            def set_id(service, no_cancel=False):
                sid = str(dabsrv.config.cfg.services[service]['id'])

                # TODO generate our own service ID if left blank

                while True:
                    code, elems = d.form('''
The \ZbService ID\Zn is a 3 character, unique, hexadecimal identifier for a service.
''',                                     title=f'Service ID - {localtitle}', colors=True, no_cancel=no_cancel, elements=[
                                        ('', 1, 1, sid[3:], 1, 1, 4, 3)
                                        ])

                    if no_cancel == False and code in (Dialog.CANCEL, Dialog.ESC):
                        break
                    elif code == Dialog.OK:
                        if not all(c in string.hexdigits for c in elems[0]):
                            _error('\ZbService ID\Zn must be a hexadecimal number')
                            continue

                        if len(elems[0]) != 3:
                            _error('Invalid length.\n\ZbService ID\Zn must be 3 hexadecimal digits in length.')
                            continue

                        if len(sid) == 0:
                            sid = f'0x{str(dabsrv.config.cfg.ensemble["id"])[2:-3]}'

                        dabsrv.config.cfg.services[service]['id'] = sid[:3] + elems[0]
                        break

            def announcements(service):
                dabsrv.config.cfg.services[service].announcements

                menu = [(k, v, bool(dabsrv.config.cfg.services[service].announcements.getboolean(k))) for k, v in dab.types.ANNOUNCEMENT_TYPES.items()]

                code, tags = d.checklist('', title=f'Announcements - {localtitle}', choices=menu)

                if code == Dialog.OK:
                    for k in dab.types.ANNOUNCEMENT_TYPES.keys():
                        dabsrv.config.cfg.services[service].announcements[k] = str(bool(k in tags)).lower()

            def stream(service, no_cancel=True):
                menu = []

                # Load streams into the menu list
                i = 0
                for stream in dabstreams.config.cfg.sections():
                    menu.insert(i, (stream, dabstreams.config.cfg[stream]['output_type'].title() + ' stream', False))
                    i += 1

                # TODO select current stream

                while True:
                    code, tag = d.radiolist('', title=f'Stream - {localtitle}', no_cancel=no_cancel, choices=menu)

                    if code == Dialog.OK:
                        dabsrv.config.cfg.components[f'comp-{service}'].subchannel = tag
                        break

            # Add a new service
            if service == '':
                # TODO Fail if there's not streams configured

                while True:
                    code, service = d.inputbox('Please enter a new identifier/name for this service (no spaces)',
                                            title=f'Add - Service - {TITLE}')

                    if code in (Dialog.CANCEL, Dialog.ESC):
                        return
                    elif service == '':
                        _error('Identifier cannot be empty.')
                    elif ' ' in service:
                        _error('Identifier cannot contain spaces.')
                    else:
                        dabsrv.config.cfg.services[service]
                        dabsrv.config.cfg.components[f'comp-{service}']['service'] = service

                        # Configure required components
                        localtitle = f'{service} - Services - {TITLE}'
                        set_id(service, no_cancel=True)
                        stream(service, no_cancel=True)

                        # Set some sane defaults
                        dabsrv.config.cfg.services[service]['label'] = 'DAB Service'
                        dabsrv.config.cfg.services[service]['shortlabel'] = 'Service'

                        break

            while True:
                code, tag = d.menu('', title=localtitle, extra_button=True, extra_label='Delete', cancel_label='Back', choices=[
                                  ('ID',              'Change the service ID'),
                                  ('Country',         'Override the Country from the ensemble default (Optional)'),
                                  ('Label',           'Change the service label'),
                                  ('Programme Type',  'Change the programme type (Optional)'),
                                  ('Announcements',   'Select which announcement to support on this service (Optional)'),
                                  ('Clusters',        'Change which announcement cluster this service belong to (Optional)'),
                                  ('Stream',          'Configure which stream this service should broadcast')
                                  ])

                if code in (Dialog.CANCEL, Dialog.ESC):
                    break
                elif code == Dialog.EXTRA:
                    yncode = d.yesno(f'Are you sure you want to delete the service {service}?', width=60, height=6)
                    if yncode == Dialog.OK:
                        # TODO check streamscfg for references in "services" tag and delete where needed

                        del dabsrv.config.cfg.services[service]
                        del dabsrv.config.cfg.components[f'comp-{service}']
                        break
                elif tag == 'ID':
                    set_id(service)
                elif tag == 'Country':
                    sid = str(dabsrv.config.cfg.services[service]['id'])

                    ecc, cid = _country_config(localtitle, str(dabsrv.config.cfg.services[service]['ecc']), sid, True)

                    # TODO check if Service ID is already in use

                    if cid is None and ecc is None:
                        ensemble_cid = str(dabsrv.config.cfg.ensemble['id'])[2:-3]

                        dabsrv.config.cfg.services[service]['id'] = f'0x{ensemble_cid}{sid[3:]}'
                        del dabsrv.config.cfg.services[service]['ecc']
                    else:
                        dabsrv.config.cfg.services[service]['id'] = str(hex(cid)) + sid[3:]
                        dabsrv.config.cfg.services[service]['ecc'] = str(hex(ecc))
                elif tag == 'Label':
                    label, shortlabel = _label_config(localtitle,
                                                      str(dabsrv.config.cfg.services[service]['label']),
                                                      str(dabsrv.config.cfg.services[service]['shortlabel']))

                    if label is not None:
                        dabsrv.config.cfg.services[service]['label'] = label

                        if shortlabel is not None:
                            dabsrv.config.cfg.services[service]['shortlabel'] = shortlabel
                        else:
                            del dabsrv.config.cfg.services[service]['shortlabel']
                elif tag == 'Programme Type':
                    curpty = str(dabsrv.config.cfg.services[service]['pty'])
                    pty = _pty_config(f'PTY - {localtitle}', int(curpty) if curpty != '' else 0)

                    if pty is not None:
                        dabsrv.config.cfg.services[service]['pty'] = str(pty)
                elif tag == 'Announcements':
                    announcements(service)
                elif tag == 'Clusters':
                    # TODO implement
                    _error('Not Yet Implemented')
                elif tag == 'Stream':
                    stream(service)

        while True:
            menu = [('Add', 'Add a new service')]

            # Load in services from multiplexer config
            i = 0
            for key, value in dabsrv.config.cfg.services:
                label = str(dabsrv.config.cfg.services[key]['label']) # TODO CHANGE
                if label == '':
                    del dabsrv.config.cfg.services[key]['label']

                menu.insert(i, (key, label))
                i += 1

            code, tag = d.menu('Please select a service', title=f'Services - {TITLE}', cancel_label='Back', choices=menu)

            if code in (Dialog.CANCEL, Dialog.ESC):
                break
            elif tag == 'Add':
                modify()
            elif code == Dialog.OK:
                modify(tag)

    def warning_config():
        localtitle = f'Warning settings - {TITLE}'

        def cap_announcement():
            # Load in announcements from multiplexer config
            menu = []

            # Load in the currently configured announcement
            curann = config['warning']['announcement']

            for name, announcement in dabsrv.config.cfg.ensemble.announcements:
                cluster = str(announcement.cluster)

                supported = ''
                for atype, state in announcement.flags:
                    if announcement.flags.getboolean(atype):
                        supported += f'{atype}, '
                supported = supported[:-2]

                subch = str(announcement.subchannel)

                menu.append((f'{name}', f'Cluster {cluster}: {supported} (Switch to "{subch}")', bool(name == curann)))

            code, tag = d.radiolist('', title=f'CAP announcement - {localtitle}', choices=menu)

            if code == Dialog.OK:
                config['warning']['announcement'] = tag

                # FIXME save in the previous menu not here
                with open(server_config, 'w') as config_file:
                    config.write(config_file)

        def method():
            code, tags = d.checklist('Select the method by which you want the server to send DAB warning messages',
                                    title=f'Method - {localtitle}', choices=[
                    ('Alarm',    'DAB native Alarm announcement', config['warning'].getboolean('alarm')),
                    ('Replace',  'Subchannel audio stream replacement', config['warning'].getboolean('replace')),
                    ('Data',     'Subchannel data stream replacement', config['warning'].getboolean('data'))
                    ])

            if code == Dialog.OK:
                # Save the changes
                config['warning']['Alarm'] = 'yes' if 'Alarm' in tags else 'no'
                config['warning']['Replace'] = 'yes' if 'Replace' in tags else 'no'
                config['warning']['Data'] = 'yes' if 'Data' in tags else 'no'

        while True:
            code, tag = d.menu('', title=localtitle, cancel_label='Back', choices=[
                              ('CAP announcement',  'Select which Alarm announcement to use for CAP Alerts'),
                              ('Label',             'Configure DAB label to show during warning messages'),
                              ('Programme Type',    'Configure PTY to show during warning messages'),
                              ('Warning method',    'Set the method by which warning messages are sent')
                              ])

            if code in (Dialog.CANCEL, Dialog.ESC):
                break
            elif tag == 'CAP announcement':
                cap_announcement()
            elif tag == 'Label':
                label, shortlabel = _label_config(localtitle,
                                                  str(config['warning']['label']),
                                                  str(config['warning']['shortlabel']))

                if label is not None:
                    config['warning']['label'] = label

                    if shortlabel is not None:
                        config['warning']['shortlabel'] = shortlabel
                    else:
                        config['warning']['shortlabel'] = label[:8]

                # FIXME save in the previous menu not here
                with open(server_config, 'w') as config_file:
                    config.write(config_file)
            elif tag == 'Programme Type':
                pty = _pty_config(f'PTY - {localtitle}', int(config['warning']['pty']))

                if pty is not None:
                    config['warning']['pty'] = str(pty)

                # FIXME save in the previous menu not here
                with open(server_config, 'w') as config_file:
                    config.write(config_file)
            elif tag == 'Warning method':
                method()

    # Before doing anything, create a copy of the current config files
    dabstreams.config.save()
    dabsrv.config.save()
    # TODO also create a copy of server.ini

    while True:
        code, tag = d.menu('', title=TITLE, extra_button=True, extra_label='Save', choices=[
                          ('Ensemble',          'Configure the ensemble'),
                          ('Streams',           'Add/Modify/Set the service streams/subchannels'),
                          ('Services',          'Add/Modify services'),
                          ('Warning settings',  'Configure various settings related to warning messages'),
                          ])

        if code == Dialog.EXTRA:
            # Write config and restart the DAB server
            # FIXME saving while announcement is playing keeps stream, but doesn't keep alarm announcement
            d.gauge_start('', height=6, width=64, percent=0)
            dabstreams.config.write()
            dabsrv.config.write()
            dab_restart()
            d.gauge_stop()
            break
        elif code in (Dialog.CANCEL, Dialog.ESC):
            # Restore the old config
            dabstreams.config.restore()
            dabsrv.config.restore()
            break
        elif tag == 'Ensemble':
            ensemble()
        elif tag == 'Streams':
            streams()
        elif tag == 'Services':
            services()
        elif tag == 'Warning settings':
            warning_config()

def settings():
    while True:
        code, elems = d.mixedform('', title='General Server Configuration', colors=True, ok_label='Save',
                                  item_help=True, help_tags=True, elements=[
            ('Server config',       1,  1, server_config,                     1,  20, 64, MAX_PATH, 2,
             'server.ini config file path'),

            ('Log directory',       2,  1, config['general']['logdir'],       2,  20, 64, MAX_PATH, 0,
             'Directory to write log files to'),

            ('Max log size',        3,  1, config['general']['max_log_size'], 3,  20, 8,  7,        0,
             'Maximum size per log file in Kb'),

            ('CAP-DAB queue limit', 4,  1, config['general']['queuelimit'],   4,  20, 8,  7,        0,
             'Maximum number of CAP messages that can be in the queue at one moment (requires manual restart)'),

            ('Streams config',      5,  1, config['dab']['stream_config'],    5,  20, 64, MAX_PATH, 0,
             'streams.ini config file path'),

            ('ODR binaries path',   6,  1, config['dab']['odrbin_path'],      6,  20, 64, MAX_PATH, 0,
             'Directory containing ODR-DabMux, ODR-DabMod, ODR-PadEnc and ODR-AudioEnc'),

            ('ODR-DabMux config',   7,  1, config['dab']['mux_config'],       7,  20, 64, MAX_PATH, 0,
             'dabmux.mux config file path'),

            ('ODR-DabMod config',   8,  1, config['dab']['mod_config'],       8,  20, 64, MAX_PATH, 0,
             'dabmod.ini config file path')
            ])

        if code == Dialog.OK:
            # Save the changes
            config['general'] = {
                                 'logdir':       elems[1],
                                 'max_log_size': elems[2],
                                 'queuelimit':   elems[3]
                                }
            config['dab'] =     {
                                 'stream_config':elems[4],
                                 'odrbin_path':  elems[5],
                                 'mux_config':   elems[6],
                                 'mod_config':   elems[7]
                                }
            with open(server_config, 'w') as config_file:
                config.write(config_file)

            # Restart the CAP and DAB server to apply changes
            d.gauge_start('', height=6, width=64, percent=0)
            cap_restart(0, 50)
            dab_restart(50, 100)
            d.gauge_stop()

        break

def logbox(file):
    while True:
        code = d.textbox(file, title=file, colors=True, no_shadow=True, ok_label='Refresh', extra_button=True, extra_label='Exit', help_button=True, help_label='Purge')

        if code in (Dialog.EXTRA, Dialog.ESC):
            break
        elif code in (Dialog.CANCEL, Dialog.HELP):
            open(file, 'w').close()
            break

def log():
    def viewlog(path):
        # Create the log file if it doesn't exist yet
        open(path, 'a').close()

        logbox(path)

    while True:
        code, tag = d.menu('', title='Server log management', ok_label='Select', cancel_label='Back', choices=[
                          ('Server',        'View main server log'),
                          ('CAP',           'View CAP HTTP server log'),
                          ('Multiplexer',   'View DAB Multiplexer log'),
                          ('Modulator',     'View DAB Modulator log')
                          ])

        logdir = config['general']['logdir']

        if code in (Dialog.CANCEL, Dialog.ESC):
            break
        elif tag == 'Server':
            viewlog(f'{logdir}/server.log')
        elif tag == 'CAP':
            viewlog(f'{logdir}/capsrv.log')
        elif tag == 'Multiplexer':
            viewlog(f'{logdir}/dabmux.log')
        elif tag == 'Modulator':
            viewlog(f'{logdir}/dabmod.log')

def cap_config():
    while True:
        code, elems = d.mixedform('', title='CAP Configuration', colors=True, ok_label='Save',
                                  item_help=True, help_tags=True, elements=[
            ('Server host',         1, 1, config['cap']['host'],            1, 20, 46, 45,  0,
             'IP address to host CAP HTTP server on (IPv4/IPv6)'),

            ('Server port',         2, 1, config['cap']['port'],            2, 20, 6,  5,   0,
             'Port to host CAP HTTP server on'),

            ('Identifier prefix',   3, 1, config['cap']['identifier'],      3, 20, 46, 128, 0,
             'String to prefix to the CAP message identifier: format will be: {prefix}.{msg_counter}'),

            ('Sender',              4, 1, config['cap']['sender'],          4, 20, 46, 128, 0,
             'CAP sender identifier'),

            ('Strict parsing',      5, 1, config['cap']['strict_parsing'],  5, 20, 4,  3,   0,
             'Enforce strict CAP XML parsing [yes/no]')
            ])

        if code == Dialog.OK:
            # Check identifier and sender for illegal characters
            if any(c in ' ,<&' for c in elems[3] + elems[4]):
                _error('Spaces, commas, < and & not allowed in Identifier and/or Sender.')
                continue

            # Save the changes
            config['cap'] = {
                             'host':             elems[0],
                             'port':             elems[1],
                             'identifier':       elems[2],
                             'sender':           elems[3],
                             'strict_parsing':   elems[4]
                            }
            with open(server_config, 'w') as config_file:
                config.write(config_file)

            # Restart the CAP server to apply changes
            d.gauge_start('', height=6, width=64, percent=0)
            cap_restart()
            d.gauge_stop()

        break

def announce():
    def cap_announcement():
        # TODO let user fill out form with description, message, etc.
        #      signal announcement and perform stream replacement if configured
        _error('Not Yet Implemented')

    while True:
        # Load in announcements from multiplexer config
        menu = [('CAP', 'Manually send a CAP alarm announcement')]

        for name, announcement in dabsrv.config.cfg.ensemble.announcements:
            cluster = str(announcement.cluster)

            supported = ''
            for atype, state in announcement.flags:
                if announcement.flags.getboolean(atype):
                    supported += f'{atype}, '
            supported = supported[:-2]

            subch = str(announcement.subchannel)

            # query the state of the announcement
            state = bool(int(utils.mux_send(dabsrv.zmqsock, ('get', name, 'active'))))

            menu.append((f'{"* " if state else "  "}{name}', f'Cluster {cluster}: {supported} (Switch to "{subch}")'))

        code, tag = d.menu('''
Please select the announcement to signal.
Announcements prefixed with a * are currently active.
''', title=f'Manual announcement signalling',
                        cancel_label='Back', choices=menu)

        if code in (Dialog.CANCEL, Dialog.ESC):
            break
        elif tag == 'CAP':
            cap_announcement()
        elif code == Dialog.OK:
            announcement = tag[2:]

            # Check if the announcement is active or not
            out = ''
            if tag[0] == '*':
                out = utils.mux_send(dabsrv.zmqsock, ('set', announcement, 'active', '0'))
                logger.info(f'Manually deactivating {announcement} announcement, res: {out}')
            else:
                out = utils.mux_send(dabsrv.zmqsock, ('set', announcement, 'active', '1'))
                logger.info(f'Manually activating {announcement} announcement, res: {out}')

            # Check if the announcement was successfully activated
            if out != 'ok':
                d.msgbox(f'Error while (de)activating announcement {announcement}: {out}', title='Error', width=60, height=8)

def restart():
    # TODO implement
    _error('Not Yet Implemented')

def main_menu():
    while True:
        code, tag = d.menu('Main menu', title='CAP-DAB Server', ok_label='Select', no_cancel=True, choices=[
                          ('Status',      'View the server status'),
                          ('DAB',         'Configure the DAB multiplex'),
                          ('CAP',         'Configure the CAP server'),
                          ('Settings',    'Configure general server settings'),
                          ('Logs',        'View the server logs'),
                          ('Announce',    'Manually signal announcements'),
                          ('Restart',     'Restart one or more server components'),
                          ('Quit',        'Stop the server and quit')
                          ])

        if code == Dialog.ESC or tag == 'Quit':
            break
        elif tag == 'Status':
            status()
        elif tag == 'DAB':
            dab_config()
        elif tag == 'CAP':
            cap_config()
        elif tag == 'Settings':
            settings()
        elif tag == 'Logs':
            log()
        elif tag == 'Announce':
            announce()
        elif tag == 'Restart':
            restart()

# Main setup
def main():
    global capsrv, dabsrv, dabstreams

    d.set_background_title('CFNS - Rijkswaterstaat CIV, Delft © 2021 - 2022 | Bastiaan Teeuwen <bastiaan@mkcl.nl>')

    # Setup a queue for synchronizing data between the CAP and DAB threads
    q = queue.Queue(maxsize=int(config['general']['queuelimit']))

    GAUGE_HEIGHT = 6
    GAUGE_WIDTH = 64

    # Start up CAP server
    d.gauge_start('Starting CAP Server...', height=GAUGE_HEIGHT, width=GAUGE_WIDTH, percent=0)
    capsrv = CAPServer(config, q)
    if not capsrv.start():
        d.gauge_stop()
        d.msgbox('Failed to start CAP server, please refer to the server logs', title='Error',
                 width=GAUGE_WIDTH, height=GAUGE_HEIGHT)
        d.gauge_start('', height=GAUGE_HEIGHT, width=GAUGE_WIDTH, percent=0)

    # Start the DAB streams
    d.gauge_update(33, 'Starting DAB streams...', update_text=True)
    dabstreams = DABStreams(config)
    if not dabstreams.start():
        d.gauge_stop()
        d.msgbox('Failed to start one or more DAB streams, please check configuration', title='Error',
                 width=GAUGE_WIDTH, height=GAUGE_HEIGHT)
        d.gauge_start('', height=GAUGE_HEIGHT, width=GAUGE_WIDTH, percent=33)

    # Start the DAB server
    d.gauge_update(66, 'Starting DAB server...', update_text=True)
    dabsrv = DABServer(config, q, dabstreams)
    if not dabsrv.start():
        d.gauge_stop()
        d.msgbox('Failed to start DAB server, please refer to the server logs', title='Error',
                 width=GAUGE_WIDTH, height=GAUGE_HEIGHT)
        d.gauge_start('', height=GAUGE_HEIGHT, width=GAUGE_WIDTH, percent=66)

    d.gauge_update(100, 'Ready!', update_text=True)
    time.sleep(0.5)
    d.gauge_stop()

    # Open the main menu
    main_menu()

    # Stop the CAP server
    d.gauge_start('Shutting down CAP Server...', height=6, width=64, percent=0)
    capsrv.stop()

    # Stop the DAB streams
    d.gauge_update(33, 'Shutting down DAB streams...', update_text=True)
    q.join()
    dabstreams.stop()

    # Stop the DAB server
    d.gauge_update(66, 'Shutting down DAB server...', update_text=True)
    dabsrv.stop()

    d.gauge_update(100, 'Goodbye!', update_text=True)
    time.sleep(0.5)
    d.gauge_stop()

if __name__ == '__main__':
    main()
