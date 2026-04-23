CREATE DATABASE IF NOT EXISTS nvocc_mailer
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;

USE nvocc_mailer;

CREATE TABLE IF NOT EXISTS draft (
    id         INT AUTO_INCREMENT PRIMARY KEY,
    name       VARCHAR(100) NOT NULL,
    subject    VARCHAR(200) NOT NULL DEFAULT '',
    body       TEXT         NOT NULL,
    created_at DATETIME     NOT NULL,
    updated_at DATETIME     NOT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS send_batch (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    subject       VARCHAR(200) NOT NULL,
    body          TEXT         NOT NULL,
    total_count   INT          NOT NULL DEFAULT 0,
    success_count INT          NOT NULL DEFAULT 0,
    fail_count    INT          NOT NULL DEFAULT 0,
    status        VARCHAR(20)  NOT NULL DEFAULT 'sending',  -- sending / done
    created_at    DATETIME     NOT NULL,
    finished_at   DATETIME
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE IF NOT EXISTS send_record (
    id        INT AUTO_INCREMENT PRIMARY KEY,
    batch_id  INT          NOT NULL,
    company   VARCHAR(200) NOT NULL DEFAULT '',
    email     VARCHAR(200) NOT NULL,
    status    VARCHAR(20)  NOT NULL DEFAULT 'pending',  -- pending / success / failed
    error_msg VARCHAR(500),
    extra_data TEXT,
    sent_at   DATETIME,
    INDEX idx_batch (batch_id),
    INDEX idx_batch_status (batch_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
