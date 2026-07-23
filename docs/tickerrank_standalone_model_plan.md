# TickerRank: Ticker-Conditioned Financial News Ranker

> **Standalone project notice**
>
> This document describes a new, independent repository and model. It is stored
> temporarily in the `stock-trader/docs/` directory for planning and will be
> copied into its own repository before implementation. TickerRank may later
> provide features to the stock-trader project, but it must not depend on the
> stock-trader codebase or make trading decisions.

## 1. Project name

**Recommended project and model-family name: `TickerRank`**

Recommended first model release:

```text
TickerRank-FinBERT-base-v1
```

Recommended Hugging Face repository slug:

```text
<organization-or-user>/tickerrank-finbert-base-v1
```

Why `TickerRank`:

- It communicates that the model ranks news in relation to a ticker.
- It does not imply that the model predicts prices or makes trades.
- It leaves room to replace FinBERT with another encoder later.
- It can cover a family of models such as `TickerRank-FinBERT`,
  `TickerRank-DeBERTa`, and multilingual variants.

Names such as `StockBERT` and `TickerBERT` are broader but less precise.
`StockBERT` may sound like a general stock-market foundation model, while this
project has a narrower and more useful contract.

## 2. Product summary

TickerRank is a lightweight financial-news model that evaluates a headline in
the context of a supplied stock ticker and company.

Given:

```text
Ticker + canonical company name + news headline
```

the model returns:

- **Relevance:** How economically relevant the headline is to the supplied
  company.
- **Importance:** How materially the event could affect the supplied company.
- **Direction:** Whether the likely effect is positive, negative, or neutral
  for the supplied company.

TickerRank does not decide whether to buy, hold, or sell a security. It converts
raw headlines into stable numerical and categorical features that other systems
can use alongside prices, fundamentals, risk controls, and other information.

## 3. Primary goal

For an input such as:

```text
Ticker: MU
Company: Micron Technology
Headline: Micron raises revenue guidance after stronger memory demand
```

TickerRank should return:

```json
{
  "relevance": 0.99,
  "importance": 0.94,
  "direction": "positive"
}
```

The model should work for companies outside any fixed ticker universe. A
security-master lookup supplies the company identity; the model should not rely
on a hard-coded list of stocks.

## 4. Non-goals

The first version will not:

- Recommend or execute trades.
- Predict a realized stock return.
- Use future price reactions as training labels.
- Read full articles.
- Model multi-company relationship graphs.
- Produce investment advice.
- Replace deterministic portfolio or risk controls.

These boundaries should appear prominently in the public model card.

## 5. Model input

### 5.1 Input fields

The initial model receives:

```text
Ticker: <ticker>
Company: <canonical company name>
Headline: <news title>
```

The serialized input should use explicit field markers:

```text
[TICKER] MU [COMPANY] Micron Technology [HEADLINE] Micron raises quarterly revenue guidance
```

Explicit markers make the fields easy to identify and avoid relying on prose
punctuation.

### 5.2 Security master

A separate security-master table should provide:

```text
security_id
ticker
canonical_company_name
known_aliases
exchange
valid_from
valid_to
```

The stable `security_id` is preferable to using ticker as the permanent company
identity because:

- A company can have multiple share classes, such as `GOOG` and `GOOGL`.
- Tickers can change.
- Company names and brands can change.
- A company may be delisted and its ticker later reused.

Aliases help connect names such as:

```text
MU    → Micron Technology → Micron
META  → Meta Platforms    → Meta
GOOGL → Alphabet          → Google
```

The security master is preprocessing infrastructure, not an additional model
input for the MVP beyond ticker and canonical company name.

## 6. Model outputs

### 6.1 Relevance

A continuous score from `0.0` to `1.0` indicating how economically relevant the
headline is to the supplied ticker.

Proposed anchors:

| Score | Meaning |
|---:|---|
| `0.00` | Unrelated to the supplied company |
| `0.25` | Weak sector or market connection |
| `0.50` | Meaningful indirect effect |
| `0.75` | Strongly affects the company |
| `1.00` | The company is the direct subject and the event clearly applies to it |

Example:

```text
Ticker: JPM
Headline: Micron raises revenue guidance
Relevance: approximately 0.00
```

Example with an indirect relationship:

```text
Ticker: AMD
Headline: Nvidia delays its next-generation GPU
Relevance: potentially moderate or high because the competitive effect may
           matter to AMD, even though AMD is not the direct subject.
```

### 6.2 Open question: one relevance score or two?

The MVP currently specifies one broad relevance score. The definition includes
meaningful indirect economic effects, not only direct company mentions.

An alternative is to separate:

```json
{
  "entity_relevance": 0.20,
  "impact_relevance": 0.80
}
```

This would distinguish “the article is about this company” from “the article
could affect this company.”

**Decision status: OPEN.**

Before freezing the label schema, run a small annotation exercise containing
direct-company, competitor, supplier, customer, sector, and macro headlines.
Keep one score if annotators can apply it consistently. Split it into two only
if the single score repeatedly causes disagreements or loses information needed
by users.

