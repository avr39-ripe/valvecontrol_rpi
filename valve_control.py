#!/usr/bin/env python

import RPi.GPIO as GPIO
from time import sleep
from daemon import runner
import yaml

import threading
import settings
import tornado.ioloop
import tornado.escape
import tornado.web

import os
import glob


class ValveControl():
    def _read_temp_raw(self):
        f = open(self.device_file, 'r')
        lines = f.readlines()
        f.close()
        return lines

    def read_temp(self):
        lines = self._read_temp_raw()
        while lines[0].strip()[-3:] != 'YES':
#            print "CRC ERROR!!!"
            sleep(0.2)
            lines = self._read_temp_raw()
        equals_pos = lines[1].find('t=')
        if equals_pos != -1:
            temp_string = lines[1][equals_pos + 2:]
            temp_c = float(temp_string) / 1000.0
#           temp_f = temp_c * 9.0 / 5.0 + 32.0
        return temp_c

    def __init__(self):
        os.system('modprobe w1-gpio')
        os.system('modprobe w1-therm')
        self.stdin_path = '/dev/null'
        self.stdout_path = '/dev/tty'
        self.stderr_path = '/dev/tty'
        self.pidfile_path = '/var/run/reletherm.pid'
        self.pidfile_timeout = 5
        self.base_dir = '/sys/bus/w1/devices/'
        self.device_folder = glob.glob(self.base_dir + '28*')[0]
        self.device_file = self.device_folder + '/w1_slave'
        self.config = dict(temp_set=21, temp_delta=0.5, delay=10, missed_delay=5, missed_stabilize_delay=15)
        self.curr_temp = 0
        self.last_temp = 0
        self.missed = False
        self.DEBUG = settings.DEBUG
        self.WARM = settings.WARM_GPIO
        self.COOL = settings.COOL_GPIO

        GPIO.cleanup()
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.WARM, GPIO.OUT, initial=True)
        GPIO.setup(self.COOL, GPIO.OUT, initial=True)

    def read_conf_file(self):
        f = open(settings.VALVE_CONTROL_CFG, 'r')
        self.config = yaml.safe_load(f)
        f.close()

    def in_range(self, temp):
        if (self.config['temp_set'] - self.config['temp_delta']) <= temp <= \
                (self.config['temp_set'] + self.config['temp_delta']):
            return True
        else:
            return False

    def above_range(self, temp):
        if temp > self.config['temp_set'] + self.config['temp_delta']:
            return True
        else:
            return False

    def below_range(self, temp):
        if temp < self.config['temp_set'] - self.config['temp_delta']:
            return True
        else:
            return False

    def is_missed(self):
        if self.below_range(self.last_temp) and self.above_range(self.curr_temp):
            if self.DEBUG:
                print "Missed above!"
            self.missed = True
            return True
        if self.above_range(self.last_temp) and self.below_range(self.curr_temp):
            if self.DEBUG:
                print "Missed below!"
            self.missed = True
            return True
        if self.in_range(self.last_temp) and not self.in_range(self.curr_temp):
            if self.DEBUG:
                print "Missed out!"
            self.missed = True
            return True
        return False

    def run(self):
        self.read_conf_file()

        ##START REST WEB
        rest_app_settings = {
            "template_path": settings.TEMPLATE_PATH,
            "static_path": settings.TEMPLATE_PATH,
            "debug": settings.DEBUG
        }
        rest_app = tornado.web.Application([
                                           (r"/", MainHandler, dict(valvecontroll=self)),
                                           (r"/config", ConfigHandler, dict(valvecontroll=self)),
                                           (r"/temp", TempHandler, dict(valvecontroll=self)),
                                           (r'/static/(.*)', tornado.web.StaticFileHandler),
                                           ], **rest_app_settings)

        rest_app.listen(8888)

        web_thread = threading.Thread(target=tornado.ioloop.IOLoop.instance().start)
        web_thread.start()
        ##
        self.curr_temp = self.read_temp()
        self.last_temp = self.curr_temp

        while True:
            self.curr_temp = self.read_temp()

            if self.below_range(self.curr_temp):
                if self.DEBUG:
                    print "Lower than temp_set=%r %r" % (self.config['temp_set'], self.curr_temp)
                GPIO.output(self.WARM, False)
                GPIO.output(self.COOL, True)
                if self.missed:
                    if self.DEBUG:
                        print "Missed is active so sleep a bit and off the valve!"
                    sleep(self.config['missed_delay'])
                    GPIO.output(self.WARM, True)

            if self.above_range(self.curr_temp):
                if self.DEBUG:
                    print "Higher than temp_set=%r %r" % (self.config['temp_set'], self.curr_temp)
                GPIO.output(self.COOL, False)
                GPIO.output(self.WARM, True)
                if self.missed:
                    if self.DEBUG:
                        print "Missed is active so sleep a bit and off the valve!"
                    sleep(self.config['missed_delay'])
                    GPIO.output(self.COOL, True)

            if self.in_range(self.curr_temp):
                if self.DEBUG:
                    print "set_temp REACHED! %r %r" % (self.config['temp_set'], self.curr_temp)
                GPIO.output(self.WARM, True)
                GPIO.output(self.COOL, True)
                self.missed = False

            if not self.missed:
                self.is_missed()
                sleep(self.config['delay'])
            else:
                sleep(self.config['missed_stabilize_delay'])

            self.last_temp = self.curr_temp


class MainHandler(tornado.web.RequestHandler):
    def initialize(self, valvecontroll):
        self.valvecontroll = valvecontroll

    def get(self):
        self.render('index.html')


class TempHandler(tornado.web.RequestHandler):
    def initialize(self, valvecontroll):
        self.valvecontroll = valvecontroll

    def get(self):
        output = tornado.escape.json_encode({'curr_temp': self.valvecontroll.curr_temp})
        self.set_header("Content-Type", "application/json")
        print output
        self.write(output)


class ConfigHandler(tornado.web.RequestHandler):
    def initialize(self, valvecontroll):
        self.valvecontroll = valvecontroll
        self.cfg = self.valvecontroll.config

    def get(self):
        output = tornado.escape.json_encode(self.valvecontroll.config)
        self.set_header("Content-Type", "application/json")
        print output
        self.write(output)

    def post(self):
        print "POST body %s " % self.request.body

        cf = tornado.escape.json_decode(self.request.body)
        self.cfg = dict((k, float(v)) for k, v in cf.iteritems())
        print self.cfg
        self.valvecontroll.config = self.cfg
        #        self.write(self.cfg)
        self.write(self.valvecontroll.config)


if __name__ == "__main__":
    vc = ValveControl()

    try:
        daemon_runner = runner.DaemonRunner(vc)
        daemon_runner.do_action()
    finally:
        print "Going down!!! ;()"
        ioloop = tornado.ioloop.IOLoop.instance()
        ioloop.add_callback(lambda x: x.stop(), ioloop)
