"""Тесты login_qr: генерация QR-SVG и безопасное сохранение сессии (0600)."""

import os
import stat

import login_qr


def test_write_qr_svg(monkeypatch, tmp_path):
    out = tmp_path / "qr.svg"
    monkeypatch.setattr(login_qr, "QR_SVG", str(out))
    login_qr._write_qr_svg("tg://login?token=abc123")
    svg = out.read_text()
    assert svg.startswith("<svg")
    assert svg.rstrip().endswith("</svg>")
    assert 'fill="#ffffff"' in svg   # белый фон — чтобы сканировалось на любой теме
    assert svg.count("<rect") > 10   # модули QR


def test_save_session_writes_and_chmod_600(monkeypatch, tmp_path):
    out = tmp_path / ".user_session"
    monkeypatch.setattr(login_qr, "SESSION_FILE", str(out))
    login_qr._save_session("SESSIONSTR")
    assert out.read_text() == "SESSIONSTR"
    assert stat.S_IMODE(os.stat(out).st_mode) == 0o600
