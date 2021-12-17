#!/usr/bin/env python3

#
#    CFNS - Rijkswaterstaat CIV, Delft © 2021 <cfns@rws.nl>
#
#    Copyright 2021 Bastiaan Teeuwen <bastiaan@mkcl.nl>
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

import configparser                 # Python INI file parser
import logging                      # Logging facilities
import logging.handlers             # Logging handlers
import queue                        # Queue for passing data to the DAB processing thread
import string                       # String utilities (for checking if string is hexadecimal)
import threading                    # Threading support (for running Flask and DAB Mux/Mod in the background)
import time                         # For sleep support
from dialog import Dialog           # Beautiful dialogs using the external program dialog
from cap.server import CAPServer    # CAP server
from dab.server import DABServer    # DAB server
from dab.streams import DABStreams  # DAB streams
from dab.odr import ODRMuxConfig    # OpenDigitalRadio server support

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
                         'mod_config': f'{CONFIG_HOME}/cap-dab-server/dabmod.ini',
                         'telnetport': '39899',
                         'output': '/tmp/cap-dab-server-output.fifo'
                        }
    config['cap'] =     {
                         'strict_parsing': 'no',
                         'host': '127.0.0.1',
                         'port': '39800'
                        }
    config['warning'] = {
                         'alarm': 'yes',
                         'replace': 'yes'
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

def cap_restart(start=0, target=100):
    d.gauge_update(start, 'Saving changes to CAP config, one moment please...', update_text=True)
    if cap.restart():
        d.gauge_update(target, 'Successfully saved!', update_text=True)
    else:
        d.gauge_update(int(target / 2), 'Failed to start CAP server, please refer to the server logs', update_text=True)
        time.sleep(4)
    time.sleep(0.5)

def dab_restart(start=0, target=100):
    d.gauge_update(start, 'Saving changes to DAB config, one moment please...', update_text=True)
    if dab.restart():
        d.gauge_update(target, 'Successfully saved!', update_text=True)
    else:
        d.gauge_update(int(target / 2), 'Failed to start DAB server, please refer to the server logs', update_text=True)
        time.sleep(4)
    time.sleep(0.5)

def status():
    def state(b):
        if b:
            return '\Zb\Z2OK\Zn'
        else:
            return '\Zb\Z1STOPPED\Zn'

    while True:
        cap_server = cap.status()
        dab_server, dab_watcher, dab_mux, dab_mod = dab.status()

        # Query the state of the various subcomponents
        states = [
            ['CAP HTTP Server', state(cap_server)],
            ['DAB Server',      state(dab_server)],
            ['DAB Streams',     ''],
            ['DAB Multiplexer', state(dab_mux)],
            ['DAB Modulator',   state(dab_mod)]
        ]

        # Insert the state of DAB Streams in separate rows (after 'DAB Streams')
        for s in streams.status():
            states.insert(3, [f'  - {s[0]}', state(s[1])])

        # Format the states list into columns
        sstr = ''
        for s in states:
            sstr += '{: <20}{: <6}\n'.format(*s)

        code = d.msgbox(sstr, colors=True, title='Server Status', no_collapse=True,
                        ok_label='Refresh', extra_button=True, extra_label='Exit')

        if code in (Dialog.EXTRA, Dialog.ESC):
            break

def error(msg=''):
    d.msgbox(f'''
Invalid entry!
{msg}
''',         title='Error', colors=True, width=60, height=8)

# Country ID modification menu, used for both ensemble and DAB services configuration
def country_config(title, cid, ecc):
    while True:
        code, elems = d.form('''
\ZbCountry ID\Zn and \ZbECC\Zn are found in section 5.4 Country Id of ETSI TS 101 756.
These values both represent a hexidecimal value.
\ZbCountry ID\Zn (Ensemble) must be padded with 0xFFF.
\ZbService ID\Zn (Service) is Country ID (0x8) + Service ID (0xDAB) -> 0x8DAB.
''',                         colors=True, title=f'Service ID and Country - {title}', elements=[
                            ('Country/Service ID',  1, 1, str(cid)[2:], 1, 20, 5, 4),
                            ('ECC',                 2, 1, str(ecc)[2:], 2, 20, 3, 2),
                            ])

        if code == Dialog.OK:
            # check if the IDs are valid hexadecimal numbers
            if not all(c in string.hexdigits for c in elems[0]):
                error('Invalid Country/Service ID.')
                continue
            if elems[1] != '' and not all(c in string.hexdigits for c in elems[1]):
                error('Invalid ECC.')
                continue

            # check the length of the IDs
            if len(elems[0]) != 4 or len(elems[1]) not in (0, 2):
                error('Invalid length.\n\ZbCountry ID\Zn must be 4 digits and \ZbECC\Zn 2 digits in length.')
                continue

            return (f'0x{elems[0]}', None if elems[1] == '' else f'0x{elems[1]}')
        else:
            return (Dialog.CANCEL, Dialog.CANCEL)

# Label and short label renaming menu, used for both ensemble and DAB services configuration
def label_config(title, label, shortlabel):
    if not isinstance(label, str):
        label = ''
    if not isinstance(shortlabel, str):
        shortlabel = ''

    while True:
        code, elems = d.form('''
\ZbLabel\Zn cannot be longer than 16 characters.
\ZbShort Label\Zn cannot be longer than 8 characters and must contain characters from \ZbLabel\Zn.
''',                         colors=True, title=f'Label - {title}', elements=[
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
                error('\ZbShort Label\Zn must contain characters from \ZbLabel\Zn.')
                continue

        return (Dialog.CANCEL, Dialog.CANCEL)

def ensemble_config():
    TITLE = 'DAB Ensemble Configuration'

    def announcements():
        # TODO implement
        pass

    # before doing anything, create a copy of the current DAB config
    dab.config.save()

    while True:
        code, tag = d.menu('', title=TITLE, extra_button=True, extra_label='Save', choices=[
                          ('Country',           'Change the DAB Country ID and ECC'),
                          ('Label',             'Change the ensemble label'),
                          ('Announcements',     'Add/Remove/Modify ensemble announcements (FIG 0/19)')
                          ])

        if code == Dialog.EXTRA:
            d.gauge_start('', height=6, width=64, percent=0)
            dab.config.write()
            dab_restart()
            d.gauge_stop()
            break
        if code in (Dialog.CANCEL, Dialog.ESC):
            # restore the old config
            dab.config.restore()
            break
        elif tag == 'Country':
            cid, ecc = country_config(TITLE, dab.config.cfg.ensemble['id'], dab.config.cfg.ensemble['ecc'])

            if cid != Dialog.CANCEL:
                if cid != None and ecc != None:
                    dab.config.cfg.ensemble['id'] = cid
                    dab.config.cfg.ensemble['ecc'] = ecc
        elif tag == 'Label':
            label, shortlabel = label_config(TITLE, dab.config.cfg.ensemble['label'], dab.config.cfg.ensemble['shortlabel'])

            if label != Dialog.CANCEL:
                if label != None and shortlabel != None:
                    dab.config.cfg.ensemble['label'] = label
                    dab.config.cfg.ensemble['shortlabel'] = shortlabel
        elif tag == 'Announcements':
            announcements()

def services_config():
    TITLE = 'Services - DAB Service Configuration'

    def services():
        def modify(service):
            # TODO check if required fields have been entered (label and ID)

            while True:
                code, tag = d.menu('', title=f'{service} - {TITLE}', extra_button=True, extra_label='Delete', cancel_label='Back', choices=[
                                ('Service ID',      'Change the service ID and override the ECC from the ensemble default'),
                                ('Label',           'Change the service label'),
                                ('Programme Type',  ''),
                                ('Announcements',   '')
                                ])

                if code in (Dialog.CANCEL, Dialog.ESC):
                    break
                elif code == Dialog.EXTRA:
                    yncode = d.yesno(f'Are you sure you want to delete the service {service}?', width=60, height=6)
                    if yncode == Dialog.OK:
                        del dab.config.cfg.services[service]
                        break
                elif tag == 'Service ID':
                    sid, ecc = country_config(TITLE,
                                              dab.config.cfg.services[service]['id'],
                                              dab.config.cfg.services[service]['ecc'])

                    # TODO check if Service ID is already in use

                    if cid != Dialog.CANCEL:
                        if sid != None:
                            dab.config.cfg.services[service]['id'] = sid

                        if ecc != None:
                            dab.config.cfg.services[service]['ecc'] = ecc
                        else:
                            del dab.config.cfg.services[service]['ecc']
                elif tag == 'Label':
                    label, shortlabel = label_config(TITLE,
                                                     dab.config.cfg.services[service]['label'],
                                                     dab.config.cfg.services[service]['shortlabel'])

                    if label != Dialog.CANCEL:
                        if label != None:
                            dab.config.cfg.services[service]['label'] = label
                        if shortlabel != None:
                            dab.config.cfg.services[service]['shortlabel'] = shortlabel
                        else:
                            del dab.config.cfg.services[service]['shortlabel']
                elif tag == 'Programme Type':
                    # TODO implement
                    pass
                elif tag == 'Announcements':
                    # TODO implement
                    pass

        def add():
            while True:
                code, string = d.inputbox('Please enter a new identifier/name for this service (no spaces)',
                                          title=f'Add service - {TITLE}')

                if code in (Dialog.CANCEL, Dialog.ESC):
                    break
                elif string == '':
                    error('Identifier cannot be empty.')
                elif ' ' in string:
                    error('Identifier cannot contain spaces.')
                else:
                    dab.config.cfg.services[string]
                    modify(string)
                    break

        while True:
            menu = [('Add', 'Add a new service')]

            # Load in services from multiplexer config
            i = 0
            for key, value in dab.config.cfg.services:
                label = dab.config.cfg.services[key]['label']
                if not isinstance(label, str):
                    label = ''

                menu.insert(i, (key, label))
                i += 1

            code, tag = d.menu('Please select a service', title=TITLE, cancel_label='Back', choices=menu)

            if code in (Dialog.CANCEL, Dialog.ESC):
                break
            elif tag == 'Add':
                add()
            elif code == Dialog.OK:
                modify(tag)

    def streams():
        #code, tags = d.menu('', title={Stream
        pass

    def warning_config():
        code, tags = d.checklist('Select the method by which you want the server to send DAB warning messages',
                                 title=f'Warning method - {TITLE}', choices=[
                   ('Alarm',    'DAB native Alarm announcement', config['warning'].getboolean('alarm')),
                   ('Replace',  'Channel stream replacement', config['warning'].getboolean('replace'))
                   ])

        if code == Dialog.OK:
            # Save the changes
            config['warning']['Alarm'] = 'yes' if 'Alarm' in tags else 'no'
            config['warning']['Replace'] = 'yes' if 'Replace' in tags else 'no'

    def announcements():
        pass

    # before doing anything, create a copy of the current DAB config
    dab.config.save()

    while True:
        code, tag = d.menu('', title=TITLE, extra_button=True, extra_label='Save', choices=[
                          ('Services',          'Add/Modify services'),
                          ('Streams',           'Add/Modify/Set the service streams/subchannels'),
                          ('Warning method',    'Set the method by which warning messages are sent'),
                          ('Announcements',     'Manually trigger announcements on a service')
                          ])

        if code == Dialog.EXTRA:
            d.gauge_start('', height=6, width=64, percent=0)
            dab.config.write()
            dab_restart()
            d.gauge_stop()
            break
        elif code in (Dialog.CANCEL, Dialog.ESC):
            # restore the old config
            dab.config.restore()
            break
        elif tag == 'Services':
            services()
        elif tag == 'Subchannels':
            subchannels()
        elif tag == 'Streams':
            streams()
        elif tag == 'Warning method':
            warning_config()
        elif tag == 'Announcements':
            announcements()

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
            ('CAP-DAB Queue limit', 4,  1, config['general']['queuelimit'],   4,  20, 8,  7,        0,
             'Maximum number of CAP messages that can be in the queue at one moment'),
            ('Streams config',      5,  1, config['dab']['stream_config'],    5,  20, 64, MAX_PATH, 0,
             'streams.ini config file path'),
            ('ODR binaries path',   6,  1, config['dab']['odrbin_path'],      6,  20, 64, MAX_PATH, 0,
             'Directory containing ODR-DabMux, ODR-DabMod, ODR-PadEnc and ODR-AudioEnc'),
            ('ODR-DabMux config',   7,  1, config['dab']['mux_config'],       7,  20, 64, MAX_PATH, 0,
             'dabmux.mux config file path'),
            ('ODR-DabMod config',   8,  1, config['dab']['mod_config'],       8,  20, 64, MAX_PATH, 0,
             'dabmod.ini config file path'),
            ('DAB telnetport',      9,  1, config['dab']['telnetport'],       9,  20, 6,  5,        0,
             'Internally used DabMux telnetport used for signalling announcements'),
            ('DAB output FIFO',     10, 1, config['dab']['output'],           10, 20, 64, MAX_PATH, 0,
             'FIFO to output modulated DAB data to'),
            ('Strict CAP parsing',  11, 1, config['cap']['strict_parsing'],   11, 20, 4,  3,        0,
             'Enforce strict CAP XML parsing (yes/no)'),
            ('CAP server host',     12, 1, config['cap']['host'],             12, 20, 46, 45,       0,
             'IP address to host CAP HTTP server on (IPv4/IPv6)'),
            ('CAP server port',     13, 1, config['cap']['port'],             13, 20, 6,  5,        0,
             'Port to host CAP HTTP server on')
            ])

        if code == Dialog.OK:
            # Save the changes
            config['general'] = {
                                'logdir': elems[1],
                                'max_log_size': elems[2],
                                'queuelimit': elems[3]
                                }
            config['dab'] = {
                                'stream_config': elems[4],
                                'odrbin_path': elems[5],
                                'mux_config': elems[6],
                                'mod_config': elems[7],
                                'telnetport': elems[8],
                                'output': elems[9]
                                }
            config['cap'] = {
                                'strict_parsing': elems[10],
                                'host': elems[11],
                                'port': elems[12]
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

def restart():
    pass

def main_menu():
    while True:
        code, tag = d.menu('Main menu', title='CAP-DAB Server Admin Interface', ok_label='Select', no_cancel=True, choices=[
                          ( 'Status',      'View the server status'),
                          ( 'Ensemble',    'Configure DAB ensemble'),
                          ( 'Services',    'Configure DAB services and streams/subchannels'),
                          ( 'Settings',    'Configure general server settings'),
                          ( 'Logs',        'View the server logs'),
                          ( 'Restart',     'Restart one or more server components'),
                          ( 'Quit',        'Stop the server and quit the admin interface')
                          ])

        if code == Dialog.ESC or tag == 'Quit':
            break
        elif tag == 'Status':
            status()
        elif tag == 'Ensemble':
            ensemble_config()
        elif tag == 'Services':
            services_config()
        elif tag == 'Settings':
            settings()
        elif tag == 'Restart':
            restart()
        elif tag == 'Logs':
            log()

# Main setup
def main():
    global cap, dab, streams

    d.set_background_title('CFNS - Rijkswaterstaat CIV, Delft © 2021 - Bastiaan Teeuwen <bastiaan@mkcl.nl>')

    # Setup a queue for synchronizing data between the CAP and DAB threads
    q = queue.Queue(maxsize=int(config['general']['queuelimit']))

    # Start up CAP server
    d.gauge_start('Starting CAP Server...', height=6, width=64, percent=0)
    cap = CAPServer(config, q)
    if not cap.start():
        d.gauge_update(17, 'Failed to start CAP server, please refer to the server logs', update_text=True)
        time.sleep(4)

    # Start the DAB streams
    d.gauge_update(33, 'Starting DAB streams...', update_text=True)
    streams = DABStreams(config)
    if not streams.start():
        d.gauge_update(50, 'Failed to start one or more DAB streams, please check configuration', update_text=True)
        time.sleep(4)

    # Start the DAB server
    d.gauge_update(66, 'Starting DAB server...', update_text=True)
    dab = DABServer(config, q, streams)
    if not dab.start():
        d.gauge_update(83, 'Failed to start DAB server, please refer to the server logs', update_text=True)
        time.sleep(4)

    d.gauge_update(100, 'Ready!', update_text=True)
    time.sleep(0.5)
    d.gauge_stop()

    # Open the main menu
    main_menu()

    # Stop the CAP server
    d.gauge_start('Shutting down CAP Server...', height=6, width=64, percent=0)
    cap.stop()

    # Stop the DAB streams
    d.gauge_update(33, 'Shutting down DAB streams...', update_text=True)
    streams.stop()

    # Stop the DAB server
    d.gauge_update(66, 'Shutting down DAB server...', update_text=True)
    dab.stop()

    d.gauge_update(100, 'Goodbye!', update_text=True)
    time.sleep(0.5)
    d.gauge_stop()

if __name__ == '__main__':
    main()
