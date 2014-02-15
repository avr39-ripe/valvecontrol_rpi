import os
DEBUG = True
DIRNAME = os.path.dirname(__file__)
STATIC_PATH = os.path.join(DIRNAME, 'static')
TEMPLATE_PATH = os.path.join(DIRNAME, 'template')
WARM_GPIO = 24
COOL_GPIO = 23
VALVE_CONTROL_CFG = os.path.join(DIRNAME, 'valvecontrol.cfg')
