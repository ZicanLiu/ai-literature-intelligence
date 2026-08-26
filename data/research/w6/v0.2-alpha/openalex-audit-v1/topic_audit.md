# W6 Post-Freeze OpenAlex Multi-Query Topic Robustness Audit

- Config identity: `w6-openalex-query-audit-config:sha256:9f312e242f3b9bed2d65da651a85620d38ece58b2ffa9e8fe7425a66f11926a4`
- Generated at: `2026-08-26T09:22:38+00:00`
- Topics / queries: 9 / 54
- Global unique works / query hits: 2977 / 4265
- Boundary: descriptive, label-free post-freeze evidence; not Topic selection or retrieval evaluation.

## Topic summary

| Topic | Union works | Target status | Multi-query works | Audit signals |
|---|---:|---|---:|---|
| `w6_topic_galaxy_activity_spectra` | 417 | above_preferred_within_soft_cap | 43 | none |
| `w6_topic_supernova_spectral_typing` | 386 | within_preferred_range | 64 | none |
| `w6_topic_exoplanet_atmospheric_retrieval` | 291 | within_preferred_range | 107 | none |
| `w6_topic_stellar_radial_velocity` | 406 | above_preferred_within_soft_cap | 58 | none |
| `w6_topic_spectral_anomaly_detection` | 386 | within_preferred_range | 58 | none |
| `w6_topic_stellar_spectral_denoising` | 408 | above_preferred_within_soft_cap | 48 | none |
| `w6_topic_stellar_spectral_emulation` | 414 | above_preferred_within_soft_cap | 53 | none |
| `w6_topic_solar_spectropolarimetric_inversion` | 379 | within_preferred_range | 65 | none |
| `w6_topic_21cm_foreground_removal` | 352 | within_preferred_range | 80 | none |

## Query evidence

### `w6_topic_galaxy_activity_spectra`

| Query variant | API hits | Retrieved | Unique contribution | Unique ratio | Union coverage |
|---|---:|---:|---:|---:|---:|
| `galaxy_activity_aq01` | 1624 | 80 | 51 | 0.6375 | 0.1918 |
| `galaxy_activity_aq02` | 225 | 80 | 73 | 0.9125 | 0.1918 |
| `galaxy_activity_aq03` | 69 | 69 | 64 | 0.9275 | 0.1655 |
| `galaxy_activity_aq04` | 1064 | 80 | 56 | 0.7000 | 0.1918 |
| `galaxy_activity_aq05` | 1508 | 80 | 60 | 0.7500 | 0.1918 |
| `galaxy_activity_aq06` | 618 | 80 | 70 | 0.8750 | 0.1918 |

- API-hit sum / retrieved hits / union / repeated hits: 5108 / 469 / 417 / 52
- Publication years: 2000–2026, median=2020, recent-five-year=168
- Abstract / DOI completeness: 0.9736 / 0.9688

Representative public works (descriptive ordering only):

- `W4296701857` (2022), support=4: The merger fraction of post-starburst galaxies in UNIONS
- `W4405197532` (2024), support=4: Galaxy Spectroscopy without Spectra: Galaxy Properties from Photometric Images with Conditional Diffusion Models
- `W2564202286` (2017), support=3: Theoretical Challenges in Galaxy Formation
- `W3030790048` (2020), support=3: AI in Medical Imaging Informatics: Current Challenges and Future Directions
- `W2554959913` (2016), support=3: The weirdest SDSS galaxies: results from an outlier detection algorithm

### `w6_topic_supernova_spectral_typing`

