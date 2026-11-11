#!/bin/bash
# Core services every profile needs to be manageable.
rc=0
for unit in sshd.service chronyd.service; do
    if ! systemctl is-active --quiet "${unit}"; then
        echo "${unit} not active"
        rc=1
    fi
done
exit "${rc}"
