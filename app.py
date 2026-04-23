import os
import uuid
import re
import csv
import io
import json
import poplib
import email as email_lib
import smtplib
import threading
from datetime import datetime
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr, formatdate
from functools import wraps

import pymysql
import pandas as pd
from flask import (Flask, render_template, request, redirect,
                   url_for, session, jsonify, flash)

import config

app = Flask(__name__)
app.secret_key = config.SECRET_KEY

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def migrate_db():
    """自动补充新字段，兼容旧版本数据库"""
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA=%s AND TABLE_NAME='send_record' AND COLUMN_NAME='extra_data'",
                (config.DB_NAME,),
            )
            if cur.fetchone()['cnt'] == 0:
                cur.execute('ALTER TABLE send_record ADD COLUMN extra_data TEXT')
        db.commit()
    finally:
        db.close()


def check_interrupted_batches():
    """启动时将卡在 sending 状态的批次标为 interrupted（上次程序异常退出导致）"""
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute("UPDATE send_batch SET status='interrupted' WHERE status='sending'")
        db.commit()
    finally:
        db.close()


# ── 数据库 ────────────────────────────────────────────────────
def get_db():
    return pymysql.connect(
        host=config.DB_HOST,
        port=config.DB_PORT,
        user=config.DB_USER,
        password=config.DB_PASSWORD,
        database=config.DB_NAME,
        charset='utf8mb4',
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=False,
        init_command="SET time_zone='+08:00'",
    )


# ── 登录守卫 ──────────────────────────────────────────────────
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


