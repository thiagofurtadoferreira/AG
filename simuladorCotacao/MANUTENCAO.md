# Manutenção do simuladorCotacao

- Use a branch `simulador-cotacao` como base para mudanças nesta pasta.
- Registre alterações relevantes no `CHANGELOG.md`. Em cada lançamento, atualize `VERSION` e `windows/version.rc`.
- Guarde os fontes, configurações, documentação e exemplos sintéticos pequenos no Git. Os CSVs brutos de captura ficam fora do repositório.
- O README contém os passos de execução e de geração do pacote Windows. O script de empacotamento usa as dependências fixadas em `windows/requirements.lock`.
- O replay OHLC é um simulador local. As limitações de compatibilidade com o Profit estão no README.

## Verificação rápida

A partir desta pasta, com as dependências do `requirements.txt` instaladas:

```bash
python -m compileall -q .
python app.py --cli otimizar --csv exemplos/otimizacao_ntsl/candles.csv --ntsl exemplos/otimizacao_ntsl/estrategia.ntsl --config exemplos/otimizacao_ntsl/config.json --saida ../resultado-exemplo
```

## Pacotes originais

Os hashes identificam os ZIPs originais gerados para cada versão. O código e os scripts de build estão neste repositório. Os ZIPs com os binários são distribuídos à parte.

| Versão | Arquivo | SHA-256 |
|---|---|---|
| 0.1 | `simuladorCotacao-v0.1.zip` | `0abad8ddbc9685e3b9219cc631e13032ceca9dbcb3fa0e81ff0ebe9e5e72418c` |
| 0.2.0 | `simuladorCotacao-v0.2.0-win64.zip` | `713b91a3cbe9896d2d6c98b9762b8fed6d41bf2d7790d064c9625a35f1f35cbc` |
| 0.2.1 | `simuladorCotacao-v0.2.1-win64.zip` | `0db950b376db8f1c29479a0d19b0503d9a9c467d3e931dba869c408a5f894bc4` |
| 0.3.0 | `simuladorCotacao-v0.3.0-win64.zip` | `f7ba0a0a28ddaf15eae63ab51dc37ca6647d2a6e0fa4a87e8be59e2e383e1698` |
| 0.4.0 | `simuladorCotacao-v0.4.0-win64.zip` | `f4b3a1b84b0715cabfd8610ba7133304564fd5e1365fc5bedc9df07432c659cd` |
