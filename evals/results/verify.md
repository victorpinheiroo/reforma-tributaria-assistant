Verifier on seeded mistakes in real agent answers (golden questions that end in an answer). A mutant counts as caught if any check flags it.

| operator | mutants | numbers | vigência | support (judge) | caught |
| --- | --- | --- | --- | --- | --- |
| amount_altered | 2 | 2 | 0 | 0 | **2/2** |
| invented_rate | 15 | 15 | 0 | 1 | **15/15** |
| invented_year | 15 | 15 | 0 | 1 | **15/15** |
| unsupported_claim | 8 | 0 | 0 | 7 | **7/8** |
| citation_swap | 6 | 0 | 0 | 4 | **4/6** |
| future_as_present | 1 | 0 | 1 | 0 | **1/1** |
| **all** | 47 | | | | **44/47** |

False alarms on the 15 original answers: 1 (numbers 0, vigência 0, support 1).

| original flagged | what |
| --- | --- |
| q08 | {"num": [], "vig": [], "sup": ["Embora a EC 132/2023, art. 9, § 6º, I autorize a concessão de crédito ao contribuinte adquirente de serviços de transportador autônomo de carga pessoa física não contribuinte, a regulamentação específica só entra em vigor em 2027 [2]."]} |

Missed mutants: q01/citation_swap, q13/unsupported_claim, q20/citation_swap
