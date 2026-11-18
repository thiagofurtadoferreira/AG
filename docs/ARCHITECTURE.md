# Arquitetura e funcionamento

## Componentes

- **Frontend**: HTML/CSS/JS embutido em app.py, servido por GET /.
- **Backend**: FastAPI/Pydantic com endpoints de validação, prévia, criação e acompanhamento de downloads.
- **Extrator**: yt-dlp invocado via subprocesso, **nunca** como código recebido do usuário.
- **Mídia**: FFmpeg no container para unir vídeo e áudio e gerar MP4 quando a fonte disponibilizar formatos compatíveis.
- **Runtime de scripts**: Node.js 24, usado pelo yt-dlp no suporte a YouTube.
- **Storage**: diretório temporário local, criado na inicialização.
- **Hospedagem**: container Docker no Render; não há banco de dados nem fila externa.

## Caminho de prévia

1. Usuário cola o link no campo.
2. JavaScript detecta domínio e solicita POST /api/preview.
3. Backend valida protocolo/domínio/rota e retira parâmetros de rastreamento.
4. Se o link estiver no cache de 20 minutos, responde com os metadados.
5. Se não, usa yt-dlp sem baixar o arquivo, até 35 s, com até 2 prévias simultâneas.
6. YouTube: a interface pode exibir imediatamente a imagem pública hqdefault pelo ID. Se o extrator falhar, a API também pode responder com capa de fallback e título genérico, marcada verified=false.
7. Exibir capa **não significa** que o arquivo seja acessível para download.

## Caminho de download

1. POST /api/download valida e normaliza URL; cria job aleatório de 32 caracteres hexadecimais.
2. Um worker daemon usa yt-dlp. O limite é de 1 download ativo por processo.
3. GET /api/download/{id} devolve status e progresso; o cliente consulta aproximadamente a cada 2 segundos.
4. Ao terminar, GET /api/file/{id} transmite MP4 e agenda remoção do job e da pasta após a resposta.
5. A limpeza de outros jobs antigos (mais de 30 minutos após ready/error) ocorre **quando uma nova requisição de download chega**; não existe processo periódico de limpeza nessa versão.

## Estados e limites

- Estados: preparing, downloading, ready, error.
- Um job e seus arquivos existem apenas em **memória/disco efêmero deste processo**. O reinício do container invalida ids.
- Tempo máximo do subprocesso de download: 180 segundos.
- Limite de arquivo: 400 MB.
- Limite de taxa atual: 10 POST /api/download por endereço visto por request.client em 10 minutos. Em proxy reverso, esse endereço pode não corresponder ao usuário real.
- A prévia tem semáforo independente de 2 tarefas; **não tem limite por IP próprio**.
- Uma única requisição de arquivo pode consumir/apagar o job; download interrompido, múltiplas tentativas e requisições de faixa HTTP (Range) podem falhar e precisam de redesign.

## Fluxo resumido

    Navegador -> POST /api/preview -> validação -> yt-dlp (metadados) -> capa
    Navegador -> POST /api/download -> validação -> thread -> yt-dlp + FFmpeg
    Navegador -> GET /api/download/{id} -> progresso
    Navegador -> GET /api/file/{id} -> MP4 -> remoção temporária

O usuário é responsável por ter permissão para baixar o material. A plataforma pode impedir o acesso independentemente da qualidade da aplicação.
