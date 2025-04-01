import sys
from PySide6.QtWidgets import QInputDialog
from PySide6.QtUiTools import QUiLoader
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QFile, QIODevice
import ennocure_controller
from ennocure_controller import EnnocureEU
from serial.tools import list_ports
import re
import ast
from PySide6.QtWidgets import QCheckBox

import os
import os.path as op
import logging
from PySide6.QtCore import QTimer
import numpy
from functools import partial
import datetime

file_channels = "fileChannels.txt"
file_LastOpening = "LastOpening.txt"

class GUI:
    logger = logging.getLogger('ennocure_eu_logger')
    state = [2]
    PCB = []
    app = []
    window = []
    numberOfChannels = 23
    StartTimer = QTimer()
    StopTimer = QTimer()
    lines_SRC = [1] * numberOfChannels
    lines_SNK = [0] * numberOfChannels
    lines_status = [0] * numberOfChannels
    offTime = 0
    cycles = 1
    cycleCounter = 0
    current_limit = 0
    dutyCycle = 50  # in percent(%)
    period = 2  # in seconds
    totalTime = 1 * 60 * 60  # in seconds
    totalTimeUnits = [1, 0, 0]  # [hours,min,sec]
    timeFactorArray = [3600, 60, 1]
    PC_mode = 1
    sub_mode = 1
    algoFlag = False
    numberForEvenFlip = 1
    is_connected = False
    doFlip = False
    toDoEvenFlip = False
    checkboxes = []

    def __init__(self):
        """Initialize the program: Open the UI, connect buttons to functions, and load the UI."""
        self.app = QApplication(sys.argv)
        ui_file_name = "PCB_GUI.ui"
        ui_file = QFile(ui_file_name)
        self.from_toggle_all = False

        if not ui_file.open(QIODevice.ReadOnly):
            print(f"Cannot open {ui_file_name}: {ui_file.errorString()}")
            sys.exit(-1)
        loader = QUiLoader()
        self.window = loader.load(ui_file)
        ui_file.close()
        if not self.window:
            print(loader.errorString())
            sys.exit(-1)

        # הגדר את מספר הערוצים ל-23 (1 עד 23 כולל)
        self.numberOfChannels = 23
        self.lines_SRC = [1] * self.numberOfChannels
        self.lines_SNK = [0] * self.numberOfChannels
        self.lines_status = [0] * self.numberOfChannels
        self.checkboxes = [0] * self.numberOfChannels
        self.group_checkboxes = [[] for _ in range(self.numberOfChannels)]

        # שמור את כל ה-QComboBox ו-QCheckBox ברשימות
        self.line_type_comboboxes = [getattr(self.window, f"Line{i}_type") for i in range(self.numberOfChannels)]
        self.line_onoff_checkboxes = [getattr(self.window, f"Line{i}_onoff") for i in range(self.numberOfChannels)]

        # דגל למניעת לולאות אין-סופיות
        self.updating_channel = False

        # חבר את ה-QComboBox וה-QCheckBox לאירועים (התאם את האינדקסים ל-1 עד 23)
        for i in range(self.numberOfChannels):
            self.line_type_comboboxes[i].activated.connect(lambda _, idx=i + 1: self.setLineType(idx))
            self.line_onoff_checkboxes[i].stateChanged.connect(lambda state, idx=i + 1: self.setLineActive(state, idx))

        # קרא לפונקציה שמגדירה את ה-group_checkboxes
        self.setup_group_checkboxes()

        # Connect buttons and actions to their respective functions
        self.window.ConnectButton.clicked.connect(self.connect)
        self.window.ConnectButton.setStyleSheet(
            "background-color: rgb(173, 0, 0); border: none; border-radius: 12px; padding: 5px;")
        self.window.RunSenario.clicked.connect(self.runAlgo)
        self.window.RunSenario.setStyleSheet(
            "background-color:rgb(173, 216, 230); border: none; border-radius: 12px; padding: 5px;")
        self.window.PC_SubMode.currentIndexChanged.connect(self.setSubMode)
        self.window.PC_Mode.currentIndexChanged.connect(self.setPCMode)
        self.window.TotalTime.editingFinished.connect(self.setTotalTime)
        self.window.DutyCycle.editingFinished.connect(self.setDutyCycle)
        self.window.Period.editingFinished.connect(self.setPeriod)
        self.window.TimeUnit.currentIndexChanged.connect(self.setTimeUnit)
        self.window.StopAlgo.clicked.connect(self.raiseFlag)
        self.window.StopAlgo.setStyleSheet(
            "background-color:rgb(225,102,102); border: none; border-radius: 12px; padding: 5px;")
        self.window.inverseButton.clicked.connect(self.inverse)
        self.window.inverseButton.setStyleSheet(
            "background-color: rgb(80, 100, 100);border: none; border-radius: 12px; padding: 5px;")
        self.window.showPorts.clicked.connect(self.getPort)
        self.window.showPorts.setStyleSheet(
            "background-color: rgb(80, 100, 100);border: none; border-radius: 12px; padding: 5px;")
        self.window.editPort.editingFinished.connect(self.setEditPort)
        self.window.editPort.setStyleSheet(
            "background-color: rgb(180, 180, 180);border: none; border-radius: 12px; padding: 5px;")
        self.window.SaveState.clicked.connect(self.saveChannels)
        self.window.SaveState.setStyleSheet(
            "background-color: rgb(80, 100, 100);border: none; border-radius: 12px; padding: 5px;")
        self.window.ChannelsMode.currentIndexChanged.connect(self.onChannelsModeChanged)
        self.window.ChannelsMode.setStyleSheet(
            "background-color: rgb(80, 100, 100);border: none; border-radius: 12px; padding: 5px;")
        self.window.inverstClick.stateChanged.connect(self.evenFlip)
        self.window.onoff_all.stateChanged.connect(self.toggleAll)
        self.window.onoff_all.setStyleSheet("background-color:rgb(150,150,150)")

        self.window.OutPut.appendPlainText("please start by connecting to hardware")
        self.window.show()

        exit_code = self.app.exec()
        if exit_code == 0:
            self.closeWindow(exit_code)

    def setup_group_checkboxes(self):
        """Set up the group checkboxes for each group and connect them to updateGroupState."""
        for i in range(self.numberOfChannels):
            layout = getattr(self.window, f"gridLayout_{i}", None)
            if layout:
                for j in range(layout.count()):
                    widget = layout.itemAt(j).widget()
                    if isinstance(widget, QCheckBox):
                        self.group_checkboxes[i].append(widget)
                        widget.stateChanged.connect(
                            lambda state, idx=i + 1, w=widget: self.updateGroupState(idx, w, state)
                        )

    def connect(self):
        """Connects the program to the hardware system (PCB) using EnnocureEU."""
        if not self.PCB:
            self.logger.setLevel(logging.DEBUG)
            ch = logging.StreamHandler()
            ch.setLevel(logging.DEBUG)
            logger_path = op.join(os.getcwd(), 'ennocure_eu_logger.txt')
            fh = logging.FileHandler(logger_path)
            formatter = logging.Formatter("%(asctime)s : %(levelname)s : %(message)s")
            ch.setFormatter(formatter)
            fh.setFormatter(formatter)
            self.logger.addHandler(ch)
            self.logger.addHandler(fh)
            self.PCB = ennocure_controller.EnnocureEU(logger=self.logger)

        self.window.OutPut.appendPlainText("Try connecting to hardware")
        try:
            with open("ennocure_eu_logger.txt", "r") as txt_file:
                txt_lines = txt_file.readlines()
        except FileNotFoundError:
            self.window.OutPut.appendPlainText("Error: Logger file not found.")
            return

        if self.PCB and self.PCB.ser.is_open:
            self.window.ConnectButton.setStyleSheet("background-color: rgb(0,180,0)")
            self.window.OutPut.appendPlainText(txt_lines[-1][33:-1])
            self.window.OutPut.appendPlainText(txt_lines[-2][33:-2])
            self.PCB.logger.info("connected successfully")
            print("connected successfully")
            self.window.OutPut.appendPlainText("connected successfully")
        else:
            self.window.OutPut.appendPlainText("Something wrong with connection")
            return

        self.setPCMode(self.PC_mode)
        self.setSubMode(self.sub_mode)

        try:
            with open("ennocure_eu_logger.txt", "r") as txt_file:
                txt_lines = txt_file.readlines()
        except FileNotFoundError:
            self.window.OutPut.appendPlainText("Error: Logger file not found.")
            return

        if 'successfully' in txt_lines[-1]:
            self.window.OutPut.appendPlainText("PC_mode set to 1 (PC control)")
            self.window.OutPut.appendPlainText("Sub_mode set to 0 (standalone base)")
            self.setAllLastParameters()
        else:
            self.window.OutPut.appendPlainText(
                "Something wrong with mode setting please check connection and try again")
    def sync_channel_state(self, line: int, channel_type: str, active: bool) -> None:
        """Synchronizes the channel state with the UI and hardware."""
        if self.updating_channel:
            return
        self.updating_channel = True

        if not (1 <= line <= 23):
            self.window.OutPut.appendPlainText(f"Error: Invalid channel number {line}. Must be between 1 and 23.")
            self.updating_channel = False
            return

        combobox = self.line_type_comboboxes[line - 1]
        checkbox = self.line_onoff_checkboxes[line - 1]

        if combobox.findText("SNK") == -1 or combobox.findText("SRC") == -1 or combobox.findText("Off") == -1:
            self.window.OutPut.appendPlainText(f"Error: QComboBox for Line {line} does not contain required values.")
            self.updating_channel = False
            return

        if channel_type == 'SNK':
            self.lines_SRC[line - 1], self.lines_SNK[line - 1] = 0, 1
            combobox.setCurrentIndex(combobox.findText("SNK"))
            combobox.setStyleSheet("background-color: #b2d0f7;")
        elif channel_type == 'SRC':
            self.lines_SRC[line - 1], self.lines_SNK[line - 1] = 1, 0
            combobox.setCurrentIndex(combobox.findText("SRC"))
            combobox.setStyleSheet("background-color: #b2f0b2;")
        else:
            self.lines_SRC[line - 1], self.lines_SNK[line - 1] = 0, 0
            combobox.setCurrentIndex(combobox.findText("Off"))
            combobox.setStyleSheet("")

        self.lines_status[line - 1] = 1 if active else 0
        checkbox.setChecked(active)
        combobox.repaint()

        if self.PCB:
            self.PCB.set_electrodes(self.lines_status * self.lines_SRC, self.lines_status * self.lines_SNK)
            try:
                self.PCB.gen_command_data()
            except Exception as e:
                self.window.OutPut.appendPlainText(f"Error in gen_commands: {str(e)}")

        self.updating_channel = False

    def updateGroupState(self, group_index: int, widget, state: int) -> None:
        """Updates the group state and changes all the checkboxes within it."""
        if not (1 <= group_index <= 23):
            self.window.OutPut.appendPlainText(f"Error: Invalid group index {group_index}. Must be between 1 and 23.")
            return

        new_state = 1 if state == 2 else 0
        if self.checkboxes[group_index - 1] == new_state:
            return

        self.checkboxes[group_index - 1] = new_state
        for checkbox in self.group_checkboxes[group_index - 1]:
            checkbox.setChecked(bool(new_state))

        combobox = self.line_type_comboboxes[group_index - 1]
        channel_type = "SRC" if new_state else "SNK" if combobox.currentText() == "Off" else combobox.currentText()
        self.sync_channel_state(group_index, channel_type, new_state)

        self.updateChannels(self.checkboxes)

    def toggleCheckbox(self, index: int, state: bool) -> None:
        """Simulate clicking the checkbox for a specific group based on the state."""
        if not (1 <= index <= 23):
            self.window.OutPut.appendPlainText(f"Error: Invalid group index {index}. Must be between 1 and 23.")
            return

        for cb in self.group_checkboxes[index - 1]:
            cb.setChecked(state)

    def setLineType(self, line: int, state_id: str = None) -> None:
        """Sets the line type (Sink/Source) based on the user selection in the interface."""
        if not (1 <= line <= 23):
            self.window.OutPut.appendPlainText(f"Error: Invalid channel number {line}. Must be between 1 and 23.")
            return

        button = self.line_type_comboboxes[line - 1]
        if state_id is None:
            state = button.currentData()
            if state is None:
                state = button.currentText()
        else:
            state = state_id

        is_active = bool(self.lines_status[line - 1])
        self.sync_channel_state(line, state, is_active)

    def setLineActive(self, state: int, line: int) -> None:
        """Sets a channel to ON or OFF, and updates the state accordingly."""
        if not (1 <= line <= 23):
            self.window.OutPut.appendPlainText(f"Error: Invalid channel number {line}. Must be between 1 and 23.")
            return

        new_state = 1 if state == 2 else 0
        self.lines_status[line - 1] = new_state

        combobox = self.line_type_comboboxes[line - 1]
        channel_type = combobox.currentText()
        if channel_type == "Off":
            channel_type = "SRC" if new_state else "SNK"

        self.sync_channel_state(line, channel_type, new_state)


    def toggleAll(self, state):
        """Toggles all lines' states (on/off) based on the given state."""
        # if state:
        #     self.lines_status = numpy.ones(self.numberOfChannels)
        # else:
        #     self.lines_status = numpy.zeros(self.numberOfChannels)
        # self.PCB.set_electrodes(self.lines_status * self.lines_SRC, self.lines_status * self.lines_SNK)
        self.from_toggle_all = True  # מציין שהקריאה היא מ-toggleAll

        for line in range(self.numberOfChannels):
            button = getattr(self.window, f"Line{line}_onoff")
            button.setChecked(state)
        #print("when toggleAll is True")
        self.PCB.set_electrodes(self.lines_status * self.lines_SRC, self.lines_status * self.lines_SNK)
        #self.window.OutPut.appendPlainText(f"Line {line} set to {state}")

        try:
            self.PCB.gen_command_data()
        except Exception as error:
            self.window.OutPut.appendPlainText("Error in gen_commands")
        self.from_toggle_all = False  # מחזיר את הדגל למצב רגיל

        # try:
        #     self.PCB.gen_command_data(True)
        # except Exception as error:
        #     self.window.OutPut.appendPlainText("Error in gen_commands")


    def evenFlip(self, state):
        """Sets the even flip state. Activates if state is 2, deactivates otherwise."""
        if state == 2:
            self.toDoEvenFlip = 1
            self.doFlip = True
            print("flip ON")
            self.window.OutPut.appendPlainText("flip ON")
        else:
            self.toDoEvenFlip = 0
            print("flip OFF")
            self.window.OutPut.appendPlainText("flip OFF")

    def inverse(self):
        """Changes the state of the channels based on ComboBox selections and updates the channels afterward."""
        newList = []
        for i in range(self.numberOfChannels):
            combo = getattr(self.window, f"Line{i}_type", None)  # Access the appropriate ComboBox
            if combo is None:
                raise AttributeError(f"ComboBox for Line{i}_type not found in the UI.")

            state = 1 if combo.currentIndex() == 0 else 0
            newList.append(state)

        self.updateChannels(newList)

    def setAllLastParameters(self):
        """Reads the last saved parameters from a file and updates the UI with the values."""
        try:
            lines = self.readFile(file_LastOpening)
            if len(lines) < 4:
                self.window.OutPut.appendPlainText("Error: LastOpening.txt is incomplete.")
                return

            for i, line in enumerate(lines[:4]):
                if ":" not in line:
                    self.window.OutPut.appendPlainText(f"Error: Invalid format in LastOpening.txt at line {i}.")
                    return

            port = lines[0].split(":", 1)[1].strip()
            self.window.editPort.setText(port)

            param_list = ast.literal_eval(lines[1].split(":", 1)[1].strip())
            if not isinstance(param_list, list) or len(param_list) < 4:
                self.window.OutPut.appendPlainText("Error: Parameters format is incorrect.")
                return

            mode = lines[2].split(":", 1)[1].strip()
            mode_number = int(mode)
            if not self.loadAndApplyState(mode_number, file_channels):
                self.window.OutPut.appendPlainText("Error: Failed to load channel state.")
                return

            flipState = lines[3].split(":", 1)[1].strip()
            self.window.Period.setText(param_list[0].strip())
            self.window.DutyCycle.setText(param_list[1].strip())
            self.window.TotalTime.setText(param_list[2].strip())
            self.window.TimeUnit.setCurrentText(param_list[3].strip())
            self.window.ChannelsMode.setCurrentText(f"Mode {mode_number}")
            if flipState == "True": self.window.inverstClick.setChecked(2)

            period_text = self.window.Period.text().strip("[]'")
            self.period = int(period_text)

        except ValueError as e:
            self.window.OutPut.appendPlainText(f"Error: Could not convert period '{period_text}' to integer.")
        except Exception as e:
            self.window.OutPut.appendPlainText(f"Error: {e}")
    def saveLastAllParameters(self):
        """Saves parameters, port, and flip state to a text file."""
        param, mode = self.getParameters()
        port = EnnocureEU.port
        flipState = True if self.toDoEvenFlip == 1 else False
        content = f"Port: {port[3:]}\nParameters: {param}\nMode: {mode}\nFlipState: {flipState}"

        with open("LastOpening.txt", "w", encoding="utf-8") as file:
            file.write(content)

    def setEditPort(self):
        """Updates the port based on user input, while checking the input validity."""
        editPort = self.window.editPort.text().strip()  # Removes unnecessary spaces
        if editPort.isdigit():  # Checks if the string contains only digits
            editPort = int(editPort)
        else:
            editPort = 0  # Or any default value you prefer
        editPort = 'COM' + str(editPort)
        print(f"EditPort is set to: {editPort}")
        self.window.OutPut.appendPlainText(f"EditPort is set to: {editPort}")
        EnnocureEU.port = editPort
        EnnocureEU.check_port(self, EnnocureEU.port)

    def getPort(self):
        """
        Retrieves and lists all available ports, sorted by port number.
        Logs and displays the available ports.
        """
        self.available_ports = sorted([p.name for p in list_ports.comports()],
                                      key=lambda port: int(re.search(r'\d+', port)[0]))
        self.window.OutPut.appendPlainText(f"Available ports: {self.available_ports}")
        print(f"Available ports: {self.available_ports}")

    def setCurrentLimit(self):
        """
        Sets the current limit from the UI and updates the PCB.
        Logs and displays the current limit.
        """
        self.current_limit = int(self.window.CurrentLimit.text())
        self.PCB.set_current_limit(self.current_limit)
        self.window.OutPut.appendPlainText(f'current limitation was set to: {self.current_limit}')
        self.PCB.gen_command_data(True)

    def setSubMode(self, setMode):
        """Sets the sub-mode in the system."""
        self.sub_mode = setMode
        self.PCB.select_sub_mode(self.sub_mode)
        self.window.OutPut.appendPlainText(f'Control SubMode is: {setMode}')
        self.PCB.gen_command_data(True)

    def setPCMode(self, setMode):
        """Sets the PC mode in the system."""
        self.PC_mode = setMode
        self.PCB.set_pc(self.PC_mode)
        self.window.OutPut.appendPlainText(f'Control Mode is: {setMode}')
        self.PCB.gen_command_data(True)

    def setTimeUnit(self, input_TimeUnit):
        """Sets the time units (hours, minutes, seconds)."""
        self.totalTimeUnits = [0, 0, 0]
        self.totalTimeUnits[input_TimeUnit] = 1
        # self.window.OutPut.appendPlainText(f'Your new units are: {self.totalTimeUnits}')

    def setTotalTime(self):
        """Calculates the total time based on the selected time units."""
        par = int(self.window.TotalTime.text())
        factor_vector = sum([self.timeFactorArray[i] * self.totalTimeUnits[i] for i in range(len(self.totalTimeUnits))])
        self.totalTime = par * factor_vector  # total time in seconds
        self.window.OutPut.appendPlainText(f'Total time in seconds: {self.totalTime}')

    def setDutyCycle(self):
        """Sets the duty cycle (the fraction of time the system is active)."""
        self.dutyCycle = int(self.window.DutyCycle.text()) / 100

    def setPeriod(self):
        """Sets the period time for each cycle."""
        self.period = int(self.window.Period.text())

    def turnOnEF(self):
        """
        Turns on the electro stimulation and handles even flip logic. Logs the activation time.
        If the cycle counter reaches the total cycles, the process stops; otherwise, the next cycle begins.
        """
        # Even flip logic
        if self.toDoEvenFlip:
            if self.doFlip:
                self.inverse()
            self.doFlip = not self.doFlip

        # Time and cycle management
        current_datetime = datetime.datetime.now()

        if self.cycleCounter >= self.cycles:
            self.StartTimer.stop()  # Stop the timer
            self.PCB.logger.info("Process has been finished")
        else:
            self.cycleCounter += 1
            self.window.OutPut.appendPlainText(
                f"Turn on {self.cycleCounter} time from {self.cycles}  :{current_datetime.strftime('%d/%m/%Y  %H:%M:%S')}")
            self.logger.info(f"Turn on {self.cycleCounter} time from {self.cycles}")

            # Set electro stimulation and trigger next cycle
            self.lines_status = numpy.ones(self.numberOfChannels)
            self.StopTimer.singleShot(self.offTime * 1000, self.turnOffEF)
            self.PCB.set_electrodes(self.lines_status * self.lines_SRC, self.lines_status * self.lines_SNK)
            self.PCB.gen_command_data(True)

    def turnOffEF(self):
        """
        Turns off the electro stimulation and updates the status. Logs the turn-off time and process details.
        If the cycle count is reached, the process is finished; otherwise, the algorithm continues.
        """
        current_datetime = datetime.datetime.now()
        self.window.OutPut.appendPlainText(
            f"Turn off {self.cycleCounter} time from {self.cycles}  :{current_datetime.strftime('%d/%m/%Y  %H:%M:%S')}")
        self.logger.info(f"Turn off {self.cycleCounter} time from {self.cycles}")

        # Reset line status and update PCB
        self.lines_status = numpy.zeros(self.numberOfChannels)
        if self.cycleCounter == self.cycles:
            self.window.OutPut.appendPlainText('Process finished')

        self.PCB.set_electrodes(self.lines_status * self.lines_SRC, self.lines_status * self.lines_SNK)
        self.PCB.gen_command_data(True)

        # Stop process if the algorithm flag is set
        if self.algoFlag:
            self.window.OutPut.appendPlainText(
                f'Process was stopped at the {self.cycleCounter} time from {self.cycles}')
            self.StartTimer.stop()
            self.PCB.logger.info(f'Process was stopped at the {self.cycleCounter} time from {self.cycles}')
            self.algoFlag = False

    def runAlgo(self):
        """
        Starts the algorithm by saving parameters, logging relevant information,
        resetting algorithm variables, and initiating the timer.
        """
        # Save parameters and log information
        self.logger.info("--------------------------------------------------------------------------------------")

        self.saveLastAllParameters()
        self.logger.info(self.window.ChannelsMode.currentText())
        self.logger.info(f"SRC: {self.lines_SRC}")
        self.logger.info(f"SNK: {self.lines_SNK}")
        self.logger.info(f"period: {self.period} | dutyCycle: {self.dutyCycle} | totalTime: {self.totalTime}")

        # Reset algorithm and set initial values
        self.resetAlgorithm()
        self.algoFlag = False
        self.cycleCounter = 0
        self.setTotalTime()
        self.offTime = self.period * self.dutyCycle
        self.cycles = int(self.totalTime / self.period)

        # Start the timer
        self.StartTimer.timeout.connect(self.turnOnEF)
        self.StartTimer.start(self.period * 1000)

    def resetAlgorithm(self):
        """
        Resets all algorithm-related variables and stops the timer.
        """
        # Reset variables
        self.offTime = 0
        self.cycles = 0
        self.totalTime = 0

        # Stop and disconnect the timer
        self.StartTimer.stop()
        self.StartTimer.timeout.disconnect()

    def readFile(self, fileTXT):
        """
        Reads the content of the specified file and returns all the lines.

        """
        try:
            with open(fileTXT, "r") as file:
                return file.readlines()
        except Exception as e:
            self.window.OutPut.appendPlainText("The file is empty. No saved states to display.")
            print(e)
            return []

    def raiseFlag(self):
        """Sets a flag to stop the algorithm."""
        current_datetime = datetime.datetime.now()
        self.window.OutPut.appendPlainText(
            f"Flag raised - process has been stopped :{current_datetime.strftime('%d/%m/%Y  %H:%M:%S')}")
        self.logger.info("process stopped")
        self.algoFlag = True
        self.StartTimer.stop()
        evenFlip = False
        numberForEvenFlip = 1

    def saveChannels(self):
        """
        Saves the current channel configuration to the file. Updates the mode's data based on
        the selected ComboBox values and writes the changes back to the file. If the file does
        not exist, it creates an empty file.

        Raises:
            AttributeError: If the ComboBox for a channel is not found.
        """
        try:
            if not os.path.exists(file_channels):
                with open(file_channels, "w") as file:
                    pass  # Create empty file if not exists

            with open(file_channels, "r") as file:
                lines = file.readlines()

            # Get selected mode and update its data
            self.selected_mode = self.window.ChannelsMode.currentText()
            selected_mode_number = int(self.selected_mode.replace("Mode ", "").strip())
            newList = []

            for i in range(self.numberOfChannels):
                combo = getattr(self.window, f"Line{i}_type", None)
                if combo is None:
                    raise AttributeError(f"ComboBox for Line{i}_type not found.")
                state = "1" if combo.currentIndex() == 1 else "0"
                newList.append(state)

            mode_data = f"Mode {selected_mode_number}: [{', '.join(newList)}]"
            lines[selected_mode_number - 1] = mode_data + "\n"

            with open(file_channels, "w") as file:
                file.writelines(lines)

            # self.setParameters()
            self.window.OutPut.appendPlainText(f"Mode {selected_mode_number} saved successfully.")

        except Exception as e:
            print(f"An error occurred: {e}")
            self.window.OutPut.appendPlainText(f"An error occurred: {e}")

    def updateChannels(self, state_values):
        """
            The function updates the ComboBox elements in the GUI to reflect the correct state
            (Source or Sink), changes their background colors accordingly, and updates
            the internal `lines_SRC` and `lines_SNK` lists.
        """
        for i, value in enumerate(state_values):
            # Update the ComboBox in the GUI
            combo = getattr(self.window, f"Line{i}_type", None)
            if combo is not None:
                combo.setCurrentIndex(1 if int(value) == 1 else 0)  # 1 = Source, 0 = Sink

            # Update the internal data
            if int(value) == 1:  # Source
                self.lines_SRC[i], self.lines_SNK[i] = 1, 0
                combo.setStyleSheet("background-color: #b2d0f7;")  # Light blue color

                # Simulate clicking the checkbox for Source
            elif int(value) == 0:  # Sink
                self.lines_SRC[i], self.lines_SNK[i] = 0, 1
                combo.setStyleSheet("background-color: #b2f0b2;")  # Light green color

                # Simulate clicking the checkbox for Sink
            else:  # Unrecognized value
                self.lines_SRC[i], self.lines_SNK[i] = 0, 0
            self.toggleCheckbox(i, int(value))

    def getStateInFile(self, mode_number, file):
        """
        Retrieves the state values for the given mode number from the specified file.
        The function reads the file, extracts the relevant state information for the
        specified mode, and returns it as a list of values.

        Args:
            mode_number: The mode number to retrieve (should be an integer).
            file: The file to read from.

        Returns:
            list: The state values if successful, None otherwise.
        """
        try:
            lines = self.readFile(file)  # Read file content
            mode_index = int(mode_number) - 1  # Convert to 0-based index
            if not lines:
                self.window.OutPut.appendPlainText(f"Error: The file {file} is empty.")
                return None
            if mode_index < 0 or mode_index >= len(lines):
                self.window.OutPut.appendPlainText(
                    f"Error: Mode {mode_number} does not exist in {file}. File has {len(lines)} modes."
                )
                return None
            line = lines[mode_index]  # Get the line for the specified mode number
            state = line.split(":", 1)[1].strip()  # Extract state information after ":"
            state_values = state[1:-1].split(",")  # Convert the state string to a list
            return state_values  # Return the state values as a list
        except FileNotFoundError:
            self.window.OutPut.appendPlainText(f"Error: File {file} not found.")
            return None
        except IndexError as e:
            self.window.OutPut.appendPlainText(f"Error: Invalid format in {file} for Mode {mode_number}: {e}")
            return None
        except Exception as e:
            self.window.OutPut.appendPlainText(f"An error occurred while reading {file}: {e}")
            return None
    def loadAndApplyState(self, mode_number, file):
        """
        Loads the state for the given mode number from the specified file
        and applies it to the channels. If successful, a confirmation message
        is displayed in the output window and printed in the console.

        Args:
            mode_number: The mode number to load (should be an integer).
            file: The file to read the state from.

        Returns:
            bool: True if the state was loaded successfully, False otherwise.
        """
        state_values = self.getStateInFile(mode_number, file)  # Retrieve state values from file
        if state_values:
            self.updateChannels(state_values)  # Update channels with the loaded state values
            self.window.OutPut.appendPlainText(f"Channel Mode {mode_number} loaded successfully.")
            print(f"Channel Mode {mode_number} loaded successfully.")
            return True
        else:
            self.window.OutPut.appendPlainText(f"Failed to load Channel Mode {mode_number}.")
            print(f"Failed to load Channel Mode {mode_number}.")
            return False

    def onChannelsModeChanged(self):
        """
        Handles the change in channel mode selection from the ComboBox.
        Retrieves the selected mode, extracts the mode number, and calls the
        relevant functions to load parameters and apply the corresponding state.
        """
        try:
            self.selected_mode = self.window.ChannelsMode.currentText()  # Get selected mode from ComboBox
            mode_number = int(self.selected_mode)  # Extract mode number from string (e.g., "Mode 2" -> 2)
            self.loadAndApplyState(mode_number, file_channels)  # Apply the state for the selected mode
        except (IndexError, ValueError) as e:
            self.window.OutPut.appendPlainText(f"Error: {str(e)}")  # Log error message
    def getParameters(self) -> tuple:
        """
        Retrieves parameter values from the UI.

        Returns:
            tuple: A list of parameters and the selected mode.
        """
        getPeriod = self.window.Period.text()
        getDutyCycle = self.window.DutyCycle.text()
        getTotalTime = self.window.TotalTime.text()
        getTimeUnit = self.window.TimeUnit.currentText()
        allParameters = [getPeriod, getDutyCycle, getTotalTime, getTimeUnit]
        self.selected_mode = self.window.ChannelsMode.currentText()
        return allParameters, self.selected_mode

    def closeWindow(self, exit_code):
        if self.PCB and self.PCB.ser.is_open:
            self.PCB.ser.close()
        self.logger.info("The program has closed")
        sys.exit(exit_code)