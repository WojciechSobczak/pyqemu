import string
import dataclasses
import subprocess
import os
import re
from .generated_devices_props_extractor import QEMUGeneratedDevicePropertiesExtractor

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

class QEMUFilesGenerator:
    _BUS_ENUM_CLASS_NAME = "QEMUDeviceBusType"
    _BUS_ENUM_FIELDS_TEMPLATE_KEY = "bus_enum_fields"
    _BUS_FILE_TEMPLATE = string.Template(f"""
import enum

class {_BUS_ENUM_CLASS_NAME}(enum.Enum): 
${_BUS_ENUM_FIELDS_TEMPLATE_KEY}

    def __init__(self, name: str):
        self.__name: str = name

    def to_qemu_string(self) -> str:
        return self.__name

""")

    _BASE_DEVICE_FILE_TEMPLATE = """
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

    _DEVICE_ENUM_CLASS_TEMPLATE_KEY = "device_enum_class_name"
    _DEVICE_ENUM_FIELDS_TEMPLATE_KEY = "device_enum_fields"
    _DEVICES_FILE_TEMPLATE = string.Template(f"""

class ${_DEVICE_ENUM_CLASS_TEMPLATE_KEY}(QEMUDevice):
${_DEVICE_ENUM_FIELDS_TEMPLATE_KEY}

    def __init__(self, name: str, description: str | None, bus: QEMUDeviceBusType | None, alias: str | None):
        super().__init__(name, description, bus, alias)

""")

    def __init__(self, qemu_path: str):
        self.__qemu_path = os.path.realpath(qemu_path)

    def _extract_devices(self) -> list[_QEMUGeneratedDevicesSection]:
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
            properties = QEMUGeneratedDevicePropertiesExtractor(line.strip()).run()
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

    def _change_to_fit_enum(self, string: str):
        string = re.sub("[^0-9a-zA-Z]+", "_", string).upper()
        if str(string[0]).isnumeric():
            string = "_" + string
        return string

    def _change_to_class_name(self, section: str):
        section = section.replace('devices', '')
        return re.sub("[^0-9a-zA-Z]+", "", section)

    def _generate_bus_file_text(self, devices_sections: list[_QEMUGeneratedDevicesSection]) -> str:
        buses = set()
        for section in devices_sections:
            for device in section.devices:
                if device.bus != None:
                    buses.add(device.bus)
        
        buses_enum_fields = {}
        for bus in buses:
            buses_enum_fields[bus] = self._change_to_fit_enum(bus)

        field_spaces = ''.join([' '] * 4)

        bus_fields = []
        for bus_name, bus_enum_name in buses_enum_fields.items():
            bus_fields.append(f'{field_spaces}{bus_enum_name} = ("{bus_name}")')
        
        return self._BUS_FILE_TEMPLATE.substitute({
            self._BUS_ENUM_FIELDS_TEMPLATE_KEY: '\n'.join(bus_fields)
        })

    def _generate_devices_file_text(self, devices_sections: list[_QEMUGeneratedDevicesSection]) -> str:
        
        field_spaces = ''.join([' '] * 4)

        class_text = self._BASE_DEVICE_FILE_TEMPLATE
        for section in devices_sections:
            tuple_lines = []
            section_name = self._change_to_class_name(section.section_name)
            class_name = f'QEMU{section_name}Device'
            for device in section.devices:
                device_name = self._change_to_fit_enum(device.name)
                device_desc = "None" if device.description == None else f'"{device.description}"'
                device_bus = "None" if device.bus == None else f'{self._BUS_ENUM_CLASS_NAME}.{self._change_to_fit_enum(device.bus)}'
                device_alias = "None" if device.description == None else f'"{device.alias}"'
                tuple_lines.append(f'{field_spaces}{device_name} = ("{device.name}", {device_desc}, {device_bus}, {device_alias})')

            class_text += self._DEVICES_FILE_TEMPLATE.substitute({
                self._DEVICE_ENUM_CLASS_TEMPLATE_KEY: class_name,
                self._DEVICE_ENUM_FIELDS_TEMPLATE_KEY: '\n'.join(tuple_lines)
            })

        return class_text

    def generate_devices_file(self, output_file_path: str | None = None):
        if output_file_path == None:
            script_dir = os.path.realpath(os.path.dirname(__file__))
            output_file_path = f"{script_dir}/qemu_devices.py"

        devices_sections = self._extract_devices()
        bus_file_text = self._generate_bus_file_text(devices_sections)
        devices_file_text = self._generate_devices_file_text(devices_sections)

        with open(output_file_path, "w") as file:
            file.write(bus_file_text)
            file.write(devices_file_text)