| Query variant | API hits | Retrieved | Unique contribution | Unique ratio | Union coverage |
|---|---:|---:|---:|---:|---:|
| `supernova_typing_aq01` | 1534 | 80 | 28 | 0.3500 | 0.2073 |
| `supernova_typing_aq02` | 9746 | 80 | 67 | 0.8375 | 0.2073 |
| `supernova_typing_aq03` | 2080 | 80 | 67 | 0.8375 | 0.2073 |
| `supernova_typing_aq04` | 823 | 80 | 58 | 0.7250 | 0.2073 |
| `supernova_typing_aq05` | 1794 | 80 | 33 | 0.4125 | 0.2073 |
| `supernova_typing_aq06` | 45904 | 80 | 69 | 0.8625 | 0.2073 |

- API-hit sum / retrieved hits / union / repeated hits: 61881 / 480 / 386 / 94
- Publication years: 2000–2026, median=2018.0, recent-five-year=97
- Abstract / DOI completeness: 0.9301 / 0.9974

Representative public works (descriptive ordering only):

- `W2921352493` (2019), support=6: DASH: Deep Learning for the Automated Spectral Classification of Supernovae and Their Hosts
- `W2147626801` (2013), support=5: LOFAR: The LOw-Frequency ARray
- `W2133620426` (2009), support=4: FIRST RESULTS FROM THE CATALINA REAL-TIME TRANSIENT SURVEY
- `W2911890654` (2019), support=4: The Zwicky Transient Facility: Science Objectives
- `W2292579160` (2016), support=4: PHOTOMETRIC SUPERNOVA CLASSIFICATION WITH MACHINE LEARNING

### `w6_topic_exoplanet_atmospheric_retrieval`

| Query variant | API hits | Retrieved | Unique contribution | Unique ratio | Union coverage |
|---|---:|---:|---:|---:|---:|
| `exoplanet_retrieval_aq01` | 296 | 80 | 16 | 0.2000 | 0.2749 |
| `exoplanet_retrieval_aq02` | 133 | 80 | 42 | 0.5250 | 0.2749 |
| `exoplanet_retrieval_aq03` | 313 | 80 | 25 | 0.3125 | 0.2749 |
| `exoplanet_retrieval_aq04` | 241 | 80 | 17 | 0.2125 | 0.2749 |
| `exoplanet_retrieval_aq05` | 136 | 80 | 40 | 0.5000 | 0.2749 |
| `exoplanet_retrieval_aq06` | 62 | 62 | 44 | 0.7097 | 0.2131 |

- API-hit sum / retrieved hits / union / repeated hits: 1181 / 462 / 291 / 171
- Publication years: 2009–2026, median=2023, recent-five-year=200
- Abstract / DOI completeness: 0.9553 / 0.9519

Representative public works (descriptive ordering only):

- `W4390748916` (2024), support=6: To Sample or Not to Sample: Retrieving Exoplanetary Spectra with Variational Inference and Normalizing Flows
- `W2805141721` (2018), support=5: ExoGAN: Retrieving Exoplanetary Atmospheres Using Deep Convolutional Generative Adversarial Networks
- `W3136101215` (2021), support=5: Aurora: A Generalized Retrieval Framework for Exoplanetary Transmission Spectra
- `W3015894544` (2020), support=5: Interpreting High-resolution Spectroscopy of Exoplanets using Cross-correlations and Supervised Machine Learning
- `W3020658478` (2020), support=5: Information Content of JWST NIRSpec Transmission Spectra of Warm Neptunes

### `w6_topic_stellar_radial_velocity`

| Query variant | API hits | Retrieved | Unique contribution | Unique ratio | Union coverage |
|---|---:|---:|---:|---:|---:|
| `stellar_rv_aq01` | 11727 | 80 | 65 | 0.8125 | 0.1970 |
| `stellar_rv_aq02` | 915 | 80 | 43 | 0.5375 | 0.1970 |
| `stellar_rv_aq03` | 1111 | 80 | 62 | 0.7750 | 0.1970 |
| `stellar_rv_aq04` | 3564 | 80 | 63 | 0.7875 | 0.1970 |
| `stellar_rv_aq05` | 990 | 80 | 42 | 0.5250 | 0.1970 |
| `stellar_rv_aq06` | 239 | 80 | 73 | 0.9125 | 0.1970 |