# ── 认证 ──────────────────────────────────────────────────────
@app.route('/')
def index():
    return redirect(url_for('compose') if session.get('logged_in') else url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    error = None
    if request.method == 'POST':
        if (request.form.get('username') == config.LOGIN_USERNAME and
                request.form.get('password') == config.LOGIN_PASSWORD):
            session['logged_in'] = True
            return redirect(url_for('compose'))
        error = '用户名或密码错误'
    return render_template('login.html', error=error)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# ── 发件主页 ──────────────────────────────────────────────────
@app.route('/compose')
@login_required
def compose():
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute('SELECT id, name, updated_at FROM draft ORDER BY updated_at DESC')
            drafts = cur.fetchall()
    finally:
        db.close()
    return render_template('compose.html', drafts=drafts)


# ── 文件上传 ──────────────────────────────────────────────────
@app.route('/upload', methods=['POST'])
@login_required
def upload():
    f = request.files.get('file')
    if not f or not f.filename:
        return jsonify({'error': '未上传文件'}), 400

    ext = f.filename.rsplit('.', 1)[-1].lower()
    if ext not in ('xlsx', 'xls', 'csv'):
        return jsonify({'error': '仅支持 Excel（xlsx/xls）或 CSV 文件'}), 400

    filename = f'{uuid.uuid4().hex}.{ext}'
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    f.save(filepath)

    try:
        df = pd.read_csv(filepath) if ext == 'csv' else pd.read_excel(filepath)
        columns = [str(c) for c in df.columns.tolist()]
        preview = df.head(3).fillna('').astype(str).values.tolist()
        session['upload_file'] = filename
        session['upload_ext'] = ext
        return jsonify({'columns': columns, 'preview': preview, 'filename': f.filename})
    except Exception as e:
        os.remove(filepath)
        return jsonify({'error': f'文件解析失败：{e}'}), 400


# ── 草稿 ──────────────────────────────────────────────────────
@app.route('/draft/list')
@login_required
def draft_list():
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute('SELECT id, name, updated_at FROM draft ORDER BY updated_at DESC')
            rows = cur.fetchall()
        for r in rows:
            if isinstance(r.get('updated_at'), datetime):
                r['updated_at'] = r['updated_at'].strftime('%Y-%m-%d %H:%M')
        return jsonify(rows)
    finally:
        db.close()


@app.route('/draft/<int:draft_id>')
@login_required
def get_draft(draft_id):
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute('SELECT id, name, subject, body FROM draft WHERE id=%s', (draft_id,))
            row = cur.fetchone()
        return jsonify(row) if row else (jsonify({'error': '草稿不存在'}), 404)
    finally:
        db.close()


@app.route('/draft/save', methods=['POST'])
@login_required
def save_draft():
    data = request.json or {}
    name    = data.get('name', '').strip()
    subject = data.get('subject', '').strip()
    body    = data.get('body', '').strip()
    did     = data.get('id')

    if not name:
        return jsonify({'error': '草稿名称不能为空'}), 400

    db = get_db()
    try:
        with db.cursor() as cur:
            if did:
                cur.execute(
                    'UPDATE draft SET name=%s, subject=%s, body=%s, updated_at=NOW() WHERE id=%s',
                    (name, subject, body, did),
                )
            else:
                cur.execute(
                    'INSERT INTO draft (name, subject, body, created_at, updated_at) VALUES (%s,%s,%s,NOW(),NOW())',
                    (name, subject, body),
                )
                did = cur.lastrowid
        db.commit()
        return jsonify({'id': did, 'name': name})
    finally:
        db.close()


@app.route('/draft/<int:draft_id>', methods=['DELETE'])
@login_required
def delete_draft(draft_id):
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute('DELETE FROM draft WHERE id=%s', (draft_id,))
        db.commit()
        return jsonify({'ok': True})
    finally:
        db.close()


# ── 发送 ──────────────────────────────────────────────────────
@app.route('/send', methods=['POST'])
@login_required
def send():
    data      = request.json or {}
    email_col = data.get('email_col', '').strip()
    company_col = data.get('company_col', '').strip()
    subject   = data.get('subject', '').strip()
    body      = data.get('body', '').strip()

    if not email_col:
        return jsonify({'error': '请选择邮箱列'}), 400
    if not subject:
        return jsonify({'error': '邮件主题不能为空'}), 400
    if not body:
        return jsonify({'error': '邮件正文不能为空'}), 400

    upload_file = session.get('upload_file')
    upload_ext  = session.get('upload_ext')
    if not upload_file:
        return jsonify({'error': '请先上传名单文件'}), 400

    filepath = os.path.join(UPLOAD_FOLDER, upload_file)
    if not os.path.exists(filepath):
        return jsonify({'error': '文件已失效，请重新上传'}), 400

    try:
        df = pd.read_csv(filepath) if upload_ext == 'csv' else pd.read_excel(filepath)
        df = df.fillna('')
        if email_col not in df.columns:
            return jsonify({'error': f'列 "{email_col}" 不存在'}), 400

        seen = set()
        recipients = []
        for _, row in df.iterrows():
            email   = str(row[email_col]).strip()
            company = str(row[company_col]).strip() if company_col and company_col in df.columns else ''
            if email and '@' in email and email not in seen:
                seen.add(email)
                extra = {str(k): str(v) for k, v in row.items()}
                recipients.append({'email': email, 'company': company, 'extra': extra})

        if not recipients:
            return jsonify({'error': '未找到有效的邮箱地址'}), 400
    except Exception as e:
        return jsonify({'error': f'文件读取失败：{e}'}), 400

    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                'INSERT INTO send_batch (subject, body, total_count, success_count, fail_count, status, created_at) '
                'VALUES (%s,%s,%s,0,0,"sending",NOW())',
                (subject, body, len(recipients)),
            )
            batch_id = cur.lastrowid
            cur.executemany(
                'INSERT INTO send_record (batch_id, company, email, status, extra_data) VALUES (%s,%s,%s,"pending",%s)',
                [(batch_id, r['company'], r['email'], json.dumps(r['extra'], ensure_ascii=False)) for r in recipients],
            )
        db.commit()
    finally:
        db.close()

    t = threading.Thread(target=_do_send, args=(batch_id, recipients, subject, body), daemon=True)
    t.start()

    return jsonify({'batch_id': batch_id})


