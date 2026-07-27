# OpenAlex Field Audit — Week 1

**Date:** 2026-07-24  
**Data source:** `data/samples/openalex_stellar_spectra_100.csv`  
**Records audited:** 100 (full dataset), spot-check first 20  
**Auditor:** W1 field audit

---

## 1. Objective

Audit all 9 key metadata fields across the 100-record OpenAlex sample for completeness, quality, and fitness for the next pipeline phase. All findings come from real data; nothing is fabricated or imputed.

---

## 2. Data Source & Pipeline Context

The CSV was produced by `app/main.py` → `src/openalex_client.py` → `src/processor.py`, querying OpenAlex with `"machine learning stellar spectra"`. The pipeline extracts 11 metadata fields plus 5 scoring columns. This audit covers the 9 core metadata fields:

| # | Field | OpenAlex Source | Processor Treatment |
|---|-------|----------------|---------------------|
| 1 | `title` | `work.display_name` | `clean_text()` — strip whitespace |
| 2 | `authors` | `work.authorships[].author.display_name` | `clean_authors()` — join with `"; "` |
| 3 | `publication_year` | `work.publication_year` | `clean_int()` — None on parse failure |
| 4 | `doi` | `work.doi` | `normalize_doi()` — lowercase, strip prefix |
| 5 | `abstract` | `work.abstract_inverted_index` | `rebuild_abstract()` — word-order reconstruction |
| 6 | `cited_by_count` | `work.cited_by_count` | `clean_int()` |
| 7 | `source_name` | `work.primary_location.source.display_name` | `clean_text()` |
| 8 | `openalex_id` | `work.id` | `clean_text()` |
| 9 | `landing_page_url` | `work.primary_location.landing_page_url` | `clean_text()` |

---

## 3. Spot Check — First 20 Records

All 20 records were checked individually. A summary of findings:

| Row | OpenAlex ID | title | authors | year | doi | abstract | cited | source | landing |
|-----|-------------|-------|---------|------|-----|----------|-------|--------|---------|
| 1 | W4395479208 | OK | OK | 2024 | OK | OK | 24 | MNRAS | OK |
| 2 | W4389097389 | OK | OK | 2023 | OK | OK | 4 | MNRAS | OK |
| 3 | W3161623437 | OK | OK | 2021 | OK | OK | 6 | arXiv | OK |
| 4 | W4200631758 | OK | OK | 2022 | OK | OK | 21 | AJ | OK |
| 5 | W4319592221 | OK | OK | 2023 | OK | OK | 26 | JCAP | OK |
| 6 | W4389613706 | OK | OK | 2023 | OK | OK | 8 | JCAP | OK |
| 7 | W3081618654 | OK | OK | 2020 | OK | OK | 24 | MNRAS | OK |
| 8 | W2907474932 | OK | OK | 2019 | OK | OK | 53 | A&A | OK |
| 9 | W4387321945 | OK | OK | 2023 | OK | OK | 27 | MNRAS | OK |
| 10 | W3036313178 | OK | OK | 2020 | OK | OK | 15 | MNRAS | OK |
| 11 | W4284892148 | OK | OK | 2022 | OK | OK | 4 | arXiv | OK |
| 12 | W4281823699 | OK | OK | 2022 | OK | OK | 28 | LA Referencia | OK |
| 13 | W4319662832 | OK* | OK | 2023 | OK | OK | 15 | A&A | OK |
| 14 | W4384942767 | OK | OK | 2023 | OK | OK | 13 | RAA | OK |
| 15 | W2206825795 | OK | OK | 2015 | OK | OK | 13 | MNRAS | OK |
| 16 | W4384201335 | OK | OK | 2023 | OK | OK | 67 | Living Rev. Sol. Phys. | OK |
| 17 | W4223474580 | OK | OK | 2022 | OK | OK | 20 | ApJS | OK |
| 18 | W3155899199 | **OFF-TOPIC** | OK | 2021 | OK | OK | 174 | IEEE Access | OK |
| 19 | W4388221752 | **OFF-TOPIC** | OK | 2023 | OK | OK | 54 | Sensors | OK |
| 20 | W4225314923 | OK | OK | 2022 | OK | OK | 16 | arXiv | OK |

_* Row 13 has HTML `<i>` tags in the title — see anomaly section._

**Key observations from the first 20:**
- 2 out of 20 (10%) are clearly off-topic for "machine learning stellar spectra"
- All core fields present for all 20 (no missing title/authors/year/doi/abstract/cited/source in the first 20)
- One title contains HTML markup (`<i>` tags)

---

## 4. Missing Field Counts & Rates (All 100 Records)