- API-hit sum / retrieved hits / union / repeated hits: 18546 / 480 / 406 / 74
- Publication years: 2000–2026, median=2018.0, recent-five-year=102
- Abstract / DOI completeness: 0.9729 / 0.9901

Representative public works (descriptive ordering only):

- `W4309685034` (2022), support=5: Statistical Methods for Exoplanet Detection with Radial Velocities
- `W1883251007` (2015), support=4: A Gaussian process framework for modelling stellar activity signals in radial velocity data
- `W2900811782` (2019), support=4: Accuracy and Precision of Industrial Stellar Abundances
- `W4220943208` (2022), support=4: Recovery of TESS Stellar Rotation Periods Using Deep Learning
- `W3098034015` (2022), support=3: Gaia Data Release 3

### `w6_topic_spectral_anomaly_detection`

| Query variant | API hits | Retrieved | Unique contribution | Unique ratio | Union coverage |
|---|---:|---:|---:|---:|---:|
| `spectral_anomaly_aq01` | 461 | 80 | 36 | 0.4500 | 0.2073 |
| `spectral_anomaly_aq02` | 724 | 80 | 59 | 0.7375 | 0.2073 |
| `spectral_anomaly_aq03` | 989 | 80 | 50 | 0.6250 | 0.2073 |
| `spectral_anomaly_aq04` | 207 | 80 | 52 | 0.6500 | 0.2073 |
| `spectral_anomaly_aq05` | 363 | 80 | 77 | 0.9625 | 0.2073 |
| `spectral_anomaly_aq06` | 2144 | 80 | 54 | 0.6750 | 0.2073 |

- API-hit sum / retrieved hits / union / repeated hits: 4888 / 480 / 386 / 94
- Publication years: 2000–2026, median=2021.0, recent-five-year=159
- Abstract / DOI completeness: 0.9508 / 0.9974

Representative public works (descriptive ordering only):

- `W4306968094` (2023), support=5: The Dawes Review 10: The impact of deep learning for the analysis of galaxy surveys
- `W4417233847` (2025), support=5: A Brief Review of Unsupervised Machine Learning Algorithms in Astronomy: Dimensionality Reduction and Clustering
- `W2554959913` (2016), support=4: The weirdest SDSS galaxies: results from an outlier detection algorithm
- `W4306248068` (2022), support=4: Machine learning in electron microscopy for advanced nanocharacterization: current developments, available tools and future outlook
- `W2550814413` (2017), support=4: Discovering the Unexpected in Astronomical Survey Data

### `w6_topic_stellar_spectral_denoising`

| Query variant | API hits | Retrieved | Unique contribution | Unique ratio | Union coverage |
|---|---:|---:|---:|---:|---:|
| `stellar_denoising_aq01` | 322 | 80 | 39 | 0.4875 | 0.1961 |
| `stellar_denoising_aq02` | 451 | 80 | 71 | 0.8875 | 0.1961 |
| `stellar_denoising_aq03` | 4389 | 80 | 71 | 0.8875 | 0.1961 |
| `stellar_denoising_aq04` | 266 | 80 | 49 | 0.6125 | 0.1961 |
| `stellar_denoising_aq05` | 114 | 80 | 53 | 0.6625 | 0.1961 |
| `stellar_denoising_aq06` | 293 | 80 | 77 | 0.9625 | 0.1961 |

- API-hit sum / retrieved hits / union / repeated hits: 5835 / 480 / 408 / 72
- Publication years: 2001–2026, median=2023.0, recent-five-year=258
- Abstract / DOI completeness: 0.9485 / 0.9485

Representative public works (descriptive ordering only):