def _do_send(batch_id, recipients, subject, body):
    # 从数据库读当前计数，支持中断后恢复续发
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute('SELECT success_count, fail_count FROM send_batch WHERE id=%s', (batch_id,))
            row = cur.fetchone()
        success = row['success_count'] if row else 0
        fail    = row['fail_count']    if row else 0
    finally:
        db.close()

    smtp_conn = None

    def connect():
        if config.SMTP_USE_SSL:
            conn = smtplib.SMTP_SSL(config.SMTP_HOST, config.SMTP_PORT, timeout=10)
        else:
            conn = smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10)
            conn.ehlo()
            conn.starttls()
            conn.ehlo()
        conn.login(config.SMTP_USER, config.SMTP_PASSWORD)
        return conn

    try:
        smtp_conn = connect()
    except Exception as e:
        db = get_db()
        try:
            with db.cursor() as cur:
                cur.execute(
                    'UPDATE send_record SET status="failed", error_msg=%s, sent_at=NOW() WHERE batch_id=%s',
                    (str(e)[:500], batch_id),
                )
                cur.execute(
                    'UPDATE send_batch SET fail_count=%s, status="done", finished_at=NOW() WHERE id=%s',
                    (len(recipients), batch_id),
                )
            db.commit()
        finally:
            db.close()
        return

    for r in recipients:
        email   = r['email']
        company = r['company']
        text    = body.replace('{company}', company)
        error_msg = None

        try:
            msg = MIMEText(text, 'html', 'utf-8')
            msg['Subject'] = Header(subject, 'utf-8')
            msg['From']    = formataddr((config.SMTP_FROM_NAME, config.SMTP_USER))
            msg['To']      = email
            msg['Date']    = formatdate(localtime=True)

            try:
                smtp_conn.sendmail(config.SMTP_USER, [email], msg.as_string())
            except smtplib.SMTPServerDisconnected:
                smtp_conn = connect()
                smtp_conn.sendmail(config.SMTP_USER, [email], msg.as_string())

            status = 'success'
            success += 1
        except Exception as e:
            status    = 'failed'
            error_msg = str(e)[:500]
            fail += 1

        db = get_db()
        try:
            with db.cursor() as cur:
                cur.execute(
                    'UPDATE send_record SET status=%s, error_msg=%s, sent_at=NOW() '
                    'WHERE batch_id=%s AND email=%s AND status="pending"',
                    (status, error_msg, batch_id, email),
                )
                cur.execute(
                    'UPDATE send_batch SET success_count=%s, fail_count=%s WHERE id=%s',
                    (success, fail, batch_id),
                )
            db.commit()
        finally:
            db.close()

        # 每封发完后查数据库，检查是否被请求暂停
        db = get_db()
        try:
            with db.cursor() as cur:
                cur.execute('SELECT status FROM send_batch WHERE id=%s', (batch_id,))
                row = cur.fetchone()
        finally:
            db.close()
        if row and row['status'] == 'paused':
            try:
                smtp_conn.quit()
            except Exception:
                pass
            return

    try:
        smtp_conn.quit()
    except Exception:
        pass

    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                'UPDATE send_batch SET status="done", finished_at=NOW() WHERE id=%s',
                (batch_id,),
            )
        db.commit()
    finally:
        db.close()


@app.route('/send/<int:batch_id>/status')
@login_required
def send_status(batch_id):
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute('SELECT * FROM send_batch WHERE id=%s', (batch_id,))
            batch = cur.fetchone()
            cur.execute(
                'SELECT company, email, status, error_msg, sent_at FROM send_record WHERE batch_id=%s ORDER BY id',
                (batch_id,),
            )
            records = cur.fetchall()

        def fmt(obj):
            for k, v in obj.items():
                if isinstance(v, datetime):
                    obj[k] = v.strftime('%Y-%m-%d %H:%M:%S')
            return obj

        if batch:
            fmt(batch)
        for r in records:
            fmt(r)

        return jsonify({'batch': batch, 'records': records})
    finally:
        db.close()


# ── 历史记录 ──────────────────────────────────────────────────
@app.route('/history')
@login_required
def history():
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute('SELECT * FROM send_batch ORDER BY created_at DESC')
            batches = cur.fetchall()
        return render_template('history.html', batches=batches)
    finally:
        db.close()


@app.route('/history/<int:batch_id>')
@login_required
def batch_detail(batch_id):
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute('SELECT * FROM send_batch WHERE id=%s', (batch_id,))
            batch = cur.fetchone()
            cur.execute('SELECT * FROM send_record WHERE batch_id=%s ORDER BY id', (batch_id,))
            records = cur.fetchall()
        if not batch:
            flash('记录不存在')
            return redirect(url_for('history'))
        return render_template('batch_detail.html', batch=batch, records=records)
    finally:
        db.close()


