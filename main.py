#!/usr/bin/env python3

# Support loading modules from subdirectories
import sys
import os
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.dirname(SCRIPT_DIR))

import threading                    # Threading support (for running Flask and DAB Mux/Mod in the background)
from dialog import Dialog           # Beautiful dialogs using the external program dialog
from cap.server import cap_server   # CAP server
from dab.server import dab_server   # DAB server

# TODO add to command line parameters
logdir = 'log' # TODO remove trailing slashes from logdir
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
    global cap_thread
    global dab_thread

    def state(b):
        if b:
            return '\Zb\Z2OK\Zn'
        else:
            return '\Zb\Z1STOPPED\Zn'

    # TODO interface with the DABServer class to obtain the mux and mod status
    while True:
        code = d.msgbox(f'''
CAP HTTP Server     {state(cap_thread.is_alive())}
DAB Server Thread   {state(dab_thread.is_alive())}
DAB Multiplexer     {state(True if subprocess.run(('pgrep', 'odr-dabmux'), capture_output=True).returncode == 0 else False)}
DAB Modulator       {state(True if subprocess.run(('pgrep', 'odr-dabmod'), capture_output=True).returncode == 0 else False)}
''',                    title='Server Status', colors=True, no_collapse=True,
                        ok_label='Refresh', extra_button=True, extra_label='Exit')

        if code in (Dialog.EXTRA, Dialog.ESC):
            break

def ensemble_config():
    def country():
        while True:
            code, elems = d.form('', title='Country - Ensemble Configuration', elements=[
                ('Country ID',  1, 1, dab_cfg.ensemble['id'][2:], 1, 20, 5, 4),
                ('ECC',         2, 1, dab_cfg.ensemble['ecc'][2:], 2, 20, 3, 2),
                ])

            # TODO check if country ID is valid

            if code == Dialog.OK:
                pass
            elif code in (Dialog.CANCEL, Dialog.ESC):
                break

    def label():
        while True:
            code, elems = d.form('''
\ZbLabel\Zn cannot be longer than 16 characters.
\ZbShort Label\Zn cannot be longer than 8 characters and must contain characters from Label.
            ''', colors=True, title='Label - Ensemble Configuration', elements=[
                ('Label',       1, 1, dab_cfg.ensemble['label'], 1, 20, 17, 16),
                ('Short Label', 2, 1, dab_cfg.ensemble['shortlabel'], 2, 20, 9, 8)
                ])

            # TODO check if label contains characters from short label

            if code == Dialog.OK:
                pass
            elif code in (Dialog.CANCEL, Dialog.ESC):
                break

    def announcements():
        pass

    while True:
        code, tag = d.menu('', title='Ensemble Configuration', choices=[
                          ('Country',       'Change the DAB Country ID and ECC'),
                          ('Label',         'Change the ensemble label'),
                          ('Announcements', 'Change the ensemble announcements (FIG 0/19)'),
                          ('< Return',      'Return to the previous menu')
                          ])

        if tag == 'Country':
            country()
        elif tag == 'Label':
            label()
        elif tag == 'Announcements':
            announcements()
        elif tag == '< Return' or code in (Dialog.CANCEL, Dialog.ESC):
            break

def channel_config():
    while True:
        code, tag = d.menu('Please select what you would like to do', title='DAB Sub-Channel Configuration', choices=[
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
        elif tag == '< Return' or code in (Dialog.CANCEL, Dialog.ESC):
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
        code, tag = d.menu('', title='Server log management', choices=[
                          ('CAP',           'View CAP HTTP server log'),
                          ('Multiplexer',   'View DAB Multiplexer log'),
                          ('Modulator',     'View DAB Modulator log'),
                          ('< Return',      'Return to the previous menu'),
                          ])

        if tag == 'CAP':
            logbox(f'{logdir}/capsrv.log')
        elif tag == 'Multiplexer':
            logbox(f'{logdir}/dabmux.log')
        elif tag == 'Modulator':
            logbox(f'{logdir}/dabmod.log')
        elif tag == '< Return' or code in (Dialog.CANCEL, Dialog.ESC):
            break

def main():
    while True:
        code, tag = d.menu('Main menu', title='CAP-DAB Server Admin Interface', cancel_label='Quit', choices=[
                          ('Status',  'View the server status'),
                          ('Ensemble','Configure DAB ensemble'),
                          ('Channels','Configure DAB sub-channels'),
                          ('Logs',    'View the server logs'),
                          ('Quit',    'Stop the server and quit the admin interface')
                          ])

        if tag == 'Status':
            status()
        elif tag == 'Ensemble':
            ensemble_config()
        elif tag == 'Channels':
            channel_config()
        elif tag == 'Logs':
            log()
        elif tag == 'Quit' or code in (Dialog.CANCEL, Dialog.ESC):
            break
    print('')

if __name__ == '__main__':
    global cap_thread
    global dab_thread, dab_cfg

    # start up CAP and DAB server threads
    cap_thread = cap_server(logdir, host, port, strict)
    dab_thread, dab_cfg = dab_server(logdir, muxcfg, modcfg)

    d.set_background_title('© 2021 Rijkswaterstaat-CIV CFNS Bastiaan Teeuwen <bastiaan@mkcl.nl>')

    # open the main menu
    main()

    # wait for CAP and DAB server threads to end
    cap_thread.join()
    dab_thread.join()