- `W4411554983` (2025), support=5: Exploring Generative Artificial Intelligence and Data Augmentation Techniques for Spectroscopy Analysis
- `W4306248068` (2022), support=4: Machine learning in electron microscopy for advanced nanocharacterization: current developments, available tools and future outlook
- `W4384201335` (2023), support=4: Machine learning in solar physics
- `W4399876663` (2024), support=4: A review of unsupervised learning in astronomy
- `W3155899199` (2021), support=3: Machine Learning Based Automatic Modulation Recognition for Wireless Communications: A Comprehensive Survey

### `w6_topic_stellar_spectral_emulation`

| Query variant | API hits | Retrieved | Unique contribution | Unique ratio | Union coverage |
|---|---:|---:|---:|---:|---:|
| `stellar_emulation_aq01` | 243 | 80 | 39 | 0.4875 | 0.1932 |
| `stellar_emulation_aq02` | 132 | 80 | 71 | 0.8875 | 0.1932 |
| `stellar_emulation_aq03` | 2082 | 80 | 72 | 0.9000 | 0.1932 |
| `stellar_emulation_aq04` | 213 | 80 | 46 | 0.5750 | 0.1932 |
| `stellar_emulation_aq05` | 875 | 80 | 67 | 0.8375 | 0.1932 |
| `stellar_emulation_aq06` | 202 | 80 | 66 | 0.8250 | 0.1932 |

- API-hit sum / retrieved hits / union / repeated hits: 3747 / 480 / 414 / 66
- Publication years: 2001–2026, median=2022.0, recent-five-year=228
- Abstract / DOI completeness: 0.9710 / 0.9589

Representative public works (descriptive ordering only):

- `W2292396867` (2015), support=4: CONSTRUCTING A FLEXIBLE LIKELIHOOD FUNCTION FOR SPECTROSCOPIC INFERENCE
- `W4380446233` (2023), support=3: Gaussian Process Regression for Astronomical Time Series
- `W4378882632` (2023), support=3: Astronomia ex machina: a history, primer and outlook on neural networks in astronomy
- `W3039097989` (2021), support=3: Cycle-StarNet: Bridging the Gap between Theory and Data by Leveraging Large Data Sets
- `W3034308574` (2020), support=3: Forecasting Chemical Abundance Precision for Extragalactic Stellar Archaeology

### `w6_topic_solar_spectropolarimetric_inversion`

| Query variant | API hits | Retrieved | Unique contribution | Unique ratio | Union coverage |
|---|---:|---:|---:|---:|---:|
| `solar_inversion_aq01` | 207 | 80 | 32 | 0.4000 | 0.2111 |
| `solar_inversion_aq02` | 1350 | 80 | 48 | 0.6000 | 0.2111 |
| `solar_inversion_aq03` | 899 | 80 | 54 | 0.6750 | 0.2111 |
| `solar_inversion_aq04` | 148 | 80 | 51 | 0.6375 | 0.2111 |
| `solar_inversion_aq05` | 737 | 80 | 70 | 0.8750 | 0.2111 |
| `solar_inversion_aq06` | 419 | 80 | 59 | 0.7375 | 0.2111 |

- API-hit sum / retrieved hits / union / repeated hits: 3760 / 480 / 379 / 101
- Publication years: 2001–2026, median=2021, recent-five-year=177
- Abstract / DOI completeness: 0.9208 / 0.9842

Representative public works (descriptive ordering only):

- `W4384201335` (2023), support=5: Machine learning in solar physics
- `W3033124288` (2020), support=5: Mimicking spectropolarimetric inversions using convolutional neural networks
- `W4405103083` (2024), support=5: Exploring spectropolarimetric inversions using neural fields
- `W3138164851` (2021), support=4: Machine learning initialization to accelerate Stokes profile inversions
- `W3147526180` (2021), support=4: Fast and Accurate Emulation of the SDO/HMI Stokes Inversion with Uncertainty Quantification

### `w6_topic_21cm_foreground_removal`

