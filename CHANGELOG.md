# Histórico de mudanças — ReelDrop

Este arquivo documenta o que foi implementado no branch de produção. Os IDs dos commits históricos constam em docs/VERSION_HISTORY.md.

## 1.3.1 — 2026-11-18 — atual

- Mensagens específicas para limitação do YouTube por **429 Too Many Requests** e **403 Forbidden**.
- Logs de categorias de falha para facilitar suporte.
- Remoção do diagnóstico temporário executado no servidor.
- **Limitação não resolvida:** o YouTube bloqueia o acesso de saída do Render no vídeo testado; a extração continua não garantida.
- Documentação consolidada, matriz de testes e guia operacional adicionados no commit documental posterior, sem alterar o número da versão de runtime.

## 1.3.0 — 2026-11-18

- Identificação de YouTube (watch, Shorts, links curtos, live e embed).
- Suporte a Node.js 24 no container e dependências atuais do yt-dlp.
- Prévia de YouTube com fallback para imagem pública pelo ID.
- Preserva Instagram/Facebook, status e compartilhamento.

## 1.2.0 — 2026-11-18

- Busca automática de miniatura e metadados no campo de link.
- Endpoint /api/preview e cache temporário em memória.
- Indicação de progresso e mensagens durante o processamento.
- WhatsApp, compartilhamento nativo e copiar URL.

## 1.1.0 — 2026-11-18

- Inclusão de vídeos e Reels públicos do Facebook.
- Normalização de domínios e rotas aceitas; mesmo campo de entrada.
- Mensagens de erro específicas para a plataforma.

## 1.0.1 — 2026-11-18

- Primeira implantação Docker do ReelDrop no Render, FastAPI + yt-dlp + FFmpeg, endpoint de saúde, download em tarefas e MP4 temporário.

## 1.0.0 — anterior

- Protótipo inicial local do ReelDrop, antes do primeiro deploy neste branch.
- O pacote local original 1.0.0 não foi publicado como commit independente neste branch; não confundir com uma tag Git.

## Versões futuras

Planejadas, **não implementadas**: fila durável, limites confiáveis por cliente atrás de proxy, limpeza periódica, streaming/resume robusto, isolamento de rede e uma arquitetura aprovada de aquisição de mídia que funcione nas condições e permissões das plataformas.