@app.route('/history/<int:batch_id>/retry', methods=['POST'])
@login_required
def retry_batch(batch_id):
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute('SELECT * FROM send_batch WHERE id=%s', (batch_id,))
            batch = cur.fetchone()
            cur.execute(
                'SELECT company, email, extra_data FROM send_record WHERE batch_id=%s AND status="failed"',
                (batch_id,),
            )
            failed = cur.fetchall()

        if not batch or not failed:
            return jsonify({'error': '无失败记录'}), 400

        with db.cursor() as cur:
            cur.execute(
                'INSERT INTO send_batch (subject, body, total_count, success_count, fail_count, status, created_at) '
                'VALUES (%s,%s,%s,0,0,"sending",NOW())',
                (batch['subject'], batch['body'], len(failed)),
            )
            new_batch_id = cur.lastrowid
            cur.executemany(
                'INSERT INTO send_record (batch_id, company, email, status, extra_data) VALUES (%s,%s,%s,"pending",%s)',
                [(new_batch_id, r['company'], r['email'], r['extra_data']) for r in failed],
            )
        db.commit()
    finally:
        db.close()

    recipients = [{'email': r['email'], 'company': r['company']} for r in failed]
    t = threading.Thread(
        target=_do_send,
        args=(new_batch_id, recipients, batch['subject'], batch['body']),
        daemon=True,
    )
    t.start()

    return jsonify({'batch_id': new_batch_id})


@app.route('/history/<int:batch_id>/pause', methods=['POST'])
@login_required
def pause_batch(batch_id):
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute(
                'UPDATE send_batch SET status="paused" WHERE id=%s AND status="sending"',
                (batch_id,),
            )
        db.commit()
    finally:
        db.close()
    return jsonify({'ok': True})


@app.route('/history/<int:batch_id>/resume', methods=['POST'])
@login_required
def resume_batch(batch_id):
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute('SELECT * FROM send_batch WHERE id=%s', (batch_id,))
            batch = cur.fetchone()
            cur.execute(
                'SELECT company, email FROM send_record WHERE batch_id=%s AND status="pending"',
                (batch_id,),
            )
            pending = cur.fetchall()

        if not batch or batch['status'] not in ('interrupted', 'paused'):
            return jsonify({'error': '该批次不是暂停或中断状态'}), 400
        if not pending:
            return jsonify({'error': '无待发送记录（可能已全部完成）'}), 400

        with db.cursor() as cur:
            cur.execute(
                'UPDATE send_batch SET status="sending" WHERE id=%s',
                (batch_id,),
            )
        db.commit()
    finally:
        db.close()

    recipients = [{'email': r['email'], 'company': r['company']} for r in pending]
    t = threading.Thread(
        target=_do_send,
        args=(batch_id, recipients, batch['subject'], batch['body']),
        daemon=True,
    )
    t.start()

    return jsonify({'batch_id': batch_id})


def _extract_email_body(msg):
    body = ''
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() in ('text/plain', 'text/html'):
                try:
                    body += part.get_payload(decode=True).decode('utf-8', errors='ignore')
                except Exception:
                    pass
    else:
        try:
            body = msg.get_payload(decode=True).decode('utf-8', errors='ignore')
        except Exception:
            pass
    return body