| Query variant | API hits | Retrieved | Unique contribution | Unique ratio | Union coverage |
|---|---:|---:|---:|---:|---:|
| `21cm_foreground_aq01` | 1669 | 80 | 57 | 0.7125 | 0.2273 |
| `21cm_foreground_aq02` | 63 | 63 | 23 | 0.3651 | 0.1790 |
| `21cm_foreground_aq03` | 278 | 80 | 51 | 0.6375 | 0.2273 |
| `21cm_foreground_aq04` | 71 | 71 | 36 | 0.5070 | 0.2017 |
| `21cm_foreground_aq05` | 192 | 80 | 41 | 0.5125 | 0.2273 |
| `21cm_foreground_aq06` | 470 | 80 | 64 | 0.8000 | 0.2273 |

- API-hit sum / retrieved hits / union / repeated hits: 2743 / 454 / 352 / 102
- Publication years: 2000–2026, median=2022.0, recent-five-year=203
- Abstract / DOI completeness: 0.9801 / 0.9148

Representative public works (descriptive ordering only):

- `W4414058109` (2025), support=6: Square Kilometre Array Science Data Challenge 3a: foreground removal for an EoR experiment
- `W4407090583` (2025), support=5: A generative modeling approach to reconstructing 21 cm tomographic data
- `W3099201768` (2021), support=4: deep21: a deep learning method for 21 cm foreground removal
- `W3195461121` (2021), support=4: The BINGO project
- `W3180708328` (2021), support=4: Cleaning foregrounds from single-dish 21 cm intensity maps with Kernel principal component analysis

## Cross-topic overlap

