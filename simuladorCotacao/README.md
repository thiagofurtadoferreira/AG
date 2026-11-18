# simuladorCotacao 0.2.0

## Abrir no Windows

1. Extraia **todo o ZIP** para uma pasta gravável.
2. Execute **SimuladorCotacao.exe**. A interface abre no navegador padrão, em endereço local da própria máquina. O runtime acompanha o programa.
3. Selecione o CSV, escolha o formato, informe o intervalo e carregue um arquivo NTSL ou cole o código do Profit.
4. Use **Replay da estratégia** e clique em **Executar**. Use **Abrir relatório** quando terminar.
5. Use **Encerrar aplicativo** para fechar o processo local. Os arquivos de saída ficam em `%USERPROFILE%\simuladorCotacao\resultados`.

Para testar a instalação com dados pequenos, selecione `exemplos/replay_minimo/candles.csv`, formato **Candles OHLC com timestamp**, e o `estrategia.ntsl` da mesma pasta. Com os valores padrão, o relatório deve mostrar dois preenchimentos e uma barra ambígua.

O campo **Substituição de inputs (JSON)** pode permanecer como `{}`. Por exemplo, `{"p_Lote": 2}` substitui um input do código. Os nomes de inputs são comparados sem distinção entre maiúsculas e minúsculas. O incremento de preço alimenta `MinPriceIncrement`. O **valor por ponto e contrato** multiplica o resultado bruto e alimenta `DailyResult`. Configure esse valor para que os limites da estratégia usem a unidade desejada.

## Formatos do CSV

| Formato | Campos | Comportamento |
|---|---|---|
| Indicador exportado do Profit | `data_minuto_origem;v_barra_id;abertura;maxima;minima;fechamento` e campos adicionais conforme a estratégia | Ordena por minuto e identificador. Use 1 s para v6 e 5 s para v7. |
| Negócios | `timestamp;preco`, com `quantidade` e `sequencia` opcionais | Reconstrói OHLC por intervalo, conta negócios e soma quantidade quando disponível. |
| Candles OHLC | `timestamp;abertura;maxima;minima;fechamento` | Ordena o timestamp ISO 8601 de cada candle, com uma linha por timestamp. |

O separador é ponto e vírgula. Preços inteiros e decimais com vírgula são aceitos. Nos formatos com `timestamp`, use data e hora ISO 8601, por exemplo `2026-11-16T09:15:00.100`. A exportação v6/v7 registra a hora até o minuto. A saída preserva a ordem dentro do minuto sem atribuir segundos exatos.

### Colunas adicionais

| Recursos NTSL | CSV |
|---|---|
| `Trades`, `Volume`, `Quantity` | `v_trades_atual`, `volume`, `volume_contratos` |
| `AgressionVolBuy`, `AgressionVolSell` | `v_agressao_compra`, `v_agressao_venda` |
| `BidPrice`, `AskPrice`, `BidSize`, `AskSize` | `v_bid`, `v_ask`, `v_qtd_bid`, `v_qtd_ask` |
| `TotalBuyQtd`, `TotalSellQtd` | `v_qtd_compra_book`, `v_qtd_venda_book` |

Estratégias que dependem de alguma dessas séries exigem a respectiva coluna. No formato negócios, `Trades` é calculado e `Quantity` fica disponível quando há quantidade por negócio. O OHLC de negócios por si só deixa book e agressão indisponíveis.

## Módulo NTSL

Compila `input`, `const`, `var`, `begin/end`, `if/then/else`, atribuições e operadores aritméticos, relacionais e booleanos. Aceita referências históricas com `[n]`, OHLC, horário, posição, médias simples e exponenciais, máximas e mínimas de janela, soma móvel e funções matemáticas básicas. Implementa entradas e saídas a mercado, limite e stop, cancelamento, zeragem, `Plot`, `PaintBar` e `ConsoleLog`. O arquivo `exemplo_cruzamento.ntsl` demonstra uma estratégia simples. A estratégia do pacote pode ser carregada pelo botão na tela.

