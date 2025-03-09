#!/usr/bin/bash

# Fail out on any error
#set -e

print() {
    echo "$(date +'%a, %b %m %T.%3N'):" $*
}

tv_cmd() {
    ./sony_commander.py $*
}

tv_cmd_durable() {
    local res
    local ec

    while :
    do
        res=$(tv_cmd $*)
        ec=$?

        if [ $ec -eq 0 ]; then
            break;
        fi

        sleep 1
    done

    if [ -n "$res" ]; then
        echo $res
    fi

    return $ec
}

wait_for_state() {
    local res

    while :
    do
        res=$(tv_cmd get_power_state)
        if [ $? -eq 0 ] && [ "$res" = "$1" ]; then
            break;
        fi

        sleep 1
    done
}

# Ensure we're running as root so we can actually do the suspend bit
if [ $EUID -ne 0 ] ; then
    >&2 echo "Error: script must be run as root"
    exit 1;
fi

# Value to use when setting the TV's sleep timer (minutes)
timer=120

# How often to check the TV's power state
check_interval=5

while :
do
    # ensure the TV is on & wait a moment for it to turn on
    if [ $(tv_cmd_durable get_power_state) -ne "1" ]; then
        print "Powering on TV..."
        tv_cmd_durable power_on true

        # wait a moment for the TV to get going
        print "Waiting for TV to enter power-on state..."
        wait_for_state 1

        # Bit of an extra sleep to ensure we give the TV enough time to startup. My TV reports it's on
        # before it's fully ready to do other stuff properly (like setting the sleep timer)
        sleep 3
    fi

    # Start the sleep timer
    print "Setting sleep timer for ${timer} minutes..."
    tv_cmd_durable set_sleep_timer ${timer}

    # Wait for the TV to shut off (manual or otherwise)
    print "Waiting until TV is shut off..."
    iteration_start=$(date +'%Y-%m-%d %T')

    while :
    do
        sleep ${check_interval}

        # Check that we didn't go into hibernation while we were sleeping
        journalctl -t systemd-sleep --since "${iteration_start}" | grep -q -m 1 -i 'System returned from sleep operation'
        if [ $? -eq 0 ]; then
            print "System was suspended by another service. Restarting iteration..."
            break;
        fi

        # Check the TV's power state
        power_state=$(tv_cmd get_power_state)
        if [ $? -eq 0 ] && [ "${power_state}" -eq "0" ]; then
            print "Detected TV power-off state; suspending..."
            systemctl suspend-then-hibernate --wait

            print "Waiting until system comes out of hibernation..."
            journalctl -t systemd-sleep --since now -f | grep -q -m 1 -i 'System returned from sleep operation'

            print "Ensuring system is in a running state..."
            systemctl is-system-running --wait

            print "System is running! Restarting sleep timer..."
            break;
        fi
    done
done
