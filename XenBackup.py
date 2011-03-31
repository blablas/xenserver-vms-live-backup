#!/usr/bin/python
#
# File      :  XenBackup.py
# Project   :  XenServer Live VMs Live Backup
# Author    :  Emiliano Giovannetti
#
# Created   :  february'11
#
# Description:
#   Project's function library
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

import os
import datetime
import shutil
import XenAPI
import smtplib
import logging
import logging.handlers
import urllib2
import base64
import threading
import wx
from email.MIMEText import MIMEText

BACKUP_EVENTS = {'start_backup': 'START_BACKUP',
                    'end_backup': 'END_BACKUP',
                    'start_task': 'START_TASK',
                    'progress_task': 'PROGRESS_TASK',
                    'end_task': 'END_TASK'
                }
TASK_STATUS = {'pending': 'pending',
                'success': 'success',
                'failure': 'failure',
                'cancelling': 'cancelling',
                'cancelled': 'cancelled',
                'undefined': 'undefined'
            }
EVT_RESULT_ID = wx.NewId()

def EVT_RESULT(win, func):
    """
        Define event result.
    """
    win.Connect(-1, -1, EVT_RESULT_ID, func)
    
class ResultEvent(wx.PyEvent):
    """
        Simple event to carry arbitrary result data.
    """
    def __init__(self, data):
        wx.PyEvent.__init__(self)
        self.SetEventType(EVT_RESULT_ID)
        self.data = data    
    
