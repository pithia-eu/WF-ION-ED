#!/bin/bash

# Use cp to copy the file to /etc/systemd/system/
sudo cp wf-ion-ed.service /etc/systemd/system/

# Use systemctl to enable the service. It will start on boot.
sudo systemctl enable wf-ion-ed.service

# Use systemctl to start the service immediately
sudo systemctl start wf-ion-ed.service