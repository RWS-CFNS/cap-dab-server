#!/usr/bin/env python3

# Support loading modules from subdirectories
import sys
import os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.dirname(SCRIPT_DIR))

import configparser                 # Python INI file parser
import logging                      # Logging facilities
import logging.handlers             # Logging handlers
import threading                    # Threading support (for running Flask and DAB Mux/Mod in the background)
import time                         # For sleep support
from dialog import Dialog           # Beautiful dialogs using the external program dialog
from cap.server import cap_server   # CAP server
from dab.server import dab_server   # DAB server
from dab.odr import ODRMuxConfig    # OpenDigitalRadio server support
import string                       # String utilities (for checking if string is hexadecimal)

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
                         'max_log_size': '8192'
                        }
    config['dab'] = {
                         'odrbin_path': f'{sys.path[0]}/bin',
                         'mux_config': f'{CONFIG_HOME}/cap-dab-server/dabmux.mux',
                         'mod_config': f'{CONFIG_HOME}/cap-dab-server/dabmod.ini',
                         'telnetport': '39899'
                        }
    config['cap'] = {
                         'strict_parsing': 'no',
                         'host': '127.0.0.1',
                         'port': '39800'
                        }

    with open(server_config, 'w') as config_file:
        config.write(config_file)

# Create directories if they didn't exist yet
os.makedirs(os.path.dirname(config['general']['logdir']), exist_ok=True)
os.makedirs(os.path.dirname(config['dab']['odrbin_path']), exist_ok=True)
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

# Method to restart the DABServer
def dab_restart():
    global dab_thread, dab_cfg

    # TODO check if any actual changes have been made

    # save changes and reload the DAB server
    logger.info('Restarting DAB server, one moment please...')
    d.gauge_start('Saving changes, one moment please...', height=6, width=64, percent=0)
    dab_cfg.write()
    d.gauge_update(25, 'Shutting down DAB Server...', update_text=True)
    dab_thread.join()

    # give sockets some time to unbind before starting back up
    d.gauge_update(50, 'Waiting for sockets to unbind...', update_text=True)
    time.sleep(4)
    d.gauge_update(75, 'Starting DAB Server...', update_text=True)
    dab_thread, dab_cfg = dab_server(config)

    d.gauge_update(100, 'Successfully saved!', update_text=True)
    time.sleep(1)
    d.gauge_stop()

