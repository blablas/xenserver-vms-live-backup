#!/usr/bin/python
#
# File      :  XenBackupGui.py
# Project   :  XenServer Live VMs Live Backup
# Author    :  Emiliano Giovannetti
#
# Created   :  march'11
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

import XenBackupGui_xrc
import datetime, wx, XenBackup, thread
from string import Template
import wx.xrc as xrc

statusLeftText = {'taggedVM': ' tagged virtual machines will be backed up',
                    'singleVM': ' will be backed up',
                    'noVM': 'Select a virtual machine to backup',
                    'backupVMs': 'Backing up ', 
                }                
statusRightText = {'notConnected': 'Not connected',
                    'connected': 'Connected to '
                }
backupButtonLabel = {'backup': 'Backup!',
                        'abort': 'Abort'
                    }
backupButtonTooltip = {'backup': 'Start backup process',
                        'abort': 'Abort backup process'
                    }
hostButtonLabel = {'connect': 'Connect...!',
                    'disconnect': 'Disconnect...'
                    }                    
                
class xrcmainFrameSub(XenBackupGui_xrc.xrcmainFrame):
    
    def __init__(self):
        XenBackupGui_xrc.xrcmainFrame.__init__(self, parent = None)
        try:
            self.xen = XenBackup.XenServer('XenBackup.cfg', self)
        except Exception, e:
            wx.MessageBox('Error creating XenServer object:\n %s ' % str(e))
            raise        
        # Set up event handler exporting thread
        XenBackup.EVT_RESULT(self, self.OnTaskEvent)        
        self.isLogged = False
        self.vmId = datetime.datetime.today().strftime("%a")
        self.vmList = None
        self.vmCount = 0
        self.exportTaskVM = ''
        self.statusBeforeBackup = ''
        self.backupProgress = 0
        xrc.XRCCTRL(self, 'mainStatus').SetStatusText(statusRightText['notConnected'], 1)
        xrc.XRCCTRL(self, 'mainStatus').SetStatusText(self.vmId + \
            statusLeftText['taggedVM'], 0)
        xrc.XRCCTRL(self, 'backupButton').Bind(wx.EVT_ENTER_WINDOW, self.OnBackupButtonMouseOver)
        xrc.XRCCTRL(self, 'backupButton').Bind(wx.EVT_LEAVE_WINDOW, self.OnBackupButtonMouseLeave)
        self.Show()
        
    def OnTaskEvent(self, evt):
        # backup process has started
        if evt.data['name'] == XenBackup.BACKUP_EVENTS['start_backup']:
            self.vmCount = len(self.xen.config['vm'])
            # provide aborting stuff
            xrc.XRCCTRL(self, 'backupButton').SetLabel(backupButtonLabel['abort'])
            # save mainStatus' left panel
            self.statusBeforeBackup = xrc.XRCCTRL(self, 'mainStatus').GetStatusText(0)
        # backup process has finished
        elif evt.data['name'] == XenBackup.BACKUP_EVENTS['end_backup']:
            # restore backup capabilities
            xrc.XRCCTRL(self, 'backupButton').SetLabel(backupButtonLabel['backup'])
            xrc.XRCCTRL(self, 'backupButton').SetToolTip(wx.ToolTip(backupButtonTooltip['backup']))
            # enable all control previously disabled
            self.toggleAllControlEnable(True)
            xrc.XRCCTRL(self, 'backupButton').Enable(True)
            # restore mainStatus' left panel
            xrc.XRCCTRL(self, 'mainStatus').SetStatusText(self.statusBeforeBackup, 0)   
            self.backupProgress = 0         
        # single exporting task has started
        elif evt.data['name'] == XenBackup.BACKUP_EVENTS['start_task']:
            # set current exporting task
            self.exportTaskVM = evt.data['task_vm']            
        # single exporting task has finished
        elif evt.data['name'] == XenBackup.BACKUP_EVENTS['end_task']:
            self.vmCount -= 1
            self.exportTaskVM = None
        # single exporting task is in progress
        elif evt.data['name'] == XenBackup.BACKUP_EVENTS['progress_task']:
            partial = int(evt.data['progress'] * 100)
            self.backupProgress = int(evt.data['progress'] / self.vmCount * 100)
            text = Template('[$status] $backupVMs$vmName: $partial% (Total: $total%)')
            status = text.safe_substitute(status = evt.data['status'], \
                                    backupVMs = statusLeftText['backupVMs'], \
                                    vmName = evt.data['original_vm'], \
                                    partial = str(partial), \
                                    total = str(self.backupProgress))                  
            xrc.XRCCTRL(self, 'mainStatus').SetStatusText(status, 0)

    def OnButton_hostButton(self, evt):
        # If not already logged...
        if not self.isLogged:  
            # ...login to specified host...                
            wx.SafeYield()
            wx.BeginBusyCursor()                        
            # ...retreiving SR list (NFS)...
            try:
                self.isLogged = self.xen.login(xrc.XRCCTRL(self, 'hostTextCtrl').GetValue())
                xrc.XRCCTRL(self, 'srCombo').AppendItems(self.xen.get_sr_list())
            except Exception, e:
                wx.MessageBox('Error retreiving SR list:\n %s ' % str(e))
            finally:   
                wx.SafeYield()
                wx.EndBusyCursor()
                # ...and finally set controls... 
                if self.isLogged:
                    try:
                        xrc.XRCCTRL(self, 'mainStatus').SetStatusText(statusRightText['connected'] \
                            + self.xen.get_pool_name(), 1)
                    except Exception, e:
                        wx.MessageBox('Error retreiving Pool name:\n %s ' % str(e))
                    xrc.XRCCTRL(self, 'srText').Enable(self.isLogged)
                    xrc.XRCCTRL(self, 'srCombo').Enable(self.isLogged)
                    xrc.XRCCTRL(self, 'vmEnableText').Enable(self.isLogged)
                    xrc.XRCCTRL(self, 'vmEnableCheck').Enable(self.isLogged)
                    xrc.XRCCTRL(self, 'hostButton').SetLabel(hostButtonLabel['disconnect'])
        else:            
            # if already logged, logout...
            self.isLogged = not self.xen.logout()
            # ...and finally set controls
            if not self.isLogged:
                xrc.XRCCTRL(self, 'mainStatus').SetStatusText(statusRightText['notConnected'], 1)
                xrc.XRCCTRL(self, 'srText').Enable(self.isLogged)
                xrc.XRCCTRL(self, 'srCombo').Clear()
                xrc.XRCCTRL(self, 'srCombo').Append('')
                xrc.XRCCTRL(self, 'srCombo').Select(0)
                xrc.XRCCTRL(self, 'srCombo').Enable(self.isLogged)
                self.OnCombobox_srCombo(wx.EVT_COMBOBOX)
                xrc.XRCCTRL(self, 'vmEnableText').Enable(self.isLogged)
                xrc.XRCCTRL(self, 'vmEnableCheck').SetValue(wx.CHK_UNCHECKED)
                xrc.XRCCTRL(self, 'vmEnableCheck').Enable(self.isLogged)
                self.OnCheckbox_vmEnableCheck(wx.EVT_CHECKBOX)
                xrc.XRCCTRL(self, 'hostButton').SetLabel(hostButtonLabel['connect'])
                xrc.XRCCTRL(self, 'hostTextCtrl').Clear()
                xrc.XRCCTRL(self, 'backupButton').Enable(self.isLogged)
        
    def OnText_hostTextCtrl(self, evt):
        isEmpty = (len(xrc.XRCCTRL(self, 'hostTextCtrl').GetValue()) == 0)
        xrc.XRCCTRL(self, 'hostButton').Enable(not isEmpty)
        
    def OnCombobox_srCombo(self, evt):
        xrc.XRCCTRL(self, 'backupButton').Enable(self.enableBackupButton())
        
    def OnCheckbox_vmEnableCheck(self, evt):
        try:
            isChecked = xrc.XRCCTRL(self, 'vmEnableCheck').GetValue()
            if not isChecked:
                xrc.XRCCTRL(self, 'vmTextCtrl').Clear()            
                xrc.XRCCTRL(self, 'mainStatus').SetStatusText(self.vmId + \
                    statusLeftText['taggedVM'], 0)
            else:
                xrc.XRCCTRL(self, 'mainStatus').SetStatusText(statusLeftText['noVM'], 0)                                    
            xrc.XRCCTRL(self, 'vmEnableText').Enable(isChecked)
            xrc.XRCCTRL(self, 'vmTextCtrl').Enable(isChecked)
            xrc.XRCCTRL(self, 'vmText').Enable(isChecked)
            xrc.XRCCTRL(self, 'vmButton').Enable(isChecked)
        finally:
            xrc.XRCCTRL(self, 'backupButton').Enable(self.enableBackupButton())
    
    def OnText_vmTextCtrl(self, evt):
        if len(xrc.XRCCTRL(self, 'vmTextCtrl').GetValue()) == 0:
            self.vmId = datetime.datetime.today().strftime("%a")
        else:
            self.vmId = xrc.XRCCTRL(self, 'vmTextCtrl').GetValue() 
            xrc.XRCCTRL(self, 'mainStatus').SetStatusText(self.vmId + \
                statusLeftText['singleVM'], 0)
    
    def OnButton_vmButton(self, evt):
        wx.SafeYield()
        wx.BeginBusyCursor()
        # get Pool's VM list
        try:
            if self.vmList is None:
                self.vmList = self.xen.get_vm_list()
        except Exception, e:
            wx.MessageBox('Error retreiving VM list by host:\n %s ' % str(e))
        finally:
            wx.SafeYield()
            wx.EndBusyCursor()         
        # create VMs selection dialog
        vmDialog = xrcvmDialogSub(self)
        # add VM list to the tree list control grouped by hostname
        try:
            vmTree = xrc.XRCCTRL(vmDialog, 'vmTreeList')
            vmTree.AddRoot(self.xen.get_pool_name())
            for host, vms in self.vmList.iteritems():
                h = vmTree.AppendItem(vmTree.GetRootItem(), host)
                for vm in vms:
                    vmTree.AppendItem(h, vm)
            vmDialog.ShowModal()          
        finally:
            xrc.XRCCTRL(self, 'backupButton').Enable(self.enableBackupButton())
            vmDialog.Destroy()        
        
    def OnBackupButtonMouseOver(self, evt):
        if xrc.XRCCTRL(self, 'backupButton').GetLabel() == backupButtonLabel['abort']:
            wx.SafeYield()
            wx.EndBusyCursor() 
        
    def OnBackupButtonMouseLeave(self, evt):
        if xrc.XRCCTRL(self, 'backupButton').GetLabel() == backupButtonLabel['abort']:
            wx.SafeYield()
            wx.BeginBusyCursor() 
        
    def OnButton_backupButton(self, evt):
        if xrc.XRCCTRL(self, 'backupButton').GetLabel() == backupButtonLabel['backup']:
            sr = xrc.XRCCTRL(self, 'srCombo').GetValue()
            # start backup process on a different thread
            thread.start_new_thread(self.xen.backup, (self.vmId, sr))
            # disable all control except this
            xrc.XRCCTRL(self, 'backupButton').SetToolTip(wx.ToolTip(backupButtonTooltip['abort']))
            self.toggleAllControlEnable(False)            
        else:
            # abort backup process            
            xrc.XRCCTRL(self, 'backupButton').Enable(False)
            self.xen.delete_task(self.exportTaskVM)
        
    def OnButton_quitButton(self, evt):
        ret  = wx.MessageBox('Are you sure to quit?', 'Question', wx.YES_NO | wx.CENTRE | wx.NO_DEFAULT, self)
        if ret == wx.YES:
            if self.isLogged:
                self.xen.logout()
            self.Close()
        
    def toggleAllControlEnable(self, enable):
        xrc.XRCCTRL(self, 'hostTextCtrl').Enable(enable)
        xrc.XRCCTRL(self, 'hostButton').Enable(enable)
        xrc.XRCCTRL(self, 'srCombo').Enable(enable)
        xrc.XRCCTRL(self, 'vmEnableCheck').Enable(enable)
        xrc.XRCCTRL(self, 'vmTextCtrl').Enable(enable)
        xrc.XRCCTRL(self, 'vmButton').Enable(enable)
        xrc.XRCCTRL(self, 'quitButton').Enable(enable)        
        wx.SafeYield()
        if enable:
            wx.EndBusyCursor()
        else:
            wx.BeginBusyCursor()            
        
    def enableBackupButton(self):
        isFullSR = (len(xrc.XRCCTRL(self, 'srCombo').GetValue()) != 0)
        isCheckedVM = xrc.XRCCTRL(self, 'vmEnableCheck').GetValue()
        isFullVM = (len(xrc.XRCCTRL(self, 'vmTextCtrl').GetValue()) != 0)
        if (isFullSR and isCheckedVM and isFullVM) or (isFullSR and (not(isCheckedVM)) and (not(isFullVM))):
            return True
        else:
            return False

class xrcvmDialogSub(XenBackupGui_xrc.xrcvmDialog):
    
    def __init__(self, parent):
        self.myParent = parent
        self.selection = None
        XenBackupGui_xrc.xrcvmDialog.__init__(self, parent)
        
    def OnTree_sel_changed_vmTreeList(self, evt):
        selection = evt.GetItem()
        isLeaf = not xrc.XRCCTRL(self, 'vmTreeList').ItemHasChildren(selection)
        xrc.XRCCTRL(self, 'OkButton').Enable(isLeaf)
        if isLeaf:
            self.selection = selection
        else:
            self.selection = None
            
    def OnButton_CancelButton(self, evt):
        self.EndModal(wx.ID_ABORT)
        
    def OnButton_OkButton(self, evt):
        if self.selection is not None:
            selectionText = xrc.XRCCTRL(self, 'vmTreeList').GetItemText(self.selection)
            xrc.XRCCTRL(self.myParent, 'vmTextCtrl').SetValue(selectionText)
            self.EndModal(wx.ID_OK)
        else:
            self.EndModal(wx.ID_ABORT)
    
if __name__ == "__main__":
    app = wx.App(False)
    frame = xrcmainFrameSub()
    app.MainLoop()
    