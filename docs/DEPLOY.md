# Operação e deploy no Render

## Estado de referência

- **App:** ReelDrop 1.3.1
- **URL:** https://reeldrop-instagram.onrender.com
- **Serviço Render:** reeldrop-instagram
- **Repositório:** thiagofurtadoferreira/AG
- **Branch publicado:** deploy-reeldrop-v1-0-1
- **Runtime:** Docker
- **Base:** Python 3.12, FFmpeg, Node.js 24, yt-dlp.
- **Health:** GET /api/health

O nome do branch não corresponde à versão do runtime. Consulte o endpoint /api/health.

## Publicar uma atualização

1. Alterar somente o branch **deploy-reeldrop-v1-0-1**. Não fazer merge por acidente em master.
2. Atualizar tests, VERSION, CHANGELOG.md e documentação quando houver mudança funcional.
3. Fazer commit.
4. Verificar no painel do Render se o deploy iniciou automaticamente. Se não, usar manual deploy selecionando o commit do branch configurado.
5. Acompanhar build, início do Uvicorn e status live.
6. Consultar /api/health e verificar o novo número de versão; executar testes não destrutivos.
7. Testar download real de conteúdo **com permissão**. "live" e resposta HTTP 200 em / não significam que o YouTube/Instagram/Facebook estejam liberando mídia.

## Construção reproduzível no Docker

    docker build -t reeldrop:1.3.1 .
    docker run --rm -p 8000:8000 reeldrop:1.3.1

O container lê PORT do ambiente, usando 8000 por padrão. No Render a variável é definida pelo serviço.

## Diagnóstico

- **Crash/build:** verificar Python/yt-dlp/Node/FFmpeg nos logs de build e aplicativo.
- **YouTube 429:** a plataforma limitou requisições provenientes do IP do servidor. Não é erro de regex ou do link; retentar excessivamente pode piorar o bloqueio.
- **YouTube 403:** acesso a páginas/API de extração foi negado; um thumbnail acessível não garante MP4.
- **Login/cookies solicitados:** o ReelDrop não usa credenciais nem contorna acesso privado.
- **No formats:** pode indicar conteúdo indisponível, restrições ou incompatibilidade do extrator.
- **404 no /api/file:** job consumido, removido, expirado ou perdido após reinício.
- **429 da própria API:** existe semáforo para um download ativo e limite de 10 tentativas/10 min por request.client.
- **Logs** registram categorias de falha do YouTube; evite publicar logs com tokens, cookies ou dados pessoais.

## Caso real registrado — 18/11/2026

URL informada no projeto: https://youtube.com/shorts/5g83JHxpI8k?si=aCifUSqiJmKwjLSN

Diagnóstico em servidor Render com yt-dlp: **HTTP 429 ao obter a página, HTTP 403 nas chamadas à API e falha de extração de resposta do player**. O tratamento de erros foi melhorado na v1.3.1; **o download desse vídeo não foi confirmado como funcional**.

## Migração para ChatGPT Sites

Foi discutida, mas **não executada** e **não validada** quanto a execução de Python/FFmpeg/yt-dlp. Migrar somente a interface não elimina, por si só, o bloqueio de IP. A hospedagem de processamento precisa ter acesso legítimo e compatível à mídia.
