# README: T&S Assignment 3 - Donation Labeler Pipeline

Cecilia Yiyue Chen, Kelly Wang, Tishya Khanna, Yixuan Liu

## Overview

This [GitHub repository](https://github.com/tishyakhanna97/trust-and-safety-assign3) implements a modular pipeline for detecting donation-related posts on Bluesky and assessing payment endpoints for potential scam risks. The system consists of four main modules: (1) Donation Intent Classifier, (2) Endpoint Extractor, (3) Org/Account Verifier, and (4) Label Assembler. The pipeline ingests post URLs, extracts relevant signals, verifies account and endpoint trustworthiness, and outputs structured labels, including a final scam-risk assessment.

The Video Presentation introducing this labeler is avaiable at [Youtube](https://youtu.be/qV3ozNHv7Ko).

## Repository Contents

All the required files are placed under the `assign_3` folder:

* `policy_proposal_labeler.py`:
Main executable script containing the full labeling pipeline implementation. This file includes all four modules, the helper functions for interacting with the Bluesky API, and the command-line interface (CLI) for running evaluations or applying labels.

* `charity-sites.json`:
A manually curated reference list of known fundraising domains and payment providers. Each entry follows the format:

```
    "domain.com": {
    "category": "fundraising_platform | p2p_payment | other",
    "cause": "other | animals | medical | ...",
    "recipient_type": "organizational | personal | mixed",
    "notes": ""
    }
```


This file is used by the Endpoint Extractor to classify URL mechanisms and detect trusted fundraising endpoints.

* `data.csv`: 
Input dataset for testing and offline evaluation. The file must contain at least one of the columns: \verb|url| or \verb|source_url|. Additional fields (donation intent, verified org, domain, etc.) may be present for comparison but are not required.

* `post_with_preds.csv`:
Output file automatically generated after running the pipeline. Contains the original dataset columns plus predictions:

```
    pred_donation_related,
    pred_contains_payment_mechanism,  
    pred_payment_mechanism,
    pred_verified_org,
    pred_verified_type,  
    pred_scam  
```

* `technical overview.png`:
A flowchart outlining the complete end-to-end pipeline. The diagram illustrates control flow between modules and the decision logic used to determine final scam-risk labels.

* `requirements.txt`:
Documentation file for the required dependencies.  

* `README.md`:
Documentation file describing the project, its structure, and instructions for running tests.


## Installation 

### Python Requirements
The project requires Python 3.9 or higher. Dependencies documented in `requirements.txt`.

### Running the Pipeline
#### Evaluation Mode
To evaluate all posts in `data.csv` and produce predictions in `post_with_preds.csv`:

```
python policy_proposal_labeler.py \
    --csv_path data.csv \
    --output_csv post_with_preds.csv
```

This mode does not apply labels to Bluesky.

#### Applying Labels to Bluesky 
Requires valid Bluesky app credentials and a registered labeler service.

```
python policy_proposal_labeler.py \
    --csv_path data.csv \
    --apply_labels \
    --output_csv post_with_preds.csv
```

### Output Schema
The pipeline generates the following predicted fields:

* `pred_donation_related`: **related** or **not_related**
* `pred_contains_payment_mechanism`: **yes** or **no**
* `pred_payment_mechanism`: mechanism classification results (e.g., fundraising_website, payment_handle)
* `pred_verified_org`: Verification on the endpoint's level, **yes**, **domain**, or **no**
* `pred_verified_type`: Verification on the account's level, **official**, **trusted**, or **none**
* `pred_scam`: **no**, **unsure**, or **unknown**

The final scam-risk classification is derived from a combination of account-level verification (trusted/official), endpoint-level verification (organization vs. unknown), and the presence or absence of payment mechanisms.

## Pipeline Summary

* **Donation Intent Classifier**: Identifies whether a post expresses donation intent using rule-based lexical matching.

* **Endpoint Extractor**: Extracts URLs, faceted links, embedded links, QR-code content, and payment handles. Classifies each endpoint using a combination of heuristics and the domain reference database.

* **Org Verifier**: Separates account-level verification (official vs. trusted vs. none) from endpoint-level verification (organization-recognized vs. domain-based vs. none).

* **Label Assembler**: Outputs structured labels for each dimension and assigns a final scam-risk label based on defined trust rules.

## Testing Instructions

To test the system with your own dataset:

* Prepare a CSV containing a column named `url` or `source_url`.
* Place the file in the repository root.
* Run:
    ```
    python policy_proposal_labeler.py \
        --csv_path your_file.csv \
        --output_csv your_output.csv
    ```
* Inspect the generated output file.

## Notes

The system is modular and can be extended with additional classifiers or verification logic. The existing pipeline is fully functional for offline evaluation and can be configured for real-time Bluesky moderation label submission.

