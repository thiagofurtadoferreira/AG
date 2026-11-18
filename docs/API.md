# API HTTP — versão 1.3.1

**Base URL pública:** https://reeldrop-instagram.onrender.com

Todos os endpoints usam JSON, exceto GET / e GET /api/file/{id}. A API é pública e **não requer login**.

## GET /api/health

Resposta 200:

    {"status":"ok","service":"ReelDrop","version":"1.3.1","platforms":["instagram","facebook","youtube"]}

O resultado confirma funcionamento do aplicativo, **não** a disponibilidade dos provedores externos.

## POST /api/preview

Corpo:

    {"url":"https://youtube.com/shorts/5g83JHxpI8k?si=exemplo"}

Resposta 200 (ilustrativa, não implica acesso ao vídeo):

    {"url":"https://www.youtube.com/shorts/5g83JHxpI8k","platform":"youtube","shortcode":"5g83JHxpI8k","title":"Vídeo do YouTube","thumbnail":"https://i.ytimg.com/vi/5g83JHxpI8k/hqdefault.jpg","verified":false}

O campo verified=false aparece no fallback do YouTube: significa que os metadados do vídeo não foram confirmados pelo extrator. Uma prévia normal pode não incluir esse campo. Erros: 422 (link/metadata), 429 (prévia ocupada), 504 (timeout não-YouTube).

## POST /api/download

Corpo:

    {"url":"https://www.instagram.com/reel/DeaSB8GxvCX/"}

Resposta 202:

    {"id":"<identificador_hexadecimal>","status":"preparing","platform":"instagram"}

Erros: 422 (link rejeitado), 429 (limite de taxa ou slot ocupado). O POST apenas cria o job; ainda não confirma sucesso.

## GET /api/download/{id}

Resposta 200, por exemplo:

    {"status":"downloading","message":"Baixando o vídeo... 45%","progress":45,"platform":"youtube"}

Valores de status: preparing, downloading, ready, error. Em erro, message detalha a falha quando identificada. Retorna 404 para id desconhecido/expirado.

## GET /api/file/{id}

Quando ready, retorna mídia video/mp4 e cabeçalho Content-Disposition como attachment. O arquivo é removido após a resposta. Retorna 404 quando não está pronto, expirou ou já foi consumido. **Não use este endpoint como link compartilhável permanente**.

## Exemplos de URL aceitos

- Instagram: https://www.instagram.com/reel/DeaSB8GxvCX/
- Facebook: https://www.facebook.com/reel/1234567890123/
- YouTube: https://youtube.com/watch?v=5g83JHxpI8k
- Shorts: https://youtube.com/shorts/5g83JHxpI8k?si=exemplo
- YouTube curto: https://youtu.be/5g83JHxpI8k

Os links acima são exemplos estruturais; não são declaração de disponibilidade pública ou de direito autoral.

Para testar sem baixar mídia, use GET /api/health e testes automatizados em tests/test_app.py.
