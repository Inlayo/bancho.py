# -*- coding: utf-8 -*-

# app name
app_name = 'guweb'

# secret key
secret_key = 'changeme'

#hCaptcha settings:
hCaptcha_sitekey = 'changeme'
hCaptcha_secret = 'changeme'

# domain (used for api, avatar, etc)
domain = 'gulag.ca'

# max image size for avatars, in megabytes
max_image_size = 2

# mysql credentials
mysql = {
    'db': 'gulag',
    'host': 'localhost',
    'user': 'cmyui',
    'password': 'changeme',
}

redisDSN = f"redis://:REDIS_PASSWORD@localhost:6379/0"

# path to gulag root (must have leading and following slash)
path_to_gulag = '/path/to/gulag/'

# enable debug (disable when in production to improve performance)
debug = False

# disallowed names (hardcoded banned usernames)
disallowed_names = {
    'cookiezi', 'rrtyui',
    'hvick225', 'qsc20010'
}

# disallowed passwords (hardcoded banned passwords)
disallowed_passwords = {
    'password', 'minilamp'
}

# enable registration
registration = True

#Daum SMTP, IMAP Email
EmailVerifyKeyLength = 16
SentEmailTimeout = 300
SMTP_serverInfo = {"host": "smtp.daum.net", "port": 465}
IMAP_serverInfo = {"host": "imap.daum.net", "port": 993}
SenderEmail = ""
SenderEmailPassword = ""
DISCORD_EMAIL_LOG_WEBHOOK = ""

# social links (used throughout guweb)
github = 'https://github.com/varkaria/guweb'
discord_server = 'https://discord.com/invite/'
youtube = 'https://youtube.com/'
twitter = 'https://twitter.com/'
instagram = 'https://instagram.com/'
