#
#   Copyright (c) 2020 Christof Ruch. All rights reserved.
#
#   Dual licensed: Distributed under Affero GPL license by default, an MIT license is available for purchase
#

# The Roland D-50 implements the Roland Exclusive Format Type IV, and thus is a good Roland example
import hashlib
import sys
from copy import copy
from typing import List, Optional, Tuple, Dict, Union

import knobkraft


def knobkraft_api(func):
    func._is_knobkraft = True
    return func


import testing
from roland import DataBlock

roland_id = 0x41  # Roland
model_id = 0b00010100  # D-50
command_rq1 = 0x11
command_dt1 = 0x12

# Construct the Roland character set as specified in the MIDI implementation
character_set = [' '] + [chr(x) for x in range(ord('A'), ord('Z') + 1)] + \
                [chr(x) for x in range(ord('a'), ord('z') + 1)] + \
                [chr(x) for x in range(ord('1'), ord('9') + 1)] + ['0', '-']

this_module = sys.modules[__name__]

# The D50 patch data
_d50_patch_data = [DataBlock((0x00, 0x00, 0x00), 0x40, "Upper partial-1"),
                   DataBlock((0x00, 0x00, 0x40), 0x40, "Upper partial-2"),
                   DataBlock((0x00, 0x01, 0x00), 0x40, "Upper common"),
                   DataBlock((0x00, 0x01, 0x40), 0x40, "Lower partial-1"),
                   DataBlock((0x00, 0x02, 0x00), 0x40, "Lower partial-2"),
                   DataBlock((0x00, 0x02, 0x40), 0x40, "Lower common"),
                   DataBlock((0x00, 0x03, 0x00), 0x40, "Patch"),
                   ]

class NonGenericRolandData:
    def __init__(self, data_name: str, num_items: int, num_address_bytes: int, num_size_bytes: int, base_address: Tuple, blocks: List[DataBlock], uses_consecutive_addresses: Optional[bool] = False):
        self.data_name = data_name
        self.num_items = num_items  # This is the "bank size" of that data type
        self.num_address_bytes = num_address_bytes
        self.num_size_bytes = num_size_bytes
        self.base_address = base_address
        self.data_blocks = blocks
        self.size = self.total_size()
        self.allowed_addresses = set([self.absolute_address(x.address) for x in self.data_blocks])
        self.blank_out_zones = None
        self.uses_consecutive_addresses = uses_consecutive_addresses

    def make_black_out_zones(self, model_id_length: int, program_position: Union[int, Tuple[int, int]] = None, device_id_position: int = None, name_blankout: Tuple[int, int, int] = None):
        # Calculate the additional bytes each data block takes. This is sysex header, checksum and sysex end, plus model ID and device ID
        # message = [0xf0, roland_id, device & 0x1f] + self.model_id + [command_id] + address + data + [0, 0xf7]
        data_block_overhead = 3 + model_id_length + 1 + 2 + self.num_address_bytes
        self.blank_out_zones = []
        # Ignore checksums, because they might include the program position and name and will be different for an edit buffer and a program dump
        self.blank_out_zones += [(self._end_index_of_block(x, data_block_overhead) - 1, 1) for x in range(len(self.data_blocks))]
        if device_id_position is not None:
            # We want the fingerprint to ignore the device ID
            self.blank_out_zones += [(self._start_index_of_block(x, data_block_overhead) + device_id_position, 1) for x in range(len(self.data_blocks))]
        if program_position is not None:
            # We want the fingerprint to ignore the program position
            if isinstance(program_position, tuple):
                self.blank_out_zones += [(self._start_index_of_block(x, data_block_overhead) + program_position[0], program_position[1]) for x in range(len(self.data_blocks))]
            else:
                self.blank_out_zones += [(self._start_index_of_block(x, data_block_overhead) + program_position, 1) for x in range(len(self.data_blocks))]
        if name_blankout is not None:
            self.blank_out_zones += [(self._start_index_of_block(name_blankout[0], data_block_overhead) + data_block_overhead - 2
                                      + name_blankout[1], name_blankout[2])]

    def _start_index_of_block(self, block_no, data_block_overhead):
        return sum([(0 if i == 0 else (self.data_blocks[i-1].size + data_block_overhead)) for i in range(block_no + 1)])

    def _end_index_of_block(self, block_no, data_block_overhead):
        return self._start_index_of_block(block_no, data_block_overhead) + self.data_blocks[block_no].size + data_block_overhead - 1

    def total_size(self) -> int:
        return sum([f.size for f in self.data_blocks])

    def total_size_as_list(self) -> List[int]:
        return DataBlock.size_as_7bit_list(self.size * 8, self.num_size_bytes)  # Why times 8?. You can't cross border from one data set into the next

    def absolute_address(self, address: Tuple[int]) -> Tuple:
        return tuple([(address[i] + self.base_address[i]) for i in range(self.num_address_bytes)])

    def address_and_size_for_sub_request(self, sub_request, sub_address) -> Tuple[List[int], List[int]]:
        if self.uses_consecutive_addresses:
            base_number = DataBlock.size_to_number(tuple(self.base_address))
            if not (0 <= sub_request < len(self.data_blocks)):
                raise Exception("Invalid subrequest index given")
            address = DataBlock.size_to_number(tuple(self.data_blocks[sub_request].address))
            multiplier = sub_address * self.size
            target_address = base_number + address + multiplier
            concrete_address = DataBlock.size_as_7bit_list(target_address, self.num_address_bytes)
        else:
            # Patch in the sub_address (i.e. the item in the bank). Assume the sub-item is always at position #1 in the tuple
            concrete_address = [(self.data_blocks[sub_request].address[i] + self.base_address[i]) if i != 1
                                else (sub_address + self.base_address[i])
                                for i in range(len(self.data_blocks[sub_request].address))]
        return concrete_address, DataBlock.size_as_7bit_list(self.data_blocks[sub_request].size, self.num_size_bytes)

    def reset_to_base_address(self, address) -> Tuple:
        if self.uses_consecutive_addresses:
            address_as_number = DataBlock.size_to_number(tuple(address))
            base_number = DataBlock.size_to_number(tuple(self.base_address))
            if address_as_number >= base_number:
                normalized_address = address_as_number - base_number
                # Calculate the normalized addressed modulo the size of the data blocks
                normalized_address = normalized_address % self.total_size()
                readjusted_base = base_number + normalized_address
                return tuple(DataBlock.size_as_7bit_list(readjusted_base, self.num_address_bytes))
            else:
                return tuple(address)
        else:
            # The address[1] part is where the program number is stored. To compare addresses we reset it to the base address
            return tuple([address[i] if i != 1 else self.base_address[i] for i in range(self.num_address_bytes)])

    def address_and_size_for_all_request(self, sub_address) -> Tuple[List[int], List[int]]:
        # The idea is that if we request the first block, but with the total size of all blocks, the device will send us all messages back.
        # Somehow that does work, but not as expected. To get all messages from a single patch on an XV-3080, I need to multiply the size by 8???

        # Patch in the sub_address (i.e. the item in the bank). Assume the sub-item is always at position #1 in the tuple
        concrete_address = [(self.data_blocks[0].address[i] + self.base_address[i]) if i != 1
                            else (sub_address + self.base_address[i])
                            for i in range(len(self.data_blocks[0].address))]
        return concrete_address, self.total_size_as_list()

