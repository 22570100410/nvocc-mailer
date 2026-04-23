import os

# 登录账号（固定）
LOGIN_USERNAME = os.getenv('LOGIN_USERNAME', 'admin')
LOGIN_PASSWORD = os.getenv('LOGIN_PASSWORD', 'Miluo@2026')

# Flask
SECRET_KEY = os.getenv('SECRET_KEY', 'nvocc-mailer-2026-secret-key')

# 数据库
DB_HOST     = os.getenv('DB_HOST', '127.0.0.1')
DB_PORT     = int(os.getenv('DB_PORT', 3306))
DB_NAME     = os.getenv('DB_NAME', 'nvocc_mailer')
DB_USER     = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD', '22570100410')

# SMTP
SMTP_HOST      = os.getenv('SMTP_HOST', 'smtp.qq.com')
SMTP_PORT      = int(os.getenv('SMTP_PORT', 465))
SMTP_USER      = os.getenv('SMTP_USER', '464197787@qq.com')
SMTP_PASSWORD  = os.getenv('SMTP_PASSWORD', 'sgpodacqbqprcaaj')
SMTP_FROM_NAME = os.getenv('SMTP_FROM_NAME', '航交所')
SMTP_USE_SSL   = os.getenv('SMTP_USE_SSL', 'true').lower() == 'true'  # True=465端口SSL, False=587端口STARTTLS

# IMAP（退信检测，账号与 SMTP 相同）
IMAP_HOST    = os.getenv('IMAP_HOST', 'imap.qq.com')
IMAP_PORT    = int(os.getenv('IMAP_PORT', 993))
IMAP_USE_SSL = os.getenv('IMAP_USE_SSL', 'true').lower() == 'true'
