from time import sleep
import pifacedigitalio
import event
import switch
import sys
import async
import time
import smtplib
from email.mime.text import MIMEText
from config import * # import SMTP details

req_version = (2,5)
cur_version = sys.version_info
print(cur_version)

PIN_INPUT_PARKED_DETECTOR = 0
PIN_INPUT_PIR_DETECTOR = 1
PIN_OUTPUT_TICK = 7
PIN_OUTPUT_PARKING_INDICATOR = 1
PIN_OUTPUT_FLOODLIGHT = 2

DURATION_DETECTING = 2
DURATION_DETECTED = 5
DURATION_LEAVING = 5
DURATION_FLOODLIGHT = 5

class ParkedState(object):
	ABSENT = 'Absent'
	DETECTING = 'Detecting'
	DETECTED = 'Detected'
	PARKED = 'Parked'
	LEAVING = 'Leaving'


class CarDetector(object):
	def __init__(self, pfd, parkedDetectorInputPin, durationDetecting, durationDetected, durationLeaving):
		self._pfd = pfd
		self._pin = parkedDetectorInputPin
		self._durationDetecting = durationDetecting
		self._durationDetected = durationDetected
		self._durationLeaving = durationLeaving

		self.carPresent = event.Event()
		self.carParked = event.Event()
		self.carLeft = event.Event()

		self._timeInState = 0
		self._lastWasParked = False

		self.state = ParkedState.PARKED if self._isDetected() else ParkedState.ABSENT

	def _onSensorPositive(self):
		for case in switch.switch(self.state):
			if case(ParkedState.ABSENT):
				self._transition(ParkedState.DETECTING)
				break
			if case(ParkedState.LEAVING):
				self._transition(ParkedState.PARKED)
				break

	def _onSensorNegative(self):
		for case in switch.switch(self.state):
			if case(ParkedState.DETECTING):
				self._transition(ParkedState.ABSENT)
				break
			if case(ParkedState.DETECTED):
				self._transition(ParkedState.ABSENT)
				break
			if case(ParkedState.PARKED):
				self._transition(ParkedState.LEAVING)
				break

	def _isDetected(self):
		return self._pfd.input_pins[self._pin].value

	def isParked(self):
		return self.state == ParkedState.PARKED

	def _transitionError(self, state):
		raise Exception('Cannot transition from ' + self.state + ' to ' + state)

	def _transition(self, state):
		print('Transition from ' + self.state + ' to ' + state)

		# ensure transition is valid
		for currState in switch.switch(self.state):
			if currState(ParkedState.ABSENT):
				if state != ParkedState.DETECTING:
					self._transitionError(state)
				break
			if currState(ParkedState.DETECTING):
				if state != ParkedState.ABSENT and state != ParkedState.DETECTED:
					self._transitionError(state)
				break
			if currState(ParkedState.DETECTED):
				if state != ParkedState.ABSENT and state != ParkedState.PARKED:
					self._transitionError(state)
				break
			if currState(ParkedState.PARKED):
				if state != ParkedState.LEAVING:
					self._transitionError(state)
				break
			if currState(ParkedState.LEAVING):
				if state != ParkedState.ABSENT and state != ParkedState.PARKED:
					self._transitionError(state)
				break
			if currState():
				self._transitionError(state)

		# transition to new state
		oldState = self.state
		self.state = state
		self._timeInState = 0

		if state == ParkedState.DETECTED:
			self.carPresent(self)
		if oldState == ParkedState.DETECTED and state == ParkedState.PARKED:
			self.carParked(self)
		if oldState == ParkedState.LEAVING and state == ParkedState.ABSENT:
			self.carLeft(self)

	def tick(self, elapsed):
		self._timeInState += elapsed
		parked = self._isDetected()
		if self._lastWasParked != parked:
			if parked:
				self._onSensorPositive()
			else:
				self._onSensorNegative()
			self._lastWasParked = parked

		for case in switch.switch(self.state):
			if case(ParkedState.DETECTING):
				if self._timeInState > self._durationDetecting:
					self._transition(ParkedState.DETECTED)
				break
			if case(ParkedState.DETECTED):
				if self._timeInState > self._durationDetected:
					self._transition(ParkedState.PARKED)
				break
			if case(ParkedState.LEAVING):
				if self._timeInState > self._durationLeaving:
					self._transition(ParkedState.ABSENT)
				break

class ParkingIndicator(object):
	def __init__(self, pfd, parkingIndicatorOutputPin):
		self._pin = parkingIndicatorOutputPin
		self._pfd = pfd

	def onCarPresent(self, sender, arg):
		# flash indicator several times
		self._shortFlashes(self, 10)


	def onCarParked(self, sender, arg):
		# flash indicator once (long pulse)
		self._longFlash(self)

	@async.Async
	def _longFlash(self):
		self._pfd.output_pins[self._pin].turn_on()
		sleep(2)
		self._pfd.output_pins[self._pin].turn_off()

	@async.Async
	def _shortFlashes(self, num):
		for i in range(num):
			self._pfd.output_pins[self._pin].turn_on()
			sleep(0.1)
			self._pfd.output_pins[self._pin].turn_off()
			sleep(0.1)