_d50_edit_buffer_addresses = NonGenericRolandData("D-50 Temporary Patch"
                                        , num_items=1
                                        , num_address_bytes=3
                                        , num_size_bytes=3
                                        , base_address=(0x00, 0x00, 0x00)
                                        , blocks=_d50_patch_data
                                        , uses_consecutive_addresses=True)
_d50_program_buffer_addresses = NonGenericRolandData("D-50 Internal Patch"
                                           , num_items=0x40
                                           , num_address_bytes=3
                                           , num_size_bytes=3
                                           , base_address=(0x02, 0x00, 0x00)
                                           , blocks=_d50_patch_data
                                           , uses_consecutive_addresses=True)
class NonGenericRoland:
    def __init__(self, name: str, model_id: List[int], address_size: int, edit_buffer: NonGenericRolandData, program_dump: NonGenericRolandData,
                 category_index: Optional[int] = None,
                 device_family: Optional[List[int]] = None,
                 device_detect_message: Optional[NonGenericRolandData] = None,
                 device_detect_ids: Optional[List[int]] = None,
                 patch_name_message_number: Optional[int] = 0,
                 patch_name_length: Optional[int] = 12,
                 use_roland_character_set: Optional[bool] = False,
                 uses_consecutive_addresses: Optional[bool] = False):
        self._name = name
        self.model_id = model_id
        self.device_family = device_family  # This is only used in the Identity Reply Message.
        self.device_detect_message = device_detect_message
        self.device_detect_ids = None if device_detect_ids is None else set(device_detect_ids)
        # The D-50 uses 0x00..0x0f, equal to MIDI basic channel - 1.
        # Keep this unset until detection; request/transfer methods fall back
        # to the channel argument if no device ID has been detected yet.
        self.device_id = None
        self._model_id_len = len(model_id)
        self.address_size = address_size
        self.edit_buffer = edit_buffer
        self.program_dump = program_dump
        self.category_index = category_index
        self.patch_name_message_number = patch_name_message_number
        self.patch_name_length = patch_name_length
        self.use_roland_character_set = use_roland_character_set
        self.uses_consecutive_addresses = uses_consecutive_addresses
        # Calculate the fingerprint blank out zones for edit buffer (just the name) and program dump (program position and name)
        edit_buffer.make_black_out_zones(self._model_id_len, program_position=(4 + self._model_id_len, 3), device_id_position=2,
                                         name_blankout=(patch_name_message_number, 0, patch_name_length))
        program_dump.make_black_out_zones(self._model_id_len, program_position=(4 + self._model_id_len, 3), device_id_position=2,
                                          name_blankout=(patch_name_message_number, 0, patch_name_length))

    @knobkraft_api
    def name(self):
        return self._name

    @knobkraft_api
    def createDeviceDetectMessage(self, channel: int) -> List[int]:
        if self.device_family is not None:
            # Detecting the Roland via an Identity Request message
            # This is a sysex generic device detect message
            return [0xf0, 0x7e, channel, 0x06, 0x01, 0xf7]
        elif self.device_detect_message is not None:
            # The D50 uses 0x00 to 0x0f for device ID, not 0x10 to 0x1f like the newer Rolands
            address, size = self.device_detect_message.address_and_size_for_sub_request(0, 0)
            return self.buildRolandMessage(channel & 0x0f, command_rq1, address, size)
        else:
            print(f"{self._name} adaptation: No auto detection implemented. Specify either device family for identity reply, or data block")
            return []

    @knobkraft_api
    def channelIfValidDeviceResponse(self, message: List[int]) -> int:
        if self.device_family is not None:
            # The Roland usually will reply on a Universal Device Identity Reply message
            if (len(message) > 6 + self._model_id_len
                    and message[0] == 0xf0  # Sysex
                    and message[1] == 0x7e  # Non-realtime
                    and message[3] == 0x06  # Device request
                    and message[4] == 0x02  # Device request reply
                    and message[5] == 0x41  # Roland
                    and message[6:6 + self._model_id_len] == self.device_family):  # Family code expected, this is *not* the model ID
                # and message[8:10] == [0x00, 0x00]):  # Family code
                self.device_id = message[2]  # Store the device ID for later, we'll need it
                return message[2] & 0x0f  # Simulate MIDI channel, but of course this is stupid
        elif self.device_detect_message is not None:
            # Check if the message is our own, and at the address we were expecting
            if self.isOwnSysex(message):
                command, address, reply = self.parseRolandMessage(message)
                if command == command_dt1 and address == list(self.device_detect_message.absolute_address(self.device_detect_message.data_blocks[0].address)):
                    self.device_id = message[2]
                    return message[2] & 0x0f
        return -1

    @knobkraft_api
    def needsChannelSpecificDetection(self) -> bool:
        # When using a standard message, we actually need to iterate over all device IDs (not implemented yet, only channels 0 to 15)
        return self.device_family is None

    def _target_device_id(self, channel: int) -> int:
        if self.device_id is not None:
            return self.device_id & 0x0f
        return channel & 0x0f

    @knobkraft_api
    def bankDescriptors(self) -> List[Dict]:
        return [{"bank": 0, "name": "User Patches", "size": self.program_dump.num_items, "type": "User Patch"}]

    def isOwnSysex(self, message) -> bool:
        if len(message) > (2 + self._model_id_len):
            if message[0] == 0xf0 and message[1] == roland_id and message[3:3 + self._model_id_len] == self.model_id:
                return True
        return False

    def _checksum_start(self) -> int:
        return 4 + self._model_id_len

    def buildRolandMessage(self, device, command_id, address, data) -> List[int]:
        if not all([0 <= d < 128 for d in data]):
            raise Exception("Invalid data, uninitalized memory!")
        message = [0xf0, roland_id, device & 0x1f] + self.model_id + [command_id] + address + data + [0, 0xf7]
        message[-2] = self.roland_checksum(message[self._checksum_start():-2])
        return message

    def parseRolandMessage(self, message: list) -> Tuple[int, List[int], List[int]]:
        if isOwnSysex(message):
            first_message = knobkraft.findSysexDelimiters(message, 1)[0]
            checksum_start = first_message[0] + self._checksum_start()
            checksum = self.roland_checksum(message[checksum_start:first_message[1]-2])
            if checksum == message[first_message[1]-2]:
                command = message[first_message[0]+3 + self._model_id_len]
                address = message[checksum_start:checksum_start + self.address_size]
                return command, address, message[checksum_start + self.address_size:-2]
            raise Exception("Checksum error in Roland message parsing, expected", message[-2], "but got", checksum)
        raise Exception("Failed to identify this as a D-50 message")

    def getCommandAndAddressFromRolandMessage(self, message: list) -> Tuple[int, List[int]]:
        checksum_start = self._checksum_start()
        return message[3 + self._model_id_len], message[checksum_start:checksum_start + self.address_size]

    def changeAddressInRolandMessage(self, message: List[int], new_address: List[int]) -> List[int]:
        checksum_start = self._checksum_start()
        assert len(new_address) == self.address_size
        return message[:checksum_start]  + new_address + message[checksum_start + self.address_size:]

    @staticmethod
    def roland_checksum(data_block) -> int:
        return sum([-x for x in data_block]) & 0x7f

    @knobkraft_api
    def createEditBufferRequest(self, channel) -> List[int]:
        # The edit buffer is called Patch mode temporary patch
        address, size = self.edit_buffer.address_and_size_for_sub_request(0, 0)
        return self.buildRolandMessage(self._target_device_id(channel), command_rq1, address, size)

    def _follow_up_device_id(self, message: List[int]) -> int:
        if self.device_id is not None:
            return self.device_id
        return message[2]

    def _createFollowUpEditBufferDumpRequest(self, previousRequestNo, device_id):
        # Check if there is a follow up data block
        if previousRequestNo + 1 < len(self.edit_buffer.data_blocks):
            address, size = self.edit_buffer.address_and_size_for_sub_request(previousRequestNo + 1, 0)
            return self.buildRolandMessage(device_id, command_rq1, address, size)
        else:
            return []

    @knobkraft_api
    def isPartOfEditBufferDump(self, message):
        # Accept a certain set of addresses. This does not verify the checksum, for speed reasons, or check the size
        if self.isOwnSysex(message):
            command, address = self.getCommandAndAddressFromRolandMessage(message)
            if command == command_dt1:
                normalized_address = tuple(self.edit_buffer.reset_to_base_address(address))
                # Find out which data block we got
                for sub_request in range(len(self.edit_buffer.data_blocks)):
                    if normalized_address == self.edit_buffer.absolute_address(self.edit_buffer.data_blocks[sub_request].address):
                        return True, self._createFollowUpEditBufferDumpRequest(sub_request, self._follow_up_device_id(message))
        return False

    @knobkraft_api
    def isEditBufferDump(self, messages):
        if len(messages) != 518:
            return False
        addresses = set()
        for message in knobkraft.sysex.findSysexDelimiters(messages):
            if self.isOwnSysex(messages[message[0]:message[1]]):
                _, address = self.getCommandAndAddressFromRolandMessage(messages[message[0]:message[1]])
                addresses.add(tuple(self.edit_buffer.reset_to_base_address(address)))
        return all(a in addresses for a in self.edit_buffer.allowed_addresses)

    @knobkraft_api
    def convertToEditBuffer(self, channel, message):
        editBuffer = []
        if self.isEditBufferDump(message) or self.isSingleProgramDump(message):
            # We need to poke the device ID and the edit buffer address into the messages
            msg_no = 0
            for message in knobkraft.sysex.splitSysexMessage(message):
                command, address, data = self.parseRolandMessage(message)
                edit_buffer_address, _ = self.edit_buffer.address_and_size_for_sub_request(msg_no, 0x00)
                editBuffer = editBuffer + self.buildRolandMessage(self._target_device_id(channel), command_dt1, edit_buffer_address, data)
                msg_no += 1
            return editBuffer
        raise Exception("Invalid argument given, can only convert edit buffers and program dumps to edit buffers")

    @knobkraft_api
    def createProgramDumpRequest(self, channel, patchNo):
        address, size = self.program_dump.address_and_size_for_sub_request(0, patchNo % self.program_dump.num_items)
        return self.buildRolandMessage(self._target_device_id(channel), command_rq1, address, size)

    def _createFollowUpProgramDumpRequest(self, patchNo, previousRequestNo, device_id):
        # Check if there is a follow up data block
        if previousRequestNo + 1 < len(self.program_dump.data_blocks):
            address, size = self.program_dump.address_and_size_for_sub_request(previousRequestNo + 1, patchNo % self.program_dump.num_items)
            return self.buildRolandMessage(device_id, command_rq1, address, size)
        else:
            return []

    @knobkraft_api
    def isPartOfSingleProgramDump(self, message):
        # Accept a certain set of addresses
        if self.isOwnSysex(message):
            command, address = self.getCommandAndAddressFromRolandMessage(message)
            if command == command_dt1:
                patchNo = self._patch_number_from_address(address)
                normalized_address = tuple(self.program_dump.reset_to_base_address(address))
                # Find out which data block we got
                for sub_request in range(len(self.program_dump.data_blocks)):
                    if normalized_address == self.program_dump.absolute_address(self.program_dump.data_blocks[sub_request].address):
                        return True, self._createFollowUpProgramDumpRequest(patchNo, sub_request, self._follow_up_device_id(message))
        return False

    @knobkraft_api
    def isSingleProgramDump(self, messages):
        if len(messages) != 518:
            return False
        addresses = set()
        programs = set()
        for message in knobkraft.sysex.findSysexDelimiters(messages):
            _, address = self.getCommandAndAddressFromRolandMessage(messages[message[0]:message[1]])
            addresses.add(self.program_dump.reset_to_base_address(address))
            programs.add(self._patch_number_from_address(address))
        return len(programs) == 1 and all(a in addresses for a in self.program_dump.allowed_addresses)

    @knobkraft_api
    def convertToProgramDump(self, channel, message, program_number):
        programDump = []
        if self.isSingleProgramDump(message) or self.isEditBufferDump(message):
            # We need to poke the device ID and the program number into the messages
            msg_no = 0
            for message in knobkraft.sysex.splitSysexMessage(message):
                _, _, data = self.parseRolandMessage(message)
                program_buffer_address, _ = self.program_dump.address_and_size_for_sub_request(msg_no, program_number % self.program_dump.num_items)
                programDump = programDump + self.buildRolandMessage(self._target_device_id(channel), command_dt1, program_buffer_address, data)
                msg_no += 1
            return programDump
        raise Exception("Can only convert single program dumps to program dumps!")

    @staticmethod
    def _apply_blankout(data: List[int], blankout: List[Tuple[int, int]]):
        result = data
        for blank in blankout:
            for i in range(blank[1]):
                result[blank[0] + i] = 0
        # Additional blankout: The checksums can't be precalculated, as we have messages with varying length
        # Instead just blank every byte before the 0xf7
        for i in range(len(data)):
            if i+1 < len(data):
                if data[i+1] == 0xf7:
                    data[i] = 0x00
        return result

    @knobkraft_api
    def blankedOut(self, message):
        # Use the prepared blank out zones to clear out a) program place and b) patch name
        if self.isEditBufferDump(message):
            return self._apply_blankout(message.copy(), self.edit_buffer.blank_out_zones)
        elif self.isSingleProgramDump(message):
            return self._apply_blankout(message, self.program_dump.blank_out_zones)
        raise Exception("Only works with edit buffers and program dumps")

    @knobkraft_api
    def calculateFingerprint(self, message):
        return hashlib.md5(bytearray(self.blankedOut(message))).hexdigest()

    def _patch_number_from_address(self, address):
        if self.uses_consecutive_addresses:
            address_as_number = DataBlock.size_to_number(tuple(address))
            base_as_number = DataBlock.size_to_number(tuple(self.program_dump.base_address))
            return (address_as_number - base_as_number) // self.program_dump.size
        else:
            return address[1] - self.program_dump.base_address[1]

    @knobkraft_api
    def numberFromDump(self, message) -> int:
        if not self.isSingleProgramDump(message):
            return 0
        messages = knobkraft.sysex.findSysexDelimiters(message, 1)
        _, address = self.getCommandAndAddressFromRolandMessage(message[messages[0][0]:messages[0][1]])
        return self._patch_number_from_address(address)

    @knobkraft_api
    def nameFromDump(self, message) -> str:
        if self.isSingleProgramDump(message) or self.isEditBufferDump(message):
            msg_no = self.patch_name_message_number
            messages = knobkraft.sysex.findSysexDelimiters(message, msg_no + 1)
            _, _, data = self.parseRolandMessage(message[messages[msg_no][0]:messages[msg_no][1]])
            if self.use_roland_character_set:
                patch_name = ''.join([character_set[x] for x in data[0:self.patch_name_length]])
            else:
                patch_name = ''.join([chr(x) for x in data[0:self.patch_name_length]])
            return patch_name
        return 'Invalid'

    def _asciiToRoland(self, name: str):
        if self.use_roland_character_set:
            result = []
            for c in name[:self.patch_name_length].ljust(self.patch_name_length, " "):
                found = False
                for i in range(len(character_set)):
                    if character_set[i] == c:
                        found = True
                        result.append(i)
                        break
                if not found:
                    result.append(len(character_set)-1)
            return result
        else:
            return [ord(c) for c in name.ljust(self.patch_name_length, " ")][:self.patch_name_length]

    @knobkraft_api
    def renamePatch(self, message, new_name) -> List[int]:
        if self.isEditBufferDump(message) or self.isSingleProgramDump(message):
            msg_no = self.patch_name_message_number
            copy_of_message = copy(message)
            messages = knobkraft.sysex.findSysexDelimiters(copy_of_message, msg_no + 1)
            name_message_start = messages[msg_no][0]
            name_message_end = messages[msg_no][1]
            name_start = name_message_start + self._checksum_start() + self.address_size
            # Poke the new name into the correct message
            copy_of_message[name_start:name_start + self.patch_name_length] = self._asciiToRoland(new_name)
            # Recalculate checksum for that message
            copy_of_message[name_message_end-2] = self.roland_checksum(copy_of_message[name_message_start+self._checksum_start():name_message_end-2])
            return copy_of_message
        raise Exception("Can only rename edit buffers or programs")

    def install(self, module):
        # This is required because the original KnobKraft modules are not objects, but rather a module namespace with
        # methods declared. Expose our objects methods in the top level module namespace so the C++ code finds it
        for a in dir(self):
            if callable(getattr(self, a)) and hasattr(getattr(self, a), "_is_knobkraft"):
                # this was helpful: http://stupidpythonideas.blogspot.com/2013/06/how-methods-work.html
                setattr(module, a, getattr(self, a))


