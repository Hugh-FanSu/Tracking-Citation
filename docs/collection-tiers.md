# UNEP citation collection tiers

Every citation carries `collection_tier` independently of confirmation status:

1. Matched to the local UNEP report catalogue (catalogue webpage dates are not assumed to be publication years; retain discrepancies in `catalog_date_differs` and match notes).
2. No catalogue match; the reference review confirms UNEP as the sole signed author.
3. No catalogue match; UNEP is a confirmed author, including joint authors and compound signatures such as UNEP-WCMC. Preserve the complete author signature and `compound_author_flag`.

`0` is an unresolved evidence state, not a fourth accepted category. A publisher name or URL alone does not prove authorship. Unknown sole/joint structure cannot receive tier 2.

JSON fields: `collection_tier`, `collection_tier_label`, `authorship_structure`, `author_signature`, `compound_author_flag`, `collection_policy_version`. Excel mappings can bind these fields to dedicated columns; existing templates receive the classification and author signature in the notes field. Legacy results require re-review/re-export; their counts are not silently changed.

Glued entries retain their original raw text. Recovery selects contiguous native PDF lines, validates their IDs and order, rechecks authorship, and indexes the recovered reference separately. A mixed original is considered resolved only when the recovered exact text accounts for its target-name occurrences. Unresolved boundaries and incomplete citation paragraphs remain review blockers.

The model reviews bibliography identity, native reference-region coverage, citation contexts and target mentions. These are semantic checks, not model training and not a certified recall score. Requests are bounded and cached by input and review version. Server workers must receive PAPER_CITATIONS_API_KEY in their runtime environment; keys do not belong in run configuration or Git. Selecting an API configuration without a key fails explicitly.