class VM2Export(threading.Thread):
    """ 
    VM2Export Class 
        derived from:
            threading.Thread
        description:
            Class representing a copy of the virtual machine to be exported
    """    
    """
    XenServer task list to be associated with the export process grouped by virtual machine's name 
    """
    export_tasks = {}    
    """
    event to notify export task creation 
    """
    event = threading.Event()
    """
    lock to guard task list 
    """
    lock = threading.Lock()

    def __init__(self, xen):
        """ 
        VM2Export Constructor 
            parameters:
                xen:    XenServer object,
        """
        threading.Thread.__init__(self)
        self.xen = xen        
        self.vm = None
        self.urldict = None

    def __del__(self): 
        """ 
        VM2Export Destructor 
        """                       
        try:           
            # get VM data
            vm_record = self.xen.session.xenapi.VM.get_record(self.vm)             
            self.xen.log('Destroying vm: %s' % vm_record['name_label'])
            # destroy disks
            for vbd in vm_record['VBDs']:
                vbd_record = self.xen.session.xenapi.VBD.get_record(vbd)
                if vbd_record['type'].lower() != 'disk':
                    continue                
                vdi = vbd_record['VDI']
                sr = self.xen.session.xenapi.VDI.get_SR(vdi)
                self.xen.session.xenapi.VDI.destroy(vdi)
                self.xen.session.xenapi.SR.scan(sr)                
            # destroy vm
            self.xen.session.xenapi.VM.destroy(self.vm)
        except Exception, e:
            self.xen.log('Error destroying vm %s: %s' % (vm_record['name_label'], str(e)))
            raise
    
    def create(self, vm_record, path):
        """ 
        Create backup virtual machine
            parameters:
                vm_record:  data for creating virtual machine to export,
                path:       path for exported virtual machine .xva file
        """        
        # Create new VM based on existing VM data
        data = {'name_label': vm_record['name_label'] + '_Exported',
                'name_description': vm_record['name_description'],
                'is_a_template': vm_record['is_a_template'],
                'user_version': vm_record['user_version'],
                'memory_static_max': vm_record['memory_static_max'],
                'memory_dynamic_max': vm_record['memory_dynamic_max'],
                'memory_dynamic_min': vm_record['memory_dynamic_min'],
                'memory_static_min': vm_record['memory_static_min'],
                'VCPUs_max': vm_record['VCPUs_max'],
                'VCPUs_params': vm_record['VCPUs_params'],
                'VCPUs_at_startup': vm_record['VCPUs_at_startup'],
                'actions_after_shutdown': vm_record['actions_after_shutdown'],
                'actions_after_reboot': vm_record['actions_after_reboot'],
                'actions_after_crash': vm_record['actions_after_crash'],
                'platform': vm_record['platform'],
                'blocked_operations': vm_record['blocked_operations'],
                'HVM_boot_policy': vm_record['HVM_boot_policy'],
                'HVM_boot_params': vm_record['HVM_boot_params'],
                'HVM_shadow_multiplier': vm_record['HVM_shadow_multiplier'],
                'PV_kernel': vm_record['PV_kernel'],
                'PV_ramdisk': vm_record['PV_ramdisk'],
                'PV_args': vm_record['PV_args'],
                'PV_legacy_args': vm_record['PV_legacy_args'],
                'PV_bootloader': vm_record['PV_bootloader'],
                'PV_bootloader_args': vm_record['PV_bootloader_args'],
                'affinity': vm_record['affinity'],
                'other_config': vm_record['other_config'],
                'xenstore_data': vm_record['xenstore_data'],
                'ha_always_run': False, #vm_record['ha_always_run'],
                'ha_restart_priority': vm_record['ha_restart_priority'],
                'protection_policy': vm_record['protection_policy'],
                'tags': vm_record['tags'],
                'PCI_bus': vm_record['PCI_bus'],
                'recommendations': vm_record['recommendations'],
        }   
        self.xen.log('Creating vm %s copying from %s' % (data['name_label'], vm_record['name_label']))      
        try:                       
            self.vm = self.xen.session.xenapi.VM.create(data)
        except Exception, e:               
            self.xen.log('Error creating vm %s: %s' % (data['name_label'], str(e)))
            raise    
        # for each VM's VBD, find out if its a disk then get VDI/VBD info
        self.xen.log('Adding disk(s)')
        for vbd in vm_record['VBDs']:
            vbd_record = self.xen.session.xenapi.VBD.get_record(vbd)  
            if vbd_record['type'].lower() != 'disk':
                continue
            vdi_record = self.xen.session.xenapi.VDI.get_record(vbd_record['VDI'])
            # take a snapshot of system VDI...
            if (vbd_record['userdevice'] == '0'): 
                self.xen.log('Snapshotting disk: %s' % vdi_record['name_label'])
                try:
                    vdi_copy = self.xen.session.xenapi.VDI.snapshot(self.xen.session.xenapi.VDI.get_by_uuid(vdi_record['uuid']))                            
                except Exception, e:
                    self.xen.log('Error taking snapshot of disk %s: %s' % (vdi_record['name_label'], str(e)))
                    raise
            # or recreate other VDI on the SR specified at startup...
            else:				                                        
                data = {'name_label': 'RESTORE_' + vdi_record['name_label'], 
                    'name_description': vdi_record['name_description'],
                    'tags': vdi_record['tags'],
                    'SR': self.xen.nfs_sr, 
                    'virtual_size': vdi_record['virtual_size'], 
                    'type': vdi_record['type'],
                    'sharable': vdi_record['sharable'], 
                    'read_only': vdi_record['read_only'],
                    'other_config': {}, 
                }
                self.xen.log('Creating disk: %s' % vdi_record['name_label'])
                try:
                    vdi_copy = self.xen.session.xenapi.VDI.create(data)
                except Exception, e:
                    self.xen.log('Error creating disk %s: %s' % (vdi_record['name_label'], str(e)))
                    raise
            # recreate VBD and attach the VDI to the backup VM...
            data = {'VM': self.vm,
                'VDI': vdi_copy,
                'userdevice': vbd_record['userdevice'],
                'mode': vbd_record['mode'],
                'type': vbd_record['type'],
                'bootable': vbd_record['bootable'],
                'unpluggable': vbd_record['unpluggable'],
                'empty': vbd_record['empty'],
                'other_config': {},
                'qos_algorithm_type': vbd_record['qos_algorithm_type'],
                'qos_algorithm_params': vbd_record['qos_algorithm_params'],
            }                           
            self.xen.log('Attaching disk: RESTORE_%s' % vdi_record['name_label'])
            try:
                vbd_copy = self.xen.session.xenapi.VBD.create(data)
            except Exception, e:
                self.xen.log('Error attaching disk RESTORE_%s: %s' % (vdi_record['name_label'], str(e)))
                raise
        # get info for each VM's VIF
        self.xen.log('Adding VIF(s)')
        for vif in vm_record['VIFs']:
            vif_record = self.xen.session.xenapi.VIF.get_record(vif)
            # recreate VIF and attach to the backup VM...
            network_uuid = self.xen.session.xenapi.network.get_record(vif_record['network'])['uuid']
            data = {'VM' : self.vm,
                'device' : vif_record['device'],
                'network': self.xen.session.xenapi.network.get_by_uuid(network_uuid),
                'MAC' : vif_record['MAC'],
                'MTU' : vif_record['MTU'],
                'other_config' : vif_record['other_config'],
                'qos_algorithm_type': vif_record['qos_algorithm_type'],
                'qos_algorithm_params': vif_record['qos_algorithm_params'],
            }                
            self.xen.log('Creating VIF: %s' % vif_record['device'])
            try:
                vif_copy = self.xen.session.xenapi.VIF.create(data)            
            except Exception, e:
                self.xen.log('Error creating VIF %s: %s' % (vif_record['device'], str(e)))
                raise
        # set data necessary for the exporting process
        self.urldict = dict(
            user = self.xen.username,
            login = self.xen.password,
            srv = self.xen.host,
            uuid = vm_record['uuid'],
            name = vm_record['name_label'] + '_Exported',
            ex1 = "https://",
            ex2 = "/export?uuid=",
            ex3 = path + "/",
            ex4 = ".xva",
            ex5 = "&task_id=",
            ex6 = "&session_id=" + str(self.xen.session),
            ex7 = "/export?ref=" + str(self.vm))
        
    def export(self, session, name_label):
        """ 
        Export backup virtual machine 
            parameters:
                session:    current Pool's session object,
                name_label: name of the virtual machine to be exported
        """        
        # set path for .xva export file
        filepath = self.urldict["ex3"] + self.urldict["name"] + self.urldict["ex4"]                    
        try:        
            # build authorization header
            auth = base64.encodestring("%s:%s" % (self.urldict["user"], self.urldict["login"])).strip()    
            VM2Export.event.set()
            VM2Export.event.clear()
            # build http url request (in mutex)
            VM2Export.lock.acquire()
            request = urllib2.Request(self.urldict["ex1"] + \
                self.urldict["srv"] + \
                self.urldict["ex7"] + \
                self.urldict["ex5"] + str(VM2Export.export_tasks[name_label]))
            VM2Export.lock.release()
            # add auth header to http request
            request.add_header("Authorization", "Basic %s" % auth)
            # send http url request
            export = urllib2.urlopen(request)            
            # export VM to filesystem
            outputfile = open(filepath, "wb")
            for line in export:
                outputfile.write(line)                
            outputfile.close()            
        except Exception, e:
            if (os.path.exists(filepath)):
                os.unlink(filepath)
            raise
        finally:
            # cancel task and remove it from the global list (in mutex)
            VM2Export.lock.acquire()
            # session.xenapi.task.cancel(VM2Export.export_tasks[name_label])
            del VM2Export.export_tasks[name_label]
            VM2Export.lock.release()
    
    def run(self):
        self.export(self.xen.session, \
            self.xen.session.xenapi.VM.get_name_label(self.vm))
        
