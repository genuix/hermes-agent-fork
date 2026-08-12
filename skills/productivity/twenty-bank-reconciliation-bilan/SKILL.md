---
name: twenty-bank-reconciliation-bilan
description: "Use for bank CSV to Twenty reconciliation and Bilan ODT."
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [twenty, banking, reconciliation, invoices, bilan, odt]
    related_skills: [twenty-writeback-ops, dolibarr-to-twenty-migration]
---

# Twenty Bank Reconciliation and Bilan

## Overview

Reusable workflow for processing a bank movement CSV in the format supplied by PostFinance, loading incoming credits into Twenty, matching them against invoice records, and generating an updated French-language 2025 Bilan ODT.

The workflow preserves the original bank export, ignores only its metadata/footer rows, keeps source-row provenance, and uses Twenty as an operational reconciliation surface—not as a bank ledger or statutory accounting system.

## When to Use

- A bank CSV contains metadata rows before the transaction header and `Crédit en CHF` / `Débit en CHF` columns.
- Incoming credits must be represented as Twenty Payment records and matched to invoices.
- A Bilan document must be regenerated from invoice, bank, and Twenty reconciliation data.

Do not use this workflow to declare a statutory balance sheet, determine TVA liability, or automatically approve ambiguous matches.

## Canonical Source Handling

### Bank CSV format

Expected structure:

```text
Date de début:,...
Date de fin:,...
Genre de comptabilisation:,...
Compte:,...
Monnaie:,...

Date,Texte de notification,Crédit en CHF,Débit en CHF,Valeur,Solde en CHF
...
,,total_credit,total_debit,,closing_balance
```

Parsing rules:

1. Preserve the original CSV byte-for-byte.
2. Locate the real header by finding the line beginning with `Date,Texte de notification` rather than relying only on a fixed line number.
3. Ignore metadata rows before the header.
4. Ignore footer/total rows after transaction rows.
5. Treat credits and debits as signed values. The debit column is already negative.
6. Calculate net movement as `credits + signed_debits`, never `credits - debit_column`.
7. Preserve the complete notification text and source row number.
8. Compute and retain a SHA-256 hash of the original source file.

### Credit-only filter

For incoming-payment reconciliation, keep only rows where `Crédit en CHF` is positive. Exclude internal movements such as `ÉMARGER`, `TRANSFÉRER LE SOLDE`, or equivalent account-to-account descriptions from invoice matching.

Keep the internal credit in the audit summary, but classify it as `excluded/non-bill`.

## Twenty Data Model

Use dedicated objects. Do not put raw bank movements into Tasks or Notes, and do not reuse the Invoice object for payment rows.

### Bank Movement

Recommended fields:

- `sourceRow`
- `transactionDate`
- `notificationText`
- `creditChf`
- `debitChf`
- `valueDate`
- `balanceChf`
- `classification`
- `counterparty`
- `extractedReferences`
- `recommendedAction`

### Payment

Recommended fields:

- `sourceRow`
- `paymentDate`
- `amountChf`
- `counterparty`
- `bankReference`
- `direction` — use `credit` for incoming bank credits
- `status` — `matched`, `pending_invoice_match`, `partial`, `ambiguous`, `duplicate`, or `excluded`
- `sourceFileHash`

### Payment Allocation

Recommended fields:

- `paymentSourceRow`
- `invoiceNumber`
- `allocatedAmountChf`
- `matchMethod`
- `confidence`
- `approvalStatus` — normally `proposed` until reviewed

The allocation object is required for split payments, partial payments, overpayments, and one payment covering multiple invoices.

### Invoice

Recommended reconciliation fields:

- `paymentDate`
- `paymentAmountChf`
- `paymentStatus`
- `matchedBankSourceRow`
- `reconciliationConfidence`
- `reconciliationMethod`
- `counterparty`
- source-authority fields for `invoiceDate`, `amountChf`, `dueDate`, and external accounting ID

Use typed DATE/CURRENCY fields after the pilot is validated. Text fields are acceptable for a safe first staging pass, but do not treat text amounts as a final accounting model.

## Matching Rules

Apply rules in this order:

1. Exact invoice number/reference in the bank notification.
2. Exact invoice amount + counterparty + currency.
3. Exact amount with a reasonable payment-date window.
4. Counterparty plus amount as a proposal only.
5. Date/value tolerance only as `ambiguous` or `proposed`, never as an automatic paid decision.

A bank reference is not automatically an invoice number. Keep it as a payment reference until it matches the authoritative invoice register.

High-confidence example:

```text
Invoice FA2508-0155
Bank credit: 2025-09-23 / CHF 2,248.48
Counterparty: EAUX SECOURS von Allmen SA
Result: matched, high confidence
Method: exact invoice reference and exact credited amount
```

## Execution Workflow

### 1. Inspect and stage

