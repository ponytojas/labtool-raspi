#!/bin/bash

# Eduroam Connection Script for Raspberry Pi
# This script automates the process of connecting to eduroam Wi-Fi network

# Exit on any error
set -e

# Check if script is run as root
if [[ $EUID -ne 0 ]]; then
   echo "This script must be run as root."
   echo "Please run: sudo $0"
   exit 1
fi

# Color codes for better readability
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}===== Eduroam Connection Script for Raspberry Pi =====${NC}"

# Function to prompt for user credentials
get_credentials() {
    read -p "Enter your username (format: usuario@uv.es): " username
    read -s -p "Enter your password: " password
    echo ""
    
    # Validate input
    if [[ -z "$username" || -z "$password" ]]; then
        echo -e "${RED}Error: Username and password cannot be empty.${NC}"
        exit 1
    fi
}

# Install required packages
install_packages() {
    echo -e "\n${YELLOW}Installing required packages...${NC}"
    apt-get update
    apt-get install -y wpa_supplicant pump net-tools wireless-tools
    echo -e "${GREEN}Packages installed successfully.${NC}"
}

# Detect wireless interface
detect_interface() {
    echo -e "\n${YELLOW}Detecting wireless interface...${NC}"
    wireless_interface=$(iw dev | grep Interface | awk '{print $2}')
    
    if [[ -z "$wireless_interface" ]]; then
        echo -e "${RED}Error: No wireless interface detected.${NC}"
        echo "Available network interfaces:"
        ip link show | grep -v "lo:" | grep "state" | awk -F: '{print $2}'
        read -p "Enter your wireless interface name manually: " wireless_interface
    else
        echo -e "${GREEN}Found wireless interface: ${wireless_interface}${NC}"
    fi
}

# Create WPA supplicant configuration
create_wpa_config() {
    echo -e "\n${YELLOW}Creating WPA supplicant configuration...${NC}"
    
    # Backup existing configuration if it exists
    if [[ -f /etc/wpa_supplicant/wpa_supplicant.conf ]]; then
        cp /etc/wpa_supplicant/wpa_supplicant.conf /etc/wpa_supplicant/wpa_supplicant.conf.backup
        echo "Backed up existing configuration to /etc/wpa_supplicant/wpa_supplicant.conf.backup"
    fi
    
    # Create new configuration
    cat > /etc/wpa_supplicant/wpa_supplicant.conf << EOF
# wpa_supplicant.conf para Eduroam
ctrl_interface=/var/run/wpa_supplicant
ap_scan=1
eapol_version=1

network={
    ssid="eduroam"
    key_mgmt=WPA-EAP
    proto=WPA2 WPA
    eap=TTLS
    pairwise=CCMP TKIP
    identity="${username}"
    password="${password}"
    priority=2
    phase2="auth=MSCHAPV2"
}
EOF

    # Set proper permissions
    chmod 600 /etc/wpa_supplicant/wpa_supplicant.conf
    echo -e "${GREEN}WPA supplicant configuration created with proper permissions.${NC}"
}

# Create systemd service for automatic connection
create_systemd_service() {
    echo -e "\n${YELLOW}Creating systemd service for automatic connection...${NC}"
    
    cat > /etc/systemd/system/wpa_supplicant@.service << EOF
[Unit]
Description=WPA supplicant for %I
Before=network.target
After=dbus.service
Wants=network.target

[Service]
Type=simple
ExecStart=/sbin/wpa_supplicant -c/etc/wpa_supplicant/wpa_supplicant.conf -i%I -Dnl80211,wext
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

    cat > /etc/systemd/system/pump@.service << EOF
[Unit]
Description=DHCP Client for %I
After=wpa_supplicant@%i.service
Wants=wpa_supplicant@%i.service

[Service]
Type=simple
ExecStart=/sbin/pump -i %I
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

    # Enable services
    systemctl enable wpa_supplicant@${wireless_interface}.service
    systemctl enable pump@${wireless_interface}.service
    
    echo -e "${GREEN}Systemd services created and enabled.${NC}"
}

# Connect to the network
connect_to_network() {
    echo -e "\n${YELLOW}Connecting to eduroam network...${NC}"
    
    # Stop any running wpa_supplicant processes
    pkill wpa_supplicant || true
    sleep 2
    
    # Start the wpa_supplicant service
    systemctl start wpa_supplicant@${wireless_interface}.service
    sleep 5
    
    # Start the DHCP client
    systemctl start pump@${wireless_interface}.service
    sleep 3
    
    # Check connection status
    if ping -c 1 -W 5 8.8.8.8 > /dev/null 2>&1; then
        echo -e "${GREEN}Successfully connected to eduroam!${NC}"
        echo "Network information:"
        ip addr show ${wireless_interface}
        echo "IP address:"
        hostname -I
    else
        echo -e "${RED}Could not establish a connection to the internet.${NC}"
        echo "Please check your credentials and try again."
        echo "You can manually run: sudo systemctl restart wpa_supplicant@${wireless_interface}.service"
    fi
}

# Create a convenience script for later use
create_convenience_script() {
    echo -e "\n${YELLOW}Creating convenience script for future use...${NC}"
    
    cat > /usr/local/bin/eduroam-connect << EOF
#!/bin/bash
# Quick eduroam reconnection script

if [[ \$EUID -ne 0 ]]; then
   echo "This script must be run as root."
   echo "Please run: sudo \$0"
   exit 1
fi

echo "Reconnecting to eduroam..."
systemctl restart wpa_supplicant@${wireless_interface}.service
sleep 3
systemctl restart pump@${wireless_interface}.service
sleep 2

if ping -c 1 -W 5 8.8.8.8 > /dev/null 2>&1; then
    echo "Successfully reconnected to eduroam!"
    echo "IP address: \$(hostname -I)"
else
    echo "Could not establish a connection to the internet."
    echo "Please check your configuration or run the full setup script again."
fi
EOF

    chmod +x /usr/local/bin/eduroam-connect
    echo -e "${GREEN}Created convenience script: /usr/local/bin/eduroam-connect${NC}"
}

# Main execution flow
main() {
    get_credentials
    install_packages
    detect_interface
    create_wpa_config
    create_systemd_service
    connect_to_network
    create_convenience_script
    
    echo -e "\n${GREEN}Setup complete!${NC}"
    echo "Your Raspberry Pi should now automatically connect to eduroam on boot."
    echo "If you need to reconnect manually, run: sudo eduroam-connect"
}

# Run the main function
main