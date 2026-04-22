# PDF → Markdown pipeline (GPN hackathon)

Конвейер преобразования PDF в Markdown для хакатона «Газпромнефть». Основан
на [Docling](https://github.com/DS4SD/docling); сверху накручены
постпроцессоры, выравнивающие вывод под формат эталонной разметки.

## Архитектура

```
 ┌────────────┐    ┌──────────────────┐    ┌───────────────────────────┐
 │ pdfs/*.pdf │ -> │ pipeline.convert │ -> │ pipeline.postprocess.*    │
 └────────────┘    │  (Docling)       │    │  images / headers_footers │
                   └──────────────────┘    │  tables / headings        │
                                           └───────────────────────────┘
                                                      │
                                                      v
                                          ┌───────────────────────────┐
                                          │ output/document_NNN.md    │
                                          │ output/images/doc_..png   │
                                          └───────────────────────────┘
                                                      │
                                                      v
                                          ┌───────────────────────────┐
                                          │ pipeline.submission       │
                                          │   -> submission.zip       │
                                          └───────────────────────────┘
```

`pipeline.orchestrator.process_pdf` обрабатывает один PDF и применяет
постпроцессоры в фиксированном порядке:

1. `normalize_image_names` — переименование артефактов Docling в формат
   `doc_<id>_image_<k>.png`, требуемый организаторами.
2. `drop_table_images` — удаление картинок типа *image_with_table*: в эталоне
   остаётся только текст таблицы, без `![…](images/…)`.
3. `dedupe_image_links` — снятие повторных ссылок на одну и ту же PNG
   (бывает на разрыве страниц).
4. `reorder_figure_captions` — приведение порядка `подпись → картинка` к
   эталонному `картинка → подпись`.
5. `strip_running_matter` — фильтрация колонтитулов, водяных знаков
   («ЧЕРНОВИК», `DRAFT`, …) и голых номеров страниц.
6. `split_merged_tables` — разбивка таблиц, склеенных Docling в один блок.
7. `drop_inner_separator_rows` — удаление лишних `| --- |`-строк в середине
   таблицы.
8. `repair_tables` — склейка слов, разорванных переносом строки внутри узких
   ячеек (используется морфословарь pymorphy3 + английский spellchecker).
9. `normalize_table_whitespace` — приведение широких ячеек Docling к
   компактному виду `| x | y |`.
10. `restore_heading_levels` — восстановление иерархии `#`/`###`/`####`,
    которую Docling схлопывает в плоское `##`.
11. `restore_em_dash_in_headings` — замена ` - ` на ` — ` в заголовках.
12. `unescape_html_entities` — раскодирование `&amp;` и других сущностей.
13. `lowercase_default_image_alt` — `![Image]` → `![image]` под формат эталона.

## Структура проекта

```
pipeline/
├── convert.py                 # обёртка над Docling, ConverterConfig
├── orchestrator.py            # процесс одного PDF целиком
├── submission.py              # упаковка output/ в zip
└── postprocess/
    ├── images.py              # переименование, дедупликация, подписи
    ├── headers_footers.py     # колонтитулы, водяные знаки, номера страниц
    ├── tables.py              # склейка слов, разбивка, нормализация
    └── headings.py            # уровни заголовков, em dash, html entities

scripts/
├── run.py                     # основной CLI (полный прогон)
└── reprocess.py               # переприменить постпроцессоры к готовому output/
```

## Установка

Требуется **Python 3.10–3.12** (Docling пока не поддерживает 3.13+).

```bash
py -3.10 -m venv .venv
.venv/Scripts/python.exe -m pip install -U pip wheel
.venv/Scripts/python.exe -m pip install -r requirements.txt
```

При первом запуске Docling скачает веса RapidOCR (~40 МБ) и TableFormer
в кэш Hugging Face.

## Запуск

```bash
# Полный прогон по всем PDF в pdfs/ + сборка submission.zip
.venv/Scripts/python.exe -m scripts.run \
    --input-dir pdfs \
    --output-dir output \
    --device cpu \
    --zip submission.zip

# Smoke-test на первых пяти файлах
.venv/Scripts/python.exe -m scripts.run \
    --input-dir pdfs \
    --output-dir output \
    --max-files 5

# Возобновить прерванный прогон
.venv/Scripts/python.exe -m scripts.run \
    --input-dir pdfs \
    --output-dir output \
    --skip-existing
```

### Флаги CLI

| Флаг | Назначение |
|------|------------|
| `--input-dir` | каталог с входными PDF (обязателен) |
| `--output-dir` | каталог для Markdown + images/ (обязателен) |
| `--max-files N` | обработать только первые N файлов |
| `--skip-existing` | пропустить PDF, для которых `.md` уже есть |
| `--device {auto,cpu,cuda,mps}` | устройство для Docling |
| `--fast` | TableFormer FAST + меньшее image-scale |
| `--no-ocr` | отключить OCR |
| `--no-table-structure` | отключить TableFormer |
| `--zip path.zip` | по завершении упаковать вывод в zip |

### Переприменить постпроцессоры без повторного Docling

Если меняется только логика постпроцессинга, не нужно гнать Docling
заново — все постпроцессоры идемпотентны:

```bash
.venv/Scripts/python.exe -m scripts.reprocess --output-dir output
```

### Аппаратные заметки

* **NVIDIA GPU**: `--device cuda`, ~5–10× быстрее CPU.
* **AMD GPU на Windows**: ROCm/CUDA не поддерживается, только `--device cpu`,
  ~15 с/PDF после прогрева моделей.
* **Apple Silicon**: `--device mps`.

## Формат вывода

```
output/
├── document_001.md
├── document_002.md
├── ...
└── images/
    ├── doc_1_image_1.png
    ├── doc_1_image_2.png
    └── ...
```

`--zip` собирает архив с теми же файлами в корне плюс `images/` — без
посторонних файлов (требование задачи).

## Ограничения задачи

* Только open-source модели с открытыми весами; никаких облачных API.
* Лицензии Apache-2.0 / MIT и совместимые.
* ≤ 1 GPU, ≤ 40 ГБ VRAM.
* Растровые/сканированные/рукописные блоки: в эталоне только извлечённый
  текст, без `![…](images/…)` и без подписи `Рис.`.