| Field | Missing Count | Missing Rate |
|-------|:------------:|:------------:|
| `title` | 0 | 0.0% |
| `authors` | 0 | 0.0% |
| `publication_year` | 0 | 0.0% |
| `openalex_id` | 0 | 0.0% |
| `cited_by_count` | 0 | 0.0% |
| `landing_page_url` | 1 | 1.0% |
| `source_name` | 2 | 2.0% |
| `doi` | 4 | 4.0% |
| `abstract` | 4 | 4.0% |

### Records with missing fields:

| Row | OpenAlex ID | Missing Fields |
|-----|-------------|----------------|
| 34 | W3101015041 | landing_page_url |
| 40 | W2098458655 | doi, source_name |
| 41 | W3101896622 | doi |
| 47 | W4363678967 | abstract |
| 54 | W3099811482 | doi, source_name |
| 76 | W3034089264 | abstract |
| 80 | W4381612653 | abstract |
| 82 | W2078829410 | abstract |
| 100 | W3124281728 | doi |

### Reproducibility

To verify these counts:

```powershell
python -c "
import csv
path = r'data\samples\openalex_stellar_spectra_100.csv'
with open(path, 'r', encoding='utf-8-sig') as f:
    rows = list(csv.DictReader(f))
fields = ['title','authors','publication_year','doi','abstract',
          'cited_by_count','source_name','openalex_id','landing_page_url']
for field in fields:
    missing = sum(1 for r in rows if not str(r.get(field,'')).strip())
    print(f'{field}: {missing}/100 ({missing}%)')
"
```

---

## 5. Anomalous & Representative Records

### 5.1 Off-Topic Papers (Keyword Pollution)

The search query `"machine learning stellar spectra"` returns 4-word results that match any subset of terms. OpenAlex does not enforce semantic relevance.

| OpenAlex ID | Title | Citations | Problem |
|-------------|-------|:---------:|---------|
| W3155899199 | Machine Learning Based Automatic Modulation Recognition for Wireless Communications | 174 | Wireless communication signals; no astronomy |
| W4388221752 | Machine Learning Model for Leak Detection Using Water Pipeline Vibration Sensor | 54 | Water pipeline; matches "vibration" |
| W2406349003 | A survey of machine learning for big data processing | 891 | Generic ML survey; no astronomy |
| W4363678967 | A Novel Approach Utilizing Machine Learning for the Early Diagnosis of Alzheimer's Disease | 91 | Biomedical; no astronomy; also missing abstract |
| W4306248068 | Machine learning in electron microscopy for advanced nanocharacterization | 124 | Materials science; no astronomy |
| W2084341220 | Statistical Modeling: The Two Cultures | 4300 | Pure statistics classic; marginal relevance |

**Impact:** Off-topic papers with high citations (Breiman at 4300, big-data survey at 891) inflate `impact_score` disproportionately and can dominate rankings.

### 5.2 Missing DOI (4 papers)

| OpenAlex ID | Title | Year | Also Missing |
|-------------|-------|------|-------------|
| W2098458655 | Prediction of stellar atmospheric parameters from spectra, spectral indices and spectral lines using machine learning | 2001 | source_name |
| W3101896622 | A Machine Learning Method to Infer Fundamental Stellar Parameters from Photometric Light Curves | 2014 | — |
| W3099811482 | An Active Instance-based Machine Learning method for Stellar Population Studies | 2005 | source_name |
| W3124281728 | Testing the chemical tagging technique with open clusters | 2015 | — |

All four are repository/preprint papers (CiteSeerX, CaltechAUTHORS). The `landing_page_url` is present for all 4, pointing to institutional repositories instead of DOIs. These 4 papers receive a ~16.7% penalty in `completeness_score`.

### 5.3 Missing Abstract (4 papers)

| OpenAlex ID | Title | Year | Citations | Source |
|-------------|-------|------|:---------:|--------|
| W4363678967 | Alzheimer's Disease diagnosis (off-topic) | 2023 | 91 | Biomed. Materials & Devices |
| W3034089264 | Atmospheric parameter measurement of Low-S/N stellar spectra based on deep learning | 2020 | 7 | Optik |
| W4381612653 | A calibration point for stellar evolution from massive star asteroseismology | 2023 | 57 | Nature Astronomy |
| W2078829410 | Classification of Spectra of Emission Line Stars Using Machine Learning Techniques | 2014 | 47 | Int. J. Automation & Computing |

**Notable:** W4381612653 is a Nature Astronomy paper with 57 citations yet has no abstract in this dataset — likely OpenAlex did not reconstruct the inverted index. This is a quality gap for a paper that would otherwise be highly relevant.

