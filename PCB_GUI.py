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
import time

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
    lines_SRC = numpy.ones(numberOfChannels)
    lines_SNK = numpy.zeros(numberOfChannels)
    lines_status = numpy.zeros(numberOfChannels)
    offTime = 0
    cycles = 1
    cycleCounter = 0
    current_limit = 0
    dutyCycle = 0  # in percent(%)
    period = 0  # in seconds
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
    is_running = False  # משתנה למעקב אחר מצב הריצה

    def __init__(self):

        """Initialize the program: Open the UI, connect buttons to functions, and load the UI."""
        self.app = QApplication(sys.argv)
        ui_file_name = "PCB_GUI.ui"
        ui_file = QFile(ui_file_name)
        self.from_toggle_all = False  # משתנה דגל למחלקה

        if not ui_file.open(QIODevice.ReadOnly):
            print(f"Cannot open {ui_file_name}: {ui_file.errorString()}")
            sys.exit(-1)
        loader = QUiLoader()
        self.window = loader.load(ui_file)
        ui_file.close()
        if not self.window:
            print(loader.errorString())
            sys.exit(-1)

        # Connect buttons and actions to their respective functions
        self.window.ConnectButton.clicked.connect(self.connect)  # Connect button activation
        self.window.ConnectButton.setStyleSheet(
            "background-color: rgb(173, 0, 0); border: none; border-radius: 12px; padding: 5px;")
        self.window.RunSenario.clicked.connect(self.runAlgo)
        self.window.RunSenario.setStyleSheet(
            "background-color:rgb(173, 216, 230); border: none; border-radius: 12px; padding: 5px;")
        self.window.PC_SubMode.currentIndexChanged.connect(self.setSubMode)
        self.window.PC_Mode.currentIndexChanged.connect(self.setPCMode)
        # self.window.CurrentLimit.editingFinished.connect(self.setCurrentLimit)
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

        self.buttons = {f"Line{line}_onoff": getattr(self.window, f"Line{line}_onoff") for line in
                        range(self.numberOfChannels)}

        self.window.OutPut.appendPlainText("please start by connecting to hardware")

        line_button_type = []
        line_button_state = []
        for i in range(self.numberOfChannels):  # Set line type activation by loop
            line_button_type.append(getattr(self.window, f"Line{i}_type"))
            line_button_type[i].activated.connect(partial(self.setLineType, i))
            line_button_state.append(getattr(self.window, f"Line{i}_onoff"))
            line_button_state[i].stateChanged.connect(lambda checked, i=i: self.setLineActive(checked, i))

        self.checkboxes = [0] * self.numberOfChannels  # מערך מצב הקבוצות
        self.group_checkboxes = [[] for _ in range(self.numberOfChannels)]  # שמירת כל ה-checkboxים לפי קבוצה

        for i in range(self.numberOfChannels):
            layout = getattr(self.window, f"gridLayout_{i}", None)  # קבלת ה-layout של הקבוצה
            if layout:
                for j in range(layout.count()):
                    widget = layout.itemAt(j).widget()
                    if isinstance(widget, QCheckBox):
                        self.group_checkboxes[i].append(widget)  # שמירת ה-checkboxים של הקבוצה
                        widget.stateChanged.connect(
                            partial(self.updateGroupState, i))  # חיבור לפונקציה שתעדכן את המצב

        self.window.show()

        exit_code = qApp.exec()
        if exit_code == 0:
            self.closeWindow(exit_code)

    def connect(self):
        """Connects the program to the hardware system (PCB) using EnnocureEU."""
        if self.PCB == []:
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
        else:
            self.PCB.connected_failed = 0
        self.window.OutPut.appendPlainText("Try connecting to hardware")
        self.PCB.connect_to_port()
        if not self.PCB.connected_failed:
            txt_file = open("ennocure_eu_logger.txt", "r")
            txt_lines = txt_file.readlines()
            if self.PCB.ser.is_open:
                self.window.ConnectButton.setStyleSheet("background-color: rgb(0,180,0)")
                self.window.OutPut.appendPlainText(txt_lines[-1][33:-1])
                # self.window.OutPut.appendPlainText(txt_lines[-2][33:-2])
                self.PCB.logger.info("connected successfully")
                print("connected successfully")
                # self.window.OutPut.appendPlainText("connected successfully")
            else:
                self.window.OutPut.appendPlainText("Something wrong with connection")

            txt_file.close()
            self.setPCMode(self.PC_mode)
            self.setSubMode(self.sub_mode)

            txt_file = open("ennocure_eu_logger.txt", "r")
            txt_lines = txt_file.readlines()
            txt_file.close()

            if ('successfully' in txt_lines[-1]):
                self.window.OutPut.appendPlainText("PC_mode set to 1 (PC control)")
                self.window.OutPut.appendPlainText("Sub_mode set to 0 (standalone base)")
                self.setAllLastParameters()
                self.window.ConnectButton.setEnabled(False)

                # self.toggleAll(True)
            else:
                self.window.OutPut.appendPlainText(
                    "Something wrong with mode setting please check connection and try again")
        else:
            self.window.OutPut.appendPlainText(self.PCB.print_text)

    def closeWindow(self, exit_code):
        print("The program has closed")
        self.logger.info("The program has closed")
        sys.exit(exit_code)

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

    def getPort(self):
        """
        Retrieves and lists all available ports, sorted by port number.
        Logs and displays the available ports.
        """
        self.available_ports = sorted([p.name for p in list_ports.comports()],
                                      key=lambda port: int(re.search(r'\d+', port)[0]))
        self.window.OutPut.appendPlainText(f"Available ports: {self.available_ports}")
        print(f"Available ports: {self.available_ports}")

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

    def setLineType(self, line, state_id):
        """Sets the line type (Sink/Source) based on the user selection in the interface."""
        button = getattr(self.window, f"Line{line}_type")

        # בדיקה אם currentData(0) מחזיר ערך תקין
        state = button.currentData(0)
        if state is None:
            state = button.currentText()  # fallback ל- currentText()

        if state == 'SNK':  # אם מדובר ב-Sink
            self.lines_SRC[line], self.lines_SNK[line] = 0, 1
            button.setStyleSheet("background-color: #b2d0f7;")

        elif state == 'SRC':  # אם מדובר ב-Source
            self.lines_SRC[line], self.lines_SNK[line] = 1, 0
            button.setStyleSheet("background-color: #b2f0b2;")

        else:
            self.lines_SRC[line], self.lines_SNK[line] = 0, 0
            button.setStyleSheet("")

        button.repaint()  # refresh the button

        self.PCB.set_electrodes(self.lines_status * self.lines_SRC, self.lines_status * self.lines_SNK)

        try:
            self.PCB.gen_command_data()
        except Exception as error:
            self.window.OutPut.appendPlainText("Error in gen_commands")

    def setLineActive(self, state, line):
        """Sets a channel to ON or OFF, and updates the state accordingly."""
        # print(f"setLineActive line {line}")
        button = getattr(self.window, f"Line{line}_onoff")  # button של ON OFF
        self.lines_status[line] = 1 if state else 0

        if not self.from_toggle_all:
            self.PCB.set_electrodes(self.lines_status * self.lines_SRC, self.lines_status * self.lines_SNK)
            try:
                self.PCB.gen_command_data(True)
            except Exception as error:
                self.window.OutPut.appendPlainText("Error in gen_commands")

    def updateGroupState(self, group_index, state):
        """Updates the group state and changes all the checkboxes within it"""
        if state == 2:
            state = 1

        if self.checkboxes[group_index] == state:
            return

        self.checkboxes[group_index] = state
        for checkbox in self.group_checkboxes[group_index]:
            if checkbox.isChecked() != state:
                checkbox.setChecked(state)
        # קריאה לפונקציות setLineType ו- setLineActive על פי המצב
        line = group_index  # הערוץ שתואם לקבוצה (נניח שהקבוצה מייצגת ערוץ)

        if self.checkboxes[group_index] == 1:  # אם המצב 1, אנחנו מדליקים את הערוץ
            self.setLineActive(1, line)  # הדלקת הערוץ
            self.setLineType(line, "SRC")  # הגדרת המצב כ-Source (לפי הצורך שלך)
        else:  # אם המצב 0, אנחנו מכבים את הערוץ
            self.setLineActive(0, line)  # כיבוי הערוץ
            self.setLineType(line, "SNK")  # הגדרת המצב כ-Sink (לפי הצורך שלך)
        self.updateChannels(self.checkboxes)

    def toggleCheckbox(self, index, state):
        """
        Simulate clicking the checkbox for a specific group based on the state (True for checked, False for unchecked).
        """
        checkbox = self.group_checkboxes[index]  # Retrieve the checkbox group
        for cb in checkbox:
            cb.setChecked(state)

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
        self.PCB.set_electrodes(self.lines_status * self.lines_SRC, self.lines_status * self.lines_SNK)

        try:
            self.PCB.gen_command_data()
        except Exception as error:
            self.window.OutPut.appendPlainText("Error in gen_commands")
        self.from_toggle_all = False  # מחזיר את הדגל למצב רגיל

    """
    def inverse(self):
        "
        Inverts the states of SRC and SNK lines directly (without GUI access),then updates the PCB accordingly."

        for i in range(self.numberOfChannels):
            self.lines_SRC[i] = int(not self.lines_SRC[i])
            self.lines_SNK[i] = int(not self.lines_SNK[i])

        self.PCB.set_electrodes(self.lines_status * self.lines_SRC, self.lines_status * self.lines_SNK)
        self.PCB.gen_command_data(True)

    """

    def inverse(self):
        'Changes the state of the channels based on ComboBox selections and updates the channels afterward.'
        newList = []

        for i in range(self.numberOfChannels):
            combo = getattr(self.window, f"Line{i}_type", None)  # Access the appropriate ComboBox
            if combo is None:
                raise AttributeError(f"ComboBox for Line{i}_type not found in the UI.")

            state = 1 if combo.currentIndex() == 0 else 0
            newList.append(state)

        self.updateChannels(newList)

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
            self.PCB.set_electrodes(self.lines_status * self.lines_SRC, self.lines_status * self.lines_SNK)

    def getStateInFile(self, mode_number, file):
        """
        Retrieves the state values for the given mode number from the specified file.
        The function reads the file, extracts the relevant state information for the
        specified mode, and returns it as a list of values.

        """
        try:
            lines = self.readFile(file)  # Read file content
            line = lines[int(mode_number) - 1]  # Get the line for the specified mode number
            state = line.split(":", 1)[1].strip()  # Extract state information after ":"
            state_values = state[1:-1].split(",")  # Convert the state string to a list
            return state_values  # Return the state values as a list

        except FileNotFoundError:
            self.window.OutPut.appendPlainText("File not found.")  # Handle file not found error
        except Exception as e:
            self.window.OutPut.appendPlainText(f"An error occurred: {e}")  # Handle other errors

    def loadAndApplyState(self, mode_number, file):
        """
        Loads the state for the given mode number from the specified file
        and applies it to the channels. If successful, a confirmation message
        is displayed in the output window and printed in the console.

        """
        state_values = self.getStateInFile(mode_number, file)  # Retrieve state values from file
        if state_values:
            self.updateChannels(state_values)  # Update channels with the loaded state values

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
            print(f"Error: {str(e)}")  # Print error message to console

    def setAllLastParameters(self):
        """Reads the last saved parameters from a file and updates the UI with the values."""
        try:
            lines = self.readFile(file_LastOpening)

            for i, line in enumerate(lines[:4]):
                if ":" not in line:
                    print(f"Invalid format in line {i}: {line}")
                    return

            # port = lines[0].split(":", 1)[1].strip()
            # self.window.editPort.setText(port)

            parameters_str = lines[1].split(":", 1)[1].strip()
            try:
                param_list = ast.literal_eval(parameters_str)  # המרה לרשימה
                if not isinstance(param_list, list) or len(param_list) < 4:
                    raise ValueError("Parameters format is incorrect")
            except Exception as e:
                print(f"Error parsing parameters: {e}")
                return

            mode = lines[2].split(":", 1)[1].strip()
            self.loadAndApplyState(mode, file_channels)
            self.window.OutPut.appendPlainText(
                f"Channel Mode {mode} loaded successfully.")  # Log success message
            print(f"Channel Mode {mode} loaded successfully.")  # Print success message to console
            flipState = lines[3].split(":", 1)[1].strip()

            # עדכון ה-UI
            self.window.ChannelsMode.setCurrentText(mode)

            if flipState == "True":
                self.window.inverstClick.setChecked(2)

            # המרת period ל-int עם בדיקה
            period_text = self.window.Period.text().strip("[]'")

            try:
                self.period = int(period_text)
            except ValueError:
                print(f"Could not convert period_text '{period_text}' to int")
                return

        except Exception as e:
            print(f"Error: {e}")
            self.window.OutPut.appendPlainText(f"Error: {e}")

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

    def runAlgo(self):
        """
        Starts the algorithm by saving parameters, logging relevant information,
        resetting algorithm variables, and initiating the timer.
        """
        if self.is_running:
            self.window.OutPut.appendPlainText("Algorithm is already running!")
            return
        self.is_running = True
        self.window.RunSenario.setEnabled(False)  # השבתת הכפתור
        self.logger.info("--------------------------------------------------------------------------------------")
        self.saveLastAllParameters()
        self.logger.info(self.window.ChannelsMode.currentText())
        self.logger.info(f"SRC: {self.lines_SRC}")
        self.logger.info(f"SNK: {self.lines_SNK}")
        self.logger.info(f"period: {self.period} | dutyCycle: {self.dutyCycle} | totalTime: {self.totalTime}")

        # Reset algorithm to ensure clean state
        self.resetAlgo()

        # Set initial values
        self.period = int(self.window.Period.text())
        self.dutyCycle = int(self.window.DutyCycle.text()) / 100
        self.algoFlag = False
        self.cycleCounter = 0
        self.setTotalTime()
        self.offTime = self.period * self.dutyCycle
        self.cycles = int(self.totalTime / self.period)

        # Connect timer to turnOnEF (only once)
        self.StartTimer.timeout.connect(self.turnOnEF)

        # Start the timer
        self.turnOnEF()
        self.StartTimer.start(self.period * 1000)

    def resetAlgo(self):
        """
        Resets all algorithm-related variables and stops the timer.
        """
        # Stop the timer if it's running
        if self.StartTimer.isActive():
            self.StartTimer.stop()

        # Disconnect all connections to StartTimer.timeout safely
        try:
            self.StartTimer.timeout.disconnect()
        except TypeError:
            pass  # No connections to disconnect, safe to ignore

        # Reset algorithm variables
        self.cycleCounter = 0
        self.algoFlag = False
        self.offTime = 0
        self.cycles = 0
        self.totalTime = 0

    def turnOnEF(self):
        """
        Turns on the electro stimulation and handles even flip logic. Logs the activation time.
        If the cycle counter reaches the total cycles, the process stops; otherwise, the next cycle begins.
        """
        current_datetime = datetime.datetime.now()

        if self.cycleCounter >= self.cycles:
            self.StartTimer.stop()  # Stop the timer
            self.PCB.logger.info("Process has been finished")
            self.window.OutPut.appendPlainText(
                f"Flag raised - process has been stopped :{current_datetime.strftime('%d/%m/%Y  %H:%M:%S')}")
            return

        self.cycleCounter += 1
        self.window.OutPut.appendPlainText(
            f"Turn on {self.cycleCounter} time from {self.cycles}  :{current_datetime.strftime('%d/%m/%Y  %H:%M:%S')}")
        self.logger.info(f"Turn on {self.cycleCounter} time from {self.cycles}")

        # Set electro stimulation and schedule turn off
        self.lines_status = numpy.ones(self.numberOfChannels)
        self.StopTimer.singleShot(self.offTime * 1000, self.turnOffEF)
        self.PCB.set_electrodes(self.lines_status * self.lines_SRC, self.lines_status * self.lines_SNK)
        self.PCB.gen_command_data(True)

    def turnOffEF(self):
        current_datetime = datetime.datetime.now()
        self.window.OutPut.appendPlainText(
            f"Turn off {self.cycleCounter} time from {self.cycles}  :{current_datetime.strftime('%d/%m/%Y  %H:%M:%S')}")
        self.logger.info(f"Turn off {self.cycleCounter} time from {self.cycles}")

        self.lines_status = numpy.zeros(self.numberOfChannels)
        if self.cycleCounter == self.cycles:
            self.window.OutPut.appendPlainText('Process finished')
            self.is_running = False
            self.window.RunSenario.setEnabled(True)  # הפעלת הכפתור מחדש

        self.PCB.set_electrodes(self.lines_status * self.lines_SRC, self.lines_status * self.lines_SNK)
        self.PCB.gen_command_data(True)

        if self.toDoEvenFlip:
            if self.doFlip:
                self.inverse()
                self.window.OutPut.appendPlainText(f"Inversion occurred after cycle {self.cycleCounter}")
            self.doFlip = not self.doFlip

        if self.algoFlag:
            self.window.OutPut.appendPlainText(
                f'Process was stopped at the {self.cycleCounter} time from {self.cycles}')
            self.StartTimer.stop()
            self.PCB.logger.info(f'Process was stopped at the {self.cycleCounter} time from {self.cycles}')
            self.algoFlag = False
            self.is_running = False
            self.window.RunSenario.setEnabled(True)  # הפעלת הכפתור מחדש

    def raiseFlag(self):
        current_datetime = datetime.datetime.now()
        self.window.OutPut.appendPlainText(
            f"Flag raised - process has been stopped :{current_datetime.strftime('%d/%m/%Y  %H:%M:%S')}")
        self.logger.info("process stopped")
        self.algoFlag = True
        self.StartTimer.stop()
        self.is_running = False
        self.window.RunSenario.setEnabled(True)  # הפעלת הכפתור מחדש
        self.toDoEvenFlip = False
        self.numberForEvenFlip = 1

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

    def saveLastAllParameters(self):
        """Saves parameters, port, and flip state to a text file."""
        param, mode = self.getParameters()
        port = EnnocureEU.port
        flipState = True if self.toDoEvenFlip == 1 else False
        content = f"Port: {port[3:]}\nParameters: {param}\nMode: {mode}\nFlipState: {flipState}"

        with open("LastOpening.txt", "w", encoding="utf-8") as file:
            file.write(content)

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
