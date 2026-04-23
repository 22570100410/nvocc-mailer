# nvocc-mailer 项目说明

## 是什么

给航交所用的批量邮件发送系统。从 Excel/CSV 名单批量向 NVOCC 公司发送通知邮件，支持富文本正文、历史记录、退信检测。

## 技术栈

- 后端：Python Flask + PyMySQL
- 数据库：MySQL 8.0（Docker）
- 前端：Bootstrap 5 + Quill.js 富文本编辑器
- 邮件发送：smtplib（SMTP）
- 退信检测：poplib（POP3）
- 部署：Docker + Gunicorn

## 功能清单

- 登录鉴权（固定账号密码）
- 上传 Excel/CSV 名单，预览并选择邮箱列、公司名列（支持 xlsx/xls/csv）
- 富文本编辑正文（支持加粗/斜体/颜色/字号，字号用中文名：初号～小五）
- 草稿保存/加载/删除
- 批量发送，逐封串行，实时写库，前端轮询进度
- 主动暂停：发送中可点暂停，当前这封发完后停止
- 中断保护：程序崩溃重启后自动将"发送中"改为"已中断"
- 暂停/中断后均可恢复续发（从断点继续）
- 重试失败：对失败记录新建批次重发
- 退信检测：通过 POP3 扫描收件箱退信，比对批次成功邮件，标记退信状态并提取原因
- 下载退信名单：CSV 文件（原始文件全列 + 退信原因），带 BOM 兼容 Excel

## 部署信息

- 服务器：192.168.1.74
- 访问地址：http://192.168.1.74:5001
- 登录账号：admin / Miluo@2026
- 容器名：nvocc-mailer-app（app）、nvocc-mailer-db（MySQL）
- 网络：nvocc-mailer_mailer-net
- 数据卷：nvocc-mailer_uploads（上传文件）、nvocc-mailer_db_data（MySQL 数据）

## 重新部署（改了代码）

详见 `docs/部署文档.md`，完整命令都在里面。

快速参考：

```bash
# 本地构建
docker build -t nvocc-mailer:1.0.0 .
docker save nvocc-mailer:1.0.0 | gzip > nvocc-mailer.tar.gz
scp nvocc-mailer.tar.gz root@192.168.1.74:/root/

# 服务器
docker load < /root/nvocc-mailer.tar.gz
docker stop nvocc-mailer-app && docker rm nvocc-mailer-app
docker run -d --name nvocc-mailer-app --restart always \
  -p 5001:5000 \
  --network nvocc-mailer_mailer-net \
  -v nvocc-mailer_uploads:/app/uploads \
  -e TZ=Asia/Shanghai \
  -e DB_HOST=db -e DB_PORT=3306 -e DB_NAME=nvocc_mailer \
  -e DB_USER=root -e DB_PASSWORD=Miluo@123 \
  -e LOGIN_USERNAME=admin -e LOGIN_PASSWORD=Miluo@2026 \
  -e SECRET_KEY=nvocc-mailer-2026-secret-key \
  -e SMTP_HOST=192.168.32.8 -e SMTP_PORT=25 \
  -e SMTP_USER=filingmail@message.sse.net.cn \
  -e SMTP_PASSWORD=Mot@SsE-65151166+zZ \
  -e SMTP_FROM_NAME=航交所 -e SMTP_USE_SSL=false \
  -e POP3_HOST=192.168.32.8 -e POP3_PORT=110 -e POP3_USE_SSL=false \
  nvocc-mailer:1.0.0
```

## 退信检测原理

1. 通过 POP3 连接 192.168.32.8:110，登录 filingmail@message.sse.net.cn
2. 遍历收件箱所有邮件，跳过早于本批次发送时间的邮件
3. 只保留发件人含 `postmaster` 或 `mailer-daemon` 的系统退信通知
4. 企业邮件服务器退信格式为英文纯文本，正则匹配 `<email>:` 提取被退信地址
5. 同时兼容中文退信格式（QQ 等）：匹配"无法发送到 xxx@xxx.com"
6. 比对本批次成功邮件列表，命中则更新状态为 bounced，记录退信原因

退信通知特征：
- 发件人：`MAILER-DAEMON@mail.message.sse.net.cn`
- 主题：`Undelivered Mail Returned to Sender`
