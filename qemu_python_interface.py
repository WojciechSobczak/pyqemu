
import os
import dataclasses
import enum
import string
import subprocess
import re

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

@dataclasses.dataclass
class _QEMUGeneratedDevice:
    name: str = ""
    description: str | None = None
    bus: str | None = None
    alias: str | None = None

@dataclasses.dataclass
class _QEMUGeneratedDevicesSection:
    section_name: str
    devices: list[_QEMUGeneratedDevice]



class _QEMUGeneratedDevicePropertiesExtractor:
    class State(enum.Enum):
        PROPERTY_NAME_SEARCH = 1
        PROPERTY_NAME = 2
        PROPERTY_VALUE = 3
        PROPERTY_VALUE_IN_QUOTES = 4
        PROPERTY_POST_VALUE = 5

    def __init__(self, property_line: str):
        self.property_line = property_line
        self.current_state = self.State.PROPERTY_NAME
        self.value_start_index = 0
        self.name_start_index = 0
        self.property_name = None
        self.property_value = None
        self.extracted_properties = {}

    def on_property_name_state(self, current_character: str, index: int):
        if current_character == ' ':
            self.current_state = self.State.PROPERTY_VALUE
            self.property_name = self.property_line[self.name_start_index:index]
            self.value_start_index = index + 1

    def on_property_value_state(self, current_character: str, index: int):
        if current_character == ',':
            self.property_value = self.property_line[self.value_start_index:index]
            self.current_state = self.State.PROPERTY_NAME_SEARCH
        elif current_character == '"':
            self.current_state = self.State.PROPERTY_VALUE_IN_QUOTES

    def on_property_value_in_quotes(self, current_character: str, index: int):
        if current_character == '"':
            self.property_value = self.property_line[self.value_start_index + 1:index]
            self.current_state = self.State.PROPERTY_POST_VALUE

    def on_property_post_value(self, current_character: str, index: int):
        if current_character == ',':
            self.current_state = self.State.PROPERTY_NAME_SEARCH

    def on_property_name_search(self, current_character: str, index: int):
        if current_character != ' ':
            self.current_state = self.State.PROPERTY_NAME
            self.name_start_index = index

    def run(self) -> dict[str, str]:
        for index, current_character in enumerate(self.property_line):
            match self.current_state:
                case self.State.PROPERTY_NAME:
                    self.on_property_name_state(current_character, index)
                case self.State.PROPERTY_VALUE:
                    self.on_property_value_state(current_character, index)
                case self.State.PROPERTY_VALUE_IN_QUOTES:
                    self.on_property_value_in_quotes(current_character, index)
                case self.State.PROPERTY_POST_VALUE:
                    self.on_property_post_value(current_character, index)
                case self.State.PROPERTY_NAME_SEARCH:
                    self.on_property_name_search(current_character, index)

            if self.property_name != None and self.property_value != None:
                self.extracted_properties[self.property_name] = self.property_value
                self.property_name = None
                self.property_value = None

        return self.extracted_properties


