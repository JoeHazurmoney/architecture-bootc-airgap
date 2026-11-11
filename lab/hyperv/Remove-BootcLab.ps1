#Requires -Modules Hyper-V
<#
.SYNOPSIS
  Removes ONLY the lab: VMs named bootc-lab-*, their folders under $LabRoot,
  and the Private "bootc-lab" switch. Nothing else is touched.
.EXAMPLE
  .\Remove-BootcLab.ps1            # asks before deleting
  .\Remove-BootcLab.ps1 -Force     # no prompt
  .\Remove-BootcLab.ps1 -KeepSwitch -Name bootc-lab-srv01   # one client only
#>
[CmdletBinding(SupportsShouldProcess, ConfirmImpact = 'High')]
param(
    [string[]]$Name,
    [string]$LabRoot = (Join-Path $env:USERPROFILE 'HyperV\bootc-lab'),
    [string]$SwitchName = 'bootc-lab',
    [switch]$KeepSwitch,
    [switch]$Force
)
$ErrorActionPreference = 'Stop'
if ($Force) { $ConfirmPreference = 'None' }

$vms = Get-VM | Where-Object { $_.Name -like 'bootc-lab-*' -and (-not $Name -or $Name -contains $_.Name) }
foreach ($vm in $vms) {
    if ($PSCmdlet.ShouldProcess($vm.Name, 'Stop and remove VM and its disks')) {
        $disks = Get-VMHardDiskDrive -VMName $vm.Name | Select-Object -ExpandProperty Path
        if ($vm.State -ne 'Off') { Stop-VM -Name $vm.Name -TurnOff -Force }
        Remove-VM -Name $vm.Name -Force
        $disks | Where-Object { $_ -like "$LabRoot*" } | ForEach-Object { Remove-Item $_ -Force }
        $dir = Join-Path $LabRoot $vm.Name
        if (Test-Path $dir) { Remove-Item $dir -Recurse -Force }
    }
}
if (-not $KeepSwitch -and -not $Name) {
    $sw = Get-VMSwitch -Name $SwitchName -ErrorAction SilentlyContinue
    if ($sw -and $sw.SwitchType -eq 'Private' -and $PSCmdlet.ShouldProcess($SwitchName, 'Remove Private switch')) {
        Remove-VMSwitch -Name $SwitchName -Force
    }
}
