# KnightAgent benchmark

Repetitions: 3

| Model | Mode | Split | Passed/evaluated | Coverage | Skipped | Mean seconds | Variance seconds² | Mean prompt tokens | Mean output tokens |
| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| qwen2.5:7b | raw | development | 14/18 | 100% | 0 | 6.84 | 8.86 | 85 | 123 |
| qwen2.5:7b | agent | development | 2/9 | 100% | 0 | 50.53 | 256.63 | 6427 | 865 |
| qwen2.5:7b | raw | holdout | 21/36 | 100% | 0 | 8.90 | 42.51 | 80 | 163 |
| qwen2.5:7b | agent | holdout | 5/6 | 100% | 0 | 45.85 | 286.23 | 10063 | 765 |
| knightagent-automation:latest | raw | development | 15/18 | 100% | 0 | 17.17 | 29.92 | 538 | 179 |
| knightagent-automation:latest | agent | development | 2/9 | 100% | 0 | 63.42 | 397.28 | 7778 | 942 |
| knightagent-automation:latest | raw | holdout | 21/36 | 100% | 0 | 15.31 | 78.94 | 533 | 217 |
| knightagent-automation:latest | agent | holdout | 5/6 | 100% | 0 | 69.31 | 1309.27 | 12648 | 1046 |

| Model | Mode | Split | Task | Pass | Mean seconds | Variance seconds² |
| --- | --- | --- | --- | ---: | ---: | ---: |
| qwen2.5:7b | raw | development | python-count-even | 3/3 (100.0%) | 4.39 | 3.92 |
| qwen2.5:7b | agent | development | python-count-even | 0/3 (0.0%) | 57.61 | 56.93 |
| qwen2.5:7b | raw | development | python-merge-intervals | 0/3 (0.0%) | 8.17 | 1.37 |
| qwen2.5:7b | raw | development | python-fix-clamp | 3/3 (100.0%) | 2.12 | 0.08 |
| qwen2.5:7b | agent | development | python-fix-clamp | 2/3 (66.7%) | 40.57 | 527.81 |
| qwen2.5:7b | raw | development | vba-copy-values | 3/3 (100.0%) | 8.22 | 0.04 |
| qwen2.5:7b | agent | development | vba-copy-values | 0/3 (0.0%) | 53.42 | 27.57 |
| qwen2.5:7b | raw | development | vbnet-double | 3/3 (100.0%) | 7.54 | 0.53 |
| qwen2.5:7b | raw | development | office-script-copy | 2/3 (66.7%) | 10.57 | 0.86 |
| qwen2.5:7b | raw | holdout | python-edit-join | 3/3 (100.0%) | 4.62 | 6.03 |
| qwen2.5:7b | agent | holdout | python-edit-join | 2/3 (66.7%) | 57.66 | 152.05 |
| qwen2.5:7b | raw | holdout | json-exact-format | 3/3 (100.0%) | 0.92 | 0.08 |
| qwen2.5:7b | agent | holdout | json-exact-format | 3/3 (100.0%) | 34.03 | 141.22 |
| qwen2.5:7b | raw | holdout | python-topological-order | 1/3 (33.3%) | 16.20 | 6.94 |
| qwen2.5:7b | raw | holdout | python-roman-strict | 0/3 (0.0%) | 13.14 | 7.25 |
| qwen2.5:7b | raw | holdout | python-group-anagrams | 2/3 (66.7%) | 8.71 | 1.21 |
| qwen2.5:7b | raw | holdout | python-edit-csv-quote | 2/3 (66.7%) | 1.90 | 0.02 |
| qwen2.5:7b | raw | holdout | python-fix-binary-search | 3/3 (100.0%) | 5.96 | 0.77 |
| qwen2.5:7b | raw | holdout | python-normalize-ranges | 0/3 (0.0%) | 12.18 | 0.12 |
| qwen2.5:7b | raw | holdout | vba-last-row | 3/3 (100.0%) | 7.27 | 2.44 |
| qwen2.5:7b | raw | holdout | office-script-fill-empty | 0/3 (0.0%) | 22.82 | 2.99 |
| qwen2.5:7b | raw | holdout | vbnet-frequency | 3/3 (100.0%) | 11.73 | 0.02 |
| qwen2.5:7b | raw | holdout | json-nested-schema | 1/3 (33.3%) | 1.41 | 0.00 |
| knightagent-automation:latest | raw | development | python-count-even | 3/3 (100.0%) | 18.58 | 0.59 |
| knightagent-automation:latest | agent | development | python-count-even | 1/3 (33.3%) | 58.77 | 171.37 |
| knightagent-automation:latest | raw | development | python-merge-intervals | 0/3 (0.0%) | 21.95 | 34.94 |
| knightagent-automation:latest | raw | development | python-fix-clamp | 3/3 (100.0%) | 14.68 | 28.71 |
| knightagent-automation:latest | agent | development | python-fix-clamp | 1/3 (33.3%) | 63.06 | 940.11 |
| knightagent-automation:latest | raw | development | vba-copy-values | 3/3 (100.0%) | 21.85 | 1.81 |
| knightagent-automation:latest | agent | development | vba-copy-values | 0/3 (0.0%) | 68.44 | 33.42 |
| knightagent-automation:latest | raw | development | vbnet-double | 3/3 (100.0%) | 11.32 | 15.44 |
| knightagent-automation:latest | raw | development | office-script-copy | 3/3 (100.0%) | 14.64 | 4.37 |
| knightagent-automation:latest | raw | holdout | python-edit-join | 3/3 (100.0%) | 12.05 | 6.09 |
| knightagent-automation:latest | agent | holdout | python-edit-join | 2/3 (66.7%) | 104.74 | 72.10 |
| knightagent-automation:latest | raw | holdout | json-exact-format | 1/3 (33.3%) | 10.35 | 1.60 |
| knightagent-automation:latest | agent | holdout | json-exact-format | 3/3 (100.0%) | 33.88 | 35.94 |
| knightagent-automation:latest | raw | holdout | python-topological-order | 2/3 (66.7%) | 33.34 | 39.77 |
| knightagent-automation:latest | raw | holdout | python-roman-strict | 0/3 (0.0%) | 21.04 | 0.91 |
| knightagent-automation:latest | raw | holdout | python-group-anagrams | 3/3 (100.0%) | 17.51 | 21.35 |
| knightagent-automation:latest | raw | holdout | python-edit-csv-quote | 3/3 (100.0%) | 3.85 | 2.42 |
| knightagent-automation:latest | raw | holdout | python-fix-binary-search | 3/3 (100.0%) | 11.62 | 0.74 |
| knightagent-automation:latest | raw | holdout | python-normalize-ranges | 0/3 (0.0%) | 25.04 | 16.48 |
| knightagent-automation:latest | raw | holdout | vba-last-row | 3/3 (100.0%) | 12.77 | 3.78 |
| knightagent-automation:latest | raw | holdout | office-script-fill-empty | 0/3 (0.0%) | 19.70 | 1.62 |
| knightagent-automation:latest | raw | holdout | vbnet-frequency | 3/3 (100.0%) | 14.89 | 1.16 |
| knightagent-automation:latest | raw | holdout | json-nested-schema | 0/3 (0.0%) | 1.60 | 0.01 |

Skipped checks:
- .NET SDK unavailable inside the isolated benchmark
- Excel/VBA COM runtime/compiler not available in the isolated benchmark
- ExcelScript type declarations unavailable in isolated benchmark
