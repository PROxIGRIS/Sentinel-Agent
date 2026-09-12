import wmi
c = wmi.WMI()
components = []
uuid_val = c.Win32_ComputerSystemProduct()[0].UUID
components.append(uuid_val.strip() if uuid_val else 'unknown')
disk_val = c.Win32_DiskDrive()[0].SerialNumber
components.append(disk_val.strip() if disk_val else 'unknown')
mac_val = None
for adapter in c.Win32_NetworkAdapter(PhysicalAdapter=True):
    if adapter.MACAddress:
        mac_val = adapter.MACAddress
        break
components.append(mac_val.strip() if mac_val else 'unknown')
print('PYTHON COMPONENTS:', components)
