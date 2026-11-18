# Segurança, privacidade e uso permitido

## Limites de entrada

- Somente HTTPS; host é comparado a allowlist exata de Instagram, Facebook, YouTube e seus domínios curtos.
- A validação impede IPs locais ou domínios arbitrários no URL inicial e descarta parâmetros extras desnecessários.
- O URL é passado ao subprocesso como argumento após --, para não ser interpretado como flag.
- Não implementamos autenticação, uso de cookies do navegador, acesso privado ou remoção de DRM.

## Riscos ainda existentes

1. **SSRF/redirecionamentos:** a allowlist verifica o URL de entrada; o extrator pode seguir redirecionamentos ou acessar destinos secundários. Isolamento de egressos e revisão dos destinos acessados continuam necessários para exposição pública ampla.
2. **Proxy/IP:** o limite atual usa request.client.host; atrás do Render/reverse proxy pode refletir infraestrutura intermediária, e não uma identificação confiável de cada usuário.
3. **Abuso do endpoint de prévia:** há limite de concorrência (2), mas não há rate-limit por usuário para /api/preview; necessita proteção adicional.
4. **Storage efêmero e memória:** arquivos temporários e jobs locais podem permanecer até limpeza oportunista ou reinício. Não há persistência segura, banco de dados ou limpeza periódica.
5. **Exaustão de recursos:** o extrator é processo externo; há limites de simultaneidade, prazo e tamanho final, mas isso não substitui cota de CPU/memória, inspeção de rede e monitoramento de armazenamento.
6. **Download parcial:** remoção após uma requisição de /api/file pode interferir em múltiplos ranges/retries de navegadores e gerenciadores de download.
7. **Metadados de terceiros:** títulos e capas podem ser indisponíveis, incorretos ou apresentar links para domínios de mídia externos. A página define title via textContent, mas o navegador carrega a capa de URL retornada pelo extrator. Requer política CSP/proxy de imagens para maior controle.
8. **Logs:** categorias e códigos de vídeo podem ser registrados; não adicione credenciais, tokens ou cookies aos logs.

## Privacidade

O aplicativo não solicita contas sociais. Links e vídeos são processados no servidor; arquivos são temporários, mas o cronograma real de remoção depende do fluxo de download e de novas requisições. Não é adequado prometer anonimato absoluto ou exclusão imediata em caso de falha.

## Direitos e regras das plataformas

Utilize apenas vídeos próprios ou com autorização. Disponibilidade de vídeo publicamente não implica permissão para redistribuição. O serviço não remove DRM, paywalls, autenticação ou medidas de controle de acesso. Restrições 403/429 podem inviabilizar downloads de certas plataformas.

## Próximas prioridades

Rate limit real por cliente, limpeza periódica, retenção explícita, endurecimento de rede, proteção contra abuso, armazenamento de objeto com expiração e testes de acesso/segurança em ambiente isolado.
