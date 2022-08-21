import enum

class QEMUGeneratedDevicePropertiesExtractor:
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

    def _on_property_name_state(self, current_character: str, index: int):
        if current_character == ' ':
            self.current_state = self.State.PROPERTY_VALUE
            self.property_name = self.property_line[self.name_start_index:index]
            self.value_start_index = index + 1

    def _on_property_value_state(self, current_character: str, index: int):
        if current_character == ',':
            self.property_value = self.property_line[self.value_start_index:index]
            self.current_state = self.State.PROPERTY_NAME_SEARCH
        elif current_character == '"':
            self.current_state = self.State.PROPERTY_VALUE_IN_QUOTES

    def _on_property_value_in_quotes(self, current_character: str, index: int):
        if current_character == '"':
            self.property_value = self.property_line[self.value_start_index + 1:index]
            self.current_state = self.State.PROPERTY_POST_VALUE

    def _on_property_post_value(self, current_character: str, index: int):
        if current_character == ',':
            self.current_state = self.State.PROPERTY_NAME_SEARCH

    def _on_property_name_search(self, current_character: str, index: int):
        if current_character != ' ':
            self.current_state = self.State.PROPERTY_NAME
            self.name_start_index = index

    def run(self) -> dict[str, str]:
        for index, current_character in enumerate(self.property_line):
            match self.current_state:
                case self.State.PROPERTY_NAME:
                    self._on_property_name_state(current_character, index)
                case self.State.PROPERTY_VALUE:
                    self._on_property_value_state(current_character, index)
                case self.State.PROPERTY_VALUE_IN_QUOTES:
                    self._on_property_value_in_quotes(current_character, index)
                case self.State.PROPERTY_POST_VALUE:
                    self._on_property_post_value(current_character, index)
                case self.State.PROPERTY_NAME_SEARCH:
                    self._on_property_name_search(current_character, index)

            if self.property_name != None and self.property_value != None:
                self.extracted_properties[self.property_name] = self.property_value
                self.property_name = None
                self.property_value = None

        return self.extracted_properties