class XenServer(object):    
    
    def __init__(self, conf_file, parent = None):
        self.parent = parent
        self.logger = logging.getLogger("Xen Backup")
        self.config = {}
        self.vm_to_export = None
        self.nfs_sr = None
        self.session = None
        self.user_session = None
        self.username = 'root'
        self.password = 'sharpmz731'        
        self.host = ''
        self.load_config(conf_file)
        self.log_config(self.config['log_file'])
        
    def backup(self, vm_id, sr):                
        backup_basedir = ''
        backup_dir = ''
        path = ''
        success = True        
        
        # SR where temporary backup VMs will be created
        nfs_sr = self.session.xenapi.SR.get_by_name_label(sr)
        if (len(nfs_sr) > 1):
            self.log('More than one sr with the name %s' % sr)
            return False
        elif (len(nfs_sr) == 0):
            self.log('No sr found with the name %s' % sr)
            return False
        self.nfs_sr = nfs_sr[0]
        # set base path where VMs will be exported
        backup_basedir = '%s' % self.config['backup_dir']    
        self.log('Starting backups...')
        # set list of VMs to be backed up
        if (not self.set_vm_backup_list(vm_id)):
            return False                
        # START OF MAIN BACKUP CICLE
        # notify GUI parent if exits 
        event_data = {'name': BACKUP_EVENTS['start_backup']}            
        if self.parent is not None:
            wx.PostEvent(self.parent, ResultEvent(event_data))             
        for name in self.config['vm']:
            self.vm_to_export = None
            self.log('Backing up vm %s' % name)             
            # setup export's filesystem structure
            date = datetime.datetime.today()
            path = '%s/%s' % (backup_basedir, name)
            self.log('Creating/Entering directory: %s' % path)
            backup_dir = '%s/backup-%02d%02d%02d-%02d%02d%02d' \
                % (path, date.year, date.month, date.day, date.hour, date.minute, date.second)
            self.log('Creating/Entering directory: %s' % backup_dir)                  
            # create VM 'name' directory
            if not os.path.exists(path):
                try:
                    os.mkdir(path);
                except OSError, error:
                    self.log('Error creating directory %s : %s' % (path, error.as_string()))
                    continue
            # create 'date' subdirectory
            if not os.path.exists(backup_dir):                    
                try:
                    os.mkdir(backup_dir)
                except OSError, error:
                    self.log('Error creating directory %s : %s' % (backup_dir, error.as_string()))
                    continue          
            # find oldest export path and select for deletion
            try:
                dirs = os.listdir(path)
                dirs.sort();
                dir_to_remove = None
                if (len(dirs) > int(self.config['max_backups'])):
                    dir_to_remove = dirs[0]
                # remove oldest path if there are more than 'max_backups' path
                if dir_to_remove:
                    self.log('Deleting oldest backup %s/%s ' % (path, dir_to_remove))
                    shutil.rmtree(path + '/' + dir_to_remove)
            except Exception, e:
                self.log('Error deleting directory %s/%s : %s' % (path, dir_to_remove, str(e)))
                continue 
            # get current VM...
            vm = self.session.xenapi.VM.get_by_name_label(name)
            if (len(vm) > 1):
                self.log('More than one vm with the name %s' % name)
                continue
            elif (len(vm) == 0):
                self.log('No machines found with the name %s' % name)
                continue
            vm_record = self.session.xenapi.VM.get_record(vm[0])
            # create a backup VM to be exported based on current VM data
            self.vm_to_export = VM2Export(self)   
            try:                           
                self.vm_to_export.create(vm_record, backup_dir)
            except Exception, e:
                self.log('Error creating vm %s: %s' % (str(e), self.session.xenapi.VM.get_name_label(self.vm_to_export.vm)))
                self.vm_to_export = None
                continue
            # create task associated to the export task 
            vm_to_export_name = self.session.xenapi.VM.get_name_label(self.vm_to_export.vm)
            task_name = 'VM Export ' + vm_to_export_name 
            try:               
                task = self.session.xenapi.task.create(task_name, '')
            except Exception, e:
                self.log('Error creating export task: %s' % str(e))
                continue
            exit = False
            this_deleted = False
            this_success = False
            this_status = TASK_STATUS['undefined']                                   
            # export backup VM in different thread
            self.log('Exporting VM')
            # start exporting thread
            # insert export task in the global list (in mutex)               
            VM2Export.lock.acquire()
            VM2Export.export_tasks[vm_to_export_name] = task
            VM2Export.lock.release()            
            self.vm_to_export.start()
            try:
                # wait for export task to be created
                VM2Export.event.wait()
                # notify GUI parent if exits 
                event_data = {'name': BACKUP_EVENTS['start_task'],
                                'task_vm': vm_to_export_name,
                                'original_vm': name
                            }            
                if self.parent is not None:
                    wx.PostEvent(self.parent, ResultEvent(event_data))                                 
                # register for 'task' events
                self.session.xenapi.event.register(["task"])
                while not exit:
                    try:        
                        # looking for task to be canceled (in mutex)
                        VM2Export.lock.acquire()
                        if VM2Export.export_tasks[vm_to_export_name] is None:
                            self.session.xenapi.task.cancel(task)
                        VM2Export.lock.release()
                        # block waiting for 'task' event to occurs
                        for event in self.session.xenapi.event.next():
                            if "snapshot" in event.keys():
                                snapshot = event["snapshot"]                                    
                                # processing only 'task_name' event                          
                                if snapshot["name_label"] == task_name:
                                    event_data = {'name': BACKUP_EVENTS['progress_task'],
                                                    'task': task_name, 
                                                    'status': snapshot["status"],
                                                    'progress': snapshot["progress"]
                                                }                                    
                                    # process modification of task 
                                    if event['operation'] == 'mod':                           
                                        if snapshot["status"] != TASK_STATUS['pending']:
                                            this_status = snapshot["status"]
                                            # exit loop if task is not in progress
                                            exit = True                    
                                            # exit loop with success if task succeded
                                            if snapshot["status"] == TASK_STATUS['success']:
                                                this_success = True                  
                                    # process deletation of task 'task_name'
                                    # exit loop wit failure if task has been canceled
                                    if event['operation'] == 'del':
                                        this_deleted = True
                                        exit = True                     
                                    # notify GUI parent if exits
                                    if self.parent is not None:
                                        wx.PostEvent(self.parent, ResultEvent(event_data))                                    
                    except XenAPI.Failure, e:
                        if e.details == [ "EVENTS_LOST" ]:
                            self.log('Error in monitoring task %s: %s' % (task_name, str(e)))
                # unregister for 'task' event
                self.session.xenapi.event.unregister(["task"])
                # wait for exporting thread to complete
            finally:            
                self.vm_to_export.join() 
                # delete exporting thread
                self.vm_to_export = None
                # notify GUI parent if exits 
                event_data = {'name': BACKUP_EVENTS['end_task'],
                                'status': this_status
                            }            
                if self.parent is not None:
                    wx.PostEvent(self.parent, ResultEvent(event_data))    
                # delete export task 
                self.session.xenapi.task.destroy(task)                                            
                # if a task has been deleted or has failed stop the entire backup process
                if this_deleted or not this_success:
                    success = this_success
                    # remove the interrupted .xva export file
                    try:
                        shutil.rmtree(backup_dir)
                    finally:
                        break
        # END OF MAIN BACKUP CICLE
        # notify GUI parent if exits 
        event_data = {'name': BACKUP_EVENTS['end_backup']}            
        if self.parent is not None:
            wx.PostEvent(self.parent, ResultEvent(event_data))
        self.log('Sending mail to %s using SMTP server %s' % (self.config['email_addrs'], self.config['smtp_server']))