| Topic pair | Shared works | Jaccard | Left overlap | Right overlap |
|---|---:|---:|---:|---:|
| `w6_topic_galaxy_activity_spectra` / `w6_topic_supernova_spectral_typing` | 25 | 0.0321 | 0.0600 | 0.0648 |
| `w6_topic_galaxy_activity_spectra` / `w6_topic_exoplanet_atmospheric_retrieval` | 10 | 0.0143 | 0.0240 | 0.0344 |
| `w6_topic_galaxy_activity_spectra` / `w6_topic_stellar_radial_velocity` | 13 | 0.0160 | 0.0312 | 0.0320 |
| `w6_topic_galaxy_activity_spectra` / `w6_topic_spectral_anomaly_detection` | 52 | 0.0692 | 0.1247 | 0.1347 |
| `w6_topic_galaxy_activity_spectra` / `w6_topic_stellar_spectral_denoising` | 16 | 0.0198 | 0.0384 | 0.0392 |
| `w6_topic_galaxy_activity_spectra` / `w6_topic_stellar_spectral_emulation` | 17 | 0.0209 | 0.0408 | 0.0411 |
| `w6_topic_galaxy_activity_spectra` / `w6_topic_solar_spectropolarimetric_inversion` | 2 | 0.0025 | 0.0048 | 0.0053 |
| `w6_topic_galaxy_activity_spectra` / `w6_topic_21cm_foreground_removal` | 11 | 0.0145 | 0.0264 | 0.0312 |
| `w6_topic_supernova_spectral_typing` / `w6_topic_exoplanet_atmospheric_retrieval` | 4 | 0.0059 | 0.0104 | 0.0137 |
| `w6_topic_supernova_spectral_typing` / `w6_topic_stellar_radial_velocity` | 14 | 0.0180 | 0.0363 | 0.0345 |
| `w6_topic_supernova_spectral_typing` / `w6_topic_spectral_anomaly_detection` | 30 | 0.0404 | 0.0777 | 0.0777 |
| `w6_topic_supernova_spectral_typing` / `w6_topic_stellar_spectral_denoising` | 9 | 0.0115 | 0.0233 | 0.0221 |
| `w6_topic_supernova_spectral_typing` / `w6_topic_stellar_spectral_emulation` | 15 | 0.0191 | 0.0389 | 0.0362 |
| `w6_topic_supernova_spectral_typing` / `w6_topic_solar_spectropolarimetric_inversion` | 4 | 0.0053 | 0.0104 | 0.0106 |
| `w6_topic_supernova_spectral_typing` / `w6_topic_21cm_foreground_removal` | 11 | 0.0151 | 0.0285 | 0.0312 |
| `w6_topic_exoplanet_atmospheric_retrieval` / `w6_topic_stellar_radial_velocity` | 20 | 0.0295 | 0.0687 | 0.0493 |
| `w6_topic_exoplanet_atmospheric_retrieval` / `w6_topic_spectral_anomaly_detection` | 21 | 0.0320 | 0.0722 | 0.0544 |
| `w6_topic_exoplanet_atmospheric_retrieval` / `w6_topic_stellar_spectral_denoising` | 11 | 0.0160 | 0.0378 | 0.0270 |
| `w6_topic_exoplanet_atmospheric_retrieval` / `w6_topic_stellar_spectral_emulation` | 35 | 0.0522 | 0.1203 | 0.0845 |
| `w6_topic_exoplanet_atmospheric_retrieval` / `w6_topic_solar_spectropolarimetric_inversion` | 5 | 0.0075 | 0.0172 | 0.0132 |
| `w6_topic_exoplanet_atmospheric_retrieval` / `w6_topic_21cm_foreground_removal` | 3 | 0.0047 | 0.0103 | 0.0085 |
| `w6_topic_stellar_radial_velocity` / `w6_topic_spectral_anomaly_detection` | 39 | 0.0518 | 0.0961 | 0.1010 |
| `w6_topic_stellar_radial_velocity` / `w6_topic_stellar_spectral_denoising` | 40 | 0.0517 | 0.0985 | 0.0980 |
| `w6_topic_stellar_radial_velocity` / `w6_topic_stellar_spectral_emulation` | 42 | 0.0540 | 0.1034 | 0.1014 |
| `w6_topic_stellar_radial_velocity` / `w6_topic_solar_spectropolarimetric_inversion` | 9 | 0.0116 | 0.0222 | 0.0237 |
| `w6_topic_stellar_radial_velocity` / `w6_topic_21cm_foreground_removal` | 3 | 0.0040 | 0.0074 | 0.0085 |
| `w6_topic_spectral_anomaly_detection` / `w6_topic_stellar_spectral_denoising` | 34 | 0.0447 | 0.0881 | 0.0833 |
| `w6_topic_spectral_anomaly_detection` / `w6_topic_stellar_spectral_emulation` | 28 | 0.0363 | 0.0725 | 0.0676 |
| `w6_topic_spectral_anomaly_detection` / `w6_topic_solar_spectropolarimetric_inversion` | 9 | 0.0119 | 0.0233 | 0.0237 |
| `w6_topic_spectral_anomaly_detection` / `w6_topic_21cm_foreground_removal` | 13 | 0.0179 | 0.0337 | 0.0369 |
| `w6_topic_stellar_spectral_denoising` / `w6_topic_stellar_spectral_emulation` | 42 | 0.0538 | 0.1029 | 0.1014 |
| `w6_topic_stellar_spectral_denoising` / `w6_topic_solar_spectropolarimetric_inversion` | 11 | 0.0142 | 0.0270 | 0.0290 |
| `w6_topic_stellar_spectral_denoising` / `w6_topic_21cm_foreground_removal` | 3 | 0.0040 | 0.0074 | 0.0085 |
| `w6_topic_stellar_spectral_emulation` / `w6_topic_solar_spectropolarimetric_inversion` | 18 | 0.0232 | 0.0435 | 0.0475 |
| `w6_topic_stellar_spectral_emulation` / `w6_topic_21cm_foreground_removal` | 13 | 0.0173 | 0.0314 | 0.0369 |

## Topic amendment record

No `potential_topic_amendment` was recorded automatically. Any amendment requires a separate scientific interpretation and must not mutate the frozen Topic Set or split.
