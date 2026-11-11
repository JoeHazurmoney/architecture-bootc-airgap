#Requires -Modules Hyper-V
<#
.SYNOPSIS
  Prints the PXE VM's uplink (Default Switch) IPv4 address, which can change
  after a host reboot. Used to SSH in from Windows.
.DESCRIPTION
  Asks Hyper-V first (KVP, from hyperv-daemons in the guest). Falls back to the
  host's neighbor table on the Default Switch, matched by the uplink's static MAC.
#>
[CmdletBinding()]
param(
    [string]$Name = 'bootc-lab-pxe',
    [string]$UplinkMac = '02-00-77-00-00-0A'
)
$ip = (Get-VMNetworkAdapter -VMName $Name -Name 'uplink').IPAddresses |
      Where-Object { $_ -match '^\d+\.\d+\.\d+\.\d+$' } | Select-Object -First 1
if (-not $ip) {
    $ip = Get-NetNeighbor -InterfaceAlias 'vEthernet (Default Switch)' -AddressFamily IPv4 -ErrorAction SilentlyContinue |
          Where-Object { $_.LinkLayerAddress -eq $UplinkMac } | Select-Object -ExpandProperty IPAddress -First 1
}
$ip
