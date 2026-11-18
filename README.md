# ReelDrop

Site para **pré-visualizar e baixar vídeos públicos** do Instagram, Facebook e YouTube, quando a plataforma permite a extração, com interface responsiva, barra de progresso e compartilhamento de links.

**Versão de referência:** 1.3.1 (18/11/2026). **Estado:** implantação web confirmada no Render; extração do YouTube **não está garantida** e o teste real de Shorts recebeu HTTP 429 e 403 do próprio YouTube.

## Acesse

- **Site:** https://reeldrop-instagram.onrender.com
- **Código implantado:** branch **deploy-reeldrop-v1-0-1** deste repositório.
- **Hospedagem:** serviço Docker existente no Render, chamado **reeldrop-instagram**.
- **Importante:** o branch principal deste repositório (master) pertence a outro projeto. **Não faça merge com master** por engano. O ReelDrop está isolado neste branch, e o Render publica este branch.

## Recursos

- Um único campo identifica automaticamente Instagram, Facebook ou YouTube.
- Aceita Instagram /reel/, /p/, /tv/; Facebook /reel/, /videos/, /watch/?v=, /share/v/, /share/r/, fb.watch; YouTube /watch?v=, /shorts/, /live/, /embed/ e youtu.be.
- Remove parâmetros de rastreamento nos links normalizados.
- Mostra capa e título quando o extrator obtém metadados. No YouTube há **capa de fallback pelo ID**, que não prova que o vídeo pode ser baixado.
- Processa vídeo e áudio em MP4, escolhendo os formatos que a fonte disponibiliza. FFmpeg executa a junção/remux.
- Exibe status e percentual do processamento e inicia o download quando o arquivo fica pronto.
- Botões de WhatsApp, compartilhamento nativo e copiar link compartilham **o URL de origem**, não os bytes do arquivo MP4.
- Não solicita login, senha ou cookies; não tem suporte a conteúdo privado/protegido.

## Rodar localmente com Docker

Pré-requisito: Docker com suporte a containers Linux.

    docker build -t reeldrop:1.3.1 .
    docker run --rm -p 8000:8000 reeldrop:1.3.1

Abra http://localhost:8000; teste HTTP GET em http://localhost:8000/api/health.

O Dockerfile usa Python 3.12, FFmpeg, Node.js 24 e yt-dlp. No Render, a porta é lida da variável PORT.

## Rodar no Python local

É necessário Python 3.12+, FFmpeg e Node.js 24 disponíveis em PATH.

    python -m venv .venv
    .venv/bin/python -m pip install -r requirements.txt
    .venv/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000

No Windows, use .venv\Scripts\python.exe em vez de .venv/bin/python.

## Testes

    python -m pip install -r requirements.txt -r requirements-dev.txt
    python -m pytest -q

Os testes são locais, sem download real, e verificam rotas, normalização de URLs, segurança de entradas e tratamento de erros. Teste real exige acesso externo, direitos de uso e compatibilidade com a plataforma.

## Organização

- **app.py:** backend FastAPI e página HTML/CSS/JS embutida (fonte atualmente implantada).
- **Dockerfile / requirements.txt:** ambiente de produção.
- **VERSION / CHANGELOG.md:** versão atual e mudanças.
- **docs/ARCHITECTURE.md:** fluxo, estado e persistência.
- **docs/API.md:** rotas HTTP.
- **docs/DEPLOY.md:** build, publicação e diagnóstico no Render.
- **docs/SECURITY.md:** restrições, riscos conhecidos e cuidados.
- **docs/TESTS.md:** cenários de teste.
- **docs/VERSION_HISTORY.md:** referência dos commits já publicados.
- **tests/test_app.py:** testes automatizados de regressão.

Arquivos **index.html** e **.github/workflows/pages.yml** já existiam neste repositório e pertencem ao projeto original do branch principal, não ao ReelDrop; o Dockerfile do ReelDrop não os utiliza.

## Limitações importantes

1. O YouTube pode bloquear o IP de saída de uma hospedagem de datacenter (403/429), mesmo para conteúdo público. **Migrar a interface para outro host não assegura a liberação do download**.
2. A capa do YouTube é independente da possibilidade de extrair o MP4; exibir a imagem não confirma sucesso.
3. Limite atual de 400 MB por arquivo, prazo de execução de 180 segundos e um download simultâneo por processo.
4. Os arquivos são temporários, mantidos no disco efêmero do container; não há persistência, fila distribuída ou garantia de retomar após reinício.
5. O sistema não contorna DRM, login, paywall, conteúdo privado ou controles de acesso.
6. Para distribuir vídeos, utilize apenas conteúdo que você possui ou tem permissão para baixar, respeitando direitos autorais e termos das plataformas.

Veja **docs/SECURITY.md** e **docs/ROADMAP.md** antes de ampliar o uso público.