d_50 = NonGenericRoland("Roland D-50",
                     model_id=[model_id],
                     address_size=3,
                     edit_buffer=_d50_edit_buffer_addresses,
                     program_dump=_d50_program_buffer_addresses,
                     device_detect_message=_d50_edit_buffer_addresses,
                     patch_name_message_number=6,  # Different from more modern Rolands the patch name is in message number 6, not 0
                     patch_name_length=18,  # Longer than the normal 12 characters!
                     use_roland_character_set=True,
                     uses_consecutive_addresses=True
                     )

d_50.install(this_module)


# ---------------------------------------------------------------------------------------------------------------------
# Parameter grid: getPatchParameters / setPatchParameters
#
# Offsets, ranges and value texts follow the D-50 MIDI Implementation (Roland), sections *4-4 (partial block),
# *4-5 (common block) and *4-6 (patch block). A patch is 7 blocks of 64 bytes, in this order. The tone and patch
# names are left to renamePatch, and the "Extension (for future)" bytes are not shown.
# ---------------------------------------------------------------------------------------------------------------------

_NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _raw(value: int) -> str:
    return str(value)


def _offset(base: int):
    def text(value: int) -> str:
        shown = value - base
        return f"+{shown}" if shown > 0 else str(shown)
    return text


def _plus(amount: int):
    return lambda value: str(value + amount)


