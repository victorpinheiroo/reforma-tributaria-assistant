Native tool calling, 8 questions (7 need a tool, 1 must not call one), 4 tools, temperature 0, 2026-11-23.

| model | right tool | valid arguments | key params right | median s |
| --- | --- | --- | --- | --- |
| databricks-meta-llama-3-3-70b-instruct | 8/8 | 8/8 | **8/8** | 2.3 |
| databricks-llama-4-maverick | 8/8 | 8/8 | **7/8** | 1.1 |
| databricks-meta-llama-3-1-8b-instruct | 7/8 | 7/8 | **7/8** | 0.9 |
| databricks-gpt-oss-120b | 8/8 | 8/8 | **8/8** | 21.1 |
| databricks-gpt-oss-20b | 8/8 | 8/8 | **8/8** | 1.3 |
| databricks-qwen3-next-80b-a3b-instruct | 8/8 | 8/8 | **8/8** | 0.8 |
| databricks-qwen35-122b-a10b | 8/8 | 8/8 | **8/8** | 2.7 |
| databricks-gemma-3-12b | 0/8 | 0/8 | **0/8** | 0.6 |

| model | case | what went wrong |
| --- | --- | --- |
| databricks-llama-4-maverick | t7 | wrong data_operacao='2026-11-23' |
| databricks-meta-llama-3-1-8b-instruct | t6 | called consultar_aliquota |
| databricks-gemma-3-12b | t1 | provider error 400: {'error_code': 'BAD_REQUEST', 'message': 'Invalid JSON schema - string types do  |
| databricks-gemma-3-12b | t2 | provider error 400: {'error_code': 'BAD_REQUEST', 'message': 'Invalid JSON schema - string types do  |
| databricks-gemma-3-12b | t3 | provider error 400: {'error_code': 'BAD_REQUEST', 'message': 'Invalid JSON schema - string types do  |
| databricks-gemma-3-12b | t4 | provider error 400: {'error_code': 'BAD_REQUEST', 'message': 'Invalid JSON schema - string types do  |
| databricks-gemma-3-12b | t5 | provider error 400: {'error_code': 'BAD_REQUEST', 'message': 'Invalid JSON schema - string types do  |
| databricks-gemma-3-12b | t6 | provider error 400: {'error_code': 'BAD_REQUEST', 'message': 'Invalid JSON schema - string types do  |
| databricks-gemma-3-12b | t7 | provider error 400: {'error_code': 'BAD_REQUEST', 'message': 'Invalid JSON schema - string types do  |
| databricks-gemma-3-12b | t8 | provider error 400: {'error_code': 'BAD_REQUEST', 'message': 'Invalid JSON schema - string types do  |