Changing this decision after thousands of teacher labels have been generated
would require relabeling, so it must be resolved before the full labeling run.

### 6.3 Importance

A continuous score from `0.0` to `1.0` indicating how materially the event could
affect the supplied company.

Use this labeling definition:

> Assuming the headline is accurate and contains new information, how
> materially could the event change the supplied company’s revenue, costs,
> risks, competitive position, capital structure, or valuation?

Importance is:

- Unsigned.
- Conditional on the supplied ticker.
- About potential materiality, not how exciting or emotional the headline is.

Proposed anchors:

| Score | Meaning |
|---:|---|
| `0.00` | No meaningful investor significance |
| `0.25` | Routine corporate news or limited consequence |
| `0.50` | Meaningful but contained event |
| `0.75` | Likely material to outlook or valuation |
| `1.00` | Potentially transformative, existential, or exceptionally material |

High-importance examples:

```text
Company raises or cuts earnings guidance.
Company wins a contract worth a large share of annual revenue.
Regulator opens an investigation with potentially substantial penalties.
Company announces a major acquisition or liquidity problem.
```

Low-importance examples:

```text
CEO receives an industry award.
Company attends a routine conference.
Generic interview repeats previously disclosed strategy.
Company announces a ceremonial community event.
```

A positive guidance increase and a negative guidance cut may both receive high
importance scores.

### 6.4 Direction

The MVP returns one class:

```text
positive | negative | neutral
```

Use this labeling definition:

> Direction is the expected effect of the disclosed information on the supplied
> company’s fundamental outlook or valuation over the next several trading
> sessions, relative to what investors previously expected when that context is
> available. It describes the likely effect of the information; it does not
> predict the realized stock return.

Rules:

- Evaluate direction for the supplied ticker, not merely the company named in
  the headline.
- Use a consistent horizon of the next several trading sessions.
- Consider “better or worse than expectations” when the headline provides that
  information.
- Use `neutral` for relevant news with a genuinely balanced, uncertain, or
  immaterial directional effect.
- Do not use subsequent price movement when creating semantic direction labels.

Examples:

```text
Micron raises revenue guidance above prior expectations
→ positive
```

```text
Micron cuts revenue guidance after weaker memory demand
→ negative
```

```text
Meta increases AI spending, potentially strengthening its position but reducing
near-term margins, with no clear net effect stated
→ neutral
```

```text
Micron reports results exactly in line with previously stated expectations
→ neutral
```

### 6.5 Explicitly deferred: direction probabilities

Direction probabilities are not part of the MVP output. The production contract
remains one categorical direction label.

The classification head will internally produce logits and probabilities, as
all softmax classifiers do, but the first public API does not promise calibrated
probabilities. Probability calibration and confidence-aware aggregation are
later enhancements that require separate evaluation.

### 6.6 Derived downstream signal

A downstream consumer may map:

```text
positive = +1
neutral  =  0
negative = -1
```

and calculate:

```text
signed_news_signal = relevance × importance × direction_value
```

Example:

```text
relevance = 0.90
importance = 0.80
direction = negative (-1)

signed_news_signal = 0.90 × 0.80 × -1 = -0.72
```

The model should still return and consumers should still retain the three
original features. The derived score is a convenience, not a replacement for
them.

## 7. Why this model exists

Ticker-specific news feeds are useful retrieval systems, but a feed association
does not guarantee that every headline is:

- Actually about the ticker.
- Economically relevant to the company.
- Important enough to affect investors.
- Consistently labeled for direction.
- Unique rather than syndicated or repeated.

TickerRank provides:

- Stable scoring across large headline collections.
- Lower inference cost than calling a large language model for every headline.
- A reusable feature extractor for research and downstream models.
- Separation between relevance, materiality, and direction.
- A public, auditable baseline for ticker-conditioned financial-news ranking.

## 8. Teacher-student training strategy

### 8.1 Teacher

Use a pinned Gemini model to label ticker-company-headline pairs.

Teacher input:

```text
Ticker
Canonical company name
Headline
```

Teacher output:

```json
{
  "relevance_score": 92,
  "importance_score": 78,
  "direction": "positive",
  "event_type": "GUIDANCE"
}
```

Teacher relevance and importance use integer scores from `0` to `100`. Normalize
them to `0.0`–`1.0` before student training.

The labeling job must record:

```text
teacher_provider
teacher_model_id
teacher_model_version_or_snapshot
prompt_version
generation_configuration
labeled_at
raw_teacher_response
validation_status
```

Do not use a moving model alias without recording the resolved model identity
when the provider exposes it.

### 8.2 Teacher scoring rubric

The teacher prompt must contain:

- The exact definitions in Section 6.
- The anchor scores for relevance and importance.
- A rule to judge every output relative to the supplied ticker.
- A rule not to infer facts that are absent from the headline.
- A rule to label mixed or unclear directional impact as `neutral`.
- A strict JSON schema.
- Diverse few-shot demonstrations.

Start with approximately 10–30 manually labeled demonstrations covering:

- Major positive earnings or guidance.
- Major negative guidance.
- High-importance legal or regulatory events.
- Low-value positive publicity.
- Broad market and sector stories.
- Competitor news.
- Supplier and customer news.
- Irrelevant ticker-feed noise.
- Ambiguous or mixed announcements.

The demonstrations calibrate Gemini’s behavior; they do not fine-tune Gemini’s
weights.

### 8.3 Teacher event types

Include an event type in the teacher dataset:

```text
EARNINGS
GUIDANCE
M&A
LEGAL
REGULATORY
PRODUCT
CONTRACT
FINANCING
MANAGEMENT
ANALYST_ACTION
SECTOR
MACRO
PUBLICITY
OTHER
IRRELEVANT
```

Event type is an audit feature for the MVP, not necessarily a student output.
It lets us check questions such as:

- Does the teacher assign high importance to guidance consistently?
- Does it give routine publicity low importance?
- Where do teacher and human labels disagree?
- Which event types are missing or underrepresented?

### 8.4 Student

Start from a pinned revision of:

```text
ProsusAI/finbert
```

FinBERT provides a finance-domain BERT encoder and an existing financial
sentiment baseline. TickerRank will replace or extend its original classification
head with a multi-task model containing:

- Relevance regression head.
- Importance regression head.
- Direction three-class classification head.

The encoder is shared by all three heads.

Benchmark at least one alternative encoder, such as `DeBERTa-v3-base`, on the
same data and splits. FinBERT is the starting point, not an assumption that must
win.

Before public release, verify and document the license of the exact base-model
revision. The current Hugging Face page for `ProsusAI/finbert` does not clearly
display a license tag, so public redistribution must not proceed on assumption
alone.

## 9. Training dataset

### 9.1 Initial size

Target:

```text
5,000–10,000 teacher-labeled ticker-headline pairs
```

The final number should be driven by label diversity and learning curves rather
than an arbitrary target. Plot validation performance against training-set size
to determine whether additional labels are still useful.

### 9.2 Dataset fields

Recommended schema:

```text
example_id
article_id
normalized_headline_hash
duplicate_cluster_id
security_id
ticker
company_name
title
published_at
source
source_url
relevance_score
importance_score
direction
event_type
example_origin
original_example_id
teacher_provider
teacher_model
prompt_version
labeled_at
split
human_review_status
```

`example_origin` should distinguish:

```text
retrieved_pair
random_ticker_swap
same_sector_ticker_swap
competitor_ticker_swap
human_authored_edge_case
```

### 9.3 Data rights checkpoint

Before labeling or public release:

1. Record the provider and original publisher for every headline.
2. Review whether the source permits collection, model training, and
   redistribution.
3. Do not publish a headline dataset on Hugging Face unless redistribution is
   clearly permitted.
4. If the raw dataset cannot be published, publish:
   - The model weights if legally permitted.
   - Dataset schema and generation methodology.
   - Aggregate statistics.
   - Evaluation code.
   - A small, separately licensed or human-authored example set.
5. Review the current Gemini API terms for the selected paid or unpaid service
   before using teacher output to train and publish a student model.

This is a release gate, not a legal conclusion. Yahoo’s terms restrict
unauthorized copying or distribution of service content, and Gemini’s current
terms place conditions on service use and generated content. Use appropriately
licensed data and obtain legal review if the public-release rights are unclear.

## 10. Deduplication

### 10.1 MVP deduplication

Deduplicate before teacher labeling and before dataset splitting.

Initial Python normalization:

1. Unicode-normalize the title.
2. Lowercase it.
3. Strip surrounding whitespace.
4. Collapse repeated whitespace.
5. Normalize punctuation.
6. Remove known publisher suffixes such as `" - Reuters"` when safe.
7. Hash the normalized title.
8. Group exact normalized matches.

Example:

```text
Micron Raises Revenue Guidance — Reuters
micron raises revenue guidance - reuters
Micron raises revenue guidance
```

should normalize to the same or an explicitly linked duplicate group when the
publisher suffix is confidently identified.

All members of a duplicate group must remain in one dataset split. A duplicate
must never appear in training while another copy appears in development or
test.

### 10.2 Why one news source is not sufficient

Using one source may reduce syndicated duplicates, but it does not remove:

- Updated versions of the same event.
- Slightly rewritten headlines.
- The same market-wide story linked to multiple tickers.
- Train/test leakage from repeated reporting.

It may also teach the model one publisher’s writing style and reduce
generalization.

### 10.3 Later embedding-based clustering

After the MVP:

```text
normalized headlines
    ↓
headline embeddings
    ↓
similarity search
    ↓
event clusters
    ↓
human inspection of threshold errors
```

Embedding clustering should be evaluated for false merges as well as missed
duplicates. Two guidance headlines about different quarters, companies, or
updates may look similar but represent distinct events.

Because TickerRank is ticker-conditioned, cache a prediction using:

```text
normalized_content_hash + security_id + model_version
```

The same headline can correctly receive different relevance, importance, and
direction labels for two companies.

## 11. Artificial examples and hard negatives

