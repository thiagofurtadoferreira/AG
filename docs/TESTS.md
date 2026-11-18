# Plano de testes — ReelDrop

## Automação

Instale dependências de dev e rode:

    python -m pip install -r requirements.txt -r requirements-dev.txt
    python -m pytest -q

A CI do GitHub executa testes em push/pull request do branch do ReelDrop. Os testes não dependem de conexão com Instagram/Facebook/YouTube.

## Cenários básicos

1. GET /api/health retorna versão 1.3.1 e lista as três plataformas.
2. GET / apresenta os campos de colar, capa, download e compartilhamento.
3. Instagram /reel/, /p/, /tv/ normalizam para www.instagram.com e retiram query.
4. Facebook /reel/, /watch/?v=, /share/r/, /share/v/, fb.watch normalizam e retiram query não necessária.
5. YouTube /watch?v=, Shorts, live, embed e youtu.be têm ID de 11 caracteres e plataformas corretas.
6. Links com HTTP, domínios falsos, credenciais em URL, portas explícitas, playlists ou ids inválidos são rejeitados com 422.
7. Endpoint de prévia com subprocesso simulado retorna a miniatura/título sem baixar mídia real.
8. Quando o yt-dlp não consegue metadados no YouTube, a prévia usa fallback sem confirmar mídia.
9. Mensagens de 429/403 do YouTube são distintas e em português.
10. /api/file e /api/download/{id} desconhecidos respondem 404.

## Teste manual permitido

O teste de integração real só deve ser realizado com material que se tenha autorização para baixar. Usar exemplos controlados de cada plataforma; comparar arquivo MP4, duração, áudio, formato e tamanho. Não usar o sucesso de /api/preview como evidência de sucesso de download.

## Estado conhecido em produção

YouTube Short 5g83JHxpI8k, em 18/11/2026: **bloqueio 429/403 no IP do Render**, extração não concluída. A versão v1.3.1 explica esse erro ao usuário, mas não o soluciona. Marcar testes reais do YouTube em Render como **bloqueados pelo provedor**, não como aprovados.

## Qualidade de download

- Testar FFmpeg para vídeos com áudio/vídeo separado.
- Testar arquivos perto do limite de 400 MB.
- Testar reinício durante job e expiração de arquivo.
- Testar downloads parciais/range (limitação conhecida).
- Testar múltiplos usuários atrás de proxy (limitação conhecida).
