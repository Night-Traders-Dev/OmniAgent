import subprocess
import sys

# Define your ports (SSH: 22, Server: 5199, 8100)
ports = [22, 5199, 8100]

def run_cmd(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True)

try:
    # 1. Get current WSL IP
    wsl_ip = subprocess.check_output(["wsl", "hostname", "-I"]).decode().strip().split()[0]
    print(f"[*] Detected WSL IP: {wsl_ip}")

    for port in ports:
        print(f"[*] Configuring Port {port}...")

        # 2. Remove stale Netsh Proxy & Firewall Rules
        # Removing first ensures a clean state regardless of previous IPs
        run_cmd(f"netsh interface portproxy delete v4tov4 listenport={port} listenaddress=0.0.0.0")
        run_cmd(f"netsh advfirewall firewall delete rule name='WSL LAN {port}'")

        # 3. Add New Netsh Proxy
        # Redirects traffic from Windows (0.0.0.0:port) to WSL (wsl_ip:port)
        add_proxy = run_cmd(f"netsh interface portproxy add v4tov4 listenport={port} listenaddress=0.0.0.0 connectport={port} connectaddress={wsl_ip}")
        
        # 4. Add Windows Firewall Rule
        # Allows external LAN devices to hit the Windows host on this port
        add_firewall = run_cmd(f"netsh advfirewall firewall add rule name='WSL LAN {port}' dir=in action=allow protocol=TCP localport={port}")

        if add_proxy.returncode == 0 and add_firewall.returncode == 0:
            print(f"    [+] Successfully proxied and broadcasted.")
        else:
            print(f"    [!] Failed to set rules for port {port}. Check Admin rights.")

except Exception as e:
    print(f"Error: {e}")
    print("\n[!] Ensure you run this script as an ADMINISTRATOR.")