def _choices(*names: str):
    def text(value: int) -> str:
        return names[value] if 0 <= value < len(names) else str(value)
    text.options = list(names)
    return text


def _note(first_semitone: int):
    """Note names counted from a starting note, as semitones above C1 (C1 = 0)."""
    def text(value: int) -> str:
        semitone = first_semitone + value
        return f"{_NOTES[semitone % 12]}{1 + semitone // 12}"
    return text


def _bias_point(value: int) -> str:
    # 0-63: below A1-C7 ("<"), 64-127: above A1-C7 (">")
    direction = "<" if value < 64 else ">"
    return direction + _note(9)(value % 64)


_KEYFOLLOW_PITCH = _choices("-1", "-1/2", "-1/4", "0", "1/8", "1/4", "3/8", "1/2", "5/8", "3/4", "7/8", "1", "5/4", "3/2", "2", "s1", "s2")
_KEYFOLLOW_TVF = _choices("-1", "-1/2", "-1/4", "0", "1/8", "1/4", "3/8", "1/2", "5/8", "3/4", "7/8", "1", "5/4", "3/2", "2")
_LFO_SELECT = _choices("+1", "-1", "+2", "-2", "+3", "-3")
_LFO_WAVE = _choices("TRI", "SAW", "SQU", "RND")
_END_LEVEL = _choices("0", "100")
_PLUS_MINUS_7 = _offset(7)
_PLUS_MINUS_12 = _offset(12)
_PLUS_MINUS_50 = _offset(50)

