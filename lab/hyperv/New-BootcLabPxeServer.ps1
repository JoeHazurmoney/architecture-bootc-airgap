#Requires -Modules Hyper-V
<#
.SYNOPSIS
  Creates the lab PXE / registry / build VM (AlmaLinux 10) from the media made
  by lab/prepare_pxe_vm.py.
.DESCRIPTION
  Gen2, Secure Boot (Microsoft UEFI CA template), 2 NICs:
    uplink  -> "Default Switch" (NAT; dnf and image pulls before the airgap)
    lab     -> "bootc-lab" Private switch, static 10.77.0.10 (from cloud-init)
  The script waits until Hyper-V reports the uplink IP, then prints the SSH command.
#>
[CmdletBinding()]
param(
    [string]$Name = 'bootc-lab-pxe',
    [string]$LabRoot = (Join-Path $env:USERPROFILE 'HyperV\bootc-lab'),
    [string]$MediaDir = (Join-Path $PSScriptRoot '..\.media'),
    [int]$DiskGB = 120,
    [int]$MemoryGB = 8,
    [int]$Cpu = 4,
    [string]$LabSwitch = 'bootc-lab',
    [string]$UplinkSwitch = 'Default Switch',
    [int]$WaitMinutes = 15
)
$ErrorActionPreference = 'Stop'

if (Get-VM -Name $Name -ErrorAction SilentlyContinue) {
    throw "VM '$Name' already exists. Remove it with Remove-BootcLab.ps1 first."
}
foreach ($sw in $LabSwitch, $UplinkSwitch) {
    if (-not (Get-VMSwitch -Name $sw -ErrorAction SilentlyContinue)) { throw "Switch '$sw' not found." }
}
$srcVhdx = Join-Path $MediaDir 'bootc-lab-pxe.vhdx'
$srcSeed = Join-Path $MediaDir 'bootc-lab-pxe-seed.iso'
foreach ($f in $srcVhdx, $srcSeed) {
    if (-not (Test-Path $f)) { throw "$f not found. Run: py lab/prepare_pxe_vm.py" }
}

$vmDir = Join-Path $LabRoot $Name
New-Item -ItemType Directory -Force -Path $vmDir | Out-Null
$vhdx = Join-Path $vmDir "$Name.vhdx"
$seed = Join-Path $vmDir "$Name-seed.iso"
Copy-Item $srcVhdx $vhdx
Copy-Item $srcSeed $seed
Resize-VHD -Path $vhdx -SizeBytes ($DiskGB * 1GB)

New-VM -Name $Name -Generation 2 -MemoryStartupBytes ($MemoryGB * 1GB) -VHDPath $vhdx `
       -SwitchName $UplinkSwitch -Path $LabRoot | Out-Null
Set-VM -Name $Name -ProcessorCount $Cpu -StaticMemory -AutomaticCheckpointsEnabled $false `
       -AutomaticStopAction ShutDown -Notes 'bootc airgap lab: PXE + registry + build host'
Get-VMNetworkAdapter -VMName $Name | Rename-VMNetworkAdapter -NewName 'uplink'
Set-VMNetworkAdapter -VMName $Name -Name 'uplink' -StaticMacAddress '02007700000A'
Add-VMNetworkAdapter -VMName $Name -Name 'lab' -SwitchName $LabSwitch -StaticMacAddress '020077000010'
Add-VMDvdDrive -VMName $Name -Path $seed
Set-VMFirmware -VMName $Name -SecureBootTemplate 'MicrosoftUEFICertificateAuthority' `
               -FirstBootDevice (Get-VMHardDiskDrive -VMName $Name)
Start-VM -Name $Name
Write-Host "Started $Name. Waiting for cloud-init to report the uplink IP (installs hyperv-daemons)..."

$deadline = (Get-Date).AddMinutes($WaitMinutes)
do {
    Start-Sleep -Seconds 10
    $ip = & (Join-Path $PSScriptRoot 'Get-BootcLabPxeIp.ps1') -Name $Name
} until ($ip -or (Get-Date) -gt $deadline)

if (-not $ip) {
    Write-Warning "No IP reported after $WaitMinutes min. Check the VM console (vmconnect localhost $Name)."
    exit 1
}
$key = Resolve-Path (Join-Path $PSScriptRoot '..\.lab-secrets\id_ed25519')
Write-Host "Uplink IP: $ip"
Write-Host "SSH:       ssh -i `"$key`" labadmin@$ip"