def check_bounces_for_batch(batch_id):
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute('SELECT * FROM send_batch WHERE id=%s', (batch_id,))
            batch = cur.fetchone()
            cur.execute(
                'SELECT email FROM send_record WHERE batch_id=%s AND status="success"',
                (batch_id,),
            )
            success_emails = {r['email'].lower() for r in cur.fetchall()}
    finally:
        db.close()

    if not batch:
        raise ValueError('批次不存在')
    if not success_emails:
        return 0

    from email.utils import parsedate_to_datetime
    batch_start = batch['created_at']
    bounced = {}

    if config.POP3_USE_SSL:
        mail = poplib.POP3_SSL(config.POP3_HOST, config.POP3_PORT)
    else:
        mail = poplib.POP3(config.POP3_HOST, config.POP3_PORT)

    try:
        mail.user(config.SMTP_USER)
        mail.pass_(config.SMTP_PASSWORD)

        num_messages = len(mail.list()[1])

        for i in range(num_messages, 0, -1):
            # 先只拉头部
            try:
                _, lines, _ = mail.top(i, 0)
            except Exception:
                continue
            hdr = email_lib.message_from_bytes(b'\n'.join(lines))

            date_str = hdr.get('Date', '')
            try:
                mail_time = parsedate_to_datetime(date_str)
                if mail_time.timestamp() < batch_start.timestamp():
                    continue  # 跳过早于本批次的邮件
            except Exception:
                pass

            from_header = hdr.get('From', '')
            if 'postmaster' not in from_header.lower() and 'mailer-daemon' not in from_header.lower():
                continue

            # 确认是退信，拉完整邮件
            try:
                _, lines, _ = mail.retr(i)
            except Exception:
                continue
            msg = email_lib.message_from_bytes(b'\n'.join(lines))
            body = _extract_email_body(msg)

            # 英文退信格式：<email@domain.com>: ...（必须在 HTML 剥离前匹配，否则尖括号会被删）
            for m in re.findall(r'<(\S+@\S+\.\S+)>:', body):
                addr = m.strip().lower()
                if addr in success_emails and addr not in bounced:
                    reason_match = re.search(r'<' + re.escape(m.strip()) + r'>:\s*(.+?)(?:\n|$)', body)
                    reason = reason_match.group(1).strip()[:200] if reason_match else '退信'
                    bounced[addr] = reason

            # 剥离 HTML 标签，处理中文格式退信（QQ 等）
            plain = re.sub(r'<[^>]+>', ' ', body)
            plain = re.sub(r'&[a-z]+;', ' ', plain)

            # 中文退信格式
            for m in re.findall(r'无法发送到\s+(\S+@\S+)', plain):
                addr = m.strip('.,;()<>').lower()
                if addr in success_emails and addr not in bounced:
                    reason_match = re.search(r'收件人[（(]\S+[）)]\s*(.+?)(?:\n|。|$)', plain)
                    reason = reason_match.group(1).strip()[:200] if reason_match else '退信'
                    bounced[addr] = reason

            # 通用英文格式兜底
            for m in re.findall(r'(?:recipient|to|failed recipient)[:\s]+<?(\S+@\S+\.\S+)>?', plain, re.IGNORECASE):
                addr = m.strip('.,;()<>').lower()
                if addr in success_emails and addr not in bounced:
                    bounced[addr] = '退信'
    finally:
        try:
            mail.quit()
        except Exception:
            pass

    if not bounced:
        return 0

    db = get_db()
    try:
        with db.cursor() as cur:
            for addr, reason in bounced.items():
                cur.execute(
                    'UPDATE send_record SET status="bounced", error_msg=%s '
                    'WHERE batch_id=%s AND email=%s AND status="success"',
                    (reason, batch_id, addr),
                )
            cur.execute(
                'UPDATE send_batch SET success_count = success_count - %s WHERE id = %s',
                (len(bounced), batch_id),
            )
        db.commit()
    finally:
        db.close()

    return len(bounced)


@app.route('/history/<int:batch_id>/check_bounces', methods=['POST'])
@login_required
def check_bounces(batch_id):
    try:
        count = check_bounces_for_batch(batch_id)
        return jsonify({'bounced': count})
    except Exception as e:
        return jsonify({'error': str(e)}), 400


@app.route('/history/<int:batch_id>/bounces.csv')
@login_required
def download_bounces(batch_id):
    db = get_db()
    try:
        with db.cursor() as cur:
            cur.execute('SELECT * FROM send_batch WHERE id=%s', (batch_id,))
            batch = cur.fetchone()
            cur.execute(
                'SELECT company, email, error_msg, extra_data FROM send_record '
                'WHERE batch_id=%s AND status="bounced" ORDER BY id',
                (batch_id,),
            )
            records = cur.fetchall()
    finally:
        db.close()

    if not batch:
        return '批次不存在', 404

    # 从第一条记录的 extra_data 推断原始列顺序
    col_keys = None
    for r in records:
        if r.get('extra_data'):
            col_keys = list(json.loads(r['extra_data']).keys())
            break

    output = io.StringIO()
    writer = csv.writer(output)
    if col_keys:
        writer.writerow(col_keys + ['退信原因'])
        for r in records:
            extra = json.loads(r['extra_data']) if r.get('extra_data') else {}
            writer.writerow([extra.get(k, '') for k in col_keys] + [r['error_msg'] or ''])
    else:
        # 兼容旧数据（无 extra_data）
        writer.writerow(['公司名', '邮箱', '退信原因'])
        for r in records:
            writer.writerow([r['company'], r['email'], r['error_msg'] or ''])

    from flask import Response
    return Response(
        '﻿' + output.getvalue(),
        mimetype='text/csv; charset=utf-8',
        headers={'Content-Disposition': f'attachment; filename=bounce_{batch_id}.csv'},
    )


# 模块加载时执行（gunicorn import 和直接运行都会触发）
try:
    migrate_db()
    check_interrupted_batches()
except Exception:
    pass

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