# (offset, name, max, formatter)
_D50_PARTIAL = [
    (0, "WG pitch coarse", 72, _note(0)),
    (1, "WG pitch fine", 100, _PLUS_MINUS_50),
    (2, "WG pitch keyfollow", 16, _KEYFOLLOW_PITCH),
    (3, "WG mod LFO mode", 3, _choices("OFF", "(+)", "(-)", "A&L")),
    (4, "WG mod P-ENV mode", 2, _choices("OFF", "(+)", "(-)")),
    (5, "WG mod bend mode", 2, _choices("OFF", "Keyfollow", "Normal")),
    (6, "WG waveform", 1, _choices("Square", "Sawtooth")),
    (7, "WG PCM wave no.", 99, _plus(1)),
    (8, "WG pulse width", 100, _raw),
    (9, "WG PW velocity range", 14, _PLUS_MINUS_7),
    (10, "WG PW LFO select", 5, _LFO_SELECT),
    (11, "WG PW LFO depth", 100, _raw),
    (12, "WG PW aftertouch range", 14, _PLUS_MINUS_7),
    (13, "TVF cutoff frequency", 100, _raw),
    (14, "TVF resonance", 30, _raw),
    (15, "TVF keyfollow", 14, _KEYFOLLOW_TVF),
    (16, "TVF bias point/dir", 127, _bias_point),
    (17, "TVF bias level", 14, _PLUS_MINUS_7),
    (18, "TVF ENV depth", 100, _raw),
    (19, "TVF ENV velocity range", 100, _raw),
    (20, "TVF ENV depth keyfollow", 4, _raw),
    (21, "TVF ENV time keyfollow", 4, _raw),
    (22, "TVF ENV time 1", 100, _raw),
    (23, "TVF ENV time 2", 100, _raw),
    (24, "TVF ENV time 3", 100, _raw),
    (25, "TVF ENV time 4", 100, _raw),
    (26, "TVF ENV time 5", 100, _raw),
    (27, "TVF ENV level 1", 100, _raw),
    (28, "TVF ENV level 2", 100, _raw),
    (29, "TVF ENV level 3", 100, _raw),
    (30, "TVF ENV sustain level", 100, _raw),
    (31, "TVF ENV end level", 1, _END_LEVEL),
    (32, "TVF mod LFO select", 5, _LFO_SELECT),
    (33, "TVF mod LFO depth", 100, _raw),
    (34, "TVF mod aftertouch range", 14, _PLUS_MINUS_7),
    (35, "TVA level", 100, _raw),
    (36, "TVA velocity range", 100, _PLUS_MINUS_50),
    (37, "TVA bias point", 127, _bias_point),
    (38, "TVA bias level", 12, _offset(12)),  # -12 to 0
    (39, "TVA ENV time 1", 100, _raw),
    (40, "TVA ENV time 2", 100, _raw),
    (41, "TVA ENV time 3", 100, _raw),
    (42, "TVA ENV time 4", 100, _raw),
    (43, "TVA ENV time 5", 100, _raw),
    (44, "TVA ENV level 1", 100, _raw),
    (45, "TVA ENV level 2", 100, _raw),
    (46, "TVA ENV level 3", 100, _raw),
    (47, "TVA ENV sustain level", 100, _raw),
    (48, "TVA ENV end level", 1, _END_LEVEL),
    (49, "TVA ENV velocity follow", 4, _raw),
    (50, "TVA ENV time keyfollow", 4, _raw),
    (51, "TVA mod LFO select", 5, _LFO_SELECT),
    (52, "TVA mod LFO depth", 100, _raw),
    (53, "TVA mod aftertouch range", 14, _PLUS_MINUS_7),
]

