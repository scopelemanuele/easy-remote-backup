
#               Created by scopel emanuele scopel.emanuele(at)gmail.com
#                               v 1.0 15 mar 2014

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>


from datetime import date, datetime
import paramiko
import os
import sys
import re
import base64
import getpass
import socket
import traceback
import logging
import string


LOG_FILE = ''


CONFIG = {
    "to_usb": True,
    "log": "/var/log/backuper.log",
    "backup_command": [('1,2,3,4,5,7', '/path/to/remote/backup_inc'), ('6', '/path/to/remote/backup_full')],
    "host": "remote.server.it",
    "remote_dir": "/remote/path/backup",
    "user": "remote_user",
    "local_dir": "/backup",
    "mount_base": "/media",
    "pwd": "********",
    "port": 22,
    "max_full_backup_age": 90,
    "max_inc_backup_age": 6,
}


def get_usb_uri(base):
    tmp = None
    root = os.listdir(base)
    for subdir in root:
        targets = os.listdir(os.path.join(base, subdir))
        if "backup" in targets:
            tmp = subdir
    if tmp:
        return os.path.join(base, tmp, CONFIG['local_dir'][1:])
    else:
        return None


class Device:
    """Simple Object to represent system mountable disk"""
    def __init__(self, dev_name, dev_UUID, dev_label, dev_type):
        self.dev_name = dev_name
        self.dev_UUID = dev_UUID
        self.dev_label = dev_label
        self.dev_type = dev_type
        self.dev_mount = False

    def already_mounted(self):
        self.dev_mount = True

    def details(self):
        print 'Device Name: %s' % (self.dev_name)
        print 'Device UUID: %s' % (self.dev_UUID)
        print 'Device Label: %s' % (self.dev_label)
        print 'Device Type: %s' % (self.dev_type)
        print 'Device Mounted?: %s' % (self.dev_mount)
        print ''


def get_device():
    devices = []
    blk_output = os.popen('blkid').read()
    dev_LABEL, dev_UUID, dev_TYPE = '_not_set', 'N/A', 'N/A'
    for items in blk_output.split('\n')[:-1]:
        dev_LABEL, dev_UUID, dev_TYPE = '_not_set', 'N/A', 'N/A'
        dev_NAME = items.strip().split()[0][:-1]
        for item in items.strip().split():
            if re.match('UUID', item):
                dev_UUID = re.search('\".*\"', item).group(0).strip('\"'); continue
            elif re.match('TYPE', item):
                dev_TYPE = re.search('\".*\"', item).group(0).strip('\"'); continue
            elif re.match('LABEL', item):
                dev_LABEL = re.search('\".*\"', item).group(0).strip('\"'); continue
        if dev_UUID != 'N/A':
            devices.append(Device(dev_NAME, dev_UUID, dev_LABEL, dev_TYPE))
    return devices


def get_mounted(dev):
    devices = []
    mount_output = os.popen('mount -l').read()
    for device in mount_output.split('\n'):
        for d in dev:
            if string.find(device, d.dev_name) != -1:
                d.already_mounted()
            if not d in devices:
                devices.append(d)
    return devices


def mount_media(mount_base):
    for device in get_mounted(get_device()):
        if device.dev_mount:
            logging.info('***Ignoring device: %s (already mounted)' % (device.dev_name))
        elif device.dev_type == 'swap':
            logging.info('***Ignoring device: %s (swap)' % (device.dev_name))
        elif device.dev_name == '/dev/mmcblk0p1':
            logging.info('***Ignoring device: %s (swap)' % (device.dev_name))
        else:
            mount_dir = os.path.join(mount_base, device.dev_UUID)
            mkdir = 'mkdir %s' % (mount_dir)
            mount = 'mount -U %s %s' % (device.dev_UUID, mount_dir)
            logging.info('***Mounting device: %s (%s)' % (device.dev_name, mount_dir))
            if not os.path.exists(mount_dir):
                result = os.popen(mkdir).read()
                if result:
                    logging.info('***Dir creation failed, aborting USB mount...')
                    sys.exit(1)
            result = os.popen(mount)
            logging.info('***Mounted device on: %s (%s)' % (device.dev_name, mount_dir))


