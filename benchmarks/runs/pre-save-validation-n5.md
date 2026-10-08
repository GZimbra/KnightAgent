# KnightAgent benchmark

Repetitions: 5

| Model | Mode | Split | Passed/evaluated | Coverage | Skipped | Mean seconds | Variance seconds² | Mean prompt tokens | Mean output tokens |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| qwen2.5:7b | raw | development | 22/30 | 100% | 0 | 6.81 | 10.63 | 85 | 125 |
| qwen2.5:7b | agent | development | 6/15 | 100% | 0 | 62.19 | 970.58 | 7606 | 978 |
| qwen2.5:7b | raw | holdout | 36/60 | 100% | 0 | 8.78 | 42.92 | 80 | 165 |
| qwen2.5:7b | agent | holdout | 6/10 | 100% | 0 | 52.30 | 754.97 | 10133 | 818 |
| knightagent-automation:latest | raw | development | 24/30 | 100% | 0 | 16.97 | 26.33 | 538 | 184 |
| knightagent-automation:latest | agent | development | 7/15 | 100% | 0 | 76.04 | 1143.05 | 8162 | 1068 |
| knightagent-automation:latest | raw | holdout | 33/60 | 100% | 0 | 14.66 | 63.74 | 533 | 217 |
| knightagent-automation:latest | agent | holdout | 9/10 | 100% | 0 | 66.87 | 1057.66 | 11416 | 952 |

| Model | Mode | Split | Task | Pass | Mean seconds | Variance seconds² |
| --- | --- | --- | --- | ---: | ---: | ---: |
| qwen2.5:7b | raw | development | python-count-even | 5/5 (100.0%) | 3.99 | 6.40 |
| qwen2.5:7b | agent | development | python-count-even | 5/5 (100.0%) | 85.20 | 228.95 |
| qwen2.5:7b | raw | development | python-merge-intervals | 0/5 (0.0%) | 7.80 | 0.88 |
| qwen2.5:7b | raw | development | python-fix-clamp | 5/5 (100.0%) | 2.27 | 0.51 |
| qwen2.5:7b | agent | development | python-fix-clamp | 1/5 (20.0%) | 31.17 | 720.21 |
| qwen2.5:7b | raw | development | vba-copy-values | 5/5 (100.0%) | 7.89 | 0.17 |
| qwen2.5:7b | agent | development | vba-copy-values | 0/5 (0.0%) | 70.19 | 406.74 |
| qwen2.5:7b | raw | development | vbnet-double | 5/5 (100.0%) | 7.53 | 0.25 |
| qwen2.5:7b | raw | development | office-script-copy | 2/5 (40.0%) | 11.35 | 3.78 |
| qwen2.5:7b | raw | holdout | python-edit-join | 5/5 (100.0%) | 3.81 | 6.76 |
| qwen2.5:7b | agent | holdout | python-edit-join | 2/5 (40.0%) | 73.64 | 421.36 |
| qwen2.5:7b | raw | holdout | json-exact-format | 5/5 (100.0%) | 0.86 | 0.03 |
| qwen2.5:7b | agent | holdout | json-exact-format | 4/5 (80.0%) | 30.96 | 177.73 |
| qwen2.5:7b | raw | holdout | python-topological-order | 1/5 (20.0%) | 14.51 | 3.42 |
| qwen2.5:7b | raw | holdout | python-roman-strict | 0/5 (0.0%) | 12.12 | 10.07 |
| qwen2.5:7b | raw | holdout | python-group-anagrams | 3/5 (60.0%) | 9.92 | 2.77 |
| qwen2.5:7b | raw | holdout | python-edit-csv-quote | 4/5 (80.0%) | 2.00 | 0.02 |
| qwen2.5:7b | raw | holdout | python-fix-binary-search | 5/5 (100.0%) | 5.62 | 0.73 |
| qwen2.5:7b | raw | holdout | python-normalize-ranges | 0/5 (0.0%) | 13.37 | 16.71 |
| qwen2.5:7b | raw | holdout | vba-last-row | 5/5 (100.0%) | 7.72 | 0.80 |
| qwen2.5:7b | raw | holdout | office-script-fill-empty | 0/5 (0.0%) | 22.86 | 1.75 |
| qwen2.5:7b | raw | holdout | vbnet-frequency | 5/5 (100.0%) | 11.26 | 0.10 |
| qwen2.5:7b | raw | holdout | json-nested-schema | 3/5 (60.0%) | 1.26 | 0.01 |
| knightagent-automation:latest | raw | development | python-count-even | 5/5 (100.0%) | 18.02 | 9.28 |
| knightagent-automation:latest | agent | development | python-count-even | 4/5 (80.0%) | 74.53 | 615.94 |
| knightagent-automation:latest | raw | development | python-merge-intervals | 0/5 (0.0%) | 19.79 | 13.95 |
| knightagent-automation:latest | raw | development | python-fix-clamp | 5/5 (100.0%) | 15.56 | 27.92 |
| knightagent-automation:latest | agent | development | python-fix-clamp | 3/5 (60.0%) | 77.38 | 2715.25 |
| knightagent-automation:latest | raw | development | vba-copy-values | 5/5 (100.0%) | 22.91 | 0.58 |
| knightagent-automation:latest | agent | development | vba-copy-values | 0/5 (0.0%) | 76.22 | 93.89 |
| knightagent-automation:latest | raw | development | vbnet-double | 5/5 (100.0%) | 10.82 | 13.12 |
| knightagent-automation:latest | raw | development | office-script-copy | 4/5 (80.0%) | 14.69 | 3.80 |
| knightagent-automation:latest | raw | holdout | python-edit-join | 5/5 (100.0%) | 12.52 | 4.42 |
| knightagent-automation:latest | agent | holdout | python-edit-join | 4/5 (80.0%) | 97.82 | 156.52 |
| knightagent-automation:latest | raw | holdout | json-exact-format | 1/5 (20.0%) | 10.88 | 0.43 |
| knightagent-automation:latest | agent | holdout | json-exact-format | 5/5 (100.0%) | 35.92 | 43.19 |
| knightagent-automation:latest | raw | holdout | python-topological-order | 3/5 (60.0%) | 29.58 | 19.80 |
| knightagent-automation:latest | raw | holdout | python-roman-strict | 0/5 (0.0%) | 20.03 | 0.62 |
| knightagent-automation:latest | raw | holdout | python-group-anagrams | 4/5 (80.0%) | 17.22 | 21.01 |
| knightagent-automation:latest | raw | holdout | python-edit-csv-quote | 5/5 (100.0%) | 2.68 | 1.69 |
| knightagent-automation:latest | raw | holdout | python-fix-binary-search | 5/5 (100.0%) | 11.76 | 1.05 |
| knightagent-automation:latest | raw | holdout | python-normalize-ranges | 0/5 (0.0%) | 22.52 | 6.05 |
| knightagent-automation:latest | raw | holdout | vba-last-row | 5/5 (100.0%) | 11.95 | 2.11 |
| knightagent-automation:latest | raw | holdout | office-script-fill-empty | 0/5 (0.0%) | 20.52 | 5.98 |
| knightagent-automation:latest | raw | holdout | vbnet-frequency | 5/5 (100.0%) | 14.57 | 0.39 |
| knightagent-automation:latest | raw | holdout | json-nested-schema | 0/5 (0.0%) | 1.66 | 0.01 |

Skipped checks:
- .NET SDK unavailable inside the isolated benchmark
- Excel/VBA COM runtime/compiler not available in the isolated benchmark
- ExcelScript type declarations unavailable in isolated benchmark
