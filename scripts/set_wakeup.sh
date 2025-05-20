#!/bin/bash

LOGFILE="/home/chinmay/wakeup.log"
LOCKFILE="/tmp/set_wakeup.lock"

# Configurable hours
TIME1_HOUR="07:00"
TIME2_HOUR="19:00"

log() {
    echo "$(date +"%Y-%m-%d %H:%M:%S") - $1" >> "$LOGFILE"
}

command -v nc >/dev/null 2>&1 || {
    log "ERROR: netcat (nc) is not installed."
    exit 1
}

# Prevent duplicate runs
if [ -e "$LOCKFILE" ]; then
    log "Another instance is already running. Exiting."
    exit 1
else
    touch "$LOCKFILE"
    trap 'rm -f "$LOCKFILE"' EXIT
fi

now_ts=$(date +%s)
today=$(date +%Y-%m-%d)

# Define time1 and time2 using variables
time1="$today $TIME1_HOUR"
time2="$today $TIME2_HOUR"

time1_ts=$(date -d "$time1" +%s)
time2_ts=$(date -d "$time2" +%s)

# If both times are in the past, shift both to tomorrow
if (( now_ts > time1_ts && now_ts > time2_ts )); then
    time1=$(date -d "$TIME1_HOUR tomorrow" +"%Y-%m-%d %H:%M")
    time2=$(date -d "$TIME2_HOUR tomorrow" +"%Y-%m-%d %H:%M")
    time1_ts=$(date -d "$time1" +%s)
    time2_ts=$(date -d "$time2" +%s)
fi

# Calculate time differences
diff1=$(( time1_ts > now_ts ? time1_ts - now_ts : now_ts - time1_ts ))
diff2=$(( time2_ts > now_ts ? time2_ts - now_ts : now_ts - time2_ts ))

# Choose the closer time
if (( diff1 < diff2 )); then
    chosen_time=$(date -d "$time1" +"%Y-%m-%dT%H:%M:%S.000%:z")
    log "Choosing time1: $time1"
else
    chosen_time=$(date -d "$time2" +"%Y-%m-%dT%H:%M:%S.000%:z")
    log "Choosing time2: $time2"
fi

log "Setting RTC wakeup for $chosen_time"
response=$(echo "rtc_alarm_set $chosen_time 127" | nc -q 0 127.0.0.1 8423)
log "RTC alarm response: $response"

log "Waiting for 2 minutes before shutdown..."
sleep 120
log "Shutting down"
sudo /sbin/shutdown -h now
