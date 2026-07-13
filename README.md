# What is AI Safety Anyway? Conceptualizing AI Safety with a Longitudinal Analysis in Academia

This is the code repository for a Stanford student research project on a longtidunal analysis of academic publications on AI safety that was co-authored by Ren Jie (RJ) Teoh, Ella Genasci Smith and Tyler Lenox Smith, and supervised by Dr. Max Lamparth. 

Tyler wrote the files in `analysis/co-occurrence/` and the initial implementation of `scrapers/paper_subscrapers/facct_scraper.py`. All other code in this repo was written by RJ. Please approach RJ at rjteoh@alumni.stanford.edu for any questions about this repo and the project code.

## Project Structure

The repo follows the pipeline: **scrape → classify → analyze**. Code lives in folders
by stage, and data lives in dedicated `input_data/` and `output_data/` folders (see
[Data Organization](#data-organization)).

```
ai-safety-project/
├── analysis/                  # R analysis scripts, one folder per analysis (each writes its own output_data/ subfolder)
│   ├── co-occurrence/             # analysis_cooc.R — year-over-year co-occurrence between safety categories (per-category plots + tables)
│   ├── iclr_acceptance/           # analysis_acceptance.R — are safety papers accepted at different rates? (ICLR)
│   ├── robustness_test/           # robustness_analysis.R — classifier vs. human labels + inter-coder reliability
│   └── safety_trends/             # analysis_safety.R — safety output vs. big-tech sponsorship; summary stats for all conferences
├── classifiers/               # LLM classification of the scraped data
│   ├── prompts/                   # Prompt sets (JSON) the classifiers use (old_prompts/ kept for reference)
│   ├── abstract_classifier.py     # Labels each paper for safety relevance, then sorts safety papers by harm/safety category
│   └── sponsor_classifier.py      # Labels each sponsor as "big tech" and maps it to a parent firm
├── input_data/                # Human-curated inputs (see Data Organization)
│   ├── facct/                     # FAccT proceedings as BibTeX (facct2021–2025.bib); FAccT abstracts are parsed from these
│   ├── naacl/                     # Drop the downloaded NAACL anthology bib here as aacl_anthology.bib (see Replication)
│   ├── test_data/                 # Held-out test set + the human coders' raw labels and the agreed human ground truth
│   └── big-tech-list.csv          # Canonical list of firms that count as "big tech" (used by the sponsor classifier)
├── output_data/               # Everything the pipeline generates (see Data Organization)
├── paper_figures/             # Final figures & tables that made it into the paper (appendix/ holds appendix tables)
├── scrapers/                  # Web scrapers that collect the raw paper & sponsor data
│   ├── paper_subscrapers/         # Per-conference paper scrapers (iclr, icml, neurips, naacl, facct)
│   ├── sponsor_subscrapers/       # Per-conference sponsor scrapers
│   ├── iclr_reject_scraper.py     # Pulls ICLR rejected/withdrawn papers (the master scraper only collects accepted ones)
│   ├── paper_scraper.py           # Master: runs each conference paper sub-scraper, combines into one abstracts CSV
│   └── sponsor_scraper.py         # Master: runs each conference sponsor sub-scraper across a range of years
├── utils/                     # Helper scripts and shared utilities
│   ├── merge_human.R              # Merges the three coders' labels into ground truth by majority vote
│   ├── remove_test_abstracts.py   # Strips the held-out test set before classification
│   ├── sampler.py, search_abstracts.py  # Ad-hoc tools to sample/search the abstract pool
│   └── uid_utils.py               # Content-derived UID helpers (+ standalone re-keying tool)
├── install_packages.R         # R dependencies
├── requirements.txt           # Python dependencies
```

## Data Organization

Data is split into three top-level folders by role, so it is always clear what a
maintainer supplies by hand versus what the code regenerates:

- **`input_data/`** — every human-curated input the code reads but never writes:
  `big-tech-list.csv`, FAccT/NAACL BibTeX files, and the test set + raw coder
  labels under `test_data/`.
- **`output_data/`** — everything the pipeline generates, in stage subfolders:
  `scrapers/` (raw scraped `abstracts.csv`, `sponsors.csv`), `classifiers/` (the
  LLM-labelled `abstracts-classified.csv`, `sponsors-classified.csv`, …), and
  `analysis/` (the stats, CSVs, and HTML tables each R script produces).
- **`paper_figures/`** — the final figures and tables that made it into the paper,
  with `paper_figures/appendix/` holding the appendix tables.

Generated outputs are deliberately kept in `output_data/` rather than next to each script to avoid confusion. Every script anchors its paths to the repo root (via [`here`](https://here.r-lib.org/) in R, or each file's own location in Python), so paths resolve no matter what directory
you run from; Python scripts also accept `-i`/`-o` overrides.

**A note on `old_*` folders.** A few spots in the repo preserve material from an
earlier version of our classification prompts, kept for reference in case anyone wants
to revisit those results: `classifiers/prompts/old_prompts/` holds the old prompt
sets, `output_data/classifiers/old_prompt_data/` holds datasets classified with
them, and `output_data/analysis/robustness_test/old_results/` holds old results
of robustness tests performed with the older prompts/different model comparisons. 

## Installation

The pipeline uses **both Python** (scraping + classification) **and R** (analysis), so
install both sets of dependencies:

```bash
pip install -r requirements.txt              # Python deps
Rscript -e 'source("install_packages.R")'    # R deps (or run install_packages.R in RStudio)
```

The classifiers also need a repo-root `.env` file with a CHECKPOINT variable and your OpenAI API key. Copy the provided template and fill in your values (`.env` is gitignored by default to avoid committing keys).

## Replication

The full pipeline is **scrape → classify → analyze**. The repo already ships with the
scraped and classified data under `output_data/`, so if you only want to reproduce the
paper's figures and tables you can skip straight to [Step 4](#step-4--run-the-analysis).
The steps below regenerate everything from scratch.

All commands are run **from the repo root**. Install the dependencies and create your
`.env` first (see [Installation](#installation)).

### Step 1 — Download the NAACL abstracts

NAACL abstracts come from a BibTeX export that was too big to include on GitHub. Download
https://aclanthology.org/anthology+abstracts.bib.gz, extract the `.bib`, place it in
`input_data/naacl/`, and rename it `aacl_anthology.bib` (the paper scraper looks for it
at exactly `input_data/naacl/aacl_anthology.bib`). If it's missing, NAACL is silently
skipped.

### Step 2 — Run the scrapers

```bash
# Papers (uses the NAACL bib from Step 1)  -> output_data/scrapers/abstracts.csv
python3 scrapers/paper_scraper.py

# ICLR rejected + withdrawn papers  -> output_data/scrapers/iclr-rejected.csv, iclr-withdrawn.csv
python3 scrapers/iclr_reject_scraper.py
python3 scrapers/iclr_reject_scraper.py -t withdraw

# Sponsors  -> output_data/scrapers/sponsors.csv
python3 scrapers/sponsor_scraper.py
```

> **Note: scraping can be temperamental.** The scrapers are reasonably durable, but web
> scraping is inherently fragile and rate limiting can break a run — just re-run if one
> fails. See the `scrapers/paper_scraper.py` docstring for a possible future
> reimplementation.

### Step 3 — Run the classifiers

```bash
# Main abstracts  -> output_data/classifiers/abstracts-classified.csv
python3 classifiers/abstract_classifier.py

# Held-out test set (needed by the robustness analysis)  -> test-set-classified.csv
python3 classifiers/abstract_classifier.py --test

# ICLR rejected + withdrawn (needed by the acceptance analysis)
python3 classifiers/abstract_classifier.py -i output_data/scrapers/iclr-rejected.csv  -o output_data/classifiers/iclr-rejects-classified.csv
python3 classifiers/abstract_classifier.py -i output_data/scrapers/iclr-withdrawn.csv -o output_data/classifiers/iclr-withdrawn-classified.csv

# Sponsors  -> output_data/classifiers/sponsors-classified.csv
python3 classifiers/sponsor_classifier.py
```

> **Note: the classification step is very slow.** Each abstract is an LLM call (the
> safety pass plus a pass per category), so a full run of `abstract_classifier.py`
> over all conferences takes around 48 hours and uses around 85 million tokens. 
> The classifier checkpoints as it goes and is resumable, so an interrupted run picks up 
> where it left off. Because `CHECKPOINT` tracks progress by row position and is shared across
> runs, **reset `CHECKPOINT=0` in `.env` before starting each new input file** (and make
> sure that input's output CSV doesn't already exist, or the new rows get appended to
> the old file).

### Step 4 — Run the analysis

```bash
Rscript analysis/safety_trends/analysis_safety.R         # safety output vs. big-tech sponsorship
Rscript analysis/iclr_acceptance/analysis_acceptance.R   # ICLR safety-paper acceptance rates
Rscript analysis/robustness_test/robustness_analysis.R   # classifier vs. human labels
Rscript analysis/co-occurrence/analysis_cooc.R           # issue co-occurrence rates
```

Outputs land in `output_data/analysis/` (stats, CSVs, HTML tables) and `paper_figures/`
(the publication-ready figures and tables).

> **Note: file paths are hardcoded.** Most scripts read and write canonical filenames
> baked into path variables at the top of the file (and the R analysis scripts read
> their inputs by fixed name). The commands above use those canonical names, so they
> chain together as-is. If you rename anything mid-pipeline, you'll need to open the
> downstream scripts and update the corresponding path variables to match.

## Paper Figures & Tables Reference
> All paths are relative to `paper_figures/`. Files in `appendix/` are the appendix
> tables; everything else is a main-paper figure or table. 

### From `analysis/safety_trends/analysis_safety.R`

General analysis script.

| File | What it is | Paper # |
| --- | --- | --- |
| `safety_trends.pdf` | Line plot: % of papers classified safety-related over time, by conference (with classifier-error band) | Figure 1 |
| `category_trends_harm_pct.pdf` | Line plot: harm-area categories as % of safety papers over time | Figure 2 |
| `category_trends_issue_pct.pdf` | Line plot: issue-area categories as % of safety papers over time | Figure 3 |
| `safety_allsponsors.tex` | Two-way fixed-effects panel regression of safety rate on big-tech sponsor share | Table 3 |
| `appendix/safety_allsponsors_byconference.tex` | Per-conference OLS of safety rate on big-tech share (NeurIPS, ICML, ICLR, NAACL, FAccT) | Table 30 |
| `appendix/safetybyconference.tex` | Conference fixed-effects LPM comparing safety output across conferences (NeurIPS reference) | Table 29 |
| `appendix/summary_appendix.tex` | Year × conference percentage tables: top-level safety + all 11 categories, appended into one file | Table 17-28 |

> **Note on `safety_trends.pdf`:** this is the only plot with a broken y-axis
> (`ggbreak::scale_y_break`). ggbreak has a known bug that sometimes causes figures 
> to print with a blank first page. You'll need to extract the second page by hand 
> before uploading to the paper body. 

### From `analysis/iclr_acceptance/analysis_acceptance.R`

ICLR safety vs. non-safety paper acceptance.

| File | What it is | Paper # |
| --- | --- | --- |
| `acceptance_by_year.pdf` | Line plot: per-year coefficient of safety on acceptance, with measurement-error band | Figure 7 |
| `acceptance_regression.tex` | Linear probability model of acceptance on the safety flag (accepted + rejected) | Table 4 |
| `appendix/acceptance_regression_withdrawn.tex` | Same LPM re-fit with withdrawn submissions counted as not accepted | Table 29 |

### From `analysis/robustness_test/robustness_analysis.R`

Classifier-vs-human agreement on the held-out validation set.

| File | What it is | Paper # |
| --- | --- | --- |
| `robustnesscm_main.tex` | Confusion-matrix tables (+ caret metrics) for binary safety and overall category assignment | Table 1-2 |
| `appendix/robustnesscm.tex` | Per-category confusion-matrix tables (+ caret metrics), two side-by-side per table | Table 5-15 |

### From `analysis/co-occurrence/analysis_cooc.R`

Year-over-year co-occurrence between safety categories.

> **TODO:** To update once Tyler has edited his code to regenerate the specific figures 
> reported in the paper. The script currently writes all per-category plots and tables to
> `output_data/analysis/co-occurrence/`; this table will be filled in once the
> code has been edited.

## Citation

The Neurips 2025 and ICLR rejected/withdrawn paper lists are sourced from the
[Paper Copilot](https://papercopilot.com/) project. If you use this repository, please
also cite Paper Copilot:

```bibtex
@inproceedings{Yang2026,
  author    = {Yang, Jing and Wei, Qiyao and Pei, Jiaxin},
  title     = {Paper Copilot: Tracking the Evolution of Peer Review in {AI} Conferences},
  booktitle={The Fourteenth International Conference on Learning Representations},
  year={2026},
  url={https://openreview.net/forum?id=CyKVrhNABo}
}
```

## License

Released under the MIT License — see [`LICENSE.txt`](LICENSE.txt). © 2025 Ren Jie Teoh.
