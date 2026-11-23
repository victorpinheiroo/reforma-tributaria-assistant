End to end on 20 golden questions (committed before the graph): live model, retrieval and the official calculator over MCP.

| passed | outcome | citation | calculator values | route |
| --- | --- | --- | --- | --- |
| **17/20** | 18/20 | 8/10 | 5/6 | 17/20 |

| id | expected outcome | got | route (exp/got) | citation | values | pass |
| --- | --- | --- | --- | --- | --- | --- |
| q01 | resposta | resposta | conceitual/conceitual | True | None  | yes |
| q02 | resposta | resposta | mista/numerica | False | True aliquotaReferencia=0.9 | **no** |
| q03 | resposta | resposta | numerica/numerica | None | True vCBS=9.00, vIBS=1.00 | yes |
| q04 | resposta | resposta | numerica/numerica | None | True vCBS=0.00, vIBS=0.00 | yes |
| q05 | sem_numero_oficial | sem_numero_oficial | numerica/numerica | None | None  | yes |
| q06 | pergunta_de_volta | pergunta_de_volta | numerica/numerica | None | None  | yes |
| q07 | resposta | resposta | numerica/numerica | None | True vCBS=176.00, vIBS=2.00 | yes |
| q08 | nao_vigente | nao_vigente | conceitual/conceitual | True | None  | yes |
| q09 | resposta | resposta | conceitual/conceitual | True | None  | yes |
| q10 | fora_escopo | fora_escopo | fora_escopo/fora_escopo | None | None  | yes |
| q11 | fora_escopo | fora_escopo | fora_escopo/fora_escopo | None | None  | yes |
| q12 | resposta | resposta | conceitual/conceitual | True | None  | yes |
| q13 | resposta | resposta | conceitual/conceitual | True | None  | yes |
| q14 | resposta | nao_encontrei | conceitual/conceitual | False | None  | **no** |
| q15 | resposta | nao_encontrei | numerica/conceitual | None | False tributadoPeloImpostoSeletivo=None | **no** |
| q16 | resposta | resposta | numerica/numerica | None | True codigo=200003 | yes |
| q17 | sem_numero_oficial | sem_numero_oficial | mista/numerica | None | None  | yes |
| q18 | resposta | resposta | conceitual/conceitual | True | None  | yes |
| q19 | resposta | resposta | conceitual/conceitual | True | None  | yes |
| q20 | resposta | resposta | conceitual/conceitual | True | None  | yes |