- Read the source file.
- Verify metadata/header/footer handling.
- Generate a normalized dry-run CSV.
- Report transaction count, total credits, total debits, net movement, and classification counts.
- Do not write to Twenty until the dry-run totals match the bank statement.

Completion criterion: normalized record count and totals reconcile with the source footer.

### 2. Ensure Twenty schema

- Query Metadata API for existing objects.
- Reuse existing `Invoice` if present.
- Create missing `Bank Movement`, `Payment`, and `Payment Allocation` objects.
- Add fields before importing records.
- Never create duplicate Invoice objects with a prefixed name if the workspace already has one.

Completion criterion: metadata readback shows every required object and field.

### 3. Import Bank Movement rows

- Use `/rest/bankMovements` or the workspace-generated REST endpoint.
- Use stable source-row names/keys.
- Import in a canary batch of 3–20 rows first.
- Read back the canary before importing the remainder.
- Skip existing source rows on reruns.

Completion criterion: `totalCount` and unique source-row count equal the normalized input count, with zero failed creates.

### 4. Import incoming credits

- Filter positive `Crédit en CHF` rows.
- Exclude internal movements from invoice matching.
- Create one Payment per genuine credit.
- Set `direction=credit`.
- Use `sourceRow` plus source-file hash for idempotency.
- Set unmatched records to `pending_invoice_match`.
- Set only evidence-backed matches to `matched`.

Completion criterion: Payment readback contains exactly the expected credit count and no duplicate source rows.

### 5. Match against authoritative invoices

Preferred authority order:

1. Dolibarr/accounting invoice export or read-only API.
2. Verified Twenty invoice export with amounts/dates/statuses.
3. Paperless OCR/PDF data as supporting evidence.
4. Bank notification text only as a reference—not as the invoice authority.

For every exact match:

- update the Invoice payment fields;
- create a Payment Allocation with `approvalStatus=proposed`;
- retain invoice number, payment source row, amount, date, and method;
- read the record back from Twenty.

Do not infer invoice totals from payment amounts unless the invoice source confirms equality.

Completion criterion: every automatic match has an invoice reference, amount, counterparty, source row, and verification readback.

### 6. Generate the Bilan

Generate both Markdown and ODT. Preserve the previous document and write an `Updated` variant.

The Bilan should include:

- scope and source files;
- warning that it is not a statutory balance sheet;
- invoice count, HT, TVA source amount, and TTC;
- invoice/payment detail;
- total bank credits, debits, and net movement;
- incoming-credit status split;
- outgoing classification;
- matched, pending, ambiguous, and excluded amounts;
- TVA caveat if the title says non-TVA but source invoices contain TVA;
- next validation steps.

Example conversion:

```bash
pandoc "Twenty Bilan 2025 - Updated.md" \
  -o "Twenty Bilan 2025 - Suisse non TVA - Updated.odt"
```

Verify the generated file is an OpenDocument Text file and contains the expected totals and match count.

## Verification Checklist

- [ ] Original bank CSV remains unchanged.
- [ ] Source SHA-256 is recorded.
- [ ] Metadata/header/footer parsing is correct.
- [ ] Credits and debits match the bank statement totals.
- [ ] Net movement uses signed debit values.
- [ ] Internal transfers are excluded from invoice matching.
- [ ] Bank Movement count equals normalized transaction count.
- [ ] Payment count equals genuine incoming-credit count.
- [ ] Payment source rows are unique.
- [ ] Every high-confidence match has exact reference/amount evidence.
- [ ] Allocation records read back from Twenty.
- [ ] Pending and ambiguous items remain unapproved.
- [ ] Existing invoice records not supported by source evidence remain untouched.
- [ ] Bilan ODT is valid and has been read/verified after generation.
- [ ] TVA wording is reviewed against the actual invoice source.

## Common Pitfalls

1. **Treating the bank CSV as an invoice register** — it is a payment source; obtain invoice amounts and dates from accounting.
2. **Subtracting a negative debit column** — this doubles the debit impact. Use credits plus signed debits.
3. **Using all credits as receivables** — exclude internal transfers and account movements.
4. **Matching by amount alone** — amount-only matches are proposals, not automatic approvals.
5. **Putting payments into Invoice records without an allocation layer** — this cannot represent partial or split payments.
6. **Re-importing the same CSV** — compare the source hash and source-row keys before writing.
7. **Overwriting the original Bilan** — create an Updated document and preserve the prior artifact.
8. **Calling the report a statutory balance sheet** — label it as a commercial/banking reconciliation until assets, liabilities, charges, equity, closing entries, and tax treatment are complete.
9. **Assuming “Suisse non TVA” is proven by the title** — source invoices containing TVA require explicit validation with the fiduciary.
10. **Printing API keys or service credentials** — read secrets only from root-owned mode-600 paths and never include them in logs or chat.