_D50_COMMON = [
    (10, "Structure", 6, _plus(1)),
    (11, "P-ENV velocity range", 2, _raw),
    (12, "P-ENV time keyfollow", 4, _raw),
    (13, "P-ENV time 1", 50, _raw),
    (14, "P-ENV time 2", 50, _raw),
    (15, "P-ENV time 3", 50, _raw),
    (16, "P-ENV time 4", 50, _raw),
    (17, "P-ENV level 0", 100, _PLUS_MINUS_50),
    (18, "P-ENV level 1", 100, _PLUS_MINUS_50),
    (19, "P-ENV level 2", 100, _PLUS_MINUS_50),
    (20, "P-ENV sustain level", 100, _PLUS_MINUS_50),
    (21, "P-ENV end level", 100, _PLUS_MINUS_50),
    (22, "P-mod LFO depth", 100, _raw),
    (23, "P-mod lever", 100, _raw),
    (24, "P-mod aftertouch", 100, _raw),
    (25, "LFO-1 waveform", 3, _LFO_WAVE),
    (26, "LFO-1 rate", 100, _raw),
    (27, "LFO-1 delay time", 100, _raw),
    (28, "LFO-1 sync", 2, _choices("OFF", "ON", "KEY")),
    (29, "LFO-2 waveform", 3, _LFO_WAVE),
    (30, "LFO-2 rate", 100, _raw),
    (31, "LFO-2 delay time", 100, _raw),
    (32, "LFO-2 sync", 1, _choices("OFF", "ON")),
    (33, "LFO-3 waveform", 3, _LFO_WAVE),
    (34, "LFO-3 rate", 100, _raw),
    (35, "LFO-3 delay time", 100, _raw),
    (36, "LFO-3 sync", 1, _choices("OFF", "ON")),
    (37, "Low EQ frequency", 15, _choices("63", "75", "88", "105", "125", "150", "175", "210", "250", "300", "350", "420",
                                          "500", "600", "700", "840")),
    (38, "Low EQ gain", 24, _PLUS_MINUS_12),
    # The manual's table names offset 39 "Low EQ Frequency" too, but its values (250 Hz to 9.5 kHz) are the high EQ's
    (39, "High EQ frequency", 21, _choices("250", "300", "350", "420", "500", "600", "700", "840", "1.0k", "1.2k", "1.4k",
                                           "1.7k", "2.0k", "2.4k", "2.8k", "3.4k", "4.0k", "4.8k", "5.7k", "6.7k", "8.0k", "9.5k")),
    (40, "High EQ Q", 8, _choices("0.3", "0.5", "0.7", "1.0", "1.4", "2.0", "3.0", "4.2", "6.0")),
    (41, "High EQ gain", 24, _PLUS_MINUS_12),
    (42, "Chorus type", 7, _plus(1)),
    (43, "Chorus rate", 100, _raw),
    (44, "Chorus depth", 100, _raw),
    (45, "Chorus balance", 100, _raw),
    (46, "Partial mute", 3, _choices("00", "01", "10", "11")),
    (47, "Partial balance", 100, _raw),
]

