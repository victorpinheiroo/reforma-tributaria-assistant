Retrieval on 30 golden questions (written before the retriever), top 5, unit = legal article.

| configuration | hit@5 | MRR@5 | leak@5 (not yet in effect) | best score: no-answer max vs answerable median |
| --- | --- | --- | --- | --- |
| bm25 | **15/26** | 0.47 | 0/2 | n/a |
| dense | **19/26** | 0.51 | 0/2 | n/a |
| hybrid (RRF) | **13/26** | 0.48 | 0/2 | n/a |
| hybrid + rerank | **22/26** | 0.72 | 0/2 | -0.61 vs 4.34 |
| hybrid + rerank, no vigência filter | **22/26** | 0.72 | 2/2 | -2.27 vs 4.38 |
| chunking: fixed 1000 chars | **20/26** | 0.67 | 1/2 | -0.61 vs 4.01 |
| chunking: by section | **22/26** | 0.67 | 0/2 | -0.30 vs 5.15 |

Full pipeline (hybrid + rerank) by question type: anexo 2/3, conceitual 14/17, data 1/1, numero_no_texto 5/5

Misses of the full pipeline:

| id | type | top 5 |
| --- | --- | --- |
| r07 | anexo | LC 214/2025, art. 448; LC 214/2025, art. 103; LC 214/2025, art. 146, § 1º; LC 214/2025, art. 110; LC 214/2025, art. 473, § 1º |
| r13 | conceitual | LC 214/2025, art. 82, § 11º; LC 214/2025, art. 96; LC 214/2025, art. 82, § 5º; LC 214/2025, art. 76; LC 214/2025, art. 72 |
| r15 | conceitual | LC 214/2025, Anexo XVII; LC 214/2025, art. 422, § 1º; Lei 9.718/1998 (red. LC 214/2025), art. 5, § 12º; Lei 9.718/1998 (red. LC 214/2025), art. 5, § 10º; LC 214/2025, art. 422, § 4º |
| r21 | conceitual | LC 214/2025, art. 294; LC 214/2025, art. 452; LC 214/2025, art. 2; LC 214/2025, art. 374; LC 214/2025, art. 25 |
