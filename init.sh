#!/bin/bash
# Rat Rack Sensor Automated Setup Script
# Usage: sudo ./setup_sensor.sh [mqtt_broker] [mqtt_port] [mqtt_user] [mqtt_pass]


# https://filebrowser.ponytojas.dev/api/public/dl/tdHcGJfJ/home/labtool/init.sh
set -e

# Color codes for better readability
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${YELLOW}==== Rat Rack Sensor Installation Script ====${NC}"

# Check if running as root
if [ "$EUID" -ne 0 ]; then
  echo -e "${RED}Please run as root (with sudo)${NC}"
  exit 1
fi

# Check if variables were passed
if [ $# -lt 4 ]; then
  echo -e "${RED}Not enough arguments provided. Usage: sudo ./setup_sensor.sh [mqtt_broker] [mqtt_port] [mqtt_user] [mqtt_pass] [username]${NC}"
  exit 1
fi

# Handle command line arguments for MQTT configuration
MQTT_BROKER=${1}
MQTT_PORT=${2}
MQTT_USER=${3}
MQTT_PASS=${4}
USER=${5}

# Configuration
# Create an array of URLs to download
FILES_URL=(
  "https://filebrowser.ponytojas.dev/api/public/dl/ShsuxvHj/home/labtool/eduroam_setup.sh" 
  "https://filebrowser.ponytojas.dev/api/public/dl/IrvZ31rZ/home/labtool/ratsensor.py" 
  "https://filebrowser.ponytojas.dev/api/public/dl/B9vjkB3O/home/labtool/requirements.txt" 
  "https://filebrowser.ponytojas.dev/api/public/dl/66sl12FB/home/labtool/ratsensor.service"
)

# Create required directories
echo -e "${YELLOW}Creating directories...${NC}"
mkdir -p /etc/ratsensor
mkdir -p /var/log

# Install dependencies
echo -e "${YELLOW}Installing required packages...${NC}"
apt update
apt install -y python3-pip i2c-tools curl

echo -e "${YELLOW}Installing Python libraries...${NC}"
pip3 install paho-mqtt smbus2 psutil

# Enable I2C interface
echo -e "${YELLOW}Enabling I2C interface...${NC}"
if ! grep -q "^dtparam=i2c_arm=on" /boot/config.txt; then
  echo "dtparam=i2c_arm=on" >> /boot/config.txt
  echo -e "${YELLOW}I2C enabled. A reboot will be required.${NC}"
  REBOOT_NEEDED=true
else
  echo -e "${GREEN}I2C already enabled.${NC}"
fi

# Download files
echo -e "${YELLOW}Downloading required files...${NC}"
for url in "${FILES_URL[@]}"; do
  # Extract filename from URL
  filename=$(basename "$url" | cut -d'/' -f1)
  echo "Downloading $filename from $url..."
  wget "$url"
  if [ $? -ne 0 ]; then
    echo -e "${RED}Error downloading $url.${NC}"
    exit 1
  fi
done

chmod +x /home/$USER/eduroam_setup.sh
chmod +x /home/$USER/ratsensor.py

# Create MQTT configuration file
echo -e "${YELLOW}Configuring MQTT...${NC}"
cat > /etc/ratsensor/mqtt_config.env << EOF
# MQTT Broker Configuration
MQTT_BROKER=${MQTT_BROKER}
MQTT_PORT=${MQTT_PORT}
MQTT_USER=${MQTT_USER}
MQTT_PASS=${MQTT_PASS}
# Enable simulation mode for testing
SIMULATION_MODE=True
EOF

# Copy systemd service file
echo -e "${YELLOW}Setting up systemd service...${NC}"
cp /home/$USER/ratsensor.service /etc/systemd/system/

# Enable and start the service
echo -e "${YELLOW}Enabling and starting service...${NC}"
systemctl enable ratsensor.service
systemctl start ratsensor.service

# Configure Wi-Fi if needed
if [ -f /home/$USER/eduroam_setup.sh ]; then
  echo -e "${YELLOW}Would you like to configure Wi-Fi? (y/n)${NC}"
  read -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    /home/$USER/eduroam_setup.sh
  fi
fi

echo -e "${GREEN}====== Installation Complete ======${NC}"
echo "Sensor is running in simulation mode for testing."
echo "To disable simulation mode, edit /etc/ratsensor/mqtt_config.env"
echo "Check logs with: tail -f /var/log/ratsensor.log"
echo "Service status: systemctl status ratsensor"

if [ "$REBOOT_NEEDED" = true ]; then
  echo -e "${YELLOW}A reboot is required for I2C changes to take effect.${NC}"
  read -p "Reboot now? (y/n): " -n 1 -r
  echo
  if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Rebooting..."
    reboot
  else
    echo "Please reboot manually when convenient."
  fi
fi