class MovementDetector(object):
	def __init__(self, pfd, pirDetectorPin):
		self._pin = pirDetectorPin
		self._pfd = pfd
		self._last = False
		self.movementDetected = event.Event()
		self.movementCeased = event.Event()

	def haveDetected(self):
		return self._pfd.input_pins[self._pin].value

	def tick(self, elapsed):
		detected = self.haveDetected()
		if self._last != detected:
			if detected:
				self.movementDetected(self)
			else:
				self.movementCeased(self)
			self._last = detected

class FloodLightController(object):
	def __init__(self, pfd, floodLightOutputPin, initialIsParked, initialMovementDetected, shineDuration):
		self._pin = floodLightOutputPin
		self._pfd = pfd
		self._shineDuration = shineDuration

		self._carParked = initialIsParked
		self._movementDetected = initialMovementDetected

		self._timeLightOn = 0
		self._lightOn = False

	def onCarParked(self, sender, arg):
		self._carParked = True

	def onCarAbsent(self, sender, arg):
		self._carParked = False

	def onMovementDetected(self, sender, arg):
		self._movementDetected = True

	def onMovementCeased(self, sender, arg):
		self._movementDetected = False

	def _changeLightState(self, state):
		if (state):
			self._pfd.output_pins[self._pin].turn_on()
		else:
			self._pfd.output_pins[self._pin].turn_off()

		self._lightOn = state

	def tick(self, elapsed):
		if self._movementDetected and self._carParked:
			self._timeLightOn = 0
			if not self._lightOn:
				self._changeLightState(True)

		if self._lightOn:
			self._timeLightOn += elapsed
			if self._timeLightOn > self._shineDuration or not self._carParked:
				self._changeLightState(False)


class Logger(object):
	def onMovementDetected(self, sender):
		print('onMovementDetected()')

	def onMovementCeased(self, sender):
		print('onMovementCeased()')

	def onCarParked(self, sender):
		print('onCarParked()')

	def onCarAbsent(self, sender):
		print('onCarAbsent()')


class PushNotifier(object):

	def __init__(self, host, port, user, password, fromAddr, to, initialIsParked):
		self._port = port
		self._host = host
		self._user = user
		self._password = password
		self._from = fromAddr
		self._to = to
		self._carParked = initialIsParked

	def _notify(self, subject, content):
		smtp = smtplib.SMTP_SSL(self._host, self._port)

		smtp.login(self._user, self._password)

		text = content
		msg = MIMEText(text)
		msg['Subject'] = subject
		msg['From'] = self._from
		msg['To'] = self._to
		try:
			smtp.sendmail(imapUser, [self._to], msg.as_string())
		finally:
			smtp.close()

	def onStartup(self):
		self._notify('STARTED UP', 'System has started')

	def onMovementDetected(self, sender, arg):
		if self._carParked:
			self._notify('DETECTED MOVEMENT', 'PIR detector has registered movement')

	def onCarParked(self, sender, arg):
		self._carParked = True

	def onCarAbsent(self, sender, arg):
		self._notify('CAR LEFT', 'The car is gone!!')
		self._carParked = False


pfd = pifacedigitalio.PiFaceDigital()

parkedTracker = CarDetector(pfd, PIN_INPUT_PARKED_DETECTOR, DURATION_DETECTING, DURATION_DETECTED, DURATION_LEAVING)
parkingIndicator = ParkingIndicator(pfd, PIN_OUTPUT_PARKING_INDICATOR)
movementDetector = MovementDetector(pfd, PIN_INPUT_PIR_DETECTOR)
floodLightController = FloodLightController(pfd, PIN_OUTPUT_FLOODLIGHT, parkedTracker.isParked(), movementDetector.haveDetected(), DURATION_FLOODLIGHT)
pushNotifier = PushNotifier(imapHost, imapPort, imapUser, imapPassword, notifyEmailFrom, notifyEmailTo, parkedTracker.isParked())
logger = Logger

parkedTracker.carPresent += parkingIndicator.onCarPresent
parkedTracker.carParked += parkingIndicator.onCarParked

parkedTracker.carParked += floodLightController.onCarParked
parkedTracker.carLeft += floodLightController.onCarAbsent
movementDetector.movementDetected += floodLightController.onMovementDetected
movementDetector.movementCeased += floodLightController.onMovementCeased

parkedTracker.carParked += logger.onCarParked
parkedTracker.carLeft += logger.onCarAbsent
movementDetector.movementDetected += logger.onMovementDetected
movementDetector.movementCeased += logger.onMovementCeased

parkedTracker.carParked += pushNotifier.onCarParked
parkedTracker.carLeft += pushNotifier.onCarAbsent
movementDetector.movementDetected += pushNotifier.onMovementDetected

print("Initial parked state is ", parkedTracker.state)

started = False

try:
	while True:
		# wait until ctrl-c
		tickRate = 0.2
		parkedTracker.tick(tickRate)
		movementDetector.tick(tickRate)
		floodLightController.tick(tickRate)
		sleep(tickRate)
		pfd.leds[PIN_OUTPUT_TICK].toggle()
		if not started:
			started = True
			pushNotifier.onStartup()

except KeyboardInterrupt:
	print('^C received, shutting down')