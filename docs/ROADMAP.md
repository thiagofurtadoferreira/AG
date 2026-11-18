# Pendências e evolução planejada

Os itens deste documento são **planejamento**, não funcionalidades entregues.

## P0 — Robustez e transparência

- Avaliar acesso legítimo ao conteúdo por infraestrutura que não receba bloqueio 403/429; não recorrer a bypass de autenticação ou DRM.
- Melhorar mensagens quando capa existe mas vídeo não está disponível.
- Criar opção de compartilhar o **arquivo** via APIs nativas quando tecnicamente permitido e com arquivo pronto. Hoje os botões compartilham somente URL.
- Atualizar fallback para conter indicação visual de prévia não verificada.

## P1 — Operação e segurança

- Queue persistente e idempotência de downloads.
- Storage com retenção/expiração e transferência reentrante, suportando Range.
- Identificação confiável do cliente atrás de proxies.
- Quotas e limites para /api/preview.
- Limpeza periódica e alertas sobre armazenamento e falhas.
- Restrição de rede para destinos externos e resposta robusta a redirects.
- Conjunto de testes de integração com conteúdos próprios em ambiente permitido.

## P2 — Experiência

- Seleção de formatos/qualidade quando houver opções autorizadas.
- Progresso detalhado por etapa: consulta de metadados, download, mesclagem, entrega.
- Tela de histórico local opcional sem coletar dados desnecessários.
- Explicações de erros e instruções de diagnóstico acessíveis no celular.
- Migração de hospedagem somente após comprovar compatibilidade de processamento e conectividade.

## Fora do escopo atual

- Conteúdo privado sem autorização, remoção de DRM, extração por login de terceiros.
- Promessa de download garantido de qualquer vídeo público.
- Serviço separado implantado em ChatGPT Sites (ainda não criado).
