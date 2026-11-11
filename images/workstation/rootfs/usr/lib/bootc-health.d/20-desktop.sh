#!/bin/bash
# A workstation that can't show a login screen counts as unhealthy.
if systemctl is-active --quiet gdm.service; then
    exit 0
fi
echo "gdm.service not active"
exit 1
