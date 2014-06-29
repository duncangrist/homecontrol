import smtplib
from email.mime.text import MIMEText
from config import * # import SMTP details


class PushNotifier(object):

	def __init__(self, host, port, user, password, fromAddr, to):
		self._port = port
		self._host = host
		self._user = user
		self._password = password
		self._from = fromAddr
		self._to = to

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
		self._notify('DETECTED MOVEMENT', 'PIR detector has registered movement')

	def onCarAbsent(self, sender, arg):
		self._notify('CAR LEFT', 'The car is gone!!')


push = PushNotifier(imapHost, imapPort, imapUser, imapPassword, notifyEmailFrom, notifyEmailTo)
push.onStartup()