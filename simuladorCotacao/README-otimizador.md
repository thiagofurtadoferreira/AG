# simuladorCotacao

O programa roda localmente e tem dois comandos. `candles` reconstrói OHLC a partir de negócios ou coloca em ordem o OHLC já exportado. `otimizar` lê o ensemble NTSL fornecido, calcula o score na abertura da barra e usa um algoritmo genético para procurar parâmetros que discriminem a classe alvo.

## Instalação e execução no Windows

Instale Python 3.11 ou superior, extraia o ZIP e abra o PowerShell na pasta do programa.

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe simulador.py otimizar --config config_v7.json --csv "C:\Dados\indicadorv7_claude.csv" --saida resultados_v7
```

No Linux, use `python3 -m venv .venv` e `.venv/bin/python` no lugar de `.\.venv\Scripts\python.exe`. O argumento `--saida` é opcional. Ao repetir uma execução, indique um diretório novo ou deixe o programa criar um automaticamente. Use `config_v6.json` para o CSV v6. O argumento `--ntsl` aponta para outro arquivo com o mesmo formato de exportação das árvores. O NTSL fornecido acompanha o projeto.

## Reconstruir candles

```powershell
.\.venv\Scripts\python.exe simulador.py candles "C:\Dados\negocios.csv" --formato negocios --segundos 5 --saida candles_5s.csv
.\.venv\Scripts\python.exe simulador.py candles "C:\Dados\indicadorv6_claude.csv" --formato profit --segundos 1 --saida candles_v6.csv
```

### CSV de negócios

Use uma linha por negócio e separador ponto e vírgula. Use timestamp local ISO 8601 com data e hora. `sequencia` e `quantidade` são opcionais. O programa ordena por timestamp e, quando fornecida, por sequência para desempatar. Sem sequência, conserva a ordem original em horários idênticos.

```csv
timestamp;preco;quantidade;sequencia
2026-11-16T09:15:00.100;169550;2;1
2026-11-16T09:15:00.900;169560;1;2
2026-11-16T09:15:01.500;169545;3;3
```

Cada janela inclui o instante inicial e exclui seu limite final. O primeiro negócio é a abertura, o último é o fechamento e os extremos são a máxima e a mínima. O programa omite intervalos sem negócios. O CSV produzido contém OHLC, contagem de negócios e soma de quantidade quando fornecida. Para a calibração das árvores, use o CSV rotulado do indicador, que também contém agressões, book e estados do setup.

### CSV do indicador

O programa usa `data_minuto_origem` e `v_barra_id` em conjunto. Na v6, o identificador reinicia em trechos diferentes do mesmo pregão. A saída mantém minuto e ordem dentro do minuto. O intervalo nominal é de 1 segundo na v6 e 5 segundos na v7. A exportação tem resolução de um minuto e uma barra não pode ser decomposta em negócios a partir de OHLC. Janelas de indicadores reiniciam na mudança de pregão, em lacunas e nas fronteiras de minutos parciais.

## Configuração da busca genética

Edite uma cópia do JSON correspondente à sua base.

| Campo | Efeito |
|---|---|
| `classe_alvo` | Rótulo literal da coluna `classe`, por exemplo `"1C"`. Cada execução avalia uma classe contra as demais. |
| `segundos_por_candle` | Resolução nominal do CSV, usada para conferir a quantidade de barras por minuto. |
| `pregoes_teste` | Quantidade dos últimos pregões reservada para a avaliação final. |
| `parametros` | Declare `min`, `max` e `passo` para cada parâmetro a pesquisar. Os demais assumem o valor do NTSL. |
| `genetico.populacao`, `geracoes`, `mutacao`, `semente` | Controlam tamanho da população, limite de gerações, probabilidade de mutação por gene e sorteio. |
| `genetico.metrica` | Aceita `f1`, `precision`, `recall`, `balanced_accuracy` ou `accuracy`. |
| `genetico.min_sinais` | Mínimo de sinais na busca para aceitar um candidato. |
| `genetico.paciencia` | Limite de gerações consecutivas sem melhora. Zero desativa. |
| `genetico.limite_segundos` | Orçamento da busca. Um lote em execução pode terminar depois do limite. Zero desativa. |
| `genetico.meta` | Valor desejado de 0 a 1 para a métrica. `null` desativa. |
| `threads` | Zero usa os núcleos lógicos disponíveis, limitado pela população e por uma estimativa de RAM livre. Valores positivos definem o máximo. |
| `cache_ram_mb` | Teto para os vetores de score em cache. Zero desativa o cache entre lotes. |

Parâmetros suportados nesta versão

- `p_CorteScoreModelo` e `p_BarrasAquecimento`.
- `p_PeriodoATR`, `p_PeriodoMedia`, `p_PeriodoVolatilidade`, `p_PeriodoEficiencia` e `p_PeriodoMediaTrades`.

A busca preserva o melhor candidato e combina parâmetros dos mais aptos com cruzamento, mutação e amostragem aleatória. As combinações já avaliadas são reaproveitadas. Candidatos que só diferem em limiar ou aquecimento compartilham o cálculo do score. As threads usam a mesma base em memória e processam em paralelo as combinações que exigem scores diferentes. O teto de cache não representa um limite total do processo. O CSV é carregado em memória.

## Relatórios

Abra `relatorio.html` no navegador. O relatório compara modelo original e otimizado, mede precisão, recall, F1, acurácia balanceada e apresenta a matriz de confusão. O diretório também contém `metricas.json`, `candles.csv`, `predicoes.csv`, `candidatos.csv` e `evolucao.csv`. Para a classe 1C e uma combinação válida, o programa gera `modelo_parametrizado.ntsl` alterando os valores dos inputs pesquisados.

No score da abertura, o único valor da barra atual usado pelas árvores fornecidas é o gap de abertura. As demais variáveis usadas no score vêm de barras fechadas. A coluna de classe entra na avaliação, e o indicador histórico auxiliar `v_FlagClasse1C` é reconstruído do OHLC passado conforme o código recebido. Barras dentro do horário de entrada com rótulo válido entram no denominador da avaliação. Se estiverem em aquecimento ou sem score, contam como ausência de sinal.

## Limites de reprodução

- O leitor aceita o formato de árvores do NTSL fornecido. Esse ensemble já foi treinado para **1C**. Para outra classe, a execução só mede quanto o score atual consegue discriminá-la. Treinar outro classificador requer uma etapa adicional.
- A simulação recalcula as séries implementadas a partir de OHLC e agressão. Usa os snapshots exportados para book e estados do setup, como referência, recuo e pressão de saída. Alterar um período pode mudar esses estados dentro do Profit. A paridade do score e dos sinais deve ser conferida no Replay.
- A resolução do CSV não altera `p_SegundosPorBarra`, que permanece com o valor fixado no NTSL para a fórmula de aceleração. Confira a configuração do gráfico e do modelo antes de importar os parâmetros.
- As métricas são de classificação por candle, sem executar ordens ou calcular fills, stop, alvo, slippage ou P&L. Os últimos pregões ficaram fora da busca genética. O ZIP não contém o histórico de treinamento das 150 árvores para verificar se elas já haviam visto esses pregões.

A pasta `exemplos` traz métricas e evolução das execuções de verificação com os dois CSVs fornecidos.
