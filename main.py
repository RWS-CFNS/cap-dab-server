#!/usr/bin/env python3

import threading            # Threading support (for running Flask and DAB Mux/Mod in the background)
import logging              # Logging facilities
from dialog import Dialog   # Beautiful dialogs using the external program dialog

import sys
import os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.dirname(SCRIPT_DIR))

from cap.server import CAPServer, cap_server
from dab.server import dab_server

# TODO add to command line parameters
logdir = 'log' # TODO remove trailing slashes from logdir
logging.basicConfig(filename=f'{logdir}/server.log', level=logging.DEBUG)
strict = False
host = '127.0.0.1'
port = 5000
muxcfg = 'cfg/dabmux.cfg'
modcfg = 'cfg/dabmod.ini'
# TODO take a textfile with a list of accepted senders as input
# TODO add config option to purge log on exit

d = Dialog(dialog='dialog', autowidgetsize=True)

import subprocess # TODO TEMP, see note below
def status():
    # TODO interface with the DABServer class to obtain the mux and mod status
    # TODO interface with cap CAPServer class to check state of CAP server
    cap = True
    mux = subprocess.run(('pgrep', 'odr-dabmux'), capture_output=True).returncode
    mod = subprocess.run(('pgrep', 'odr-dabmod'), capture_output=True).returncode

    while True:
        code = d.msgbox(f'''
CAP HTTP server     {'OK' if cap else 'STOPPED'}
DAB Multiplexer     {'OK' if mux == 0 else 'STOPPED'}
DAB Modulator       {'OK' if mod == 0 else 'STOPPED'}
''',
                        title='Server Status', no_collapse=True, ok_label='Refresh', extra_button=True, extra_label='Exit')

        if code in (Dialog.EXTRA, Dialog.ESC):
            break

def channel_config():
    while True:
        code, tag = d.menu('Please select what you would like to do', title='Radio configuration', choices=[
                        ('Add',           'Add a new sub-channel'),
                        ('Rename',        'Rename the subchannel'),
                        ('Announcements', 'Modify the supported announcements on the subchannel'),
                        ('Stream',        'Set the sub-channel stream source'),
                        ('Delete',        'Delete a sub-channel'),
                        ('Alarm',         'Manually trigger an alarm announcement on a sub-channel'),
                        ('< Return',      'Return to the previous menu')
                        ])

        if tag == 'Alarm':
            pass
        elif tag == '< Return' or code == Dialog.ESC:
            break

def logbox(file):
    #while d.textbox(file, title=file, no_shadow=True, ok_label='Refresh', extra_button=True, extra_label='Exit') not in (Dialog.EXTRA, Dialog.ESC):
    while True:
        code = d.textbox(file, title=file, no_shadow=True, ok_label='Refresh', extra_button=True, extra_label='Exit', help_button=True, help_label='Purge')

        if code in (Dialog.EXTRA, Dialog.ESC):
            break
        elif code in (Dialog.CANCEL, Dialog.HELP):
            open(file, 'w').close()
            break

def log():
    while True:
        code, tag = d.menu('', title='Server log management', choices=[
                          ('CAP',           'View CAP HTTP server log'),
                          ('Multiplexer',   'View DAB Multiplexer log'),
                          ('Modulator',     'View DAB Modulator log'),
                          ('< Return',      'Return to the previous menu'),
                          ])

        if tag == 'CAP':
            logbox(f'{logdir}/server.log')
        elif tag == 'Multiplexer':
            logbox(f'{logdir}/dabmux.log')
        elif tag == 'Modulator':
            logbox(f'{logdir}/dabmod.log')
        elif tag == '< Return' or code == Dialog.ESC:
            break

def main():
    while True:
        code, tag = d.menu('Main menu', title='CAP-DAB Server Admin Interface', choices=[
                          ('Status',  'View the server status'),
                          ('Channels','Configure DAB sub-channels'),
                          ('Log',     'View the server logs'),
                          ('Exit',    'Stop the server and exit')
                          ])

        if tag == 'Status':
            status()
        if tag == 'Channels':
            channel_config()
        elif tag == 'Log':
            log()
        elif tag == 'Exit' or code == Dialog.ESC:
            break

if __name__ == '__main__':
    # start up CAP and DAB server threads
    cap_thread = cap_server(host, port, strict)
    dab_thread = dab_server(logdir, muxcfg, modcfg)

    # Make sure dialog switches to alternate screen so it won't leave behind a mess when it's closed
    #d.add_persistent_args(['--keep-tite']) # disabled because it causes flickering
    d.set_background_title('© 2021 Rijkswaterstaat-CIV CFNS Bastiaan Teeuwen <bastiaan@mkcl.nl>')

    # open the main menu
    main()

    # wait for CAP and DAB server threads to end
    cap_thread.join()
    dab_thread.join()
