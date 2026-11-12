#Requires -Modules Hyper-V
<#
.SYNOPSIS
  Creates a blank lab client that network-boots (PXE) from the lab PXE server.
.DESCRIPTION
  Gen2 + Secure Boot (Microsoft UEFI CA, so shim -> GRUB -> kernel is checked),
  network first in the boot order, a static MAC that matches bootc_pxe_hosts in
  lab/inventory/group_vars/pxe_servers.yml, and an empty disk. GRUB's per-MAC
  file then installs the right profile with no keyboard input. Once installed,
  the same network boot falls through to the local disk.
.EXAMPLE
  .\New-BootcLabClient.ps1 -Profile server
  .\New-BootcLabClient.ps1 -Profile workstation
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][ValidateSet('server', 'workstation', 'rpm')][string]$Profile,
    [string]$Name,
    [string]$Mac,
    [int]$MemoryGB,
    [int]$Cpu = 2,
    [int]$DiskGB = 60,
    [string]$LabRoot = (Join-Path $env:USERPROFILE 'HyperV\bootc-lab'),
    [string]$LabSwitch = 'bootc-lab',
    [switch]$NoStart
)
$ErrorActionPreference = 'Stop'

$defaults = @{
    server      = @{ Name = 'bootc-lab-srv01'; Mac = '020077000065'; MemoryGB = 4 }
    workstation = @{ Name = 'bootc-lab-ws01';  Mac = '020077000066'; MemoryGB = 6 }
    # STIG comparison host, installed the traditional RPM way (lab_rpm_host.yml)
    rpm         = @{ Name = 'bootc-lab-rpm01'; Mac = '020077000067'; MemoryGB = 4 }
}
if (-not $Name)     { $Name = $defaults[$Profile].Name }
if (-not $Mac)      { $Mac = $defaults[$Profile].Mac }
if (-not $MemoryGB) { $MemoryGB = $defaults[$Profile].MemoryGB }

if (Get-VM -Name $Name -ErrorAction SilentlyContinue) { throw "VM '$Name' already exists." }
$sw = Get-VMSwitch -Name $LabSwitch -ErrorAction SilentlyContinue
if (-not $sw -or $sw.SwitchType -ne 'Private') { throw "Private switch '$LabSwitch' not found. Run New-BootcLabNetwork.ps1." }

$vmDir = Join-Path $LabRoot $Name
New-Item -ItemType Directory -Force -Path $vmDir | Out-Null
$vhdx = Join-Path $vmDir "$Name.vhdx"
New-VHD -Path $vhdx -SizeBytes ($DiskGB * 1GB) -Dynamic | Out-Null

New-VM -Name $Name -Generation 2 -MemoryStartupBytes ($MemoryGB * 1GB) -VHDPath $vhdx `
       -SwitchName $LabSwitch -Path $LabRoot | Out-Null
Set-VM -Name $Name -ProcessorCount $Cpu -StaticMemory -AutomaticCheckpointsEnabled $false `
       -AutomaticStopAction ShutDown -Notes "bootc airgap lab client ($Profile)"
Set-VMNetworkAdapter -VMName $Name -StaticMacAddress $Mac
Set-VMFirmware -VMName $Name -SecureBootTemplate 'MicrosoftUEFICertificateAuthority' `
               -FirstBootDevice (Get-VMNetworkAdapter -VMName $Name)

if (-not $NoStart) { Start-VM -Name $Name }
Write-Host "Created $Name ($Profile, MAC $Mac). Watch it with: vmconnect localhost $Name"
