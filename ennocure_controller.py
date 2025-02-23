import struct
import serial
from serial.tools import list_ports
import os
import os.path as op
import logging
import time
import datetime
import numpy as np
import re
import PCB_GUI


class EnnocureEU:
    available_ports = []

    port = "COM3"  # fill in right port #com8
    baud_rate = 9600
    data_bits = 8
    stop_bits = 1
    parity = None
    ser = serial.Serial(baudrate=baud_rate, timeout=2, parity=serial.PARITY_NONE)
    connected = False

    send_header = [0xAA, 0x55]
    recv_header = [0x55, 0xAA]
    eu_address = 0x1
    require_echo = 0x1
    pc_mode = 0x0
    sub_mode = 0x0
    msg_attr = (eu_address) + (require_echo << 2) + (pc_mode << 3) + (sub_mode << 4)
    sub_modes = {'standalone': 1, 'standalone_inv': 2, 'external_pwm': 3, 'external_pwm_pol': 4}
    n_electrodes = 23
    el_snk = np.zeros(n_electrodes, dtype=int)
    el_src = np.zeros(n_electrodes, dtype=int)
    el_fcn = ['off'] * n_electrodes
    states = ['sink', 'source', 'off']
    current_limit = 0.25  # mA
    current_limit_w = 0x1
    data = []
    msg_len = 12
    echo_data = None

    def __init__(self, logger):
        self.logger = logger
        self.port = "COM3"  # יש להחליף לפורט הנכון
        self.ser = serial.Serial()

    def find_available_ports(self) -> list:
        """Finds and returns a sorted list of available ports in the system."""
        self.available_ports = sorted([p.name for p in list_ports.comports()],
                                      key=lambda port: int(re.search(r'\d+', port)[0]))
        print(f"Available ports: {self.available_ports}")

        return self.available_ports

    def connect_to_port(self) -> bool:
        """Tries to connect to an available port and sends a command to check if successful."""
        if self.connected:  # אם כבר מחובר, אין צורך לנסות להתחבר שוב
            print("Already connected to the port.")
            return True
        ports = self.find_available_ports()
        if self.port not in ports:
            print(f"Error: Port {self.port} is not available. Available ports: {ports}")
            return False

        try:
            for port in ports:
                self.ser.port = self.port
                self.ser.open()  # Open the port
                status = self.gen_command_data(send_cmd=True)
                if status:
                    self.logger.info(f'Successfully connected to port {port}')
                    self.connected = True
                    self.pc_mode = 0x1
                    self.set_msg_attr()
                    break
        except serial.SerialException as e:
            print(f"SerialException: {e}")
        except FileNotFoundError:
            print(f"FileNotFoundError: Port {self.port} does not exist!")
        except Exception as e:
            print(f"Unexpected error: {e}")

        return False

    def check_port(self, port: str) -> bool:
        """Checks if a specific port is available."""
        available_ports = [p.name for p in list_ports.comports()]
        if port not in available_ports:
            print(f"Error: Port {port} is not available.\nAvailable ports: {available_ports}")
            return False
        return True

    def set_msg_attr(self) -> None:
        """Sets the message attribute based on current configuration."""
        self.msg_attr = self.eu_address + (self.require_echo << 2) + (self.pc_mode << 3) + (self.sub_mode << 4)

    def set_echo(self, require_echo: bool) -> None:
        """Sets whether echo is required and updates the message attribute."""
        self.require_echo = require_echo
        self.set_msg_attr()

    def set_pc(self, pc_mode: int) -> None:
        """Sets the PC mode and updates the message attribute."""
        self.pc_mode = pc_mode
        self.set_msg_attr()

    def select_sub_mode(self, sub_mode: int = None) -> None:
        """Selects a sub-mode, updating the message attribute."""
        if sub_mode is None:
            self.logger.info(self.sub_modes.keys())
            return
        if isinstance(sub_mode, str):
            sub_mode = self.sub_modes.get(sub_mode, 0)
        if sub_mode not in range(5):
            raise ValueError('sub_mode should be integer in the range [0-4]')
        self.sub_mode = sub_mode
        self.set_msg_attr()

    def set_electrode(self, el_idx: int, state: str) -> None:
        """Sets the state of a specific electrode ('sink' or 'source')."""
        if el_idx not in range(self.n_electrodes):
            raise ValueError(f'electrode index should be in the range [0-{self.n_electrodes - 1}]')
        if state not in self.states:
            raise ValueError(f'electrode state should be one of {self.states}')
        if state == 'sink':
            self.el_snk[el_idx] = 0x1
            self.el_src[el_idx] = 0
        elif state == 'source':
            self.el_snk[el_idx] = 0
            self.el_src[el_idx] = 0x1
        else:
            self.el_snk[el_idx] = 0
            self.el_src[el_idx] = 0
        self.set_el_fcn(el_idx)

    def set_electrodes(self, input_el_snk: list, input_el_src: list) -> None:
        """Sets the full configuration of sink and source electrodes."""
        if len(input_el_snk) != self.n_electrodes or len(input_el_src) != self.n_electrodes:
            raise ValueError(f"Input arrays must have length {self.n_electrodes}")
        self.el_snk = input_el_snk
        self.el_src = input_el_src

    def set_el_fcn(self, el_idx):
        pass

    def calc_sink_bytes(self) -> list:
        """Calculate and return the 3 sink bytes based on the sink elements."""
        seed = 2 ** np.arange(8)
        byte4 = (self.el_snk[:8] * seed).sum()
        byte5 = (self.el_snk[8:16] * seed).sum()
        byte6 = (self.el_snk[16:] * seed[:-1]).sum()
        return [int(byte4), int(byte5), int(byte6)]

    def calc_src_bytes(self) -> list:
        """Calculate and return the 3 source bytes based on the source elements."""
        seed = 2 ** np.arange(8)
        byte7 = (self.el_src[:8] * seed).sum()
        byte8 = (self.el_src[8:16] * seed).sum()
        byte9 = (self.el_src[16:] * seed[:-1]).sum()
        return [int(byte7), int(byte8), int(byte9)]

    def set_current_limit(self, current_limit: float) -> None:
        """Set the current limit if it is within the valid range (0.25 to 63.75)."""
        if 0.25 <= current_limit <= 63.75:
            current_limit_w = int(round(current_limit / 0.25))
            self.set_current_limit_word(current_limit_w)

    def set_current_limit_word(self, current_limit_w: int) -> None:
        """Set the current limit word and store the corresponding limit in the class."""
        if current_limit_w not in range(256):
            raise ValueError('current limit word is in the range [0-255]')
        self.current_limit_w = current_limit_w
        self.current_limit = current_limit_w * 0.25

    def calc_checksum(self, data: list) -> int:
        """Calculate the checksum by summing the data and masking with 8 bits."""
        return sum(data) & 0xff

    def gen_command_data(self, send_cmd=True) -> bool:
        """
        Generates the command data and optionally sends it.
        """
        data = self.send_header.copy()
        data.append(self.msg_attr)
        data += self.calc_sink_bytes()
        data += self.calc_src_bytes()
        data.append(self.current_limit_w)
        data.append(0x0)
        data.append(self.calc_checksum(data))
        self.data = data
        if send_cmd:
            return self.send_command()
        return True

    def send_command(self) -> bool:
        """
        Sends a command with data and checks for echo if required.
        """
        if len(self.data) == 0:
            self.logger.warning('gen data first')
            return False
        n_bytes = len(self.data)
        command = struct.pack(f"<{n_bytes}B", *self.data)
        print(self.data)
        # self.logger.info(f"Echo data sending: {self.data}")

        self.ser.write(command)
        if self.require_echo is False:
            time.sleep(0.1)
            recv = self.ser.read(len(self.data))
            if len(recv) != n_bytes:
                return False
            self.echo_data = list(struct.unpack(f"<{n_bytes}B", recv))
            print(f"echo_data{self.echo_data}")
            return self.check_echo()

        return True

    def check_echo(self) -> bool:
        """
        Verifies the received echo data against expected values.
        """
        if len(self.echo_data) != self.msg_len:
            self.logger.error(f"Received echo length ({len(self.echo_data)}) differs from expected ({self.msg_len})")
            return False

        self.logger.info(f"Echo data received: {self.echo_data}")

        # בדיקת ההדר של ה-Echo
        if self.echo_data[:2] != self.recv_header:
            self.logger.error(f"Incorrect echo header: {self.echo_data[:2]}, expected {self.recv_header}")
            return False

        # בדיקת Check Fault
        check_fault = self.echo_data[2] >> 4  # הזזת 4 ביטים ימינה
    if check_fault == 5:
            self.logger.error("EU fault detected in echo response!")
            return False

        if (self.data[0] == self.echo_data[1]) != (self.data[1] == self.echo_data[0]):
            return False

        self.logger.info("Echo check passed successfully.")
        return True


if __name__ == "__main__":
    logger = logging.getLogger('ennocure_eu_logger')
    logger.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    logger_path = op.join(os.getcwd(), 'ennocure_eu_logger.txt')
    fh = logging.FileHandler(logger_path)
    formatter = logging.Formatter("%(asctime)s : %(levelname)s : %(message)s")
    ch.setFormatter(formatter)
    fh.setFormatter(formatter)
    logger.addHandler(ch)
    logger.addHandler(fh)
    eu = EnnocureEU(logger=logger)