A ticker-linked feed will likely contain mostly relevant pairs. Training only on
those pairs could teach the model to assign high relevance to everything.

Create additional ticker-conditioned examples by pairing a real headline with
other companies.

Original:

```text
Ticker: MU
Company: Micron Technology
Headline: Micron raises revenue guidance
```

Easy negative candidate:

```text
Ticker: JPM
Company: JPMorgan Chase
Headline: Micron raises revenue guidance
```

Harder same-sector candidate:

```text
Ticker: AMD
Company: Advanced Micro Devices
Headline: Micron raises revenue guidance
```

Do not automatically label swapped examples as zero relevance. Send them
through the same teacher workflow. A competitor, supplier, customer, or sector
event may be economically relevant to the supplied ticker.

Construct a controlled mix of:

- Random unrelated-company swaps.
- Same-sector swaps.
- Direct competitor swaps.
- Supplier/customer swaps where relationship data is available.
- Parent/subsidiary mismatches.
- Similar company-name cases.
- Share-class and alias cases.
- Broad sector and macro headlines.

Track the origin of every artificial example so metrics can be reported
separately for retrieved and constructed pairs.

## 12. Dataset splits

TickerRank is intended to work for any ticker, so evaluation must include
companies never observed during training.

### 12.1 Group by company identity

Split by `security_id` or company group, not literal ticker:

```text
GOOG and GOOGL → same company group → same split
```

No company group may cross training, development, and final test sets.

### 12.2 Group duplicates

Duplicate or event clusters must also remain within one split. If a broad sector
headline is paired with multiple companies, keep its duplicate cluster from
crossing the split boundary.

### 12.3 Recommended evaluation views

Maintain two complementary views:

1. **Unseen-company evaluation:** Can the model generalize to companies it never
   saw during training?
2. **Future-news evaluation:** On known development companies, can a model
   trained on older news generalize to later news?

The unseen-company split is the primary standalone-model test. The chronological
view catches changing market language and event patterns.

### 12.4 Human-reviewed sets

Create at least:

- A human-reviewed development set used during iteration.
- A larger, locked human-reviewed final test set used only after model and
  threshold decisions are frozen.

The original 300–500 target is a minimum, not a limit. More human evaluation is
preferred if annotation resources permit.

The human sets should over-sample difficult cases:

- Company mentioned only indirectly.
- Competitor announcements.
- Supplier and customer announcements.
- Sector-wide and macro stories.
- CEO awards, interviews, and routine publicity.
- Earnings and guidance.
- Products with unclear materiality.
- Emotional language with little financial significance.
- Important news with mixed or uncertain direction.
- Company aliases and similar names.
- Artificial ticker swaps.

For a representative subset:

1. Obtain labels from at least two reviewers.
2. Measure agreement.
3. Adjudicate disagreements.
4. Record the final label and a short reason.

This reveals whether the task definition itself is clear enough for reliable
evaluation.

## 13. Training objective

### 13.1 Multi-task heads

For each encoded input, the student predicts:

```text
relevance score
importance score
direction class
```

Initial losses:

```text
relevance: regression loss
importance: regression loss
direction: cross-entropy classification loss
```

Combine them:

```text
total_loss =
    relevance_weight × relevance_loss
  + importance_weight × importance_loss
  + direction_weight × masked_direction_loss
```

Start with equal task weights and tune only from development-set evidence.

### 13.2 Mask direction loss for irrelevant pairs

Direction does not have a meaningful target when the headline is unrelated to
the supplied company.

Example:

```text
Ticker: JPM
Headline: Micron raises revenue guidance
Relevance: 0.01
```

Calling this `neutral` would confuse two different meanings:

- Relevant news with balanced directional impact.
- Unrelated news for which direction is undefined.

Therefore:

```python
if relevance_score >= direction_loss_relevance_threshold:
    include_direction_loss()
else:
    mask_direction_loss()
```

Use `0.20` as an initial threshold, then validate it on the human development
set. Relevance and importance losses still apply to every example.

This prevents artificially generated negatives from overwhelming the direction
head with `neutral` labels.

### 13.3 Output bounds

Use bounded inference outputs for relevance and importance, such as a sigmoid
activation, so the public scores always remain between `0.0` and `1.0`.

Direction must return exactly one of:

```text
positive
negative
neutral
```

## 14. Evaluation

### 14.1 Baselines

Compare TickerRank against:

- Unmodified `ProsusAI/finbert` sentiment output.
- Gemini few-shot teacher labels.
- Simple keyword and event rules.
- A majority/mean predictor.
- Optionally, DeBERTa-v3-base trained on the same data.

All student comparisons must use the same dataset versions and splits.

### 14.2 Relevance and importance metrics

Report:

- Mean absolute error.
- Spearman rank correlation.
- Pairwise ranking accuracy.
- NDCG at K.

Calculate ranking metrics over a defined group such as:

```text
supplied ticker × news batch
```

Do not calculate NDCG over unrelated global examples without explaining the
grouping.

### 14.3 Direction metrics

Report:

- Macro F1 as the primary metric.
- Per-class precision.
- Per-class recall.
- Confusion matrix.
- Class distribution.

Macro F1 prevents a dominant `neutral` class from hiding poor positive or
negative performance.

### 14.4 Required metric slices

Report metrics separately for:

- Seen versus unseen companies.
- Retrieved versus artificial examples.
- Direct-company versus indirect/sector examples.
- High versus low importance.
- Each event type.
- Each direction class.
- Common versus rare companies.
- Older versus more recent time periods.
- Major news-source groups when legally and statistically appropriate.

Aggregate scores alone are insufficient for a public model card.

### 14.5 Teacher evaluation

Before training the student, evaluate Gemini itself against the human-reviewed
sets. This answers:

- Is the teacher reliable enough to bootstrap the student?
- Where does it disagree with humans?
- Does disagreement cluster around competitor or sector news?
- Does it inflate importance?
- Does it overuse positive, negative, or neutral?

The student should be compared with human labels, not only with teacher labels.
A model can imitate Gemini well while preserving Gemini’s mistakes.

### 14.6 Semantic and downstream gates

Keep two separate claims:

1. **Semantic claim:** TickerRank accurately ranks ticker-conditioned news.
2. **Investment claim:** TickerRank improves a trading or forecasting system.

The public MVP needs to establish only the semantic claim. Any future investment
claim requires point-in-time, walk-forward evaluation with trading costs and
appropriate baselines. The model card must not imply profitable trading from
semantic evaluation alone.

## 15. Production inference contract

### 15.1 Python API

Target usage:

```python
from tickerrank import TickerRanker

ranker = TickerRanker.from_pretrained(
    "<organization-or-user>/tickerrank-finbert-base-v1"
)

result = ranker.predict(
    ticker="MU",
    company_name="Micron Technology",
    headline="Micron raises revenue guidance after stronger memory demand",
)

print(result)
```

Expected result:

```python
{
    "relevance": 0.99,
    "importance": 0.94,
    "direction": "positive",
    "model_version": "tickerrank-finbert-base-v1"
}
```

### 15.2 Batch API

Support batches from the first release:

```python
results = ranker.predict_batch(
    [
        {
            "ticker": "MU",
            "company_name": "Micron Technology",
            "headline": "Micron raises revenue guidance",
        },
        {
            "ticker": "AMD",
            "company_name": "Advanced Micro Devices",
            "headline": "Nvidia delays its next-generation GPU",
        },
    ]
)
```

Batch inference is important for news ranking and makes CPU usage more efficient.

### 15.3 Validation

The inference wrapper must:

- Reject missing ticker, company name, or headline.
- Enforce a documented maximum input length.
- Return finite relevance and importance values within `[0, 1]`.
- Return a known direction class.
- Include the loaded model revision in metadata.
- Handle empty and non-English headlines explicitly.

The MVP is English-only unless multilingual data and evaluation are added.

## 16. Downstream aggregation guidance

TickerRank scores individual ticker-headline pairs. It does not prescribe a
single ticker-level sentiment formula.

Possible rolling-window features:

- Maximum importance.
- Mean importance weighted by relevance.
- Count of high-importance events.
- Positive importance sum.
- Negative importance sum.
- Net signed-news score.
- News-volume spike relative to baseline.
- Time since the most important positive headline.
- Time since the most important negative headline.
- Number of distinct sources.
- Number of distinct events.

Do not use only the highest-ranked headline.

Article age and freshness should remain separate downstream features rather than
being baked into semantic relevance or importance. Source quality should also
remain a separate weight or feature. A credible source reporting negative news
should not change the event’s direction; credibility affects confidence in the
report, not whether it is positive or negative.

When near-duplicate clustering is available, aggregate event clusters rather
than raw article counts so syndicated coverage does not masquerade as multiple
independent signals.

## 17. Step-by-step implementation plan

### Phase 0: Create the standalone repository

1. Create a new repository named `tickerrank`.
2. Use Python and a reproducible environment manager.
3. Add:

   ```text
   src/tickerrank/
   tests/
   scripts/
   configs/
   data/
   notebooks/
   reports/
   model_card/
   ```

4. Add formatting, linting, type checking, unit tests, and CI.
5. Add deterministic random seeds and configuration files.
6. Keep credentials and raw licensed data out of Git.
7. Document that the repository is independent from stock-trader.

**Exit criteria:** A clean installation can run a placeholder CLI and test suite.

### Phase 1: Freeze task definitions

1. Convert Section 6 into an annotation guide.
2. Manually label 30–50 diverse examples.
3. Include direct, indirect, competitor, sector, publicity, guidance, and
   irrelevant cases.
4. Have a second reviewer label a subset.
5. Inspect disagreements.
6. Resolve the open relevance question:
   - One economic-relevance score, or
   - Separate entity and impact relevance.
7. Freeze label schema version `v1`.

**Exit criteria:** Reviewers can apply the definitions consistently, and the
relevance schema is no longer open.

### Phase 2: Establish data rights and provenance

