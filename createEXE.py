import os
import subprocess

def create_exe_from_folder(folder_path):
    """
    Creates an EXE from main.py and includes icon.ico from the same folder.
    """
    main_py = os.path.join(folder_path, "main.py")
    icon_ico = os.path.join(folder_path, "icon.ico")

    # Check if main.py exists
    if not os.path.isfile(main_py):
        print(f"Error: main.py not found in: {main_py}")
        return

    # Check if icon.ico exists
    if not os.path.isfile(icon_ico):
        print(f"Error: icon.ico not found in: {icon_ico}")
        return

    # Change working directory to the target folder
    os.chdir(folder_path)

    # Build the PyInstaller command
    command = [
        "pyinstaller",
        "--onefile",
        "--windowed",
        f"--icon={icon_ico}",
        "--name=EnnocureApp",
        "main.py"
    ]

    try:
        subprocess.run(command, check=True)
        print("✅ EnnocureApp.exe was successfully created! Check the 'dist' folder.")
    except subprocess.CalledProcessError as e:
        print(f"Error during EXE creation: {e}")

if __name__ == "__main__":
    folder_path = input("📂 Enter the path to the folder containing main.py and icon.ico:\n")
    folder_path = folder_path.strip('"')  # Remove quotes if user added them

    if os.path.isdir(folder_path):
        create_exe_from_folder(folder_path)
    else:
        print(f"Error: The provided path is not a valid directory: {folder_path}")
