# Plano de execução — reforma-tributaria-assistant

Mesmo ritmo e princípios do macro-sql-br: toda manchete com denominador, oráculo fora do código,
fatia vertical primeiro, prometer só o demonstrável.

## Estado atual: marco 1 (spike de viabilidade) concluído em 2026-11-23

### Calculadora oficial

- `receitafederal/calculadora-rtc-regime-regular` **1.7.2** (19/11/2026), banco **V0073** de
  09/11/2026 ("Nova tabela de Classificações Tributárias, IT 2025.002 v.1.71"). Fixada em
  `scripts/setup_calculadora.sh`; OpenAPI salvo em `docs/calculadora/openapi-1.7.2.json`.
- **Exige Java 25** (o documento de escopo dizia 21). JDK Temurin 25.0.5.1 portátil em `tools/`,
  checksum conferido; o Java 17 da máquina não foi tocado.
- Sobe em ~30 s no perfil `offline` (SQLite gerado por Flyway na primeira vez).
- 6 cálculos pela API, todos com o resultado esperado; requisição e resposta salvas em
  `tests/fixtures/calculadora/` e testadas (`tests/test_fixtures.py`):

| caso | o que testa | resultado |
| --- | --- | --- |
| c1 | exemplo da própria documentação (serviço de educação, redução 60%) | CBS 42,24 / IBS 0,48 = doc |
| c2 | 2026, tributação integral, base 1.000, alíquotas de referência | CBS 9,00 / IBS 1,00 |
| c3 | 2027, camiseta, alíquotas nominais hipotéticas 8,8 / 0,05 / 0,05 | CBS 88,00 / IBS 1,00 |
| c4 | 2026, arroz da cesta básica (200003), redução 100% | CBS 0,00 / IBS 0,00 |
| c5 | 2027 sem alíquotas nominais | 422 "Alíquotas nominais não informadas" |
| c6 | 2027, cerveja sem dados do Imposto Seletivo | 422 "Dados do IS não informados" |

### Achados que mudam o desenho

1. **Só existe alíquota de referência para 2026** (ano de teste: CBS 0,9%, IBS UF 0,1%, IBS mun.
   0%). De 2027 em diante a calculadora responde 404 e exige alíquotas nominais de quem chama,
   porque o Senado ainda não fixou as alíquotas de referência. O assistente **não pode** inventar
   uma alíquota para 2027+: ou pergunta, ou calcula com uma hipótese explícita e marcada como
   hipótese. Vira categoria do golden set.
2. **A calculadora aplica regras dependentes de data por conta própria**: cerveja (22030000) não
   exige Imposto Seletivo em 2026 e exige a partir de 2027. Erro 422 da calculadora é resposta
   legítima ("falta X"), não falha do sistema; o grafo precisa traduzi-lo, não esconder.
3. Quase todo endpoint de dados abertos recebe `data`: vigência é parâmetro de primeira classe na
   própria fonte oficial, o que confirma a premissa do projeto.
4. **Comitê Gestor do IBS**: o PLP 108/2024 foi sancionado em 13/01/2026; uma página do Planalto o
   numera como LC 227/2026, número ainda a confirmar no texto oficial. Entra no corpus junto com a
   EC 132/2023 e a LC 214/2025 (texto compilado do Planalto, que já incorpora alterações).

### Tool calling nos modelos gratuitos (`docs/spike_toolcalling.md`)

8 perguntas, 4 ferramentas, tool calling nativo: 6 de 8 modelos acertam 8/8 (ferramenta,
argumentos válidos e parâmetros-chave). Llama 4 Maverick troca a data de uma operação de 2027 por
"hoje"; Llama 3.1 8B chama ferramenta em pergunta conceitual; **Gemma 3 12B 0/8** porque rejeita
`format: date` no schema (mesma causa do projeto A; a correção conhecida é tirar `format`).
Conclusão: tool calling nativo não é o gargalo; a dificuldade vai estar em datas, vigência e
parâmetros que o usuário não deu (cClassTrib, alíquota de 2027+). O conjunto do spike é fácil
demais para escolher modelo: o `tool_calls.jsonl` do marco 2 precisa de casos ambíguos.

## Marco 2: servidor MCP `rtc-tools` (2026-11-23)

- `src/rtc/calculadora.py`: cliente tipado. Entradas validadas por Pydantic antes da chamada (NCM 8
  dígitos, cClassTrib 6, lista de itens não vazia); município por nome resolvido para código IBGE
  pelos dados abertos da própria calculadora, nunca pelo modelo; recusa da calculadora (4xx) vira
  `erro` com o título oficial, sem número.
- `src/rtc/mcp_server.py` (SDK oficial `mcp` 2.3, `MCPServer`): 5 ferramentas, todas exigem data.
  Resultado `{ok, dados | erro, fonte}` com versão da calculadora e do banco, endpoint e requisição.
- Testes: 13 cenários gravados da calculadora real (`scripts/record_fixtures.py` ->
  `tests/fixtures/calculadora/http.json`) e reproduzidos pela camada MCP; requisição não gravada
  falha o teste, o que prova que parâmetro inválido é recusado antes da chamada. CI sem Java.
- `scripts/mcp_smoke.py`: 14/14 pelo protocolo real (stdio), calculadora ao vivo, incluindo
  violação de schema chegando ao cliente como `is_error`.