1. Identify candidate headline sources.
2. Record each source’s collection, training, storage, and redistribution terms.
3. Verify the exact FinBERT base-model license.
4. Review the applicable Gemini API terms and use an appropriate service tier.
5. Decide whether the labeled dataset can be public, private, or partially
   released.
6. Record provenance and license decisions in a data card.

**Exit criteria:** The team knows what may be trained on, retained, and
published. No public release relies on an assumed license.

### Phase 3: Build the security master

1. Define the stable `security_id`.
2. Collect ticker, company name, aliases, exchange, and effective dates.
3. Group multiple share classes under the same company identity for splitting.
4. Add validation for duplicated and conflicting ticker records.
5. Version the security-master snapshot used for each dataset.

**Exit criteria:** Every training pair resolves to one documented company
identity.

### Phase 4: Collect and normalize candidate headlines

1. Ingest ticker-linked candidate headlines.
2. Retain source, URL, publication time, and provider article ID.
3. Normalize titles deterministically.
4. Generate content hashes.
5. Collapse exact normalized duplicates.
6. Produce a deduplication report:
   - Raw count.
   - Unique normalized count.
   - Duplicate rate.
   - Examples of collapsed titles.
7. Unit-test normalization edge cases.

**Exit criteria:** Re-running normalization produces identical hashes and
duplicate groups.

### Phase 5: Construct training candidates

1. Keep retrieved ticker-headline pairs.
2. Generate unrelated-company swaps.
3. Generate same-sector and competitor swaps.
4. Add alias and similar-name cases.
5. Add manually authored difficult examples.
6. Avoid uncontrolled inflation:
   - Cap synthetic examples per original.
   - Track `example_origin`.
   - Monitor relevance and direction distributions.

**Exit criteria:** The candidate set contains meaningful positive, negative,
neutral, relevant, indirect, and irrelevant examples.

### Phase 6: Build and validate the Gemini teacher

1. Write prompt version `v1` using the frozen annotation guide.
2. Add 10–30 few-shot examples.
3. Require strict structured output.
4. Use deterministic or low-variance generation settings where supported.
5. Validate:
   - Scores are within `0`–`100`.
   - Direction is a known class.
   - Event type is known.
   - Exactly one output exists per input.
6. Retry malformed responses with a bounded retry policy.
7. Store raw response, prompt version, and teacher identity.
8. Compare teacher labels with the initial human examples.
9. Revise the prompt before scaling if systematic errors appear.

**Exit criteria:** Teacher output passes schema validation and reaches an
acceptable agreement level on the human pilot set.

### Phase 7: Generate the labeled dataset

1. Label a small pilot batch first.
2. Inspect score distributions and event-type coverage.
3. Review random examples and extreme scores.
4. Correct data or prompt problems.
5. Label the full 5,000–10,000 pair dataset.
6. Normalize regression scores to `[0, 1]`.
7. Version the complete dataset manifest.
8. Freeze a reproducible dataset release candidate.

**Exit criteria:** Every row has valid provenance, labels, teacher metadata, and
normalization identifiers.

### Phase 8: Create development and test sets

1. Group rows by company identity.
2. Group duplicates and event clusters.
3. Assign company-disjoint train, development, and test partitions.
4. Create a secondary chronological evaluation slice.
5. Build a substantial human-reviewed development set.
6. Build a larger locked human-reviewed final test set.
7. Measure reviewer agreement on a multi-annotator subset.
8. Freeze the final test set before model selection.

**Exit criteria:** No company or duplicate cluster leaks across primary splits,
and the final human test set is locked.

### Phase 9: Implement baselines

1. Majority and mean predictors.
2. Keyword/event-rule baseline.
3. Unmodified FinBERT sentiment baseline.
4. Gemini teacher baseline on human labels.
5. Save baseline predictions and evaluation reports.

**Exit criteria:** Every future model is compared against reproducible baselines.

### Phase 10: Implement the multi-task student

1. Pin the exact tokenizer and base-model revision.
2. Add relevance and importance regression heads.
3. Add the three-class direction head.
4. Implement direction-loss masking for low-relevance examples.
5. Add bounded relevance and importance outputs.
6. Create unit tests for:
   - Tensor shapes.
   - Loss masking.
   - Output bounds.
   - Label mapping.
   - Save/load round trips.
7. Save all hyperparameters and seeds.

**Exit criteria:** A tiny overfit test succeeds, save/load predictions match, and
the training loop is reproducible.

### Phase 11: Train and tune

1. Train an initial FinBERT-based model.
2. Tune only against development data.
3. Track:
   - Per-head loss.
   - MAE.
   - Spearman correlation.
   - Macro F1.
   - Per-class metrics.
4. Compare loss weights and masking thresholds.
5. Plot learning curves against dataset size.
6. Train the selected alternative encoder baseline.
7. Choose the model using predeclared development metrics, latency, and size.

**Exit criteria:** The selected model improves meaningfully over simple and
unmodified-FinBERT baselines without relying on the final test set.

### Phase 12: Run final evaluation