class QEMUGenerator:

    __BUS_ENUM_CLASS_NAME = "QEMUDeviceBusType"
    __BUS_ENUM_FIELDS_TEMPLATE_KEY = "bus_enum_fields"
    __BUS_FILE_TEMPLATE = string.Template(f"""
import enum

class {__BUS_ENUM_CLASS_NAME}(enum.Enum): 
${__BUS_ENUM_FIELDS_TEMPLATE_KEY}

    def __init__(self, name: str):
        self.__name: str = name

    def to_qemu_string(self) -> str:
        return self.__name

""")

    __BASE_DEVICE_FILE_TEMPLATE = """
class QEMUDevice(enum.Enum):
    def __init__(self, name: str, description: str | None, bus: QEMUDeviceBusType | None, alias: str | None):
        self.__name: str = name
        self.__description: str | None = description
        self.__bus: QEMUDeviceBusType = bus
        self.__alias: str | None = alias

    def to_qemu_string(self) -> str:
        return self.__name

    def has_bus(self) -> bool:
        return self.__bus != None

    def get_bus(self) -> QEMUDeviceBusType | None:
        return self.__bus

    def has_description(self) -> bool:
        return self.__description != None

    def get_description(self) -> str | None:
        return self.__description

    def has_alias(self) -> bool:
        return self.__alias != None

    def get_alias(self) -> str | None:
        return self.__alias    
"""

    __DEVICE_ENUM_CLASS_TEMPLATE_KEY = "device_enum_class_name"
    __DEVICE_ENUM_FIELDS_TEMPLATE_KEY = "device_enum_fields"
    __DEVICES_FILE_TEMPLATE = string.Template(f"""

class ${__DEVICE_ENUM_CLASS_TEMPLATE_KEY}(QEMUDevice):
${__DEVICE_ENUM_FIELDS_TEMPLATE_KEY}

    def __init__(self, name: str, description: str | None, bus: QEMUDeviceBusType | None, alias: str | None):
        super().__init__(name, description, bus, alias)

""")




    def __init__(self, qemu_path: str):
        self.__qemu_path = os.path.realpath(qemu_path)

    def __extract_devices(self) -> list[_QEMUGeneratedDevicesSection]:
        output = subprocess.check_output([self.__qemu_path, '-device', 'help'])
        lines = output.decode('utf-8').splitlines(False)
        
        current_section: _QEMUGeneratedDevicesSection | None = None
        generated_sections: list[_QEMUGeneratedDevicesSection] = []

        for line in lines:
            if len(line.strip()) == 0:
                current_section = None
                continue

            if current_section == None:
                current_section = _QEMUGeneratedDevicesSection(line, [])
                generated_sections.append(current_section)
                continue

            device = _QEMUGeneratedDevice()
            properties = _QEMUGeneratedDevicePropertiesExtractor(line.strip()).run()
            for key, value in properties.items():
                if key.startswith('name'):
                    device.name = value
                elif key.startswith('bus'):
                    device.bus = value
                elif key.startswith('desc'):
                    device.description = value
                elif key.startswith('alias'):
                    device.alias = value
                else:
                    raise Exception(f"Unrecognized device format: {(key, value)}")

            if device.name == "":
                raise Exception(f"device_name property None")
            
            current_section.devices.append(device)

        return generated_sections

    def __change_to_fit_enum(self, string: str):
        string = re.sub("[^0-9a-zA-Z]+", "_", string).upper()
        if str(string[0]).isnumeric():
            string = "_" + string
        return string

    def __change_to_class_name(self, section: str):
        section = section.replace('devices', '')
        return re.sub("[^0-9a-zA-Z]+", "", section)

    def __generate_bus_file_text(self, devices_sections: list[_QEMUGeneratedDevicesSection]) -> str:
        buses = set()
        for section in devices_sections:
            for device in section.devices:
                if device.bus != None:
                    buses.add(device.bus)
        
        buses_enum_fields = {}
        for bus in buses:
            buses_enum_fields[bus] = self.__change_to_fit_enum(bus)

        field_spaces = ''.join([' '] * 4)

        bus_fields = []
        for bus_name, bus_enum_name in buses_enum_fields.items():
            bus_fields.append(f'{field_spaces}{bus_enum_name} = ("{bus_name}")')
        
        return self.__BUS_FILE_TEMPLATE.substitute({
            self.__BUS_ENUM_FIELDS_TEMPLATE_KEY: '\n'.join(bus_fields)
        })

    def __generate_devices_file_text(self, devices_sections: list[_QEMUGeneratedDevicesSection]) -> str:
        
        field_spaces = ''.join([' '] * 4)

        class_text = self.__BASE_DEVICE_FILE_TEMPLATE
        for section in devices_sections:
            tuple_lines = []
            section_name = self.__change_to_class_name(section.section_name)
            class_name = f'QEMU{section_name}Device'
            for device in section.devices:
                device_name = self.__change_to_fit_enum(device.name)
                device_desc = "None" if device.description == None else f'"{device.description}"'
                device_bus = "None" if device.bus == None else f'{self.__BUS_ENUM_CLASS_NAME}.{self.__change_to_fit_enum(device.bus)}'
                device_alias = "None" if device.description == None else f'"{device.alias}"'
                tuple_lines.append(f'{field_spaces}{device_name} = ("{device.name}", {device_desc}, {device_bus}, {device_alias})')

            class_text += self.__DEVICES_FILE_TEMPLATE.substitute({
                self.__DEVICE_ENUM_CLASS_TEMPLATE_KEY: class_name,
                self.__DEVICE_ENUM_FIELDS_TEMPLATE_KEY: '\n'.join(tuple_lines)
            })

        return class_text

    def generate_devices_file(self, output_file_path: str | None = None):
        if output_file_path == None:
            output_file_path = "./qemu_devices.py"

        devices_sections = self.__extract_devices()
        bus_file_text = self.__generate_bus_file_text(devices_sections)
        devices_file_text = self.__generate_devices_file_text(devices_sections)

        with open(output_file_path, "w") as file:
            file.write(bus_file_text)
            file.write(devices_file_text)
            
        
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

    def __find_drive_with_id(self, id: str) -> _QEMUDrive | None:
        for drive in self.__drives:
            if drive.id == id:
                return drive
        return None

    def __find_bootorder_for_drive(self, id: str) -> _QEMUBootOrderEntry | None:
        for order in self.__boot_order:
            if order.drive_id == id:
                return order
        return None

    def __create_id_for_driver(self) -> str:
        DRIVE_ID_FORMAT = "drive_{}"
        drive_id_suffix = len(self.__drives)
        drive_id = DRIVE_ID_FORMAT.format(drive_id_suffix)
        while self.__find_drive_with_id(drive_id) != None:
            drive_id_suffix += 1
            drive_id = DRIVE_ID_FORMAT.format(drive_id_suffix)
        return drive_id

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
        drive = _QEMUCDRom(iso_file, self.__create_id_for_driver())
        self.__drives.append(drive)
        return drive.id

    def add_hard_drive(self, image_file: str) -> str:
        image_file = os.path.realpath(image_file)
        drive = _QEMUHardDrive(image_file, self.__create_id_for_driver())
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
                drive_parameters.append(f'media=cdrom')
            elif type(drive) is _QEMUHardDrive: 
                drive_parameters.append(f'media=disk')
            else:
                raise Exception(f"Not recognized drive type: {type(drive)}")

            command.append(f"-drive {','.join(drive_parameters)}")

            # boot_order = self.__find_bootorder_for_drive(drive.id)
            # if boot_order != None:
            #     # if type(drive) is _QEMUCDRom: 
            #     #     drive_parameters.append(f'-device ide-hd,drive=disk1,bootindex=4')
            #     # el
            #     if type(drive) is _QEMUHardDrive: 
            #         command.append(f'-device ide-hd,drive={drive.id},bootindex={boot_order.index}')

        if self.__processor != None:
            command.append(f'-cpu {self.__processor}')
        command.append(f'-smp {self.__cores}')
        command.append(f'-m {self.__ram_size.amount}{self.__ram_size.unit.as_string()}')

        if self.__acceleration_mode != None:
            command.append(f'-accel {self.__acceleration_mode}')

        return ' '.join(command)
    