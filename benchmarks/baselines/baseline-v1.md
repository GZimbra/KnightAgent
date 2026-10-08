# KnightAgent benchmark

Repetitions: 3

| Model | Split | Passed/evaluated | Skipped | Mean seconds | Variance seconds² | Mean prompt tokens | Mean output tokens |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |
| qwen2.5:7b | development | 6/12 | 6 | 9.27 | 11.95 | 925 | 156 |
| qwen2.5:7b | holdout | 6/6 | 0 | 2.89 | 1.07 | 917 | 22 |
| knightagent-automation:latest | development | 6/12 | 6 | 8.78 | 5.17 | 925 | 156 |
| knightagent-automation:latest | holdout | 6/6 | 0 | 1.47 | 0.14 | 917 | 22 |

| Model | Split | Task | Pass | Mean seconds | Variance seconds² |
| --- | --- | --- | ---: | ---: | ---: |
| qwen2.5:7b | development | python-count-even | 0/3 (0.0%) | 5.98 | 0.40 |
| qwen2.5:7b | development | python-merge-intervals | 0/3 (0.0%) | 9.43 | 0.46 |
| qwen2.5:7b | development | python-fix-clamp | 3/3 (100.0%) | 5.85 | 1.30 |
| qwen2.5:7b | development | vba-copy-values | 3/3 (100.0%) | 8.45 | 0.17 |
| qwen2.5:7b | development | vbnet-double | skipped | 10.13 | 1.55 |
| qwen2.5:7b | development | office-script-copy | skipped | 15.80 | 1.24 |
| qwen2.5:7b | holdout | python-edit-join | 3/3 (100.0%) | 3.39 | 1.50 |
| qwen2.5:7b | holdout | json-exact-format | 3/3 (100.0%) | 2.40 | 0.16 |
| knightagent-automation:latest | development | python-count-even | 0/3 (0.0%) | 8.27 | 5.31 |
| knightagent-automation:latest | development | python-merge-intervals | 0/3 (0.0%) | 9.98 | 0.36 |
| knightagent-automation:latest | development | python-fix-clamp | 3/3 (100.0%) | 5.82 | 1.04 |
| knightagent-automation:latest | development | vba-copy-values | 3/3 (100.0%) | 8.30 | 0.39 |
| knightagent-automation:latest | development | vbnet-double | skipped | 8.02 | 0.22 |
| knightagent-automation:latest | development | office-script-copy | skipped | 12.26 | 0.33 |
| knightagent-automation:latest | holdout | python-edit-join | 3/3 (100.0%) | 1.83 | 0.03 |
| knightagent-automation:latest | holdout | json-exact-format | 3/3 (100.0%) | 1.10 | 0.00 |

Skipped checks:
- .NET SDK unavailable
- Excel/VBA COM runtime/compiler not available in the isolated benchmark
- ExcelScript type declarations unavailable in isolated benchmark