### 5.4 HTML/Markup in Titles

Several titles contain HTML tags from OpenAlex's `display_name` field:

| OpenAlex ID | Title Fragment |
|-------------|---------------|
| W4319662832 | The `<i>Gaia</i>`-ESO Survey... |
| W4320341265 | ...in `<scp>ppxf</scp>`: stellar... |
| W2139768786 | ...for 35`<i>Kepler</i>`solar-type... |

The processor's `clean_text()` does not strip HTML tags (`<i>`, `<scp>`, `</i>`, `</scp>`). This affects text matching, display, and potentially downstream NLP tokenization.

### 5.5 Citation Outliers

| OpenAlex ID | Citations | Title | Relevance |
|-------------|:---------:|-------|-----------|
| W2084341220 | 4300 | Statistical Modeling: The Two Cultures | Marginal (classic statistics) |
| W2740236269 | 1051 | SDSS Fourteenth Data Release | High (survey data) |
| W2406349003 | 891 | A survey of ML for big data processing | Low (generic) |
| W3017279354 | 543 | Painting a portrait of the Galactic disc | High (stellar clusters) |
| W2920947047 | 398 | ML in Space Weather | Medium |
| W2905331806 | 353 | SDSS Fifteenth Data Release | High |

The `impact_score` formula uses `log1p(cited_by_count) / max_log1p` within each batch. With Breiman at 4300, `max_log1p` ≈ 8.37, compressing scores for papers with <100 citations into a narrow range near 0.55.

### 5.6 Abstract Quality Issues

- **"ABSTRACT" / "Abstract" prefix**: Rows 1, 2, 7, 8, 9, 10, 12, 13, 14, 16, 17, 20 and others contain the literal string "ABSTRACT" or "Abstract" at the start of the abstract field. OpenAlex reconstruction preserves this from certain source formats.
- **HTML entities**: Some abstracts contain `&amp;lt;` and similar entities (e.g., row 1).
- **Empty abstracts**: 4 papers (4%) have no abstract at all.

---

## 6. Fitness for Next Phase

### Current phase (v0.2) — Adequate

The 9 fields are sufficient for Phase 1 MVP operations: dedup by DOI/title, preliminary scoring, and basic charts. Missing rates are low (0–4%).

### Next phase (v0.3+) — Gaps identified

| Concern | Severity | Mitigation Needed |
|---------|:--------:|-------------------|
| **HTML in titles** | Medium | Add `re.sub(r'<[^>]+>', '', title)` to `clean_text()` |
| **Off-topic papers** | High | Add a keyword-relevance gate or domain classifier before scoring; ~6% of dataset is off-topic |
| **Missing DOI enrichment** | Low | 4% missing; could add Crossref reverse-lookup for papers with title+year but no DOI |
| **Abstract quality** | Medium | Strip "ABSTRACT" prefix; decode HTML entities; 4% missing rate is acceptable but should not grow |
| **No topic/subject field** | Medium | OpenAlex `concepts` field is not currently fetched. Adding it would enable subject-based filtering (e.g., require `Physics` or `Astronomy` concept) |
| **No publication type** | Low | Cannot distinguish journal articles from preprints (arXiv) or conference proceedings |
| **Citation outlier bias** | Low | `log1p` normalization helps but extreme outliers still compress the distribution |
| **No language field** | Low | Some papers may be non-English; no language metadata currently captured |
| **BOM in CSV** | Low | The output CSV starts with a UTF-8 BOM (`\ufeff`). Tools using `utf-8-sig` handle it, but `csv.DictReader` with plain `utf-8` reads the first column key as `\ufefftitle`. |

### Recommendation

The current 9-field schema is **mostly sufficient** for the next phase, with two actionable fixes:

1. **HTML tag stripping in `clean_text()`** — trivial fix, high impact for NLP downstream
2. **Add `concepts` field from OpenAlex** — small code change, enables topic filtering that would eliminate off-topic papers

These two changes address the most impactful quality gaps without adding complexity.

---

## 7. Deliverables

| File | Path |
|------|------|
| Audit report (this file) | `docs/reports/week1/openalex_field_audit_w1.md` |
| Anomaly records CSV | `data/analysis/openalex_field_audit_w1.csv` |

---

## 8. Verification Checklist

- [x] At least 20 records spot-checked (first 20)
- [x] All conclusions backed by actual CSV data
- [x] Missing counts and rates independently reproducible (see Section 4)
- [x] All anomaly records retain OpenAlex ID
- [x] No fields artificially created or imputed
- [x] Source code (`openalex_client.py`, `processor.py`) reviewed for field extraction logic
