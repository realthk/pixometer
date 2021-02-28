# pixometer
Custom component Pixometer sensor for Home Assistant

### Install
Clone this repo under ```custom_components```

eg.
```
cd [HA PATH]/custom_components
git clone https://github.com/realthk/pixometer.git
```
enter Pixometer username and password in secrets.yaml, restart Home Assistant and set sensor

```
sensor:
  - platform: pixometer
    username: !secret pixometer_username
    password: !secret pixometer_password
    scan_interval: 3600
```