1. Freeze model weights and inference code.
2. Run exactly once on the locked human final test set.
3. Generate:
   - Overall metrics.
   - Required slices.
   - Confusion matrices.
   - Ranking examples.
   - Error analysis.
4. Measure CPU and GPU:
   - Latency.
   - Throughput.
   - Memory.
   - Batch-size scaling.
5. Record known failure modes.
6. Do not change the chosen model based on final-test results; a subsequent
   change creates a new version and evaluation cycle.

**Exit criteria:** A reproducible final evaluation report is ready for the model
card.

### Phase 13: Package for external users

1. Implement `TickerRanker.from_pretrained`.
2. Implement single and batch prediction.
3. Add type hints and input validation.
4. Add copy-paste usage examples.
5. Support CPU inference by default.
6. Export SafeTensors weights.
7. Consider ONNX export after verifying prediction parity.
8. Add semantic versioning and a changelog.
9. Add integration tests that load the final artifact from a clean environment.

**Exit criteria:** A new user can install, load, and score examples without
access to the training repository or dataset.

### Phase 14: Write the Hugging Face model card

The Hub renders a model repository’s `README.md` as its model card and supports
structured YAML metadata for discoverability and evaluation results. Include:

1. Model summary.
2. Intended use.
3. Out-of-scope use.
4. Input and output schema.
5. Copy-paste inference examples.
6. Base model and exact revision.
7. Training-data description and rights.
8. Teacher model and prompt methodology.
9. Dataset split strategy.
10. Evaluation metrics and slices.
11. Baseline comparisons.
12. Limitations and biases.
13. English-only limitation.
14. Failure cases involving aliases, indirect effects, and ambiguous headlines.
15. Statement that the model does not provide investment advice or demonstrate
    trading profitability.
16. Environmental and hardware information when available.
17. Citation information.
18. License.

Add Hub metadata such as:

```yaml
---
language:
  - en
library_name: transformers
pipeline_tag: text-classification
base_model: ProsusAI/finbert
tags:
  - finance
  - financial-news
  - news-ranking
  - multi-task-learning
  - ticker-conditioned
license: <verified-license>
---
```

Because the model has a custom multi-task output, verify that
`text-classification` is the least misleading supported pipeline tag and explain
the custom output contract prominently.

**Exit criteria:** The model card lets a stranger understand what the model
does, reproduce the evaluation, and avoid unsupported uses.

### Phase 15: Publish to the Hugging Face Hub

1. Create a private model repository first.
2. Upload:
   - Config.
   - Tokenizer.
   - SafeTensors weights.
   - Custom model/inference code.
   - Model card.
   - Evaluation report.
   - License and citation files.
3. Load the model from the private Hub repository in a clean environment.
4. Confirm model-revision pinning works.
5. Confirm examples return the documented schema.
6. Tag the release, for example `v1.0.0`.
7. Make the repository public only after license and artifact checks pass.

Hugging Face supports model repositories, version history, metadata-rich model
cards, and structured evaluation results. Its Hub documentation recommends
explicitly declaring the library and base model in model-card metadata.

**Exit criteria:** The public model can be downloaded, loaded, and reproduced
from a pinned Hub revision.

### Phase 16: Publish an interactive demo

1. Create a separate Hugging Face Space.
2. Use a simple Gradio interface with:
   - Ticker input.
   - Company-name input.
   - Headline input.
   - Relevance, importance, and direction output.
3. Include several examples:
   - Direct positive event.
   - Direct negative event.
   - Competitor event.
   - Irrelevant event.
   - Low-importance publicity.
4. Display model limitations and the non-advice disclaimer.
5. Link the Space to the model repository.
6. Test on CPU and document expected latency.

Hugging Face Spaces are designed for hosted model demos and support Gradio,
Docker, and static apps. A lightweight encoder should be evaluated on the
available CPU tier before paid hardware is considered.

**Exit criteria:** A visitor can understand and try the model without writing
code.

### Phase 17: Optional hosted production endpoint

Hub publication and a public Space are sufficient for community use. A dedicated
API is optional.

If demand justifies it:

1. Benchmark expected traffic and CPU latency.
2. Decide whether the standard model artifact can be served directly or whether
   the custom multi-head output needs a custom inference handler/container.
3. Deploy an authenticated Hugging Face Inference Endpoint.
4. Add request validation, batching, version metadata, and health checks.
5. Load test it.
6. Configure scale-to-zero if cold starts are acceptable.
7. Monitor latency, failures, and model-version usage.

Hugging Face Inference Endpoints provide managed deployment and lifecycle
operations, including pause, resume, and scale-to-zero. Do not pay for a
dedicated endpoint until the Hub model and Space demonstrate actual demand.

**Exit criteria:** The hosted API returns the same outputs as local inference
for a fixed conformance set.

### Phase 18: Community release and maintenance

1. Publish a short launch post with honest claims.
2. Provide contribution guidelines and issue templates.
3. Invite users to submit difficult, properly licensed examples.
4. Track model and dataset versions separately.
5. Publish evaluation changes for every release.
6. Never replace weights silently under the same version.
7. Maintain a public changelog.
8. Define a process for reporting harmful, incorrect, or financially misleading
   outputs.

