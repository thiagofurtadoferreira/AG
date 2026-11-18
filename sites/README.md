# ReelDrop — frontend de migração para ChatGPT Sites

**Status:** código-fonte adaptado e salvo no GitHub. **NÃO publicado no ChatGPT Sites**, pois o publicador do Sites não está acessível nesta conversa. Este diretório é material para importar, testar e publicar a partir do ChatGPT Work / Codex usando @Sites.

## O que esta adaptação implementa

- Next.js com interface responsiva semelhante à versão ReelDrop v1.3.1.
- Detecta Instagram, Facebook e YouTube, incluindo Shorts e youtu.be.
- Busca miniatura, título e plataforma; disponibiliza preview de fallback do YouTube com aviso de não-verificação.
- Permite compartilhar o link original via WhatsApp e pelo celular.
- Cria download e acompanha progresso por API.
- **Proxy server-side** de chamadas de metadata e jobs ao backend já implantado no Render, sem depender de CORS no navegador.
- Quando o backend conclui o download, oferece link direto de arquivo ao Render para evitar transferir vídeo pesado via ChatGPT Sites.

## Pré-requisitos para uso

O Next.js precisa ser compatível com o runtime efetivamente habilitado na sua conta Sites. O projeto pode necessitar ajustes durante a importação feita no ChatGPT Work.

Para testar em máquina com Node e acesso à internet:

    cd sites
    npm install
    npm run build
    npm run dev

Abra http://localhost:3000.

## Importante: o problema do YouTube não está resolvido

Esta adaptação ainda usa https://reeldrop-instagram.onrender.com como backend por padrão. Se o IP do Render recebe HTTP 429/403 do YouTube, a versão no Sites **continuará apresentando o mesmo bloqueio**. A interface no ChatGPT Sites não altera a origem das requisições feitas pelo extrator.

Antes de afirmar que um Site permite downloads do YouTube, é necessário testar um backend de processamento legalmente acessível, com FFmpeg/yt-dlp executáveis se suportados, controle de tamanho, storage, políticas de acesso e proteção contra abuso.

Não configure proxies de terceiros ou cookies de usuários sem autorização. Não contorne login, DRM, paywalls ou outros controles de acesso.

## Segurança / privacidade

O frontend usa uma lista de domínios permitidos e envia requisições a endpoints fixos. O backend também valida as URLs. Nenhuma senha de redes sociais é solicitada. Vídeos são mantidos temporariamente no Render, não no Site. A entrega do MP4 a partir do Render pode falhar em downloads parciais/repetidos (limitação já conhecida da versão atual).

## Publicação

1. Abra ChatGPT na web ou no app desktop, selecione **Work**.
2. Use **@Sites** e peça que importe este diretório via GitHub e mantenha o frontend fiel ao ReelDrop.
3. Configure e valide o servidor proxy de API. Salve a versão privada primeiro.
4. Teste pelo menos três links autorizados, um de cada plataforma; revise falhas 403/429 antes de abrir ao público.
5. Publique usando o fluxo do Sites e só então forneça o URL real gerado.

Código original em https://github.com/thiagofurtadoferreira/AG/tree/deploy-reeldrop-v1-0-1. Esta adaptação está no branch **chatgpt-sites-reeldrop**, diretório **sites**.
