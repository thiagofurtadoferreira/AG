"""Testes locais sem baixar mídia e sem acessos a redes sociais."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import app as reeldrop


@pytest.mark.parametrize("original,normalized,code,platform", [
    ("https://www.instagram.com/reel/DeaSB8GxvCX/?utm_source=test",
     "https://www.instagram.com/reel/DeaSB8GxvCX/", "DeaSB8GxvCX", "instagram"),
    ("https://instagram.com/p/Abcd_1234/?foo=bar",
     "https://www.instagram.com/p/Abcd_1234/", "Abcd_1234", "instagram"),
    ("https://www.facebook.com/reel/1234567890123/?ref=test",
     "https://www.facebook.com/reel/1234567890123/", "1234567890123", "facebook"),
    ("https://www.facebook.com/watch/?v=1234567890123&ref=abc",
     "https://www.facebook.com/watch/?v=1234567890123", "1234567890123", "facebook"),
    ("https://fb.watch/AbcdEf12345/?ref=abc",
     "https://fb.watch/AbcdEf12345/", "AbcdEf12345", "facebook"),
    ("https://www.facebook.com/share/r/AbcdEf12345/?foo=x",
     "https://www.facebook.com/share/r/AbcdEf12345/", "AbcdEf12345", "facebook"),
    ("https://youtube.com/shorts/5g83JHxpI8k?si=aCifUSqiJmKwjLSN",
     "https://www.youtube.com/shorts/5g83JHxpI8k", "5g83JHxpI8k", "youtube"),
    ("https://youtu.be/G6Kspj3OO0s?si=tracking",
     "https://youtu.be/G6Kspj3OO0s", "G6Kspj3OO0s", "youtube"),
    ("https://www.youtube.com/watch?v=5g83JHxpI8k&list=PLtest",
     "https://www.youtube.com/watch?v=5g83JHxpI8k", "5g83JHxpI8k", "youtube"),
    ("https://www.youtube.com/live/5g83JHxpI8k",
     "https://www.youtube.com/live/5g83JHxpI8k", "5g83JHxpI8k", "youtube"),
    ("https://www.youtube.com/embed/5g83JHxpI8k",
     "https://www.youtube.com/embed/5g83JHxpI8k", "5g83JHxpI8k", "youtube"),
])
def test_urls_validas(original, normalized, code, platform):
    assert reeldrop.canonical(original) == (normalized, code, platform)


@pytest.mark.parametrize("url", [
    "http://youtube.com/shorts/5g83JHxpI8k",
    "https://youtube.com.evil.example/watch?v=5g83JHxpI8k",
    "https://youtube.com@evil.example/watch?v=5g83JHxpI8k",
    "https://www.youtube.com:443/watch?v=5g83JHxpI8k",
    "https://youtube.com/watch?v=123",
    "https://youtube.com/watch?v=5g83JHxpI8k&v=G6Kspj3OO0s",
    "https://youtube.com/playlist?list=PL12345",
    "https://www.instagram.com/stories/user/12345/",
    "https://facebook.com/l.php?u=https://127.0.0.1/",
    "https://fb.watch/../../etc/passwd",
    "https://127.0.0.1/video",
    "file:///etc/passwd",
    " ",
])
def test_urls_rejeitadas(url):
    with pytest.raises(HTTPException) as exc:
        reeldrop.canonical(url)
    assert exc.value.status_code == 422


def test_health_e_pagina():
    with TestClient(reeldrop.app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        body = health.json()
        assert body["version"] == "1.3.1"
        assert set(body["platforms"]) == {"instagram", "facebook", "youtube"}
        page = client.get("/")
        assert page.status_code == 200
        assert "YouTube" in page.text
        assert "Compartilhar no WhatsApp" in page.text
        assert "Baixar vídeo" in page.text


def test_rotas_desconhecidas():
    with TestClient(reeldrop.app) as client:
        assert client.get("/api/download/unknown").status_code == 404
        assert client.get("/api/file/unknown").status_code == 404
        assert client.post("/api/download", json={"url":"https://evil.example/abc"}).status_code == 422
        assert client.post("/api/preview", json={"url":"https://evil.example/abc"}).status_code == 422


def test_preview_com_metadados_simulados(monkeypatch):
    video_id = "G6Kspj3OO0s"
    fake = SimpleNamespace(
        returncode=0,
        stdout=json.dumps({"title":"Teste autorizado","thumbnail":"https://example.org/image.jpg"}),
        stderr="",
    )
    monkeypatch.setattr(reeldrop.subprocess, "run", lambda *args, **kwargs: fake)
    with TestClient(reeldrop.app) as client:
        response = client.post("/api/preview", json={"url":f"https://youtu.be/{video_id}?si=test"})
        assert response.status_code == 200
        body = response.json()
        assert body["title"] == "Teste autorizado"
        assert body["thumbnail"] == "https://example.org/image.jpg"
        assert body["platform"] == "youtube"


def test_preview_youtube_fallback_em_erro(monkeypatch):
    video_id = "aBcdE123_45"
    fake = SimpleNamespace(returncode=1, stdout="", stderr="HTTP Error 429")
    monkeypatch.setattr(reeldrop.subprocess, "run", lambda *args, **kwargs: fake)
    with TestClient(reeldrop.app) as client:
        response = client.post("/api/preview", json={"url":f"https://youtube.com/watch?v={video_id}"})
        assert response.status_code == 200
        body = response.json()
        assert body["platform"] == "youtube"
        assert body["verified"] is False
        assert video_id in body["thumbnail"]


def test_mensagens_de_bloqueio():
    assert "429" in reeldrop.friendly("HTTP Error 429: Too Many Requests", "youtube")
    assert "403" in reeldrop.friendly("HTTP Error 403: Forbidden", "youtube")
    assert "YouTube" in reeldrop.friendly("Unable to get formats", "youtube")
    assert "Facebook" in reeldrop.friendly("Login required", "facebook")


def test_selecao_thumbnail():
    info = {"thumbnail":"https://x.example/preview.jpg",
            "thumbnails":[{"url":"https://x.example/a.jpg","width":100,"height":100},
                          {"url":"https://x.example/b.jpg","width":300,"height":200}]}
    assert reeldrop.select_thumbnail(info) == "https://x.example/b.jpg"
