# Pedido pronto para executar no ChatGPT Work com @Sites

@Sites Crie, valide e publique um novo site ReelDrop usando o código-fonte do repositório
https://github.com/thiagofurtadoferreira/AG/tree/chatgpt-sites-reeldrop/sites

**Objetivos obrigatórios**
- Importar e adaptar o Next.js de `sites/` ao ambiente compatível do ChatGPT Sites.
- Preservar a UX do ReelDrop: um campo de URL para Instagram, Facebook e YouTube, capa, título, progresso, avisos, copiar link, WhatsApp e compartilhamento nativo.
- Manter público apenas conteúdo próprio ou autorizado, sem contornar autenticação, paywalls ou DRM.
- Antes de publicar, testar /api/health, /api/preview, /api/download e polling em links controlados com permissão.
- Validar o comportamento do download real e diferenciar claramente capa/metadata de sucesso do arquivo MP4.
- IMPORTANTE: o backend atual Render sofre HTTP 429/403 ao extrair vídeos do YouTube. Migrar somente o frontend para Sites NÃO corrige esse problema. Teste se o runtime Sites comporta um backend autônomo com dependências necessárias e saída autorizada; se não, preserve o Render para Instagram/Facebook e mostre limitação honesta para YouTube, sem prometer downloads universais.
- Não comprometer o site atual https://reeldrop-instagram.onrender.com nem a branch de produção. Salvar a nova versão separadamente.
- Gerar um URL privado de prévia, validar responsividade no celular e só depois publicar para o público quando os recursos estiverem corretos.

**Documentação:** arquivos README e docs no mesmo repositório.
