# atd-irb-diff

Basic configs to demo the difference between IRB models using ATD network topology

How to use:

- Create Python3 virtual environment, activate it and install the requirements.
- Create ATD lab and unassign all configlets from all devices.
- Adjust `upload-configlet-settings.yml`
- Select the branch corresponding for the IRB model you are going to demo. (master branch is EVPN)
- Run `upload-configlets.py` to deploy the configs.

> ## This branch can be used to demo static flood list with direct routing
