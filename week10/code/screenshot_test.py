import subprocess
import time

subprocess.Popen(["libreoffice", "--norestore", "--calc", "/home/acer/Documents/DEEPAK/eva_april2026/mainbranch/eva_april2026/week10/data/tasklist.ods"])
time.sleep(5)
subprocess.run(["xdotool", "key", "alt+s"])
time.sleep(1)
subprocess.run(["import", "-window", "root", "menu_visible.png"])
subprocess.run(["pkill", "soffice"])
