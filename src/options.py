
import os
import dataclasses
import enum

from qemu_devices import QEMUDevice, QEMUStorageDevice
class _QEMUDriveInterface(enum.Enum):
    IDE = ("ide")
    SCSI = ("scsi")
    SD = ("sd")
    MTD = ("mtd")
    FLOPPY = ("floppy")
    PFLASH = ("pflash")
    VIRTIO = ("virtio")
    NONE = ("none")

    def __init__(self, name: str):
        self.__name: str = name

    def to_qemu_string(self) -> str:
        return self.__name
        
@dataclasses.dataclass
class _QEMUDrive:
    file_path: str
    id: str

@dataclasses.dataclass
class _QEMUCDRom(_QEMUDrive):
    pass
@dataclasses.dataclass
class _QEMUHardDrive(_QEMUDrive):
    pass

class _QEMURamUnit(enum.Enum):
    MEGABYTES = 0
    GIGABYTES = 1

    def as_string(self):
        match self:
            case _QEMURamUnit.MEGABYTES: return "M"
            case _QEMURamUnit.GIGABYTES: return "G"
        raise Exception(f"Not recognized unit: {self}")

@dataclasses.dataclass
class _QEMURamSize:
    amount: int
    unit: _QEMURamUnit

@dataclasses.dataclass
class _QEMUBootOrderEntry:
    drive_id: str
    index: int
            
        
class QEMUAccelerationMode(enum.Enum): 
    KVM = ("kvm")
    XEN = ("xen")
    HAX = ("hax")
    HVF = ("hvf")
    NVMM = ("nvmm")
    WHPX = ("whpx")
    TCG = ("tcg")

    def __init__(self, name) -> None:
        self.__name = name

    def to_qemu_string(self) -> str:
        return self.__name
    


class QEMUOptions:
    def __init__(self, qemu_path: str) -> None:
        self.__qemu_path: str = os.path.realpath(qemu_path)
        self.__processor: str | None = None
        self.__cores: int = 1
        self.__ram_size: _QEMURamSize = _QEMURamSize(512, _QEMURamUnit.MEGABYTES)
        self.__drives: list[_QEMUDrive] = []
        self.__acceleration_mode: str | None = None
        self.__boot_order: list[_QEMUBootOrderEntry] = []

    def _find_drive_with_id(self, id: str) -> _QEMUDrive | None:
        for drive in self.__drives:
            if drive.id == id:
                return drive
        return None

    def _find_bootorder_for_drive(self, id: str) -> _QEMUBootOrderEntry | None:
        for order in self.__boot_order:
            if order.drive_id == id:
                return order
        return None

    def _create_id_for_driver(self) -> str:
        DRIVE_ID_FORMAT = "drive_{}"
        drive_id_suffix = len(self.__drives)
        drive_id = DRIVE_ID_FORMAT.format(drive_id_suffix)
        while self._find_drive_with_id(drive_id) != None:
            drive_id_suffix += 1
            drive_id = DRIVE_ID_FORMAT.format(drive_id_suffix)
        return drive_id

    def set_cores_count(self, cores: int):
        if cores <= 0:
            cores = 1
        self.__cores = cores

    def set_ram_megabytes(self, megabytes: int):
        if megabytes <= 0:
            megabytes = 512
        self.__ram_size = _QEMURamSize(megabytes, _QEMURamUnit.MEGABYTES)

    def set_ram_gigabytes(self, gigabytes: int):
        if gigabytes <= 0:
            gigabytes = 1
        self.__ram_size = _QEMURamSize(gigabytes, _QEMURamUnit.GIGABYTES)

    def set_acceleration_mode(self, mode: QEMUAccelerationMode):
        self.__acceleration_mode = mode.to_qemu_string()

    def set_boot_order(self, drive_id: str, index: int):
        boot_order_set = False
        for order in self.__boot_order:
            if order.drive_id == drive_id:
                order.index = index
                boot_order_set = True
                break

        if boot_order_set == False:
            self.__boot_order.append(_QEMUBootOrderEntry(drive_id, index))

        self.__boot_order.sort(key=lambda order_key: order_key.drive_id)

    def add_cdrom(self, iso_file: str) -> str:
        iso_file = os.path.realpath(iso_file)
        drive = _QEMUCDRom(iso_file, self._create_id_for_driver())
        self.__drives.append(drive)
        return drive.id

    def add_hard_drive(self, image_file: str) -> str:
        image_file = os.path.realpath(image_file)
        drive = _QEMUHardDrive(image_file, self._create_id_for_driver())
        self.__drives.append(drive)
        return drive.id

    def to_command_line(self) -> str:
        command = [self.__qemu_path]
        for drive in self.__drives:
            drive_parameters = [
                f'file="{drive.file_path}"',
                f'id={drive.id}'
            ]

            if type(drive) is _QEMUCDRom: 
                drive_parameters.append(f'media=cdrom,if=none')
            elif type(drive) is _QEMUHardDrive: 
                drive_parameters.append(f'media=disk,if=none')
            else:
                raise Exception(f"Not recognized drive type: {type(drive)}")

            device_parameters = []
            if type(drive) is _QEMUCDRom: 
                device_parameters.append(f'{QEMUStorageDevice.IDE_CD.to_qemu_string()},drive={drive.id}')
            elif type(drive) is _QEMUHardDrive: 
                device_parameters.append(f'{QEMUStorageDevice.IDE_HD.to_qemu_string()},drive={drive.id}')


            boot_order = self._find_bootorder_for_drive(drive.id)
            if boot_order != None:
                device_parameters.append(f'bootindex={boot_order.index}')

            command.append(f"-drive {','.join(drive_parameters)}")
            command.append(f"-device {','.join(device_parameters)}")

            

        if self.__processor != None:
            command.append(f'-cpu {self.__processor}')
        command.append(f'-smp {self.__cores}')
        command.append(f'-m {self.__ram_size.amount}{self.__ram_size.unit.as_string()}')

        if self.__acceleration_mode != None:
            command.append(f'-accel {self.__acceleration_mode}')

        return ' '.join(command)
    