# pyqemu
Scripting utility to create qemu machines with decent interface


## Example:
```python
import os
import pyqemu

#To generate device files
gen = pyqemu.QEMUFilesGenerator("/path/to/quemu")
gen.generate_devices_file()

#Example with one cdron and one hard drive
options = pyqemu.QEMUOptions("/path/to/quemu")
cd_rom_id = options.add_cdrom("/path/to/install.iso")
hdd_id = options.add_hard_drive("/path/to/disk_image.iso")
options.set_boot_order(cd_rom_id, 0)
options.set_acceleration_mode(QEMUAccelerationMode.HAX)
options.set_boot_order(hdd_id, 1)
options.set_ram_megabytes(4096)

os.system(options.to_command_line())
```
