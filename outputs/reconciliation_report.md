# Reconciliation report

## Cross-check vs the manual Q2 2025 snapshot

| company | metric | snapshot | pipeline | status | note |
|---|---|---|---|---|---|
| novacloud | recognized_revenue | $8.4M | $8.4M | agree |  |
| novacloud | arr | $34.2M | $34.2M | agree |  |
| medisight | recognized_revenue | 6.8M | 6.8M | agree |  |
| medisight | arr | 27.9M | 27.9M | agree | Snapshot buries MediSight ARR in a footnote, not its table. |
| talentvault | headcount | None | 103 | recovered_by_pipeline | Snapshot omits TalentVault headcount entirely; the pipeline recovers it from the standalone report. |
| carbontrack | recognized_revenue | $4.1M | $4.1M | agree |  |

## Restatements auto-proposed from document text (machine-detected)

_The pipeline scans each document's own footnotes/commentary for restatement language and proposes the conflict with verbatim evidence; a human ratifies it below._

- **peopleflow / recognized_revenue Q1 2025**: 4.7M → 4.6M _(ratified in reconciliation.yaml)_<br>evidence (p1, PeopleFlow_Q2_2025.pdf): "(2) Q1 2025 Quarterly Revenue has been restated from 4.7M to 4.6M to reflect the reversal of a contract modification initially recognised in Q1 but subsequently unwound in April 2025 following a customer renegotiation"

## Restatements ratified in reconciliation.yaml (human-approved tier)

- **peopleflow / recognized_revenue Q1 2025**: 4.7M - PeopleFlow_Q1_2025.pdf<br>4.6M (restated) - PeopleFlow_Q2_2025.pdf<br>Q1 revenue restated 4.7M -> 4.6M after a contract modification was reversed in April 2025; the Q1 standalone report was not reissued.