def get_connections(config):
    """
    If return 0 the connection is failed else return connection object.
    """
    try:
        client = paramiko.SSHClient()
        client.load_system_host_keys()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        logging.info('*** Connecting...')
        client.connect(config['host'], int(config['port']), config['user'], config['pwd'])
        logging.info('***Connected.')
        return client
    except Exception, e:
        logging.error('***Caught exception: %s: %s' % (e.__class__, e))
        traceback.print_exc()
        try:
            client.close()
        except:
            pass
        return 0


def get_backup(config, connection):
    """
    return code:
        0 = success
        1 = generic error
    """
    logging.info('***Open sftp')
    sftp = connection.open_sftp()
    logging.info('***Succesfull opened sftp')
    remote_dir = config['remote_dir']
    if config['to_usb']:
        usb = get_usb_uri(config['mount_base'])
        #controlla che la chiave sia inserita e che abbia la cartella backup
        if usb:
            local_dir = get_usb_uri(config['mount_base'])
        else:
            local_dir = config['local_dir']
    else:
        local_dir = config['local_dir']

    local_files = os.listdir(local_dir)
    remote_files = sftp.listdir(remote_dir)
    logging.info('***Beggining download')
    for remote_file in remote_files:
        if not remote_file in local_files:
            logging.info('***Get remote file: %s' % remote_file)
            sftp.get(os.path.join(remote_dir, remote_file), os.path.join(local_dir, remote_file))
            logging.info('***Success download: %s' % remote_file)
    logging.info('***End download')
    sftp.close()
    logging.info('***Sftp closed.')


def run_remote_backup(config, connection):
    day_cron = date.today().isoweekday()
    for command in config['backup_command']:
        cron = command[0].split(',')
        if command:
            logging.info('***Run remote commands')
            try:
                if str(day_cron) in cron:
                    logging.info('***Run cron %s command: %s' % (day_cron, command[1]))
                    stdin, stdout, stderr = connection.exec_command(command[1], bufsize=1024)
                    if stderr.read():
                        logging.error('***Error to run remote command: %s' % stderr.read())
                    if stdout.read():
                        logging.info("***Stdout: %s" % stdout.read())
            except IOError:
                logging.error('***Error to run remote command, system exist.')
                try:
                    connection.close()
                    logging.info('***Disconnected.')
                except:
                    pass
                sys.exists()


def delete_max_age(config):
    #Cancella vecchi backup
    if config['to_usb']:
        usb = get_usb_uri(config['mount_base'])
        #controlla che la chiave sia inserita e che abbia la cartella backup
        if usb:
            local_dir = get_usb_uri(config['mount_base'])
        else:
            local_dir = config['local_dir']
    else:
        local_dir = config['local_dir']
    logging.info("***Delete full backup in %s older %s" % (local_dir, config['max_full_backup_age']))
    logging.info("***Command: find %s -ctime +%s -type f -name backup-full* -exec rm  {} \;" % (local_dir, config['max_full_backup_age']))
    os.popen("find %s -ctime +%s -type f -name backup-full* -exec rm  {} \;" % (local_dir, config['max_full_backup_age']))
    logging.info("***Delete inc backup in %s" % (local_dir, config['max_inc_backup_age']))
    logging.info("***Command: find %s -type f -name backup-inc* -exec rm  {} \;" % (local_dir, config['max_inc_backup_age']))
    os.popen("find %s -ctime +%s -type f -name backup-inc* -exec rm  {} \;" % (local_dir, config['max_inc_backup_age']))


def main():
    conf_date = CONFIG
    LOG_FILE = conf_date['log']
    logging.basicConfig(format='%(asctime)s %(message)s', filename=LOG_FILE, level=logging.INFO)

    if conf_date['to_usb']:
        mount_media(conf_date['mount_base'])

    #Apre la connessione
    server_connect = get_connections(conf_date)

    #Esegue il backup remoto
    run_remote_backup(conf_date, server_connect)

    #Scarica il backup in locale
    get_backup(conf_date, server_connect)

    #Chiude la connessione
    try:
        server_connect.close()
        logging.info('***Disconnected.')
    except:
        pass
    #pulisce vecchi backup
    delete_max_age(conf_date)
    logging.info("***Exit...")


if __name__ == '__main__':
    main()
