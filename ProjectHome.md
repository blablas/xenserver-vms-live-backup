## TINABS (This Is Not Another Backup Script) ##
It is based on using the python API and tested under XenServer 5.6 FP1.

I wrote this one because other methods didn't quite meet my organization needs.

### Description: ###
This library allows you to create simple scripts to backup the skeleton of one or more virtual machines.
By skeleton I mean the complete virtual machine structure:
  * CPUs
  * Memory
  * VIFs
  * HA stuff
  * System disk (/ or c:\)

Data disks are not included and they are recreated empty.

### Features highligths: ###
  1. Live backup and export of virtual machines.
  1. I don't care about creating a snapshot of the entire virtual machine including even any data disks since their data are already backed up with a backup tool.
  1. Run from a remote host (even a Windows machine)
  1. Provide a simple GUI (WxPython + XRC)
  1. ~~By default (if running through the GUI) all pool's virtual machines tagged with the current day of the week (in the format: Mon, Tue, Wed, Thu, Fri, Sat, Sun) are selected for backup.~~
  1. VMs list to be backed up could be selected by tag (a single virtual machine can be selected by name as well)

### How it works: ###
The core of the library is the **backup()** function which iterates through a list of user supplied virtual machines and:
  * gets a snapshot of the system disk, attach it to a brand new virtual machine created based on the parameters of the current one in the list,
  * recreates any data disks on a shared SR (I preferly use an NFS SR as destination due to the fact that **_“For file-based VHDs, all nodes consume only as much data as has been written, and the leaf node files grow to accommodate data as it is actively written. If a 100GB VDI is allocated for a new VM and an OS is installed, the VDI file will physically be only the size of the OS data that has been written to the disk, plus some minor metadata overhead”_** as stated in [XenServer Administrator's Guide](http://docs.vmd.citrix.com/XenServer/5.6.0fp1/1.0/en_gb/reference.html#id869395)) and attaches them to the backup one,
  * recreates any VIFs of the original virtual machine and attaches them to the backup one,
  * exports the backup virtual machine in .xva format on a local directory,
  * completely deletes the backup virtual machine.

The restoring process simply consists in importing the .xva previously created and restoring any data from a former backup!

## UPDATE 12/10/2011 ##
I start a new branch which slightly differs from the main trunk.
It's a bit less general and addresses a particular backup scenario in our enterprise:

Basically we would likely to avoid network traffic spawned by the export process and shift the load on the storage subsystem.
Indeed we copy the snapshot of the system VDI to a "backup" SR, reattach that copy to the backup-VM metadata and finally export its metadata only.
We end up having the VM metadata saved on a network path and the root VDI (and eventualy other data VDIs skeleton) saved on a bakup SR.
The backup SR could be located on a different storage subsystem than the one hosting the original system VDI.
Obviously the two disk subsystem must reside in the same storage area network so that the backup SR can be attached/detached to the production environment as needed; this way we also move forward disaster recovery stuff :D

Major modifications are located in file **XenBackup.py**.

## UPDATE 02/10/2012 ##
Merged branch 2.0 into trunk