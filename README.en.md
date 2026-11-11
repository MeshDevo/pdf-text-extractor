# Local PDF Pipeline — From PDF to TXT

A fully local pipeline: drop PDF files into `input/`, run it, and find TXT files in `output/`. No server, no internet, no uploads. The quick single-file versions (the web page and the earlier `pdf2txt.py` script) remain available for one-off use; this pipeline is the tool for batches and repeated work.

## Run (two steps)

```bash
# 1) Put PDF files in input/
# 2) Run:
./run.sh
```

On first run, `run.sh` creates a virtual environment `.venv` and installs the only dependency (PyMuPDF). Later runs are instant.

## The five stages (in order)

| # | Stage | What it does |
|---|---|---|
| 1 | `intake` | Discovers PDF files: one file or a whole folder (recursive), in alphabetical order |
| 2 | `extract` | Extracts text with PyMuPDF, separating the two columns (left column fully, then right) |
| 3 | `clean` | Conservative cleaning only: dehyphenates split words, trims trailing spaces, collapses blank lines |
| 4 | `write` | Writes UTF-8 TXT, preserving the relative folder structure |
| 5 | `report` | Writes `output/manifest.json`, updates `pipeline-state.json`, prints a summary |

## Resume

The pipeline stores a `sha256` hash of every file in `pipeline-state.json` (project root). On the next run it skips every unchanged file (`[SKIP]`) and processes only new or changed files. `--force` reprocesses everything.

## Commands

```bash
./run.sh                      # One batch run
./run.sh --watch 10           # Watch mode: check input/ every 10 seconds until Ctrl+C
./run.sh paper.pdf            # One file → output/paper.txt
./run.sh --input docs --output out   # Custom folders
./run.sh --page-markers       # Insert a "--- Page N ---" line between pages
./run.sh --force              # Reprocess everything
./run.sh --self-test          # Self-test (generates 3 files, verifies, then cleans up)
```

## Outputs

- `output/<name>.txt` — Full text of each paper, with the input folder structure preserved.
- `output/manifest.json` — Record of the last run: source, hash, pages, characters, words, status (`done` / `skipped` / `empty` / `failed`), warnings.
- `pipeline-state.json` — The pipeline's permanent state for resuming.

## Dependencies

| Library | Role | Install |
|---|---|---|
| **PyMuPDF** (only required one) | Text extraction and column separation | `pip install -r requirements.txt` (automatic via `run.sh`) |
| pypdf (fallback only) | Used automatically if PyMuPDF is missing | Usually not needed |

## Known limits

- A scanned PDF with no text layer produces an empty TXT with status `empty` and a warning in the manifest; OCR is needed first, which is outside this lightweight pipeline.
- No image extraction, no table-to-table conversion, no reference formatting — plain text only.
- Column order is a geometric heuristic that works for the common two-column layout; rare layouts may order differently.
- Chinese (CJK) text: extracted in full, with wrapped lines rejoined inside a single column. A character may appear in a compatibility form (e.g. 行 instead of 行) if the file's own embedded font is Japanese — that comes from the font, not the extraction.