_D50_PATCH = [
    (18, "Key mode", 8, _choices("Whole", "Dual", "Split", "Separate", "Whole-S", "Dual-S", "Split-US", "Split-LS", "Separate-S")),
    (19, "Split point", 60, _note(12)),  # C2 to C7
    (20, "Portamento mode", 2, _choices("U", "L", "UL")),
    (21, "Hold mode", 2, _choices("U", "L", "UL")),
    (22, "Upper tone key shift", 48, _offset(24)),
    (23, "Lower tone key shift", 48, _offset(24)),
    (24, "Upper tone fine tune", 100, _PLUS_MINUS_50),
    (25, "Lower tone fine tune", 100, _PLUS_MINUS_50),
    (26, "Bender range", 12, _raw),
    (27, "Aftertouch bend range", 24, _PLUS_MINUS_12),
    (28, "Portamento time", 100, _raw),
    (29, "Output mode", 3, _plus(1)),
    (30, "Reverb type", 31, _plus(1)),
    (31, "Reverb balance", 100, _raw),
    (32, "Total volume", 100, _raw),
    (33, "Tone balance", 100, _raw),
    (34, "Chase mode", 2, _choices("UL", "ULL", "ULU")),
    (35, "Chase level", 100, _raw),
    (36, "Chase time", 100, _raw),
    (37, "MIDI transmit channel", 16, lambda v: "Basic CH" if v == 0 else str(v)),
    (38, "MIDI separate receive channel", 16, lambda v: "OFF" if v == 0 else str(v)),
    (39, "MIDI transmit program change", 100, lambda v: "OFF" if v == 0 else str(v)),
]

_D50_BLOCK_SIZE = 0x40
# Grid order: the patch settings first, then each tone's common settings and its two partials
_D50_SECTIONS = [
    (6, "Patch", "patch", _D50_PATCH),
    (2, "Upper common", "upper.common", _D50_COMMON),
    (0, "Upper partial 1", "upper.partial1", _D50_PARTIAL),
    (1, "Upper partial 2", "upper.partial2", _D50_PARTIAL),
    (5, "Lower common", "lower.common", _D50_COMMON),
    (3, "Lower partial 1", "lower.partial1", _D50_PARTIAL),
    (4, "Lower partial 2", "lower.partial2", _D50_PARTIAL),
]


def _d50_layout():
    """(id, name, group, block number, offset in block, max, formatter)"""
    result = []
    for block, group, prefix, table in _D50_SECTIONS:
        for offset, name, max_value, formatter in table:
            parameter_id = prefix + "." + name.lower().replace(" ", "_").replace(".", "").replace("/", "_")
            result.append((parameter_id, name, group, block, offset, max_value, formatter))
    return result


_D50_LAYOUT = _d50_layout()


def _d50_blocks(messages: List[int]) -> Optional[Tuple[List[Tuple[int, int]], List[List[int]]]]:
    """The 7 blocks of an edit buffer or program dump, with each message's position, or None for other data."""
    if not (d_50.isEditBufferDump(messages) or d_50.isSingleProgramDump(messages)):
        return None
    positions = knobkraft.sysex.findSysexDelimiters(messages, len(_d50_patch_data))
    blocks = []
    for start, end in positions:
        _, _, data = d_50.parseRolandMessage(messages[start:end])
        if len(data) != _D50_BLOCK_SIZE:
            return None
        blocks.append(list(data))
    return (positions, blocks) if len(blocks) == len(_d50_patch_data) else None


@knobkraft_api
def getPatchParameters(messages: List[int]) -> List[Dict]:
    found = _d50_blocks(messages)
    if found is None:
        return []
    _, blocks = found
    result = []
    for parameter_id, name, group, block, offset, max_value, formatter in _D50_LAYOUT:
        value = blocks[block][offset]
        parameter = {"id": parameter_id, "name": name, "group": group, "value": value, "min": 0, "max": max_value,
                     "text": formatter(value)}
        if hasattr(formatter, "options"):
            parameter["options"] = formatter.options
        result.append(parameter)
    return result


@knobkraft_api
def setPatchParameters(messages: List[int], values: Dict[str, int]) -> List[int]:
    """The same messages with the given raw values written in and their checksums updated."""
    found = _d50_blocks(messages)
    if found is None:
        raise ValueError("Not a D-50 edit buffer or program dump")
    positions, blocks = found
    by_id = {entry[0]: entry for entry in _D50_LAYOUT}
    for parameter_id, value in values.items():
        if parameter_id not in by_id:
            raise ValueError(f"Unknown D-50 parameter '{parameter_id}'")
        _, _, _, block, offset, max_value, _ = by_id[parameter_id]
        if not 0 <= value <= max_value:
            raise ValueError(f"Value {value} out of range 0..{max_value} for '{parameter_id}'")
        blocks[block][offset] = value
    result = list(messages)
    data_start = d_50._checksum_start() + d_50.address_size
    for (start, end), data in zip(positions, blocks):
        result[start + data_start:start + data_start + len(data)] = data
        result[end - 2] = d_50.roland_checksum(result[start + d_50._checksum_start():end - 2])
    return result


