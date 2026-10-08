# KnightAgent benchmark

Repetitions: 5

| Model | Mode | Split | Passed/evaluated | Coverage | Skipped | Mean seconds | Variance seconds² | Mean prompt tokens | Mean output tokens |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| qwen2.5:7b | raw | development | 22/30 | 100% | 0 | 7.12 | 10.99 | 85 | 125 |
| qwen2.5:7b | agent | development | 2/15 | 100% | 0 | 49.99 | 445.58 | 6565 | 843 |
| qwen2.5:7b | raw | holdout | 36/60 | 100% | 0 | 9.17 | 46.69 | 80 | 165 |
| qwen2.5:7b | agent | holdout | 9/10 | 100% | 0 | 55.21 | 1170.68 | 11132 | 914 |
| knightagent-automation:latest | raw | development | 24/30 | 100% | 0 | 17.58 | 27.74 | 538 | 184 |
| knightagent-automation:latest | agent | development | 5/15 | 100% | 0 | 60.32 | 469.47 | 6593 | 832 |
| knightagent-automation:latest | raw | holdout | 33/60 | 100% | 0 | 15.38 | 74.51 | 533 | 217 |
| knightagent-automation:latest | agent | holdout | 8/10 | 100% | 0 | 77.24 | 3090.50 | 12129 | 998 |

| Model | Mode | Split | Task | Pass | Mean seconds | Variance seconds² |
| --- | --- | --- | --- | ---: | ---: | ---: |
| qwen2.5:7b | raw | development | python-count-even | 5/5 (100.0%) | 3.69 | 2.97 |
| qwen2.5:7b | agent | development | python-count-even | 1/5 (20.0%) | 59.35 | 91.01 |
| qwen2.5:7b | raw | development | python-merge-intervals | 0/5 (0.0%) | 8.21 | 1.48 |
| qwen2.5:7b | raw | development | python-fix-clamp | 5/5 (100.0%) | 2.88 | 1.47 |
| qwen2.5:7b | agent | development | python-fix-clamp | 1/5 (20.0%) | 31.95 | 679.36 |
| qwen2.5:7b | raw | development | vba-copy-values | 5/5 (100.0%) | 8.54 | 1.17 |
| qwen2.5:7b | agent | development | vba-copy-values | 0/5 (0.0%) | 58.67 | 78.06 |
| qwen2.5:7b | raw | development | vbnet-double | 5/5 (100.0%) | 7.66 | 0.45 |
| qwen2.5:7b | raw | development | office-script-copy | 2/5 (40.0%) | 11.76 | 3.53 |
| qwen2.5:7b | raw | holdout | python-edit-join | 5/5 (100.0%) | 4.14 | 3.91 |
| qwen2.5:7b | agent | holdout | python-edit-join | 5/5 (100.0%) | 81.88 | 744.36 |
| qwen2.5:7b | raw | holdout | json-exact-format | 5/5 (100.0%) | 0.90 | 0.06 |
| qwen2.5:7b | agent | holdout | json-exact-format | 4/5 (80.0%) | 28.54 | 174.55 |
| qwen2.5:7b | raw | holdout | python-topological-order | 1/5 (20.0%) | 16.96 | 6.70 |
| qwen2.5:7b | raw | holdout | python-roman-strict | 0/5 (0.0%) | 12.68 | 14.60 |
| qwen2.5:7b | raw | holdout | python-group-anagrams | 3/5 (60.0%) | 9.85 | 2.25 |
| qwen2.5:7b | raw | holdout | python-edit-csv-quote | 4/5 (80.0%) | 2.10 | 0.02 |
| qwen2.5:7b | raw | holdout | python-fix-binary-search | 5/5 (100.0%) | 6.11 | 0.93 |
| qwen2.5:7b | raw | holdout | python-normalize-ranges | 0/5 (0.0%) | 13.87 | 19.68 |
| qwen2.5:7b | raw | holdout | vba-last-row | 5/5 (100.0%) | 7.58 | 1.97 |
| qwen2.5:7b | raw | holdout | office-script-fill-empty | 0/5 (0.0%) | 22.98 | 2.29 |
| qwen2.5:7b | raw | holdout | vbnet-frequency | 5/5 (100.0%) | 11.51 | 0.22 |
| qwen2.5:7b | raw | holdout | json-nested-schema | 3/5 (60.0%) | 1.40 | 0.04 |
| knightagent-automation:latest | raw | development | python-count-even | 5/5 (100.0%) | 19.22 | 1.08 |
| knightagent-automation:latest | agent | development | python-count-even | 2/5 (40.0%) | 58.50 | 67.45 |
| knightagent-automation:latest | raw | development | python-merge-intervals | 0/5 (0.0%) | 22.05 | 22.08 |
| knightagent-automation:latest | raw | development | python-fix-clamp | 5/5 (100.0%) | 16.75 | 27.58 |
| knightagent-automation:latest | agent | development | python-fix-clamp | 3/5 (60.0%) | 56.85 | 1263.63 |
| knightagent-automation:latest | raw | development | vba-copy-values | 5/5 (100.0%) | 21.88 | 1.88 |
| knightagent-automation:latest | agent | development | vba-copy-values | 0/5 (0.0%) | 65.60 | 34.08 |
| knightagent-automation:latest | raw | development | vbnet-double | 5/5 (100.0%) | 10.78 | 13.46 |
| knightagent-automation:latest | raw | development | office-script-copy | 4/5 (80.0%) | 14.81 | 4.65 |
| knightagent-automation:latest | raw | holdout | python-edit-join | 5/5 (100.0%) | 13.76 | 9.96 |
| knightagent-automation:latest | agent | holdout | python-edit-join | 3/5 (60.0%) | 121.50 | 2228.76 |
| knightagent-automation:latest | raw | holdout | json-exact-format | 1/5 (20.0%) | 9.91 | 1.71 |
| knightagent-automation:latest | agent | holdout | json-exact-format | 5/5 (100.0%) | 32.98 | 34.23 |
| knightagent-automation:latest | raw | holdout | python-topological-order | 3/5 (60.0%) | 30.77 | 22.74 |
| knightagent-automation:latest | raw | holdout | python-roman-strict | 0/5 (0.0%) | 21.93 | 0.73 |
| knightagent-automation:latest | raw | holdout | python-group-anagrams | 4/5 (80.0%) | 19.31 | 29.78 |
| knightagent-automation:latest | raw | holdout | python-edit-csv-quote | 5/5 (100.0%) | 2.92 | 1.80 |
| knightagent-automation:latest | raw | holdout | python-fix-binary-search | 5/5 (100.0%) | 12.00 | 1.47 |
| knightagent-automation:latest | raw | holdout | python-normalize-ranges | 0/5 (0.0%) | 24.78 | 8.44 |
| knightagent-automation:latest | raw | holdout | vba-last-row | 5/5 (100.0%) | 12.52 | 2.38 |
| knightagent-automation:latest | raw | holdout | office-script-fill-empty | 0/5 (0.0%) | 20.61 | 5.67 |
| knightagent-automation:latest | raw | holdout | vbnet-frequency | 5/5 (100.0%) | 14.43 | 1.12 |
| knightagent-automation:latest | raw | holdout | json-nested-schema | 0/5 (0.0%) | 1.62 | 0.00 |

Skipped checks:
- .NET SDK unavailable inside the isolated benchmark
- Excel/VBA COM runtime/compiler not available in the isolated benchmark
- ExcelScript type declarations unavailable in isolated benchmark