import subprocess # TODO TEMP, see note below
def status():
    def state(b):
        if b:
            return '\Zb\Z2OK\Zn'
        else:
            return '\Zb\Z1STOPPED\Zn'

    # TODO interface with the DABServer class to obtain the mux and mod status
    while True:
        code = d.msgbox(f'''
CAP HTTP Server     {'FAILED' if cap_thread == None else state(cap_thread.is_alive())}
DAB Server Thread   {'FAILED' if dab_thread == None else state(dab_thread.is_alive())}
DAB Multiplexer     {state(True if subprocess.run(('pgrep', 'odr-dabmux'), capture_output=True).returncode == 0 else False)}
DAB Modulator       {state(True if subprocess.run(('pgrep', 'odr-dabmod'), capture_output=True).returncode == 0 else False)}
''',                    colors=True, title='Server Status', no_collapse=True,
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
            return (None, None)

# Label and short label renaming menu, used for both ensemble and DAB services configuration
def label_config(title, label, shortlabel):
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

        return (None, None)

def ensemble_config():
    TITLE = 'DAB Ensemble Configuration'

    def announcements():
        # TODO implement
        pass

    # before doing anything, create a copy of the current DAB config
    dab_cfg.save()

    while True:
        code, tag = d.menu('', title=TITLE, extra_button=True, extra_label='Save', choices=[
                          ('Country',           'Change the DAB Country ID and ECC'),
                          ('Label',             'Change the ensemble label'),
                          ('Announcements',     'Add/Remove/Modify ensemble announcements (FIG 0/19)')
                          ])

        if code == Dialog.EXTRA:
            dab_restart()
            break
        if code in (Dialog.CANCEL, Dialog.ESC):
            # restore the old config
            dab_cfg.restore()
            break
        elif tag == 'Country':
            cid, ecc = country_config(TITLE, dab_cfg.cfg.ensemble['id'], dab_cfg.cfg.ensemble['ecc'])

            if cid != None and ecc != None:
                dab_cfg.cfg.ensemble['id'] = cid
                dab_cfg.cfg.ensemble['ecc'] = ecc
        elif tag == 'Label':
            label, shortlabel = label_config(TITLE, dab_cfg.cfg.ensemble['label'], dab_cfg.cfg.ensemble['shortlabel'])

            if label != None and shortlabel != None:
                dab_cfg.cfg.ensemble['label'] = label
                dab_cfg.cfg.ensemble['shortlabel'] = shortlabel
        elif tag == 'Announcements':
            announcements()

def services_config():
    TITLE = 'DAB Service Configuration'

    def services():
        def modify(channel):
            # TODO check if required fields have been entered (label and ID)

            while True:
                code, tag = d.menu('', title=f'{channel} - {TITLE}', extra_button=True, extra_label='Delete', cancel_label='Back', choices=[
                                ('Service ID',      'Change the service ID and override the ECC from the ensemble default'),
                                ('Label',           'Change the service label'),
                                ('Programme Type',  ''),
                                ('Announcements',   '')
                                ])

                if code in (Dialog.CANCEL, Dialog.ESC):
                    break
                elif code == Dialog.EXTRA:
                    yncode = d.yesno(f'Are you sure you want to delete the service {channel}?', width=60, height=6)
                    if yncode == Dialog.OK:
                        del dab_cfg.cfg.services[channel]
                        break
                elif tag == 'Service ID':
                    sid, ecc = country_config(TITLE, dab_cfg.cfg.services[channel]['id'], dab_cfg.cfg.services[channel]['ecc'])

                    # TODO check if Service ID is already in use

                    if sid != None:
                        dab_cfg.cfg.services[channel]['id'] = sid

                    if ecc != None:
                        dab_cfg.cfg.services[channel]['ecc'] = ecc
                    else:
                        del dab_cfg.cfg.services[channel]['ecc']
                elif tag == 'Label':
                    label, shortlabel = label_config(TITLE, dab_cfg.cfg.services[channel]['label'], dab_cfg.cfg.services[channel]['shortlabel'])

                    if label != None:
                        dab_cfg.cfg.services[channel]['label'] = label
                    if shortlabel != None:
                        dab_cfg.cfg.services[channel]['shortlabel'] = shortlabel
                    else:
                        del dab_cfg.cfg.services[channel]['shortlabel']
                elif tag == 'Programme Type':
                    # TODO implement
                    pass
                elif tag == 'Announcements':
                    # TODO implement
                    pass

        def add():
            while True:
                code, string = d.inputbox('Please enter a new identifier/name for this service (no spaces)')
                if ' ' in string:
                    error('String cannot contain spaces.')
                else:
                    dab_cfg.cfg.services[string]
                    modify(string)
                    break

        while True:
            menu = [
                   ('Add',      'Add a new service')
                   ]

            # Load in services from multiplexer config
            i = 0
            for key, value in dab_cfg.cfg.services:
                menu.insert(i, (key, dab_cfg.cfg.services[key]['label']))
                i += 1

            code, tag = d.menu('Please select a service', title=TITLE, cancel_label='Back', choices=menu)

            if code in (Dialog.CANCEL, Dialog.ESC):
                break
            elif tag == 'Add':
                add()
            elif code == Dialog.OK:
                modify(tag)

    def streams():
        pass

    def announcements():
        pass

    # before doing anything, create a copy of the current DAB config
    dab_cfg.save()

    while True:
        code, tag = d.menu('', title=TITLE, extra_button=True, extra_label='Save', choices=[
                          ('Services',          'Add/Modify services'),
                          ('Subchannels',       'Add/Modify subchannels'),
                          ('Streams',           'Add/Modify/Set the service stream source'),
                          ('Announcements',     'Manually trigger announcements on a service')
                          ])

        if code == Dialog.EXTRA:
            dab_restart()
            break
        elif code in (Dialog.CANCEL, Dialog.ESC):
            # restore the old config
            dab_cfg.restore()
            break
        elif tag == 'Services':
            services()
        elif tag == 'Subchannels':
            services()
        elif tag == 'Streams':
            streams()
        elif tag == 'Announcements':
            announcements()

def settings():
    while True:
        code, elems = d.mixedform('''
'''                              , title='Country - Ensemble Configuration', colors=True, ok_label='Save', item_help=True, help_tags=True, elements=[
            ('Server config',       1,  1, server_config,                     1,  20, 64, MAX_PATH, 2,
             'server.ini config file path'),
            ('Log directory',       2,  1, config['general']['logdir'],       2,  20, 64, MAX_PATH, 0,
             'Directory to write log files to'),
            ('Max log size',        3,  1, config['general']['max_log_size'], 3,  20, 8,  7,        0,
             'Maximum size per log file in Kb'),
            ('ODR binaries path',   4,  1, config['dab']['odrbin_path'],      4,  20, 64, MAX_PATH, 0,
             'Directory containing ODR-DabMux, ODR-DabMod, ODR-PadEnc and ODR-AudioEnc'),
            ('ODR-DabMux config',   5,  1, config['dab']['mux_config'],       5,  20, 64, MAX_PATH, 0,
             'dabmux.mux config file path'),
            ('ODR-DabMod config',   6,  1, config['dab']['mod_config'],       6,  20, 64, MAX_PATH, 0,
             'dabmod.ini config file path'),
            ('DAB telnetport',      7,  1, config['dab']['telnetport'],       7,  20, 6,  5,        0,
             'Internally used DabMux telnetport used for signalling announcements'),
            ('Strict CAP parsing',  8,  1, config['cap']['strict_parsing'],   8,  20, 4,  3,        0,
             'Enforce strict CAP XML parsing (yes/no)'),
            ('CAP server host',     9,  1, config['cap']['host'],             9,  20, 46, 45,       0,
             'IP address to host CAP HTTP server on (IPv4/IPv6)'),
            ('CAP server port',     10, 1, config['cap']['port'],             10, 20, 6,  5,        0,
             'Port to host CAP HTTP server on')
            ])

        if code == Dialog.OK:
            # Save the changes
            config['general'] = {
                                'logdir': elems[1],
                                'max_log_size': elems[2]
                                }
            config['dab'] = {
                                'odrbin_path': elems[3],
                                'mux_config': elems[4],
                                'mod_config': elems[5],
                                'telnetport': elems[6]
                                }
            config['cap'] = {
                                'strict_parsing': elems[7],
                                'host': elems[8],
                                'port': elems[9]
                                }
            with open(server_config, 'w') as config_file:
                config.write(config_file)

            # TODO restart server if necessary

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
            logbox(f'{logdir}/server.log')
        elif tag == 'CAP':
            logbox(f'{logdir}/capsrv.log')
        elif tag == 'Multiplexer':
            logbox(f'{logdir}/dabmux.log')
        elif tag == 'Modulator':
            logbox(f'{logdir}/dabmod.log')

def main():
    while True:
        code, tag = d.menu('Main menu', title='CAP-DAB Server Admin Interface', ok_label='Select', no_cancel=True, choices=
                          [( 'Status',      'View the server status')] +
                          ([('Ensemble',    'Configure DAB ensemble')] if dab_thread != None else []) +
                          ([('Services',    'Configure DAB services and subchannels')] if dab_thread != None else []) +
                          [( 'Settings',    'Configure general server settings')] +
                          [( 'Logs',        'View the server logs')] +
                          [( 'Quit',        'Stop the server and quit the admin interface')]
                          )

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
        elif tag == 'Logs':
            log()

if __name__ == '__main__':
    global cap_thread
    global dab_thread, dab_cfg

    d.set_background_title('© 2021 Rijkswaterstaat-CIV CFNS - Bastiaan Teeuwen <bastiaan@mkcl.nl>')

    # start up CAP and DAB server threads
    d.gauge_start('Starting CAP Server...', height=6, width=64, percent=0)
    cap_thread = cap_server(config)
    d.gauge_update(50, 'Starting DAB Server...', update_text=True)
    dab_thread, dab_cfg = dab_server(config)
    d.gauge_update(75, 'Starting DAB streams...', update_text=True)
    # TODO
    d.gauge_update(100, 'Ready!', update_text=True)
    d.gauge_stop()

    # open the main menu
    main()

    # wait for CAP and DAB server threads to end
    d.gauge_start('Shutting down CAP Server...', height=6, width=64, percent=0)
    if cap_thread != None:
        cap_thread.join()
    d.gauge_update(50, 'Shutting down DAB Server...', update_text=True)
    if dab_thread != None:
        dab_thread.join()
    d.gauge_update(100, 'Goodbye!', update_text=True)
    d.gauge_stop()