- Funções ou procedimentos definidos pelo usuário, comandos de laço, arrays próprios, indicadores fora da lista do compilador e múltiplos ativos ainda estão fora do subconjunto desta versão. Identificadores incompatíveis geram erro com a linha do código.
- `Asset(GetAsset, ...)` permite ligar as chamadas de book aos snapshots exportados. O replay não reconstrói os níveis do book ou séries independentes por ativo ou intervalo. O parâmetro de profundidade é representado pelo agregado já existente no CSV.
- As séries históricas se restringem ao pregão. No início do pregão, referências sem histórico acessível retornam zero para dados de mercado e o valor padrão para variáveis. As médias usam o histórico disponível no pregão. A estratégia pode definir aquecimento próprio.
- `Date` e `Time` usam a data do candle e a hora HHMM. O intervalo da interface organiza os dados e fica registrado no relatório. Altere explicitamente os inputs temporais do seu código quando forem diferentes do intervalo analisado.

## Preenchimentos e limitações do replay

O código é avaliado uma vez, no **fechamento**. Ordens emitidas no fechamento podem executar a partir da próxima barra disponível. Ordens a mercado usam a abertura seguinte. Limites e stops usam os extremos da barra com ajuste de gap. Um stop com limite que sofre gap além do limite pode permanecer pendente para a barra seguinte.

Se alvo e stop forem tocados na mesma barra, o relatório registra ambiguidade e aplica o preenchimento menos favorável entre as saídas tocadas. Uma ordem a mercado já pendente tem prioridade na abertura. O replay mantém uma posição líquida, substitui ordens pendentes da mesma função e limita saídas ao saldo da posição. Ao fim de cada pregão, cancela ordens pendentes e encerra a posição restante no último fechamento disponível.

O simulador usa hipóteses de preenchimento por OHLC, sem reproduzir fila, custos, latência, timestamps intrabar ou o motor do Replay Profit. A estratégia das 150 árvores pode ser analisada pelo classificador na abertura via modo **Otimização genética**, ou executada no fechamento via **Replay da estratégia**. Os dois modos têm unidades de avaliação e regras de execução próprias.

### Relatórios

- `relatorio.html` e `metricas.json` resumem preenchimentos, saídas, pontos × contratos, drawdown realizado, inputs, hash do código e ambiguidades.
- `execucoes.csv` lista preenchimentos. `candles.csv` contém OHLC, intenções de entrada, posição, pontos acumulados e chamadas de plot.
- `console.csv` contém as primeiras 10 mil mensagens de `ConsoleLog`.
- `estrategia.ntsl` guarda o código efetivamente executado. Os inputs aplicados ficam em `metricas.json`.

## Otimizador genético

Use **Otimização genética do ensemble**, o CSV de indicador rotulado e um NTSL compatível com o formato de árvores do modelo fornecido. Defina no JSON a classe, os parâmetros, faixas e passos, a métrica, população, número máximo de gerações, tempo, meta, paciência, threads e cache RAM. A execução reserva os últimos pregões para o teste.

O replay aceita o subconjunto NTSL descrito acima. A otimização genética desta versão opera sobre o classificador de árvores. Veja [README-otimizador.md](README-otimizador.md) para o formato e os parâmetros suportados.

## Linha de comando

No PowerShell, abra a pasta extraída:

```powershell
.\SimuladorCotacao-CLI.exe --version
.\SimuladorCotacao-CLI.exe estrategia --csv "C:\Dados\indicadorv7_claude.csv" --ntsl .\modelo_profit.ntsl --segundos 5 --formato profit --saida .\replay_v7
.\SimuladorCotacao-CLI.exe otimizar --config .\config_v7.json --csv "C:\Dados\indicadorv7_claude.csv" --saida .\otim_v7
.\SimuladorCotacao-CLI.exe candles "C:\Dados\negocios.csv" --formato negocios --segundos 5 --saida .\candles.csv
```

## Código e reconstrução do pacote

O motor e a interface estão em `ntsl.py`, `estrategia.py`, `app.py` e `interface.html`. A versão está em `VERSION`, nas propriedades dos executáveis e no [CHANGELOG.md](CHANGELOG.md). A pasta `windows` contém fonte dos launchers e dependências fixadas.

Em Linux, use Python 3.11+ e um toolchain MinGW-w64 x64. Baixe a distribuição embutida do Python **3.12.10 Windows x64** e as wheels correspondentes. Depois:

```bash
python -m pip download --only-binary=:all: --platform win_amd64 --python-version 312 -r windows/requirements.lock -d wheels
python windows/package.py --python-win python-3.12.10-embed-amd64.zip --wheels wheels --saida simuladorCotacao-v0.2.0-win64.zip
```

Para desenvolver ou testar com o seu Python local, instale `requirements.txt` e rode `python app.py`. Para um comando de terminal no código-fonte, use `python app.py --cli estrategia --help`.
