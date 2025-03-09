This repo is a dumping ground of some scripts I've written to control my TV and media center PCs. These were written to run on a modern Fedora system (F41+), but will probably work on any distro with systemd, python, and USB-serial device drivers. Probably.

There is absolutely no guarantee these scripts will work for anyone or any device other than myself and the things I own. The code it also low quality and comes with no tests, no validation or verification scripts, or anything even approaching CI. Use at your own risk.

# sony_commander.py
A simple python script which can control Sony TVs through the RS232 port. Requires python 3+ and pySerial 3.0+

pySerial can be installed via pip: `python -m pip install pySerial`

# sleep_timer.sh
This script automatically sets the sleep timer function on the TV, then suspends the system (suspend-then-hibernate) once the it detects the TV has turned off. When the system comes back up from suspend/hibernate, it will turn the TV on and repeat the cycle.