**Exit criteria:** Users can understand version changes and reproduce the
reported results.

## 18. Suggested standalone repository layout

```text
tickerrank/
├── README.md
├── LICENSE
├── pyproject.toml
├── src/
│   └── tickerrank/
│       ├── __init__.py
│       ├── configuration_tickerrank.py
│       ├── modeling_tickerrank.py
│       ├── inference.py
│       ├── schemas.py
│       └── normalization.py
├── scripts/
│   ├── build_security_master.py
│   ├── collect_headlines.py
│   ├── normalize_and_deduplicate.py
│   ├── construct_training_pairs.py
│   ├── label_with_teacher.py
│   ├── build_splits.py
│   ├── train.py
│   ├── evaluate.py
│   └── publish_to_hub.py
├── configs/
│   ├── teacher_v1.yaml
│   ├── dataset_v1.yaml
│   └── train_finbert_v1.yaml
├── tests/
│   ├── test_normalization.py
│   ├── test_deduplication.py
│   ├── test_teacher_schema.py
│   ├── test_splits.py
│   ├── test_loss_masking.py
│   ├── test_model_roundtrip.py
│   └── test_inference_contract.py
├── model_card/
│   ├── README.template.md
│   └── evaluation_results.json
├── reports/
│   └── README.md
└── space/
    ├── app.py
    └── requirements.txt
```

## 19. Release gates

TickerRank v1 should not be published as a stable public release until:

- [ ] The relevance-label design is resolved.
- [ ] Data and base-model licensing are documented.
- [ ] Exact deduplication runs before labeling and splitting.
- [ ] Company groups do not cross primary dataset splits.
- [ ] The Gemini teacher is evaluated against human labels.
- [ ] A substantial human development set exists.
- [ ] A locked human final test set exists.
- [ ] Direction loss is masked for clearly irrelevant examples.
- [ ] Baselines are implemented.
- [ ] Final metrics and slices are reproducible.
- [ ] Save/load and inference-contract tests pass.
- [ ] A clean environment can load the pinned Hub revision.
- [ ] The model card states limitations and non-investment use clearly.
- [ ] The public demo matches local predictions on a conformance set.

## 20. MVP definition

The MVP includes:

- Ticker, company name, and headline input.
- One relevance score, unless the open annotation study selects two.
- One importance score.
- One categorical direction.
- Exact normalized-title deduplication.
- Artificial random and hard ticker swaps.
- Company-disjoint evaluation.
- A chronological secondary evaluation.
- Gemini teacher labels with a versioned rubric and event types.
- A FinBERT-based multi-task student.
- Direction-loss masking for irrelevant examples.
- Strong human evaluation.
- A Hugging Face model repository and model card.
- A small public Hugging Face Space.

The MVP does not require:

- Full article text.
- Direction probabilities in the public contract.
- Embedding-based event clustering.
- Multi-ticker relationship graphs.
- Price-reaction labels.
- A complex event taxonomy as a model output.
- A paid production endpoint.

## 21. Later enhancements

Possible later work:

- Add article summaries.
- Add embedding-based near-duplicate and event clustering.
- Add source credibility as a downstream feature.
- Add article freshness as a downstream feature.
- Add calibrated direction probabilities.
- Add separate entity and impact relevance if the MVP retains one score.
- Train an event-type head.
- Train a second-stage market-impact model using point-in-time abnormal returns
  and volume responses.
- Add supplier, customer, and competitor graphs.
- Add sector and macro context.
- Add multilingual models and evaluation sets.
- Distill into a smaller encoder for high-throughput CPU inference.
- Export ONNX and quantized variants.

## 22. Success criteria

The project is successful when:

1. A user can supply an arbitrary ticker, company name, and English headline.
2. The model returns deterministic, bounded relevance and importance scores plus
   a valid direction class.
3. It materially outperforms simple baselines on a locked, human-reviewed,
   company-disjoint test set.
4. Its strongest and weakest slices are clearly documented.
5. The model can be loaded from a pinned Hugging Face revision with a small,
   documented Python API.
6. A public demo makes the features understandable.
7. The model card enables responsible reuse without suggesting that the model
   predicts profitable trades.

## 23. References

- [ProsusAI FinBERT model page](https://huggingface.co/ProsusAI/finbert)
- [Hugging Face model-card documentation](https://huggingface.co/docs/hub/en/model-cards)
- [Hugging Face repository guide](https://huggingface.co/docs/hub/main/repositories-getting-started)
- [Hugging Face model-upload guide](https://huggingface.co/docs/hub/models-uploading)
- [Hugging Face Spaces overview](https://huggingface.co/docs/hub/main/spaces-overview)
- [Hugging Face Inference Endpoints guide](https://huggingface.co/docs/huggingface_hub/guides/inference_endpoints)
- [Gemini API Additional Terms of Service](https://ai.google.dev/gemini-api/terms)
- [Yahoo Terms of Service](https://legal.yahoo.com/us/en/aol/legacy/terms-service/index.html)