- Fora por ora: `calcular_simples_nacional` (outra aplicação Java, `calculadora-rtc-simples-nacional`).

## Marco 3: corpus com vigência e busca híbrida (2026-11-23)

**Corpus** (`corpus/`, fixado por sha256, coletado em 2026-11-23 no Planalto, texto compilado):
LC 214/2025, LC 227/2026 (confirmada: "Institui o Comitê Gestor do IBS (CGIBS)", DOU 14/1/2026) e
EC 132/2023. 6.977 dispositivos (artigo, §, inciso, alínea). Redação revogada vem riscada no
Planalto (`line-through`, 1.953 trechos na LC 214) e é descartada; texto citado depois de "a Lei X
passa a vigorar" vai para a Lei X com o artigo de origem; as 679 cópias de dispositivos da LC 214
dentro da LC 227 ficam fora do índice (o compilado da LC 214 já as tem). LC 214 com os 544
artigos; art. 217 registrado como revogado pela LC 227.

**Vigência** transcrita das cláusulas de efeitos (LC 214 art. 544, red. LC 227; LC 227 art. 182;
EC 132 art. 23), com teste que confere cada número de artigo contra o texto oficial. Dispositivos
com vigência condicional (LC 227 art. 52, §§ 4º e 5º: eleição do presidente do CGIBS) ficam com
início nulo e a condição escrita. Regras de calendário dentro do texto ("em 2029, 1,3%") são
conteúdo, não filtro.

**Golden set de busca** (`evals/golden_retrieval.jsonl`, 30 perguntas) commitado antes de
existir código de busca (commit `ab23af0`).

**Resultado** (`evals/results/retrieval.md`, top 5, unidade = artigo):

| configuração | hit@5 | MRR@5 | vazamento de dispositivo futuro |
| --- | --- | --- | --- |
| BM25 | 15/26 | 0,47 | 0/2 |
| denso (e5-small) | 19/26 | 0,51 | 0/2 |
| híbrido RRF | 13/26 | 0,48 | 0/2 |
| **híbrido + reranker** | **22/26** | **0,72** | **0/2** |
| idem, sem filtro de vigência | 22/26 | 0,72 | 2/2 |
| chunk fixo 1.000 caracteres | 20/26 | 0,67 | 1/2 |
| chunk por seção | 22/26 | 0,67 | 0/2 |

Achados:
- O reranker é o que faz a busca funcionar (13 → 22). RRF sem reranker fica abaixo do denso
  sozinho: 50 candidatos de cada lado diluem o topo.
- O filtro de vigência é o que impede citar regra de 2027 numa pergunta de 2026 (2/2 → 0/2).
  Chunk fixo vaza porque uma janela mistura dispositivos com vigências diferentes.
- Erros: arroz (Anexo I não sobe), exportação (arts. 8 e 79), "imposto do pecado" (gíria) e "quais
  tributos a LC 214 criou" (art. 1).
- **"Não encontrei" não pode ser só limiar do reranker**: fora do corpus (IRPF -0,61; INSS -2,28)
  se sobrepõe a pergunta respondível (cashback -1,02). E pergunta sobre regra futura tem nota alta
  (2,5 e 8,5) porque há texto vigente parecido; detectar "ainda não vale" exige buscar também sem
  o filtro e comparar. Entra no marco 5.
- Não ajustei nada contra este golden set (evitar sobreajuste); melhorias vão com perguntas novas.

**Desvio do escopo**: vetor em numpy atrás de interface, não Chroma (exato e determinístico para ~2
mil chunks; Chroma pode implementar a mesma interface no marco 6).

## Cronograma (fatia vertical primeiro)

| Marco | Entrega | Critério de pronto |
| --- | --- | --- |
| 1 ✅ | Spike: calculadora local, 5+ cálculos, tool calling nos modelos gratuitos | este documento |
| 2 ✅ | Servidor MCP `rtc-tools` sobre a calculadora + testes contra as fixtures | cliente MCP real por stdio lista e chama as ferramentas (o Inspector exige Node, ausente aqui); testes sem a calculadora no ar |
| 3 ✅ | Corpus por dispositivo com vigência; RAG híbrido (denso + BM25 + RRF + filtro de vigência); golden set escrito **antes** da busca | recall@k por tipo de pergunta |
| 4 | Grafo LangGraph: data de referência, roteador, RAG, ferramenta, síntese | ponta a ponta no golden set |
| 5 | Verificação: citação sustenta a frase, todo número veio de ferramenta, vigência bate | % de números sem origem bloqueados |
| 6 | 60+ perguntas, Streamlit, Docker (calculadora + API + app), README | `docker compose up` sem conta Databricks |
| 7 | (extensão) Sugestão de classificação fiscal | |

## Decisões pendentes

- [ ] Docker da calculadora: o repositório oficial não traz Dockerfile; escrever um (Temurin 25 +
  build do JAR + banco Flyway) e validar no CI (esta máquina não tem Docker).
- [ ] Confirmar o número da lei do Comitê Gestor (LC 227/2026?) no texto oficial.
- [ ] Casos de 2027+ no golden set: resposta esperada = pedir alíquota ou calcular com hipótese
  declarada; nunca número apresentado como oficial.
- [ ] Município: a calculadora usa código IBGE; resolver nome → código via
  `/dados-abertos/ufs/municipios` dentro da ferramenta, não pelo modelo.
