#Requires -Modules Hyper-V
<#
.SYNOPSIS
  Creates the isolated lab switch: a Private vSwitch named "bootc-lab".
.DESCRIPTION
  A Private switch has no host adapter and no uplink, so lab clients can only
  reach each other and the PXE VM's second NIC. Nothing on it can reach your
  existing networks, and its DHCP can't leak onto them. Needs no admin rights
  beyond Hyper-V Administrators.
#>
[CmdletBinding()]
param(
    [string]$SwitchName = 'bootc-lab'
)
$ErrorActionPreference = 'Stop'

$sw = Get-VMSwitch -Name $SwitchName -ErrorAction SilentlyContinue
if ($sw) {
    if ($sw.SwitchType -ne 'Private') {
        throw "Switch '$SwitchName' exists but is $($sw.SwitchType), not Private. Refusing to use it."
    }
    Write-Host "Switch '$SwitchName' already exists (Private)."
} else {
    New-VMSwitch -Name $SwitchName -SwitchType Private -Notes 'bootc airgap lab (isolated)' | Out-Null
    Write-Host "Created Private switch '$SwitchName'."
}