##            self.send_email(success)
        return success
        
    def delete_task(self, task_vm):
        self.log('Aborting task \'VM Export %s\'' % task_vm)
        VM2Export.lock.acquire()
        if task_vm in VM2Export.export_tasks:
            VM2Export.export_tasks[task_vm] = None
        VM2Export.lock.release()
        
    def login(self, host):        
        self.host = host
        try:
            self.session = XenAPI.Session('https://' + self.host)
            self.user_session = self.session.xenapi.login_with_password(self.username, self.password)
        # if 'host' is not the Pool's master, retreive the master from exception details 
        # and try to reconnect (adjust 'self.host' to point to the Pool's master)
        except XenAPI.Failure, e:
            if e.details[0] == 'HOST_IS_SLAVE':
                self.session = XenAPI.Session('https://' + e.details[1])
                self.user_session = self.session.xenapi.login_with_password(self.username, self.password)
                self.host = e.details[1]
            else:
                # raise
                return False 
        self.log('Successfully login to %s' % self.host)                 
        return True

    def logout(self):
        try:
            self.session.xenapi.session.logout()
        except Exception, e:
            self.log('Logout from %s failed: %s' % (self.host, str(e)))
            # raise
            return False
                            
        self.log('Logout from %s ' % self.host)
        return True
        
    def set_vm_backup_list(self, vm_id):
        tags = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
        # if 'vm_id' was automatically set to current week day
        # retreive all VMs tagged with one of 'tags' values
        # and add them to the backup list
        if vm_id in tags:
            try:
                vms = self.session.xenapi.VM.get_all()
                for v in vms:
                    vtags = self.session.xenapi.VM.get_tags(v)            
                    if vm_id in vtags:
                        vname = self.session.xenapi.VM.get_name_label(v)
                        self.config['vm'].append(vname)
                if (len(self.config['vm']) == 0):
                    self.log('No machines found with tag %s' % vm_id)
                    return False
            except Exception, e:
                self.log('Error retreiving VM list: %s' % str(e))
                # raise
                return False                    
        # otherwise, if a single VM name was specified at startup
        # check if the VM exists and add it to the backup list
        else:
            try:
                v = self.session.xenapi.VM.get_by_name_label(vm_id)
                if (len(v) > 1):
                    self.log('More than one vm with the name %s' % vm_id)
                    return False
                elif (len(v) == 0):
                    self.log('No machines found with the name %s' % vm_id)
                    return False     
                vname = self.session.xenapi.VM.get_name_label(v[0])
                self.config['vm'].append(vname)
            except Exception, e:
                self.log('Error retreiving VM: %s' % str(e))
                # raise
                return False                                
      
        return True
    
    def get_vm_list(self):
        vm_list = {}
        try:
            vms = self.session.xenapi.VM.get_all()
            for v in vms:
                vname = ''
                vhostname = ''
                # discard templates and control domains
                if not self.session.xenapi.VM.get_is_control_domain(v) \
                    and not self.session.xenapi.VM.get_is_a_template(v):
                    vname = self.session.xenapi.VM.get_name_label(v)
                    # if vm is running find hosting node
                    if self.session.xenapi.VM.get_power_state(v) == 'Running':
                        vhost = self.session.xenapi.VM.get_resident_on(v)
                        vhostname = self.session.xenapi.host.get_name_label(vhost)
                    # otherwise set it to 'Halted'
                    else: 
                        vhostname = 'Halted'
                    if vhostname not in vm_list:
                        vm_list[vhostname] = []                        
                    vm_list[vhostname].append(vname)                                                  
        except Exception, e:
            self.log('Error retreiving VM list by host: %s' % str(e))
            raise
        finally:
            return vm_list
        
    def get_sr_list(self):
        try:
            sr_name = []
            srs = self.session.xenapi.SR.get_all()
            for sr in srs:
                if self.session.xenapi.SR.get_shared(sr):
                    sr_name.append(self.session.xenapi.SR.get_name_label(sr))
        except Exception, e:
            self.log('Error retreiving SR list: %s' % str(e))
            raise
        finally:
            return sr_name
        
    def get_pool_name(self):
        try:
            pool_name = ''
            pools = self.session.xenapi.pool.get_all()
            for p in pools:
                m = self.session.xenapi.pool.get_master(p)
                if self.session.xenapi.host.get_address(m) == self.host:
                    pool_name = self.session.xenapi.pool.get_name_label(p)
                    break
        except Exception, e:
            self.log('Error retreiving Pool name: %s' % str(e))
            raise        
        finally:
            return pool_name
        
    def load_config(self, path):
        config_file = open(path, 'r')
        self.config['vm'] = []
        for line in config_file:
            if (not line.startswith('#') and len(line.strip()) > 0):
                (key,value) = line.strip().split('=')
                key = key.strip()
                value = value.strip()
                if key in self.config:
                    if type(self.config[key]) is list:
                        self.config[key].append(value)
                    else:
                        self.config[key] = [self.config[key], value]
                else:
                    self.config[key] = value
        config_file.close()

    def log_config(self, fn):
        # set logger level
        self.logger.setLevel(logging.INFO)        
        # create rotational handler and set level to INFO
        handler = logging.handlers.RotatingFileHandler(fn, maxBytes=1000000, backupCount=3)
        handler.setLevel(logging.INFO)        
        # create formatter
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")        
        # add formatter to ch        
        handler.setFormatter(formatter)        
        # add ch to logger        
        self.logger.addHandler(handler)

    def log(self, mes):
        self.logger.info('%s' % mes)

    def send_email(self, success):
        if not 'email_addrs' in self.config:
            return        
        message = 'This message is automatically generate by XenBackup script. Please don not reply to this message.'
        # create mail message 
        msg = MIMEText(message)
        if success:
            msg['subject'] = 'Xen Backup SUCCESS %s' % self.get_pool_name()
        else:
            msg['subject'] = 'Xen Backup FAILURE %s' % self.get_pool_name()
        msg['From'] = self.config['smtp_from']
        msg['To'] = self.config['email_addrs']
        # open connection to SMTP server
        s = smtplib.SMTP(self.config['smtp_server'])
        # send mail 
        s.sendmail(self.config['smtp_from'], self.config['email_addrs'].split(','), msg.as_string())
        # close connection to SMTP server
        s.quit()