def old_createDeviceDetectMessage(channel):
    # Just request the upper common block from the edit buffer - if we get a reply, there is a D-50
    # Command is RQ1 = 0x11, the address is 0 1 0, the size is 0x40 for one block
    return d_50.buildRolandMessage(channel, command_rq1, [0x00, 0x01, 0x00], [0x00, 0x00, 0x40])


def old_channelIfValidDeviceResponse(message):
    # We are expecting a DT1 message response (command 0x12)
    if isOwnSysex(message):
        command, address, data = d_50.parseRolandMessage(message)
        if command == command_dt1 and address == [0x00, 0x01, 0x00]:
            return message[2] & 0x0f
    return -1


def isBankDumpFinished(messages):
    addresses = set()
    for message in messages:
        if isPartOfBankDump(message):
            command, address = d_50.getCommandAndAddressFromRolandMessage(message)
            addresses.add(tuple(address))
    return len(addresses) == 136


def isPartOfBankDump(message):
    if d_50.isOwnSysex(message):
        command, address = d_50.getCommandAndAddressFromRolandMessage(message)
        return command == command_dt1
    return False


def bankDownloadMethodOverride():
    return "EDITBUFFERS"


def generalMessageDelay():
    # The D-50 manual requires more than 20 ms between received DT1 messages.
    return 25


def extractPatchesFromAllBankMessages(messages: List[List[int]]) -> List[List[int]]:
    # The Bank dumps of the D-50 basically are just a lists of messages with the whole memory content of the synth
    # We need to put them together, and then can read the individual data items from the RAM
    synth_ram = [0xff] * (address_to_index([0x04, 0x0c, 0x08]) + 376)
    for message in messages:
        command, address, data = d_50.parseRolandMessage(message)
        if command == command_dt1:
            memory_base_index = address_to_index(address)
            synth_ram[memory_base_index:memory_base_index + len(data)] = data

    # Now pull 64 patches out of the RAM and create individual edit buffer messages
    result = []
    for p in range(64):
        patch = []
        patch_base = address_to_index([0x2, 0x00, 0x00]) + p * (7 * 0x40)
        for subsection in range(7):
            target_base = subsection * 0x40
            source_base = patch_base + target_base
            patch = patch + d_50.buildRolandMessage(0, command_dt1,
                                               index_to_address(target_base),
                                               synth_ram[source_base:source_base + 0x40])
        result.append(patch)
    return result


def isOwnSysex(message):
    return len(message) > 3 and message[0] == 0xf0 and message[1] == roland_id and message[3] == model_id


def address_to_index(address):
    return address[2] + (address[1] << 7) + (address[0] << 14)


def index_to_address(index):
    return [index >> 14, (index & 0x3f80) >> 7, index & 0x7f]


def make_test_data():
    def make_patches(test_data: testing.TestData) -> List[testing.ProgramTestData]:
        patches = extractPatchesFromAllBankMessages(test_data.all_messages)
        yield testing.ProgramTestData(message=patches[0], name="SOUNDTRACK II     ")
        yield testing.ProgramTestData(message=patches[17], name="DIMENSIONAL PAD   ")

        onemore = knobkraft.load_sysex("testData/Roland_D50/vibraphone edit buffer.syx", as_single_list=True)
        yield testing.ProgramTestData(message=onemore, name="Vibraphone        ")

        testbank = knobkraft.load_sysex("testData/Roland_D50/testbank_d50.syx")
        edit_buffer = []
        for message in testbank:
            if d_50.isPartOfEditBufferDump(message):
                edit_buffer.extend(message)
            else:
                assert False, "Expected only edit buffer dumps here"
            if d_50.isEditBufferDump(edit_buffer):
                yield testing.ProgramTestData(message=edit_buffer)
                edit_buffer.clear()

    def make_programs(test_data: testing.TestData) -> List[testing.ProgramTestData]:
        patches = extractPatchesFromAllBankMessages(test_data.all_messages)
        prog0 = d_50.convertToProgramDump(11, patches[0], 12)
        yield testing.ProgramTestData(message=prog0, name="SOUNDTRACK II     ", number=12)
        prog1 = d_50.convertToProgramDump(11, patches[63], 2)
        yield testing.ProgramTestData(message=prog1, name="EQUILIBRIUM       ", number=2)

    def bankGenerator(test_data: testing.TestData) -> List[int]:
        yield test_data.all_messages

    messages = knobkraft.load_sysex(R"testData/Roland_D50/Roland_D50_DIGITAL DREAMS.syx", as_single_list=False)
    dump = []
    for message in messages:
        if isPartOfBankDump(message):
            dump.append(message)
        else:
            print(f"Message not part of bank dump: {message}")
    assert isBankDumpFinished(dump)
    patches = extractPatchesFromAllBankMessages(dump)
    return testing.TestData(sysex=R"testData/Roland_D50/Roland_D50_DIGITAL DREAMS.syx", edit_buffer_generator=make_patches,
                            program_generator=make_programs,
                            bank_generator=bankGenerator,
                            banks_are_edit_buffers=True,
                            device_detect_call="f0 41 00 14 11 00 00 00 00 00 40 40 f7",
                            device_detect_reply=(patches[0], 0),
                            expected_patch_count=64)
