#Requires -Modules Hyper-V
<#
.SYNOPSIS
  VM path test: boots a bootc-image-builder disk (converted to VHDX) with a
  cloud-init NoCloud seed. This is the Hyper-V stand-in for KubeVirt +
  cloudInitNoCloud.
.DESCRIPTION
  1. On the PXE VM: ansible-playbook -i lab/inventory ansible/playbooks/image_disk.yml
     (writes /var/lib/bootc-build/output/server-stable/disk.vhdx)
  2. Copy disk.vhdx to this PC, e.g.
     scp -i lab/.lab-secrets/id_ed25519 labadmin@<pxe-uplink-ip>:/var/lib/bootc-build/output/server-stable/disk.vhdx lab/.media/bootc-vm.vhdx
  3. Run this script. It makes the seed ISO in the tools container and boots the VM on the lab switch.
#>
[CmdletBinding()]
param(
    [string]$Name = 'bootc-lab-vm01',
    [string]$SourceVhdx = (Join-Path $PSScriptRoot '..\.media\bootc-vm.vhdx'),
    [string]$LabRoot = (Join-Path $env:USERPROFILE 'HyperV\bootc-lab'),
    [string]$LabSwitch = 'bootc-lab',
    [string]$Ip = '10.77.0.110/24',
    [string]$Mac = '02007700006E',
    [int]$MemoryGB = 4
)
$ErrorActionPreference = 'Stop'
if (Get-VM -Name $Name -ErrorAction SilentlyContinue) { throw "VM '$Name' already exists." }
if (-not (Test-Path $SourceVhdx)) { throw "$SourceVhdx not found (see step 2 in the help)." }

$repo = Resolve-Path (Join-Path $PSScriptRoot '..\..')
$pub = (Get-Content (Join-Path $repo 'lab\.lab-secrets\id_ed25519.pub') -Raw).Trim()
$vmDir = Join-Path $LabRoot $Name
$seedDir = Join-Path $vmDir 'seed'
New-Item -ItemType Directory -Force -Path $seedDir | Out-Null
$macColon = ($Mac -split '(..)' | Where-Object { $_ }) -join ':'

# Same cloud-init shape KubeVirt's cloudInitNoCloud would hand the VM
Set-Content -Path (Join-Path $seedDir 'meta-data') -Value "instance-id: $Name-001`nlocal-hostname: $Name" -NoNewline
Set-Content -Path (Join-Path $seedDir 'user-data') -NoNewline -Value @"
#cloud-config
hostname: $Name
users:
  - name: labadmin
    groups: [wheel]
    sudo: "ALL=(ALL) NOPASSWD:ALL"
    lock_passwd: true
    ssh_authorized_keys:
      - $pub
"@
Set-Content -Path (Join-Path $seedDir 'network-config') -NoNewline -Value @"
version: 2
ethernets:
  lab:
    match:
      macaddress: "$($macColon.ToLower())"
    addresses: [$Ip]
"@

$engine = if (Get-Command docker -ErrorAction SilentlyContinue) { 'docker' } else { 'podman' }
& $engine run --rm -v "${vmDir}:/out" -w /out localhost/bootc-tools:latest `
    genisoimage -quiet -output seed.iso -volid cidata -joliet -rock seed/user-data seed/meta-data seed/network-config
if ($LASTEXITCODE -ne 0) { throw 'Seed ISO build failed.' }

$vhdx = Join-Path $vmDir "$Name.vhdx"
Copy-Item $SourceVhdx $vhdx
New-VM -Name $Name -Generation 2 -MemoryStartupBytes ($MemoryGB * 1GB) -VHDPath $vhdx `
       -SwitchName $LabSwitch -Path $LabRoot | Out-Null
Set-VM -Name $Name -ProcessorCount 2 -StaticMemory -AutomaticCheckpointsEnabled $false -AutomaticStopAction ShutDown
Set-VMNetworkAdapter -VMName $Name -StaticMacAddress $Mac
Add-VMDvdDrive -VMName $Name -Path (Join-Path $vmDir 'seed.iso')
Set-VMFirmware -VMName $Name -SecureBootTemplate 'MicrosoftUEFICertificateAuthority' `
               -FirstBootDevice (Get-VMHardDiskDrive -VMName $Name)
Start-VM -Name $Name
Write-Host "Started $Name. From the PXE VM: ssh labadmin@$($Ip.Split('/')[0])"
