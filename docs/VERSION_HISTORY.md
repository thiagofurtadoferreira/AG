# Controle de versões e commits

**Repositório:** https://github.com/thiagofurtadoferreira/AG

**Branch de produção:** https://github.com/thiagofurtadoferreira/AG/tree/deploy-reeldrop-v1-0-1

**Atenção:** o nome do branch tem "v1-0-1" por razões históricas, mas o conteúdo atual é **v1.3.1**. Para conferir a versão executável, consulte **VERSION** e a rota /api/health.

| Versão | Commit principal | Conteúdo |
|---|---|---|
| 1.0.0 | Não registrado no branch | Protótipo/pacote local anterior |
| 1.0.1 | 5b4c45bdbebeb8872d2f89dd60a9f41ca070180f | Base Docker do ReelDrop |
| 1.1.0 | a431007df14ec4704176fb81fc95d75e223e524d | Facebook |
| 1.2.0 | e5ef0f264a926864ed8864470e8bc1d526274c93 | Capa, status, compartilhamento |
| 1.3.0 | b23759c7c6343ef65f58f7646c4a2cfabb1b8709 | YouTube + Node.js |
| 1.3.1 | 10822781299296c7a44abcdddd7e44d0aeed09bf | Erros 403/429, retirada do diagnóstico temporário |

Os commits acima são registros verificáveis no histórico do GitHub; **não são tags de release**. O commit posterior de documentação não altera a versão do runtime.

## Procedimento de manutenção da versão

1. Criar mudanças no branch do ReelDrop, sem tocar em master.
2. Atualizar versão retornada por /api/health em **app.py**.
3. Atualizar **VERSION**, **CHANGELOG.md**, testes e docs.
4. Commit com descrição clara da alteração, citando a versão.
5. Verificar CI e, quando necessário, executar deploy no Render.
6. Confirmar a versão no /api/health e verificar logs, sem afirmar sucesso de download real apenas pelo estado "live" do servidor.
7. Para release formal, criar uma tag Git manualmente com o mesmo commit (não há tags de release criadas por esta documentação).

## Histórico de hospedagem

Render mantém o serviço **reeldrop-instagram** no endereço https://reeldrop-instagram.onrender.com. O estado "live" confirma que o processo iniciou; não comprova compatibilidade com as regras e bloqueios de Instagram, Facebook ou YouTube.
